import logging
import threading
import time
from collections import deque
from datetime import datetime
from typing import Callable

from playwright.sync_api import Error as PlaywrightError, Frame, Page, sync_playwright

from ad_sentinel import __version__
from ad_sentinel.config import CrawlConfig
from ad_sentinel.crawler.browser import launch_browser
from ad_sentinel.crawler.extract_js import EXTRACT_JS, SELECTOR_JS
from ad_sentinel.crawler.robots import RobotsChecker
from ad_sentinel.crawler.url_utils import is_crawlable, is_same_site, normalize_url
from ad_sentinel.paths import setup_bundled_browser

log = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str], None]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 AD-Sentinel/" + __version__
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Crawler:
    def __init__(
        self,
        config: CrawlConfig,
        on_progress: ProgressCallback | None = None,
        stop_event: threading.Event | None = None,
    ):
        self.config = config
        self.on_progress = on_progress
        self.stop_event = stop_event or threading.Event()
        self.robots = RobotsChecker() if config.respect_robots else None

    def run(self) -> dict:
        cfg = self.config
        start_url = normalize_url(cfg.start_url)
        if not start_url:
            raise ValueError(f"올바른 http/https 주소가 아닙니다: {cfg.start_url}")

        result = {
            "meta": {
                "tool": "AD Sentinel",
                "version": __version__,
                "start_url": start_url,
                "started_at": _now(),
                "finished_at": None,
                "stopped_by_user": False,
                "config": vars(cfg).copy(),
            },
            "pages": [],
            "skipped": [],
        }

        queue = deque([(start_url, 0, "")])
        seen = {start_url}

        setup_bundled_browser()
        with sync_playwright() as pw:
            browser = launch_browser(pw, cfg)
            context = browser.new_context(
                user_agent=USER_AGENT,
                locale="ko-KR",
                viewport={"width": 1366, "height": 900},
                ignore_https_errors=True,
            )
            try:
                while queue and len(result["pages"]) < cfg.max_pages:
                    if self.stop_event.is_set():
                        result["meta"]["stopped_by_user"] = True
                        break

                    url, depth, found_on = queue.popleft()
                    if self.robots and not self.robots.allowed(url):
                        result["skipped"].append({"url": url, "reason": "robots.txt"})
                        continue

                    self._report(len(result["pages"]), url)
                    page_result, links = self._crawl_page(context, url, depth)
                    page_result["found_on"] = found_on
                    result["pages"].append(page_result)

                    if page_result["final_url"]:
                        seen.add(page_result["final_url"])

                    if depth < cfg.max_depth:
                        for link in links:
                            if link not in seen:
                                seen.add(link)
                                queue.append((link, depth + 1, url))

                    if queue and cfg.delay_sec > 0:
                        time.sleep(cfg.delay_sec)
            finally:
                context.close()
                browser.close()

        self._report(len(result["pages"]), "")
        result["meta"]["finished_at"] = _now()
        result["meta"]["page_count"] = len(result["pages"])
        return result

    def _report(self, done: int, url: str) -> None:
        log.info("[%d/%d] %s", done, self.config.max_pages, url or "완료")
        if self.on_progress:
            self.on_progress(done, self.config.max_pages, url)

    def _crawl_page(self, context, url: str, depth: int) -> tuple[dict, list[str]]:
        cfg = self.config
        page_result = {
            "url": url,
            "final_url": "",
            "depth": depth,
            "status": None,
            "title": "",
            "crawled_at": _now(),
            "error": None,
            "offsite_redirect": False,
            "frames": [],
            "elements": [],
        }

        page = context.new_page()
        page.on("popup", lambda p: p.close())
        page.on("dialog", lambda d: d.dismiss())
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=cfg.page_timeout_ms)
            page_result["status"] = response.status if response else None

            content_type = response.headers.get("content-type", "") if response else ""
            if content_type and "html" not in content_type:
                page_result["error"] = f"HTML 문서가 아님 ({content_type})"
                return page_result, []

            self._wait_for_render(page)
            page_result["final_url"] = normalize_url(page.url) or page.url
            page_result["title"] = page.title()
            page_result["offsite_redirect"] = not is_same_site(
                page.url, cfg.start_url, cfg.include_subdomains
            )

            for frame in page.frames:
                self._extract_frame(frame, page_result)

        except PlaywrightError as e:
            page_result["error"] = str(e).strip().splitlines()[0]
            log.warning("페이지 수집 실패 %s: %s", url, page_result["error"])
        finally:
            page.close()

        links = [] if page_result["offsite_redirect"] else self._next_links(page_result)
        return page_result, links

    def _wait_for_render(self, page: Page) -> None:
        cfg = self.config
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightError:
            pass
        try:
            page.evaluate("window.scrollTo(0, document.body ? document.body.scrollHeight : 0)")
            page.wait_for_timeout(cfg.render_wait_ms)
            page.evaluate("window.scrollTo(0, 0)")
        except PlaywrightError:
            pass

    def _extract_frame(self, frame: Frame, page_result: dict) -> None:
        cfg = self.config
        if frame.is_detached():
            return
        frame_path = self._frame_path(frame)
        frame_info = {
            "frame_url": frame.url,
            "frame_path": frame_path,
            "is_main": frame.parent_frame is None,
            "title": "",
            "text": "",
            "truncated": False,
            "error": None,
        }
        try:
            data = frame.evaluate(
                EXTRACT_JS,
                {"maxElements": cfg.max_elements_per_frame, "maxTextLen": cfg.max_text_len},
            )
        except PlaywrightError as e:
            frame_info["error"] = str(e).strip().splitlines()[0]
            page_result["frames"].append(frame_info)
            return

        frame_info["title"] = data["title"]
        frame_info["text"] = data["text"]
        frame_info["truncated"] = data["truncated"]
        page_result["frames"].append(frame_info)

        for rec in data["records"]:
            rec["frame_url"] = frame.url
            rec["frame_path"] = frame_path
            page_result["elements"].append(rec)

    def _frame_path(self, frame: Frame) -> list[str]:
        path = []
        cur = frame
        while cur.parent_frame is not None:
            try:
                handle = cur.frame_element()
                path.insert(0, handle.evaluate(SELECTOR_JS))
            except PlaywrightError:
                path.insert(0, "(알 수 없음)")
            cur = cur.parent_frame
        return path

    def _next_links(self, page_result: dict) -> list[str]:
        cfg = self.config
        base = page_result["final_url"] or page_result["url"]
        links = []
        for rec in page_result["elements"]:
            if rec["type"] != "link":
                continue
            url = normalize_url(rec.get("href", ""), base)
            if url and is_crawlable(url) and is_same_site(url, cfg.start_url, cfg.include_subdomains):
                links.append(url)
        return links
