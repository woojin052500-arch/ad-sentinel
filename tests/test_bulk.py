import functools
import http.server
import os
import threading
from pathlib import Path

import pytest

from ad_sentinel.config import CrawlConfig
from ad_sentinel.crawler import Crawler
from ad_sentinel.crawler.sitemap import parse_document
from ad_sentinel.detector import detect

SITE_DIR = Path(__file__).parent / "fixtures" / "posts"


class PostServer:
    def __init__(self, blocked: bool = False):
        self.requests: list[str] = []
        self.first_seen: set[str] = set()
        owner = self

        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                owner.requests.append(self.path)
                path = self.path.split("?")[0]
                if path.startswith("/clicked/"):
                    self.send_response(204)
                    self.end_headers()
                    return
                if path.startswith("/post/"):
                    first = path not in owner.first_seen
                    owner.first_seen.add(path)
                    if blocked or (first and path == "/post/5"):
                        self.send_response(429)
                        self.send_header("Retry-After", "1")
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.end_headers()
                        self.wfile.write("<h1>Too Many Requests</h1>".encode())
                        return
                    if first and path == "/post/9":
                        self.send_response(302)
                        self.send_header("Location", "/rate-limit.html")
                        self.end_headers()
                        return
                    self.path = "/post.html"
                super().do_GET()

        os.environ["NO_PROXY"] = "127.0.0.1,localhost"
        os.environ["no_proxy"] = "127.0.0.1,localhost"
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
                                                      functools.partial(Handler, directory=str(SITE_DIR)))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}/"

    def crawl(self, **options):
        values = dict(start_url=self.base, max_pages=50, delay_sec=0, render_wait_ms=300,
                      networkidle_timeout_ms=1500, throttle_backoff_min_sec=0.2, throttle_max_delay_sec=0.5)
        values.update(options)
        try:
            return Crawler(CrawlConfig(**values)).run()
        finally:
            self.server.shutdown()


def _paths(crawl):
    return [p["url"].split("/", 3)[3] for p in crawl["pages"]]


@pytest.fixture(scope="module")
def bulk_run():
    server = PostServer()
    crawl = server.crawl()
    return crawl, server.requests


def test_nonstandard_sitemap_and_rss_are_found(bulk_run):
    crawl, _ = bulk_run
    sources = {(s["url"].split("/", 3)[3], s["type"], s["source"]) for s in crawl["meta"]["sitemap"]["sources"]}
    assert ("sitemap.xml", "sitemap", "자동 탐색") in sources
    assert ("all/sitemap.xml", "sitemap", "자동 탐색") in sources
    assert ("rss", "rss", "자동 탐색") in sources
    paths = _paths(crawl)
    assert all(f"post/{i}" in paths for i in range(1, 13))
    assert len(paths) == 16


def test_throttled_pages_are_retried_with_longer_delay(bulk_run):
    crawl, requests = bulk_run
    events = crawl["meta"]["throttle_events"]
    reasons = {e["url"].split("/", 3)[3]: e["reason"] for e in events}
    assert reasons["post/5"].startswith("HTTP 429")
    assert reasons["post/9"] == "요청 제한 안내 페이지로 이동됨"
    assert requests.count("/post/5") == 2 and requests.count("/post/9") == 2
    post5 = next(p for p in crawl["pages"] if p["url"].endswith("/post/5"))
    assert post5["status"] == 200
    rate_page = next(p for p in crawl["pages"] if p["url"].endswith("/rate-limit.html"))
    assert rate_page["status"] == 200
    assert crawl["meta"]["final_delay_sec"] >= 0.2
    assert crawl["meta"]["stopped_reason"] is None


def test_post_pages_pass_gate_and_titles_are_shown(bulk_run):
    crawl, requests = bulk_run
    post7 = next(p for p in crawl["pages"] if p["url"].endswith("/post/7"))
    assert post7["gate"] is not None and post7["listed_title"] == "글 제목 7"
    assert "/clicked/agree" not in requests
    report = detect(crawl)
    ad = next(f for f in report["findings"] if "카지노 먹튀검증" in f["content"])
    assert ad["post_title"] == "글 제목 7"
    assert ad["pages"][0].endswith("/post/7")


def test_sitemap_limited_by_max_pages():
    crawl = PostServer().crawl(max_pages=5)
    assert len(crawl["pages"]) == 5
    assert crawl["meta"]["sitemap"]["urls"] == 15
    assert crawl["meta"]["sitemap"]["limited_to"] == 4


def test_explicit_atom_feed():
    server = PostServer()
    crawl = server.crawl(use_sitemap=False, sitemap_urls=[server.base + "board/feed.atom"], max_pages=2)
    assert [(s["type"], s["source"]) for s in crawl["meta"]["sitemap"]["sources"]] == [("atom", "지정")]
    assert _paths(crawl) == ["", "post/13"]
    assert crawl["pages"][1]["listed_title"] == "글 제목 13"


def test_continuous_blocking_stops_with_notice():
    crawl = PostServer(blocked=True).crawl(throttle_max_consecutive=3)
    assert crawl["meta"]["stopped_reason"] == "blocked"
    assert _paths(crawl) == ["", "terms.html", "privacy.html", "rate-limit.html"]
    assert any(s["url"].endswith("/post/1") and "요청 제한" in s["reason"] for s in crawl["skipped"])
    assert "요청을 계속 제한해" in crawl["meta"]["notes"][0]
    assert len(crawl["meta"]["throttle_events"]) == 3


def test_feed_parsing():
    rss = b'<rss><channel><item><title>T</title><link>/a</link></item><item><guid>https://x.kr/b</guid></item></channel></rss>'
    assert parse_document(rss, "https://x.kr/") == ("rss", [("https://x.kr/a", "T"), ("https://x.kr/b", "")], [])
    atom = (b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>A</title>'
            b'<link rel="self" href="/self"/><link href="/post/1"/></entry></feed>')
    assert parse_document(atom, "https://x.kr/") == ("atom", [("https://x.kr/post/1", "A")], [])
    assert parse_document(b"<html><body>not a feed</body></html>", "https://x.kr/")[0] == ""
