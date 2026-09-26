import logging
import threading
import time
from collections import deque
from datetime import datetime
from typing import Callable

from playwright.sync_api import Error as PlaywrightError, Frame, Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from ad_sentinel import __version__
from ad_sentinel.config import ROBOTS_IGNORE_WARNING, CrawlConfig
from ad_sentinel.crawler.browser import launch_browser
from ad_sentinel.crawler.extract_js import EXTRACT_JS, FRAME_ELEMENT_JS
from ad_sentinel.crawler.robots import RobotsChecker
from ad_sentinel.crawler.url_utils import is_crawlable, is_same_site, normalize_url
from ad_sentinel.paths import setup_bundled_browser

log = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str], None]
PageCallback = Callable[[int, dict], None]

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
        on_page: PageCallback | None = None,
    ):
        self.config = config
        self.on_progress = on_progress
        self.on_page = on_page
        self.stop_event = stop_event or threading.Event()
        self.robots = RobotsChecker() if config.respect_robots else None

    def run(self) -> dict:
        cfg = self.config
        if cfg.url_list:
            seeds = list(dict.fromkeys(u for u in (normalize_url(x) for x in cfg.url_list) if u))
            if not seeds:
                raise ValueError("목록에 점검할 수 있는 http/https 주소가 없습니다.")
            mode, start_url, self.total = "list", seeds[0], len(seeds)
        else:
            start_url = normalize_url(cfg.start_url)
            if not start_url:
                raise ValueError(f"올바른 http/https 주소가 아닙니다: {cfg.start_url}")
            seeds, mode, self.total = [start_url], "site", cfg.max_pages

        result = {
            "meta": {
                "tool": "AD Sentinel",
                "version": __version__,
                "mode": mode,
                "start_url": start_url,
                "seed_urls": seeds,
                "started_at": _now(),
                "finished_at": None,
                "stopped_by_user": False,
                "robots_ignored": not cfg.respect_robots,
                "config": vars(cfg).copy(),
            },
            "pages": [],
            "skipped": [],
        }

        if not cfg.respect_robots:
            log.warning("[경고] %s", ROBOTS_IGNORE_WARNING)

        found_on = "URL 목록" if mode == "list" else ""
        queue = deque((u, 0, found_on) for u in seeds)
        seen = set(seeds)
        follow_links = mode == "site"

        setup_bundled_browser()
        with sync_playwright() as pw:
            browser = launch_browser(pw, cfg)
            context = browser.new_context(
                user_agent=USER_AGENT,
                locale="ko-KR",
                viewport={"width": 1366, "height": 900},
                ignore_https_errors=True,
                bypass_csp=True,
            )
            try:
                while queue and len(result["pages"]) < self.total:
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
                    if self.on_page:
                        self.on_page(len(result["pages"]), page_result)

                    if page_result["final_url"]:
                        seen.add(page_result["final_url"])

                    if follow_links and depth < cfg.max_depth:
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
        log.info("[%d/%d] %s", done, self.total, url or "완료")
        if self.on_progress:
            self.on_progress(done, self.total, url)

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
            "timed_out": False,
            "offsite_redirect": False,
            "timings": {},
            "frames_skipped": [],
            "frames": [],
            "elements": [],
        }
        started = time.monotonic()
        deadline = started + cfg.page_total_timeout_sec

        def remaining_ms() -> int:
            return max(0, int((deadline - time.monotonic()) * 1000))

        page = context.new_page()
        page.on("popup", lambda p: p.close())
        page.on("dialog", lambda d: d.dismiss())
        try:
            t = time.monotonic()
            response = page.goto(
                url, wait_until="domcontentloaded", timeout=max(1, min(cfg.page_timeout_ms, remaining_ms()))
            )
            page_result["status"] = response.status if response else None
            page_result["timings"]["load"] = round(time.monotonic() - t, 2)
            log.info("  로딩 %.2fs (HTTP %s)", page_result["timings"]["load"], page_result["status"])

            content_type = response.headers.get("content-type", "") if response else ""
            if content_type and "html" not in content_type:
                page_result["error"] = f"HTML 문서가 아님 ({content_type})"
                return page_result, []

            t = time.monotonic()
            self._wait_for_render(page, remaining_ms)
            page_result["timings"]["render"] = round(time.monotonic() - t, 2)
            log.info("  렌더링 대기·스크롤 %.2fs", page_result["timings"]["render"])

            page_result["final_url"] = normalize_url(page.url) or page.url
            page_result["offsite_redirect"] = not is_same_site(page.url, url, cfg.include_subdomains)

            t = time.monotonic()
            frames = page.frames
            if len(frames) > cfg.max_frames_per_page:
                log.warning("  프레임 %d개 중 %d개만 추출", len(frames), cfg.max_frames_per_page)
                page_result["frames_skipped"] = [
                    {"frame_url": f.url, "reason": f"프레임 수 상한({cfg.max_frames_per_page}개) 초과"}
                    for f in frames[cfg.max_frames_per_page:]
                ]
                frames = frames[: cfg.max_frames_per_page]
            for i, frame in enumerate(frames, 1):
                if remaining_ms() < 500:
                    page_result["timed_out"] = True
                    log.warning("  페이지 제한 시간(%ss) 초과 → 남은 프레임 %d개 건너뜀",
                                cfg.page_total_timeout_sec, len(frames) - i + 1)
                    page_result["frames_skipped"] += [
                        {"frame_url": f.url, "reason": f"페이지 제한 시간({cfg.page_total_timeout_sec:g}초) 초과"}
                        for f in frames[i - 1:]
                    ]
                    break
                self._extract_frame(frame, page_result, i, len(frames), remaining_ms())
            page_result["timings"]["extract"] = round(time.monotonic() - t, 2)

            main = next((f for f in page_result["frames"] if f["is_main"]), None)
            page_result["title"] = main["title"] if main else ""

        except PlaywrightError as e:
            page_result["error"] = str(e).strip().splitlines()[0]
            if isinstance(e, PlaywrightTimeoutError):
                page_result["timed_out"] = True
            log.warning("  페이지 수집 실패 %s: %s", url, page_result["error"])
        finally:
            try:
                page.close()
            except PlaywrightError:
                pass

        page_result["timings"]["total"] = round(time.monotonic() - started, 2)
        log.info("  페이지 완료 %.2fs (프레임 %d개, 레코드 %d개%s)", page_result["timings"]["total"],
                 len(page_result["frames"]), len(page_result["elements"]),
                 ", 시간 초과" if page_result["timed_out"] else "")

        links = [] if page_result["offsite_redirect"] else self._next_links(page_result)
        return page_result, links

    def _evaluate(self, frame: Frame, js: str, arg, timeout_ms: int):
        expression = "(arg) => ({ value: (" + js + ")(arg) })"
        handle = frame.wait_for_function(expression, arg=arg, timeout=max(1, timeout_ms), polling=100)
        try:
            return handle.json_value()["value"]
        finally:
            handle.dispose()

    def _wait_for_render(self, page: Page, remaining_ms: Callable[[], int]) -> None:
        cfg = self.config
        try:
            page.wait_for_load_state("networkidle", timeout=max(1, min(cfg.networkidle_timeout_ms, remaining_ms())))
        except PlaywrightError:
            pass
        try:
            scroll_timeout = min(5000, remaining_ms())
            self._evaluate(page.main_frame, "() => window.scrollTo(0, document.body ? document.body.scrollHeight : 0)",
                           None, scroll_timeout)
            page.wait_for_timeout(max(0, min(cfg.render_wait_ms, remaining_ms() - 1000)))
            self._evaluate(page.main_frame, "() => window.scrollTo(0, 0)", None, min(5000, remaining_ms()))
        except PlaywrightError as e:
            log.warning("  스크롤 실패: %s", str(e).strip().splitlines()[0])

    def _extract_frame(self, frame: Frame, page_result: dict, index: int, count: int, remaining_ms: int) -> None:
        cfg = self.config
        if frame.is_detached():
            return
        frame_timeout = cfg.frame_eval_timeout_ms if frame.parent_frame is None else cfg.iframe_eval_timeout_ms
        timeout_ms = min(frame_timeout, remaining_ms)
        budget_ms = max(300, min(cfg.extract_time_budget_ms, int(timeout_ms * 0.7)))
        started = time.monotonic()

        frame_path, src = self._frame_path(frame, timeout_ms)
        loaded_url = "" if frame.url in ("", "about:blank") and src else frame.url
        frame_url = loaded_url or src
        frame_info = {
            "frame_url": frame_url,
            "src": src,
            "loaded": bool(loaded_url),
            "frame_path": frame_path,
            "is_main": frame.parent_frame is None,
            "title": "",
            "text": "",
            "truncated": False,
            "timed_out": False,
            "scanned": 0,
            "total_elements": 0,
            "elapsed_ms": 0,
            "error": None,
        }
        label = "메인" if frame_info["is_main"] else "iframe"
        try:
            data = self._evaluate(
                frame,
                EXTRACT_JS,
                {
                    "maxRecords": cfg.max_elements_per_frame,
                    "maxScan": cfg.max_scan_elements,
                    "maxTextLen": cfg.max_text_len,
                    "timeBudgetMs": budget_ms,
                },
                max(1, timeout_ms - int((time.monotonic() - started) * 1000)),
            )
        except PlaywrightError as e:
            frame_info["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            if isinstance(e, PlaywrightTimeoutError):
                frame_info["timed_out"] = True
                frame_info["error"] = f"추출 시간 초과 ({timeout_ms / 1000:.1f}s)"
            else:
                frame_info["error"] = str(e).strip().splitlines()[0]
            page_result["frames"].append(frame_info)
            log.warning("  프레임 %d/%d %s %s → 건너뜀: %s", index, count, label, frame_url[:80], frame_info["error"])
            return

        frame_info["title"] = data["title"]
        frame_info["text"] = data["text"]
        frame_info["truncated"] = data["truncated"]
        frame_info["timed_out"] = data["timed_out"]
        frame_info["scanned"] = data["scanned"]
        frame_info["total_elements"] = data["total_elements"]
        frame_info["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        page_result["frames"].append(frame_info)

        for rec in data["records"]:
            rec["frame_url"] = frame_url
            rec["frame_path"] = frame_path
            page_result["elements"].append(rec)

        notes = []
        if data["timed_out"]:
            notes.append(f"스크립트 시간 예산 {budget_ms / 1000:.1f}s 초과로 일부만 검사")
        if data["truncated"]:
            notes.append(f"텍스트·링크 수집 상한 {cfg.max_elements_per_frame}개 도달")
        log.info("  프레임 %d/%d %s %.2fs (스크립트 %.2fs) 요소 %d개 중 %d개 검사, 레코드 %d개%s %s",
                 index, count, label, frame_info["elapsed_ms"] / 1000, data["elapsed_ms"] / 1000,
                 data["total_elements"], data["scanned"], len(data["records"]),
                 " [" + ", ".join(notes) + "]" if notes else "", "" if frame_info["is_main"] else frame_url[:80])

    def _frame_path(self, frame: Frame, timeout_ms: int) -> tuple[list[str], str]:
        path = []
        src = ""
        cur = frame
        while cur.parent_frame is not None:
            try:
                handle = cur.frame_element()
                try:
                    info = self._evaluate(cur.parent_frame, FRAME_ELEMENT_JS, handle, min(3000, timeout_ms))
                finally:
                    handle.dispose()
                path.insert(0, info["selector"])
                if cur is frame:
                    src = info["src"]
            except PlaywrightError:
                path.insert(0, "(알 수 없음)")
            cur = cur.parent_frame
        return path, src

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
