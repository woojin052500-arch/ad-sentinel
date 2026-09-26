import functools
import http.server
import os
import threading
from pathlib import Path

import pytest

from ad_sentinel.config import CrawlConfig
from ad_sentinel.crawler import Crawler
from ad_sentinel.detector import detect
from ad_sentinel.detector.reflection import query_params, reflected_params

SITE_DIR = Path(__file__).parent / "fixtures" / "reflect"
GONGDAN = "http://old.gongdan.go.kr/home.jsp?play=%EB%B0%94%EC%B9%B4%EB%9D%BC%EB%B6%84%EC%84%9D"


def test_query_params_utf8():
    assert query_params(GONGDAN) == [("play", "바카라분석")]


def test_query_params_euckr_and_plus():
    assert query_params("http://x.go.kr/a.jsp?play=%B9%D9%C4%AB%B6%F3&q=a+b") == [("play", "바카라"), ("q", "a b")]


def test_reflection_requires_suspicious_value():
    params = [("play", "바카라분석"), ("menu", "공지사항"), ("page", "12")]
    assert reflected_params(params, "바카라분석") == [{"name": "play", "value": "바카라분석"}]
    assert reflected_params(params, "공지사항 12") == []
    assert reflected_params(params, "블랙잭") == []


def test_reflection_ignores_whitespace_differences():
    assert reflected_params([("q", "먹튀 검증")], "먹튀검증 사이트") == [{"name": "q", "value": "먹튀 검증"}]


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def report():
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = "127.0.0.1,localhost"
    handler = functools.partial(QuietHandler, directory=str(SITE_DIR))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/"
    config = CrawlConfig(start_url=base + "index.html", max_pages=10, delay_sec=0, render_wait_ms=300,
                         networkidle_timeout_ms=2000, respect_robots=False)
    try:
        crawl = Crawler(config).run()
    finally:
        server.shutdown()
    return crawl, detect(crawl)


def test_reflected_spam_page_is_detected(report):
    crawl, result = report
    assert len(crawl["pages"]) == 5
    spam = [f for f in result["findings"] if "play=%EB%B0%94" in f["pages"][0]]
    assert {f["type"] for f in spam} == {"text", "title"}
    for f in spam:
        assert f["level"] == "high"
        assert f["pattern"] == "param_reflection"
        assert f["pattern_label"] == "URL 파라미터 반사"
        assert f["reflected_params"] == [{"name": "play", "value": "바카라분석"}]
        assert any(e["kind"] == "reflection" for e in f["evidence"])
    text = next(f for f in spam if f["type"] == "text")
    assert text["selector"] == "#content > h2"
    assert result["summary"]["by_pattern"] == {"URL 파라미터 반사": 3}


def test_search_page_reflecting_keyword_is_reflection_surface(report):
    _, result = report
    search = [f for f in result["findings"] if "search.html" in f["pages"][0]]
    assert len(search) == 1
    assert search[0]["reflected_params"] == [{"name": "q", "value": "카지노 규제"}]


def test_normal_reflection_is_not_reported(report):
    _, result = report
    urls = {u for f in result["findings"] for u in f["pages"]}
    assert all("play=%EA%B3%B5" not in u and "q=%EC%A3%BC" not in u for u in urls)
