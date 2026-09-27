import functools
import http.server
import logging
import os
import threading
from pathlib import Path

from ad_sentinel.config import CrawlConfig
from ad_sentinel.crawler import Crawler
from ad_sentinel.detector import detect

SITE_DIR = Path(__file__).parent / "fixtures" / "softerr"
STATIC = {"/common.js", "/start.html", "/rss", "/dup.rss"}


class SoftErrorServer:
    def __init__(self):
        self.requests: list[str] = []
        owner = self

        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send_page(self, name: str, status: int = 200):
                body = (SITE_DIR / name).read_bytes()
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                owner.requests.append(self.path)
                path = self.path.split("?")[0]
                if path.startswith("/clicked/"):
                    self.send_response(204)
                    self.end_headers()
                elif path in STATIC:
                    super().do_GET()
                elif path in ("/", "/index.html") or path.startswith("/dup/"):
                    self.send_page("index.html")
                elif path.startswith("/post/"):
                    self.send_page("post.html")
                elif path == "/hard404":
                    self.send_page("notfound.html", 404)
                else:
                    self.send_page("notfound.html")

        os.environ["NO_PROXY"] = "127.0.0.1,localhost"
        os.environ["no_proxy"] = "127.0.0.1,localhost"
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
                                                      functools.partial(Handler, directory=str(SITE_DIR)))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}/"

    def crawl(self, path: str, **options):
        values = dict(start_url=self.base + path, max_pages=20, delay_sec=0, render_wait_ms=300,
                      networkidle_timeout_ms=1500, gate_wait_ms=3000)
        values.update(options)
        try:
            return Crawler(CrawlConfig(**values)).run()
        finally:
            self.server.shutdown()


def _paths(crawl):
    return [p["url"].split("/", 3)[3] for p in crawl["pages"]]


def test_sitemap_url_in_start_field_and_post_reclick(caplog):
    server = SoftErrorServer()
    with caplog.at_level(logging.INFO, logger="ad_sentinel"):
        crawl = server.crawl("all/sitemap.xml")
    assert crawl["meta"]["start_url"] == server.base
    assert "sitemap·RSS 주소로 보여" in caplog.text
    assert "/sitemap.xml 없음(sitemap·RSS 형식이 아님)" in caplog.text
    assert _paths(crawl) == ["", "post/1", "post/2", "post/3", "post/4", "post/5"]
    assert "/clicked/home" not in server.requests
    assert server.requests.count("/clicked/restart") == 3
    assert crawl["meta"]["gate_rejections"] == 3
    assert "이후 페이지에서는 입장 버튼을 누르지 않습니다" in caplog.text
    for i, page in enumerate(crawl["pages"][1:], 1):
        assert page["final_url"].endswith(f"/post/{i}")
        texts = " ".join(e["content"] for e in page["elements"] if e["type"] == "text")
        assert f"글 제목 {i}" in texts and "오늘의 생각" not in texts
    assert crawl["meta"]["repeated_screens"] == []
    report = detect(crawl)
    ad = next(f for f in report["findings"] if "카지노" in f["content"])
    assert ad["post_title"] == "글 제목 3"


def test_soft_404_start_page_is_not_entered():
    server = SoftErrorServer()
    crawl = server.crawl("board/view.do?id=999", use_sitemap=False, max_pages=1)
    page = crawl["pages"][0]
    assert "소프트 404" in page["error_page"]
    assert page["gate"] is None and page["gate_attempt"] is None
    assert "/clicked/home" not in server.requests
    assert crawl["meta"]["notes"][0].startswith("시작 주소가 오류 페이지입니다")
    report = detect(crawl)
    assert any("오류 페이지로 열림" in u["reason"] for u in report["unchecked"])


def test_hard_404_start_page():
    server = SoftErrorServer()
    crawl = server.crawl("hard404", use_sitemap=False, max_pages=1)
    assert crawl["pages"][0]["error_page"] == "HTTP 404"
    assert crawl["meta"]["start_error"] == "HTTP 404"
    assert "/clicked/home" not in server.requests


def test_learned_gate_reclick_moving_home_is_discarded():
    server = SoftErrorServer()
    crawl = server.crawl("start.html", use_sitemap=False, sitemap_urls=[server.base + "rss"], max_pages=6)
    first = crawl["pages"][0]
    assert first["gate"]["text"] == "지금 시작하기"
    rejected = [p for p in crawl["pages"][1:] if p["gate_rejected"]]
    assert len(rejected) == 3 and all(p["gate_rejected"]["moved_to"] == server.base for p in rejected)
    assert all(p["gate"] is None for p in crawl["pages"][1:])
    assert server.requests.count("/clicked/restart") == 3
    for i, page in enumerate(crawl["pages"][1:], 1):
        assert page["final_url"].endswith(f"/post/{i}")


def test_repeated_same_screen_warning():
    server = SoftErrorServer()
    crawl = server.crawl("", use_sitemap=False, sitemap_urls=[server.base + "dup.rss"])
    assert _paths(crawl) == ["", "dup/1", "dup/2", "dup/3", "dup/4"]
    screens = crawl["meta"]["repeated_screens"]
    assert len(screens) == 1 and screens[0]["count"] == 5
    assert screens[0]["title"] == "상정인사이드 - 자유로운 토론 커뮤니티"
    assert any("같은 화면이 반복 점검되었습니다" in n for n in crawl["meta"]["notes"])
    report = detect(crawl)
    repeated = [u for u in report["unchecked"] if "똑같은 화면" in u["reason"]]
    assert len(repeated) == 4


def test_exit_words_are_not_gate_candidates():
    from ad_sentinel.crawler.gate import EXIT_PATTERN, GATE_PARTS, GATE_WORDS
    import re

    for text in ["홈으로돌아가기", "메인으로", "뒤로가기", "이전페이지", "처음으로", "gohome", "back"]:
        assert re.search(EXIT_PATTERN, text, re.IGNORECASE)
    assert "홈으로" not in GATE_WORDS and "홈으로" not in GATE_PARTS and "메인으로" not in GATE_PARTS


def test_repeated_screen_warning_only_for_home_redirect_or_gate():
    from ad_sentinel.config import CrawlConfig
    from ad_sentinel.crawler import Crawler

    crawler = Crawler(CrawlConfig(start_url="https://www.example.go.kr/"))

    def page(url, final=None, title="화면", text="본문 " * 20, gate=None):
        return {"url": url, "final_url": final or url, "title": title, "gate": gate, "gate_rejected": None,
                "frames": [{"is_main": True, "text": text}]}

    crawler._track_screen(page("https://www.example.go.kr/", title="홈", text="홈 화면 " * 20))
    for i in range(3):
        crawler._track_screen(page(f"https://www.example.go.kr/search?q={i}", title="검색", text="검색 결과 " * 20))
    for i in range(3):
        crawler._track_screen(page(f"https://www.example.go.kr/old/{i}", final="https://www.example.go.kr/moved",
                                   title="이동", text="이동한 화면 " * 20))
    for i in range(3):
        crawler._track_screen(page(f"https://www.example.go.kr/post/{i}", title="홈", text="홈 화면 " * 20))
    suspect = dict(zip(["홈", "검색", "이동"], (crawler.screen_suspect.get(key, False) for key in crawler.screens)))
    assert suspect == {"홈": True, "검색": False, "이동": True}
    assert len(crawler.repeat_warned) == 2
