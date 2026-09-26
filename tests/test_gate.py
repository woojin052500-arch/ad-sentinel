import functools
import logging
import http.server
import os
import threading
from pathlib import Path

import pytest

from ad_sentinel.config import BOT_BLOCK_NOTICE, CrawlConfig
from ad_sentinel.crawler import Crawler
from ad_sentinel.crawler.sitemap import parse_sitemap, sitemap_locations
from ad_sentinel.crawler.url_utils import is_safe_to_visit
from ad_sentinel.detector import detect

FIXTURES = Path(__file__).parent / "fixtures"


class Server:
    def __init__(self, name: str, spa: bool = False):
        root = FIXTURES / name
        self.requests: list[str] = []
        requests = self.requests

        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                requests.append(self.path)
                if self.path.startswith("/clicked/"):
                    self.send_response(204)
                    self.end_headers()
                    return
                if spa and "." not in self.path.split("?")[0].rsplit("/", 1)[-1]:
                    self.path = "/index.html"
                super().do_GET()

            def do_POST(self):
                requests.append("POST " + self.path)
                self.send_response(204)
                self.end_headers()

        os.environ["NO_PROXY"] = "127.0.0.1,localhost"
        os.environ["no_proxy"] = "127.0.0.1,localhost"
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(root)))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}/"

    def crawl(self, path="", **options):
        values = dict(start_url=self.base + path, max_pages=50, delay_sec=0, render_wait_ms=300,
                      networkidle_timeout_ms=1500)
        values.update(options)
        try:
            return Crawler(CrawlConfig(**values)).run()
        finally:
            self.server.shutdown()


def _paths(crawl):
    return sorted(p["url"].split("/", 3)[3] for p in crawl["pages"])


@pytest.fixture(scope="module")
def gate_run():
    server = Server("gate")
    crawl = server.crawl("index.html")
    return crawl, server.requests


def test_gate_button_is_clicked_and_site_is_crawled(gate_run):
    crawl, requests = gate_run
    assert _paths(crawl) == ["board.html", "gallery.html", "index.html", "notice.html"]
    first = crawl["pages"][0]
    assert first["gate"]["text"].startswith("입장하기")
    assert first["gate"]["url_changed"] is True and first["final_url"].endswith("main.html")
    assert first["gate"]["links_before"] == 0 and first["gate"]["links_after"] == 3
    assert crawl["meta"]["gate"]["text"].startswith("입장하기")
    assert crawl["meta"]["notes"] == []
    report = detect(crawl)
    assert any(f["content"] == "온라인 카지노 바로가기" for f in report["findings"])


def test_dangerous_buttons_and_links_are_never_used(gate_run):
    _, requests = gate_run
    assert "/clicked/enter" in requests
    for danger in ["/clicked/login", "/clicked/join", "/clicked/delete", "/clicked/report", "POST /clicked/form-post"]:
        assert danger not in requests
    assert not any("logout" in r or "delete.do" in r for r in requests)


def test_gate_disabled_shows_hint():
    crawl = Server("gate").crawl("index.html", enter_gate=False)
    assert len(crawl["pages"]) == 1
    assert crawl["pages"][0]["gate"] is None
    assert crawl["meta"]["notes"] == [
        "발견한 링크가 적어 1페이지만 점검했습니다. 입장 버튼이 있는 사이트라면 입장 후 주소를 시작 주소로 넣어보세요."]


def test_spa_without_url_change_is_crawled():
    crawl = Server("spa", spa=True).crawl("")
    assert _paths(crawl) == ["", "board", "gallery", "notice"]
    first = crawl["pages"][0]
    assert first["gate"]["text"] == "Enter" and first["gate"]["url_changed"] is False
    sources = {e.get("source") for e in first["elements"] if e["type"] == "link"}
    assert {"onclick", "data-href"} <= sources
    board = next(p for p in crawl["pages"] if p["url"].endswith("/board"))
    assert board["gate"] is not None
    report = detect(crawl)
    assert any("토토사이트" in f["content"] for f in report["findings"])


def test_sitemap_pages_are_added():
    server = Server("sitemap")
    crawl = server.crawl("index.html")
    assert _paths(crawl) == ["index.html", "page1.html", "page2.html", "page3.html"]
    assert crawl["meta"]["sitemap"]["urls"] == 4
    assert [f.rsplit("/", 1)[1] for f in crawl["meta"]["sitemap"]["files"]] == ["sitemap_index.xml",
                                                                                 "sitemap-pages.xml"]
    assert any("private/secret.html" in s["url"] for s in crawl["skipped"])
    assert not any("logout" in r for r in server.requests)
    assert crawl["meta"]["notes"] == [
        "sitemap.xml에 있는 주소로만 4페이지를 점검했습니다. 게시판 페이지를 찾지 못했을 수 있습니다. "
        "입장 버튼이 있는 사이트라면 입장 후 주소를, 게시판이 있다면 게시판 주소를 시작 주소로 넣어보세요."]
    assert any(p["found_on"] == "sitemap.xml" for p in crawl["pages"])
    report = detect(crawl)
    assert any("바카라" in f["content"] for f in report["findings"])


def test_sitemap_parsing():
    robots = "User-agent: *\nSitemap: https://x.go.kr/a.xml\nsitemap: /b.xml\n"
    assert sitemap_locations(robots, "https://x.go.kr/") == ["https://x.go.kr/a.xml", "https://x.go.kr/b.xml"]
    urlset = b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>/p.html</loc></url></urlset>'
    assert parse_sitemap(urlset, "https://x.go.kr/s.xml") == (["https://x.go.kr/p.html"], [])
    index = b'<sitemapindex><sitemap><loc>https://x.go.kr/s2.xml</loc></sitemap></sitemapindex>'
    assert parse_sitemap(index, "https://x.go.kr/") == ([], ["https://x.go.kr/s2.xml"])
    assert parse_sitemap(b"<html>not xml", "https://x.go.kr/") == ([], [])


@pytest.mark.parametrize("url,safe", [
    ("http://x.go.kr/board/delete.do?id=3", False),
    ("http://x.go.kr/member/logout.do", False),
    ("http://x.go.kr/bbs?act=del&id=1", False),
    ("http://x.go.kr/board/view.do?id=3", True),
    ("http://x.go.kr/deliver/info.do", True),
])
def test_unsafe_urls_are_not_visited(url, safe):
    assert is_safe_to_visit(url) is safe


@pytest.fixture(scope="module")
def community_run():
    server = Server("community")
    crawl = server.crawl("index.html")
    return crawl, server.requests


def test_community_gate_with_many_footer_links_is_entered(community_run):
    crawl, requests = community_run
    paths = _paths(crawl)
    assert "board/view.html?no=1" in paths and "board/view.html?no=2" in paths and "board/view.html?no=3" in paths
    assert len(paths) == 10
    first = crawl["pages"][0]
    assert first["gate"]["text"] == "커뮤니티 입장하기"
    assert first["gate"]["links_before"] == 0 and first["gate"]["links_after"] == 3
    assert first["gate"]["new_links"] >= 3
    assert "/clicked/enter" in requests and "/clicked/login" not in requests
    assert crawl["meta"]["notes"] == []
    report = detect(crawl)
    spam = [f for f in report["findings"] if "바카라" in f["content"]]
    assert spam and spam[0]["pages"][0].endswith("view.html?no=2")


def test_footer_links_are_marked(community_run):
    crawl, _ = community_run
    links = [e for e in crawl["pages"][0]["elements"] if e["type"] == "link"]
    footer = [e for e in links if e.get("footer")]
    assert {e["content"] for e in footer} >= {"이용약관", "개인정보처리방침", "서비스 안내", "통계"}


def test_community_without_gate_warns_board_missing():
    crawl = Server("community").crawl("index.html", enter_gate=False)
    assert len(crawl["pages"]) == 7
    assert not any("board" in p["url"] for p in crawl["pages"])
    assert crawl["meta"]["notes"] == [
        "sitemap.xml에 있는 주소로만 7페이지를 점검했습니다. 게시판 페이지를 찾지 못했을 수 있습니다. "
        "입장 버튼이 있는 사이트라면 입장 후 주소를, 게시판이 있다면 게시판 주소를 시작 주소로 넣어보세요."]


def test_content_page_weak_button_is_not_clicked():
    server = Server("community")
    crawl = server.crawl("normal.html", use_sitemap=False, max_depth=0)
    first = crawl["pages"][0]
    assert first["gate"] is None and first["gate_attempt"] is None
    assert not any(r.startswith("/clicked/") for r in server.requests)


def test_boilerplate_link_rules():
    from ad_sentinel.crawler.gate import is_boilerplate_link

    assert is_boilerplate_link({"content": "개인정보 처리방침"})
    assert is_boilerplate_link({"content": "이용약관"})
    assert is_boilerplate_link({"content": "공지사항", "footer": True})
    assert not is_boilerplate_link({"content": "자유게시판"})
    assert not is_boilerplate_link({"content": "사업 안내"})


@pytest.fixture(scope="module")
def feed_run():
    server = Server("feed")
    crawl = server.crawl("")
    return crawl, server.requests


def test_feed_gate_with_anchor_menu_and_javascript_button(feed_run):
    crawl, requests = feed_run
    assert len(crawl["pages"]) == 4
    first = crawl["pages"][0]
    gate = first["gate"]
    assert gate["text"] == "지금, 익명으로 시작하기 >"
    assert gate["url_changed"] is False and first["final_url"].endswith("/?sec=hero")
    assert gate["text_after"] > gate["text_before"]
    assert "스타일시트 다운로드 중" not in " ".join(e["content"] for e in first["elements"] if e["type"] == "text")
    assert crawl["meta"]["notes"] == []
    assert "/clicked/start" in requests


def test_feed_load_more_collects_later_posts(feed_run):
    crawl, requests = feed_run
    first = crawl["pages"][0]
    assert first["gate"]["load_more_scrolls"] == 3
    assert first["gate"]["load_more_clicks"] == 2
    assert requests.count("/clicked/more") == 2
    assert "/clicked/reveal" not in requests
    texts = " ".join(e["content"] for e in first["elements"] if e["type"] == "text")
    assert "익명 30번째 생각" in texts
    report = detect(crawl)
    contents = {f["content"] for f in report["findings"]}
    assert any("토토사이트 추천" in c for c in contents)
    assert any("카지노 먹튀검증" in c for c in contents)


def test_feed_consent_and_join_popups_are_not_clicked(feed_run):
    crawl, requests = feed_run
    assert "/clicked/agree" not in requests and "/clicked/discord" not in requests
    assert "/clicked/later" not in requests
    texts = " ".join(e["content"] for e in crawl["pages"][0]["elements"] if e["type"] == "text")
    assert "약관에 동의하는 것으로 간주됩니다" in texts and "양파 원조교제하다" in texts


def test_feed_without_gate_warns_board_missing():
    crawl = Server("feed").crawl("", enter_gate=False)
    assert len(crawl["pages"]) == 4
    assert "게시판 페이지를 찾지 못했을 수 있습니다" in crawl["meta"]["notes"][0]


def test_anchor_links_are_not_content_links():
    from ad_sentinel.crawler.gate import is_boilerplate_link

    assert is_boilerplate_link({"content": "About", "raw_href": "#about"})
    assert not is_boilerplate_link({"content": "자유게시판", "raw_href": "/board"})


def _feed_titles(page):
    return [e["content"] for e in page["elements"] if e["type"] == "text" and e["content"].startswith("피드 글")]


@pytest.mark.parametrize("query", ["", "?plain=1"])
def test_loading_screen_after_gate_waits_for_feed(query, caplog):
    with caplog.at_level(logging.INFO, logger="ad_sentinel"):
        crawl = Server("biglanding").crawl(query, use_sitemap=False, max_pages=1, gate_wait_ms=20000)
    first = crawl["pages"][0]
    gate = first["gate"]
    assert gate["text_before"] > 2000 and gate["text_after"] > 150
    assert gate["incomplete"] is False
    assert len(_feed_titles(first)) == 20
    assert "로딩 화면으로 보여 대기 중" in caplog.text
    assert "대기 시간" not in caplog.text and "다 불러와지지 않았을" not in caplog.text
    assert "새로 나타난 글 제목 20개를 수집했습니다" in caplog.text
    assert gate["post_titles"] == 20 and gate["titles_before"] >= 1
    assert "왜 우리는 온라인에서" not in caplog.text.split("글 제목 20개")[1].split("\n")[0]
    assert not any("봇 차단" in n for n in crawl["meta"]["notes"])
    contents = {f["content"] for f in detect(crawl)["findings"]}
    assert any("토토사이트 추천" in c for c in contents)


def test_long_loading_screen_with_progress_bar_is_waited_out():
    crawl = Server("biglanding").crawl("?slow=1", use_sitemap=False, max_pages=1, gate_wait_ms=20000)
    first = crawl["pages"][0]
    assert first["gate"]["incomplete"] is False
    assert len(_feed_titles(first)) == 20


def test_long_plain_loading_screen_is_reported_incomplete(caplog):
    with caplog.at_level(logging.INFO, logger="ad_sentinel"):
        crawl = Server("biglanding").crawl("?slow=1&plain=1", use_sitemap=False, max_pages=1, gate_wait_ms=20000,
                                           load_more=False)
    assert crawl["pages"][0]["gate"]["incomplete"] is True
    assert "다 불러와지지 않았을 수 있습니다" in caplog.text
    assert "더보기·추가 로딩 없음" not in caplog.text


def test_bot_blocked_loading_screen_is_reported(caplog, tmp_path):
    with caplog.at_level(logging.INFO, logger="ad_sentinel"):
        crawl = Server("biglanding").crawl("?blocked=1", use_sitemap=False, max_pages=1, gate_wait_ms=6000,
                                           load_more=False, screenshot_dir=str(tmp_path))
    gate = crawl["pages"][0]["gate"]
    assert gate["incomplete"] is True
    assert gate["post_titles"] == 0 and gate["titles_before"] >= 1
    assert "새로 나타난 글 제목이 없습니다" in caplog.text
    assert "브라우저 보안" in gate["block_hints"]
    assert any(n.startswith(BOT_BLOCK_NOTICE) for n in crawl["meta"]["notes"])
    names = sorted(Path(p).name for p in gate["screenshots"])
    assert [n.split("_", 2)[2] for n in names] == ["gate1_clicked.png", "gate1_waited.png"]
    assert all((tmp_path / n).stat().st_size > 1000 for n in names)


def test_screenshots_are_off_by_default(tmp_path):
    crawl = Server("gate").crawl("index.html", max_pages=1)
    assert crawl["pages"][0]["gate"]["screenshots"] == []
