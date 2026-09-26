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
    assert result["summary"]["by_pattern"] == {"URL 파라미터 반사": 2, "악용 가능 지점": 1}


def test_search_page_reflecting_keyword_is_reflection_surface(report):
    _, result = report
    search = [f for f in result["findings"] if "search.html" in f["pages"][0]]
    assert len(search) == 1
    f = search[0]
    assert f["reflected_params"] == [{"name": "q", "value": "카지노 규제"}]
    assert f["pattern"] == "reflection_surface" and f["pattern_label"] == "악용 가능 지점"
    assert f["level"] == "suspect" and f["level_label"] == "검토 필요"
    assert "입력값을 그대로 출력하지 않도록 조치" in f["advice"]


def _score_reflection(content, url):
    from ad_sentinel.detector import Detector

    rec = {"type": "text", "content": content, "selector": "#result > p", "frame_path": [], "frame_url": url}
    return Detector({"meta": {"start_url": url}, "pages": []}).score(rec, params=query_params(url))


def test_spam_payload_in_search_param_is_still_ad():
    url = "http://x.go.kr/search.do?query=%EB%B0%94%EC%B9%B4%EB%9D%BC%EC%82%AC%EC%9D%B4%ED%8A%B8+%ED%85%94%EB%A0%88%EA%B7%B8%EB%9E%A8+%40bet777"
    f = _score_reflection("'바카라사이트 텔레그램 @bet777' 검색 결과", url)
    assert f["pattern"] == "param_reflection" and f["level"] == "high"


def test_non_search_param_reflecting_keyword_is_ad():
    f = _score_reflection("바카라분석", GONGDAN)
    assert f["pattern"] == "param_reflection" and f["level"] == "high"


def test_search_param_with_other_evidence_is_ad():
    url = "http://x.go.kr/search.do?q=%EC%B9%B4%EC%A7%80%EB%85%B8"
    f = _score_reflection("카지노 검색 결과 - 먹튀 없는 곳", url)
    assert f["pattern"] == "param_reflection" and f["level"] == "high"


def test_normal_reflection_is_not_reported(report):
    _, result = report
    urls = {u for f in result["findings"] for u in f["pages"]}
    assert all("play=%EA%B3%B5" not in u and "q=%EC%A3%BC" not in u for u in urls)
