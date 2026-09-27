import functools
import http.server
import threading
from pathlib import Path

import pytest

from ad_sentinel.config import CrawlConfig
from ad_sentinel.crawler import Crawler

SITE_DIR = Path(__file__).parent / "fixtures" / "site"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def result():
    handler = functools.partial(QuietHandler, directory=str(SITE_DIR))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/"

    import os
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = "127.0.0.1,localhost"

    config = CrawlConfig(start_url=base + "index.html", max_pages=10, delay_sec=0, render_wait_ms=800)
    try:
        yield Crawler(config).run()
    finally:
        server.shutdown()


def _page(result, name):
    return next(p for p in result["pages"] if p["url"].split("/")[-1].startswith(name))


def test_visits_same_site_only(result):
    urls = [p["url"] for p in result["pages"]]
    names = sorted(u.split("/")[-1] for u in urls)
    assert names == ["board.html?nttId=1", "index.html", "page2.html"]
    assert any("private/secret.html" in s["url"] for s in result["skipped"])


def test_hidden_elements_detected(result):
    index = _page(result, "index.html")
    hidden = {e["content"]: e for e in index["elements"] if e["type"] == "hidden"}

    assert "display:none" in hidden["온라인 카지노 바로가기"]["hidden_reasons"]
    assert "http://casino.invalid/" in hidden["온라인 카지노 바로가기"]["links"]
    assert "same-color-as-background" in hidden["토토사이트 추천"]["hidden_reasons"]
    assert "off-screen" in hidden["성인 무료 영상"]["hidden_reasons"]
    assert "tiny-font" in hidden["바카라 사이트"]["hidden_reasons"]
    texts = [e["content"] for e in index["elements"] if e["type"] == "text"]
    assert "정상적인 기관 소개 문구입니다." in texts
    assert "토토사이트 추천" not in texts


def test_iframes_collected(result):
    index = _page(result, "index.html")
    iframes = {e["raw_src"]: e for e in index["elements"] if e["type"] == "iframe"}
    assert iframes["frame.html"]["hidden"] is False
    assert iframes["ad-frame.html"]["hidden"] is True
    assert "tiny-size" in iframes["ad-frame.html"]["hidden_reasons"]

    inner = [e for e in index["elements"] if e["frame_path"] == ["#notice-frame"]]
    assert any(e["type"] == "text" and e["content"] == "iframe 내부 공지 내용" for e in inner)
    assert any(e["type"] == "hidden" and "visibility:hidden" in e["hidden_reasons"] for e in inner)
    ad = [e for e in index["elements"] if e["frame_url"].endswith("ad-frame.html")]
    assert any("홀덤" in e["content"] for e in ad)


def test_text_keeps_context_and_dynamic_content(result):
    page2 = _page(result, "page2.html")
    comment = next(e for e in page2["elements"] if e["type"] == "text" and "먹튀" in e["content"])
    assert comment["content"] == "먹튀 없는 안전놀이터 가입코드 777"
    assert comment["selector"] == "#comments > li:nth-of-type(2)"

    board = _page(result, "board.html")
    assert any(e["type"] == "link" and e["href"] == "http://bet.invalid/" for e in board["elements"])


def test_detector_on_sample_site(result):
    from ad_sentinel.detector import detect

    report = detect(result)
    by_content = {f["content"]: f for f in report["findings"]}
    for content in ["온라인 카지노 바로가기", "토토사이트 추천", "성인 무료 영상", "바카라 사이트",
                    "슬롯 무료 체험", "홀덤 입금 보너스 100%", "먹튀 없는 안전놀이터 가입코드 777",
                    "ⓒⓐⓢⓘⓝⓞ 신규 가입 이벤트 바로가기"]:
        assert by_content[content]["level"] == "high", content
    assert by_content["스포츠 베팅 바로가기"]["level"] == "high"
    assert by_content["스포츠 베팅 바로가기"]["urls"] == ["http://bet.invalid/"]
    assert "바로가기" not in by_content
    enclosed = by_content["ⓒⓐⓢⓘⓝⓞ 신규 가입 이벤트 바로가기"]
    assert any("변형 표기: ⓒⓐⓢⓘⓝⓞ → casino, 감싼 문자" in e["label"] for e in enclosed["evidence"])
    assert all("정상적인" not in f["content"] for f in report["findings"])


def test_ignore_robots_visits_blocked_page_with_warning(caplog):
    import logging

    from ad_sentinel.config import ROBOTS_IGNORE_WARNING

    handler = functools.partial(QuietHandler, directory=str(SITE_DIR))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/"
    config = CrawlConfig(start_url=base + "index.html", max_pages=10, delay_sec=0, render_wait_ms=300,
                         respect_robots=False)
    try:
        with caplog.at_level(logging.WARNING):
            result = Crawler(config).run()
    finally:
        server.shutdown()
    assert result["meta"]["robots_ignored"] is True
    assert result["skipped"] == []
    assert any(p["url"].endswith("private/secret.html") for p in result["pages"])
    assert ROBOTS_IGNORE_WARNING in caplog.text


def test_robots_respected_by_default(result):
    assert result["meta"]["robots_ignored"] is False
