import functools
import http.server
import os
import threading
import time
from pathlib import Path

import pytest

from ad_sentinel.config import CrawlConfig
from ad_sentinel.crawler import Crawler

SITE_DIR = Path(__file__).parent / "fixtures" / "heavy"
RELEASE = threading.Event()


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/never-responds"):
            RELEASE.wait(120)
            return
        super().do_GET()


@pytest.fixture(scope="module")
def base_url():
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = "127.0.0.1,localhost"
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(SITE_DIR)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/"
    RELEASE.set()
    server.shutdown()


def _config(url, **overrides):
    values = dict(start_url=url, delay_sec=0, render_wait_ms=300, networkidle_timeout_ms=2000,
                  iframe_eval_timeout_ms=3000, respect_robots=False)
    values.update(overrides)
    return CrawlConfig(**values)


@pytest.fixture(scope="module")
def heavy_run(base_url):
    started = time.monotonic()
    result = Crawler(_config(base_url + "index.html", max_pages=3)).run()
    return result, time.monotonic() - started


def _page(result, name):
    return next(p for p in result["pages"] if p["url"].endswith(name))


def test_whole_crawl_finishes_in_time(heavy_run):
    result, elapsed = heavy_run
    assert len(result["pages"]) == 3
    assert elapsed < 60


def test_heavy_page_scans_all_elements(heavy_run):
    page = _page(heavy_run[0], "heavy.html")
    main = page["frames"][0]
    assert main["total_elements"] > 10000
    assert main["scanned"] == main["total_elements"]
    assert main["elapsed_ms"] < 15000
    assert page["timings"]["total"] < 30


def test_hidden_ad_kept_after_record_limit(heavy_run):
    page = _page(heavy_run[0], "heavy.html")
    assert page["frames"][0]["truncated"] is True
    ads = [e for e in page["elements"] if e["type"] == "hidden" and "카지노" in e["content"]]
    assert ads and "off-screen" in ads[0]["hidden_reasons"]
    assert "http://casino.invalid/" in ads[0]["links"]


def test_unresponsive_iframe_is_skipped(heavy_run):
    page = _page(heavy_run[0], "slow-frame.html")
    assert page["error"] is None
    main = next(f for f in page["frames"] if f["is_main"])
    assert "본문 내용" in main["text"]
    stuck = [f for f in page["frames"] if not f["is_main"]]
    assert stuck and stuck[0]["timed_out"] is True
    assert any(e["type"] == "iframe" and e["raw_src"] == "/never-responds" for e in page["elements"])


def test_page_total_timeout_moves_on(base_url):
    config = _config(base_url + "slow-frame.html", max_pages=1, page_total_timeout_sec=3,
                     networkidle_timeout_ms=10000, iframe_eval_timeout_ms=10000)
    started = time.monotonic()
    result = Crawler(config).run()
    elapsed = time.monotonic() - started
    page = result["pages"][0]
    assert page["timed_out"] is True
    assert page["timings"]["total"] < 6
    assert elapsed < 20
