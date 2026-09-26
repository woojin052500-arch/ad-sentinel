"""샘플 사이트(tests/fixtures/site)를 로컬 서버로 띄워 크롤러 전체를 검증한다.

브라우저가 필요하다. Playwright Chromium이 없으면 환경변수 AD_SENTINEL_BROWSER 로 경로 지정.
"""

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

    # 테스트 서버의 robots.txt 는 urllib 로 읽으므로 프록시를 거치지 않게 한다
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
    # robots.txt 로 막힌 페이지는 방문하지 않고 skipped 에 기록
    assert any("private/secret.html" in s["url"] for s in result["skipped"])


def test_hidden_elements_detected(result):
    index = _page(result, "index.html")
    hidden = {e["content"]: e for e in index["elements"] if e["type"] == "hidden"}

    assert "display:none" in hidden["온라인 카지노 바로가기"]["hidden_reasons"]
    assert "http://casino.invalid/" in hidden["온라인 카지노 바로가기"]["links"]
    assert "same-color-as-background" in hidden["토토사이트 추천"]["hidden_reasons"]
    assert "off-screen" in hidden["성인 무료 영상"]["hidden_reasons"]
    assert "tiny-font" in hidden["바카라 사이트"]["hidden_reasons"]
    # 정상 문구는 숨김이 아니라 text 로 분류
    texts = [e["content"] for e in index["elements"] if e["type"] == "text"]
    assert "정상적인 기관 소개 문구입니다." in texts
    assert "토토사이트 추천" not in texts


def test_iframes_collected(result):
    index = _page(result, "index.html")
    iframes = {e["raw_src"]: e for e in index["elements"] if e["type"] == "iframe"}
    assert iframes["frame.html"]["hidden"] is False
    assert iframes["ad-frame.html"]["hidden"] is True
    assert "tiny-size" in iframes["ad-frame.html"]["hidden_reasons"]

    # iframe 내부 문서의 내용과 위치(frame_path)
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

    # 자바스크립트로 나중에 추가된 링크도 수집
    board = _page(result, "board.html")
    assert any(e["type"] == "link" and e["href"] == "http://bet.invalid/" for e in board["elements"])
