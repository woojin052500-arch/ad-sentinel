import functools
import http.server
import os
import threading
from pathlib import Path

import pytest

from ad_sentinel.config import CrawlConfig
from ad_sentinel.crawler import Crawler
from ad_sentinel.detector import detect

ROOT = Path(__file__).parent / "fixtures" / "resources"
HEAVY = (".woff2", ".ttf", ".mp4", ".mp3")


def _run(block: bool):
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    requests: list[str] = []

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append(self.path)
            super().do_GET()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        crawl = Crawler(CrawlConfig(start_url=f"http://127.0.0.1:{server.server_port}/index.html", max_pages=1,
                                    delay_sec=0, render_wait_ms=300, networkidle_timeout_ms=1500, use_sitemap=False,
                                    block_heavy_resources=block)).run()
    finally:
        server.shutdown()
    return crawl, requests


@pytest.fixture(scope="module")
def runs():
    return {block: _run(block) for block in (True, False)}


def _summary(crawl):
    return sorted((f["pattern"], f["content"], f["level"]) for f in detect(crawl)["findings"])


def test_fonts_and_media_are_not_requested(runs):
    crawl, requests = runs[True]
    assert not any(r.endswith(HEAVY) for r in requests)
    assert "/photo.png" in requests and "/bg.png" in requests and "/ad.html" in requests
    assert crawl["meta"]["blocked_resources"] >= 3
    _, unblocked = runs[False]
    assert any(r.endswith(HEAVY) for r in unblocked)


def test_detection_is_the_same_with_blocking(runs):
    blocked, unblocked = _summary(runs[True][0]), _summary(runs[False][0])
    assert blocked == unblocked
    contents = {content for _, content, _ in blocked}
    assert "토토사이트 추천 먹튀검증 가입코드 777" in contents
    assert "온라인 카지노 바로가기" in contents
    assert "슬롯사이트 꽁머니 지급" in contents


def test_image_alt_and_tiny_iframe_still_detected(runs):
    report = detect(runs[True][0])
    alt = next(f for f in report["findings"] if f["type"] == "alt")
    assert "이미지 대체 텍스트(alt)에 들어 있음" in [e["label"] for e in alt["evidence"]]
    assert alt["hidden_reasons"] == []
    iframe_ad = next(f for f in report["findings"] if f["content"] == "슬롯사이트 꽁머니 지급")
    assert any(e["label"] == "숨겨진 iframe 내부" for e in iframe_ad["evidence"])
