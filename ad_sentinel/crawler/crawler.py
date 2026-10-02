import logging
import re
import threading
import time
from collections import deque
from datetime import datetime
from typing import Callable
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError, Frame, Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from ad_sentinel import __version__
from ad_sentinel.config import BOT_BLOCK_NOTICE, CLOAKING_ALL, CLOAKING_OFF, ROBOTS_IGNORE_WARNING, CrawlConfig
from ad_sentinel.crawler.browser import launch_browser
from ad_sentinel.crawler import cloaking, sitemap
from ad_sentinel.crawler.extract_js import EXTRACT_JS, FRAME_ELEMENT_JS
from ad_sentinel.crawler.gate import (BOT_BLOCK_HINT, DANGER_WORDS, EXIT_PATTERN, FIND_GATE_JS, FIND_MORE_JS, FOOTER_SELECTOR, GATE_PARTS,
                                      GATE_WORDS, JS_CLICK, MAX_GATE_CANDIDATES, PAGE_METRICS_JS, SCREEN_TEXT_JS,
                                      STRONG_GATE_WORDS,
                                      content_changed, content_grew, is_boilerplate_link)
from ad_sentinel.crawler.robots import RobotsChecker
from ad_sentinel.crawler.url_utils import is_crawlable, is_safe_to_visit, is_same_site, normalize_url
from ad_sentinel.paths import setup_bundled_browser

log = logging.getLogger(__name__)
notice = logging.getLogger("ad_sentinel.notice")

ProgressCallback = Callable[[int, int, str], None]
ERROR_PAGE_TEXT = re.compile(
    r"404|찾을\s*수\s*없|존재하지\s*않|길을\s*(잠깐\s*|잠시\s*)?잃|이동되었|없는\s*페이지|페이지가\s*없|"
    r"잘못된\s*(주소|경로|접근)|not\s*found|page\s*not|does\s*not\s*exist", re.IGNORECASE)
FEED_PATH = re.compile(r"\.(xml|rss|atom)(\.gz)?$|/(rss|feed|atom)/?$", re.IGNORECASE)
REPEAT_WARN = 3
HEAVY_RESOURCE = re.compile(r"\.(?:woff2?|ttf|otf|eot|mp4|m4v|webm|ogv|ogg|oga|mp3|m4a|aac|wav|flac|avi|mov|wmv|m3u8|mpd)"
                            r"(?:[?#]|$)", re.IGNORECASE)
SHRINK_SETTLE_SEC = 5
RATE_LIMIT_TEXT = re.compile(
    r"요청\s*(속도|횟수)?\s*제한|too\s*many\s*requests|rate\s*limit|과도한\s*(요청|접속)|"
    r"잠시\s*후\s*다시\s*(시도|접속)|접속이\s*(차단|제한)", re.IGNORECASE)
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
        self.gate_key = ""
        self.content_linked: set[str] = set()
        self.listed_titles: dict[str, str] = {}
        self.run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.delay = config.delay_sec
        self.sitemap_urls = list(config.sitemap_urls)
        self.gate_rejections = 0
        self.gate_disabled = False
        self.screens: dict[int, list[str]] = {}
        self.screen_suspect: dict[int, bool] = {}
        self.home_screen: int | None = None
        self.repeat_warned: set[int] = set()
        self.throttle_streak = 0
        self.blocked_resources = 0
        self.forbidden_streak = 0

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
            if FEED_PATH.search(urlsplit(start_url).path):
                parts = urlsplit(start_url)
                home = f"{parts.scheme}://{parts.netloc}/"
                self.sitemap_urls.append(start_url)
                notice.warning("시작 주소(%s)가 sitemap·RSS 주소로 보여 sitemap으로 읽고, 사이트 첫 화면(%s)부터 "
                               "점검합니다. sitemap 주소는 'sitemap 또는 RSS 주소' 칸에 넣어 주세요.", start_url, home)
                start_url, seeds = home, [home]

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
                "stopped_reason": None,
                "throttle_events": [],
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
            self._prepare_context(context)
            try:
                if mode == "site" and (cfg.use_sitemap or self.sitemap_urls):
                    added = self._add_sitemap_urls(context, start_url, queue, seen)
                    result["meta"]["sitemap"] = added
                while queue and len(result["pages"]) < self.total:
                    if self.stop_event.is_set():
                        result["meta"]["stopped_by_user"] = True
                        break

                    url, depth, found_on = queue.popleft()
                    if self.robots and not self.robots.allowed(url):
                        result["skipped"].append({"url": url, "reason": "robots.txt"})
                        continue

                    self._report(len(result["pages"]), url, len(queue))
                    page_result, links = self._crawl_page(context, url, depth, cfg.enter_gate,
                                                          first_page=not result["pages"])
                    reason = self._throttle_reason(page_result, url)
                    if reason:
                        if self._handle_throttle(result, url, reason, page_result):
                            queue.appendleft((url, depth, found_on))
                            continue
                        break
                    self.throttle_streak = 0
                    self.content_linked |= self._content_links(page_result)
                    page_result["found_on"] = found_on
                    page_result["listed_title"] = self.listed_titles.get(url, "")
                    result["pages"].append(page_result)
                    if len(result["pages"]) == 1 and page_result.get("error_page"):
                        result["meta"]["start_error"] = page_result["error_page"]
                        notice.warning("시작 주소가 오류 페이지입니다(%s). 입장 버튼은 누르지 않았습니다. 주소를 확인하세요: %s",
                                       page_result["error_page"], url)
                    self._track_screen(page_result)
                    cloaking_reason = self._cloaking_reason(page_result, first=len(result["pages"]) == 1)
                    if cloaking_reason:
                        self._check_cloaking(browser, page_result, cloaking_reason)
                    if self.on_page:
                        self.on_page(len(result["pages"]), page_result)

                    if page_result["final_url"]:
                        seen.add(page_result["final_url"])

                    if follow_links and depth < cfg.max_depth:
                        for link in links:
                            if link not in seen:
                                seen.add(link)
                                queue.append((link, depth + 1, url))

                    if queue and self.delay > 0:
                        self._sleep(self.delay)
            finally:
                context.close()
                browser.close()

        self._report(len(result["pages"]), "", 0)
        result["meta"]["final_delay_sec"] = self.delay
        result["meta"]["blocked_resources"] = self.blocked_resources
        result["meta"]["gate"] = next((p["gate"] for p in result["pages"] if p.get("gate")), None)
        result["meta"]["repeated_screens"] = [
            {"title": self._screen_title(result, urls[0]), "count": len(urls), "urls": urls[:10]}
            for key, urls in self.screens.items() if len(urls) >= REPEAT_WARN and self.screen_suspect.get(key)
        ]
        result["meta"]["duplicate_screens"] = [
            {"title": self._screen_title(result, urls[0]), "count": len(urls), "urls": urls[:10]}
            for key, urls in self.screens.items() if len(urls) >= 2 and not self.screen_suspect.get(key)
        ]
        result["meta"]["gate_rejections"] = self.gate_rejections
        result["meta"]["notes"] = self._notes(mode, result)
        for note in result["meta"]["notes"]:
            notice.info(note)
        result["meta"]["finished_at"] = _now()
        result["meta"]["page_count"] = len(result["pages"])
        return result

    def _report(self, done: int, url: str, pending: int) -> None:
        total = min(self.total, done + pending + (1 if url else 0))
        log.info("[%d/%d] %s", done, total, url or "완료")
        if self.on_progress:
            self.on_progress(done, total, url)

    def _track_screen(self, page_result: dict) -> None:
        main = next((f for f in page_result["frames"] if f["is_main"]), None)
        text = re.sub(r"\s+", "", (main or {}).get("text") or "")[:5000]
        if len(text) < 20:
            return
        key = hash((page_result.get("title") or "", text))
        if self.home_screen is None:
            self.home_screen = key
        moved = normalize_url(page_result.get("final_url") or "") not in ("", normalize_url(page_result["url"]))
        reclicked = bool(page_result.get("gate") or page_result.get("gate_rejected"))
        if key == self.home_screen or moved or reclicked:
            self.screen_suspect[key] = True
        urls = self.screens.setdefault(key, [])
        if page_result["url"] not in urls:
            urls.append(page_result["url"])
        if len(urls) >= REPEAT_WARN and self.screen_suspect.get(key) and key not in self.repeat_warned:
            self.repeat_warned.add(key)
            notice.warning("게시글 대신 같은 화면이 반복 점검되고 있습니다: 제목 '%s'인 화면이 서로 다른 주소 %d곳에서 똑같이 "
                           "나왔습니다. (예: %s)", page_result.get("title") or "(제목 없음)", len(urls), ", ".join(urls[:3]))

    @staticmethod
    def _screen_title(result: dict, url: str) -> str:
        return next((p.get("title") or "" for p in result["pages"] if p["url"] == url), "")

    @staticmethod
    def _error_page_reason(page_result: dict) -> str:
        status = page_result.get("status") or 0
        if status >= 400:
            return f"HTTP {status}"
        main = next((f for f in page_result["frames"] if f["is_main"]), None)
        text = ((main or {}).get("text") or "")
        if len(re.sub(r"\s+", "", text)) < 800 and ERROR_PAGE_TEXT.search((page_result.get("title") or "") + " " + text):
            return "오류 안내 문구가 있는 짧은 페이지(소프트 404)"
        return ""

    def _sleep(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while not self.stop_event.is_set() and time.monotonic() < end:
            time.sleep(min(0.2, max(0.0, end - time.monotonic())))

    def _throttle_reason(self, page_result: dict, url: str) -> str:
        status = page_result.get("status")
        if status == 429:
            return "HTTP 429 요청이 너무 많음"
        if status == 503 and page_result.get("retry_after"):
            return "HTTP 503 일시적으로 사용할 수 없음"
        if status == 403:
            self.forbidden_streak += 1
            if self.forbidden_streak >= 3:
                return "HTTP 403 접근 거부가 연속 3회"
        else:
            self.forbidden_streak = 0
        final = page_result.get("final_url") or ""
        if final and urlsplit(final).path != urlsplit(url).path:
            main = next((f for f in page_result["frames"] if f["is_main"]), None)
            text = (page_result.get("title") or "") + " " + ((main or {}).get("text") or "")[:2000]
            if RATE_LIMIT_TEXT.search(text):
                return "요청 제한 안내 페이지로 이동됨"
        return ""

    def _handle_throttle(self, result: dict, url: str, reason: str, page_result: dict) -> bool:
        cfg = self.config
        self.throttle_streak += 1
        self.delay = min(cfg.throttle_max_delay_sec, max(self.delay * 2, cfg.throttle_backoff_min_sec))
        wait = self.delay
        retry_after = page_result.get("retry_after") or ""
        if retry_after.strip().isdigit():
            wait = min(cfg.throttle_max_delay_sec * 2, max(wait, float(retry_after.strip())))
        result["meta"]["throttle_events"].append(
            {"url": url, "reason": reason, "delay_sec": self.delay, "wait_sec": wait, "at": _now()})
        if self.throttle_streak >= cfg.throttle_max_consecutive:
            result["meta"]["stopped_reason"] = "blocked"
            result["meta"]["blocked_reason"] = reason
            result["skipped"].append({"url": url, "reason": f"요청 제한({reason})으로 점검 중단"})
            notice.warning("사이트가 요청을 계속 제한해(%s) 점검을 멈췄습니다.", reason)
            return False
        notice.warning("요청이 제한되었습니다(%s). 요청 간격을 %g초로 늘리고 %g초 뒤 다시 시도합니다.",
                       reason, self.delay, wait)
        self._sleep(wait)
        return not self.stop_event.is_set()

    def _crawl_page(self, context, url: str, depth: int, allow_gate: bool = False,
                    first_page: bool = False) -> tuple[dict, list[str]]:
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
            "gate": None,
            "gate_attempt": None,
            "gate_rejected": None,
            "error_page": "",
            "timings": {},
            "frames_skipped": [],
            "frames": [],
            "elements": [],
        }
        started = time.monotonic()
        self._deadline = started + cfg.page_total_timeout_sec

        def remaining_ms() -> int:
            return max(0, int((self._deadline - time.monotonic()) * 1000))

        page = context.new_page()
        page.on("popup", lambda p: p.close())
        page.on("dialog", lambda d: d.dismiss())
        try:
            t = time.monotonic()
            response = page.goto(
                url, wait_until="domcontentloaded", timeout=max(1, min(cfg.page_timeout_ms, remaining_ms()))
            )
            page_result["status"] = response.status if response else None
            page_result["retry_after"] = response.headers.get("retry-after", "") if response else ""
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
            self._extract_all(page, page_result, remaining_ms)
            page_result["timings"]["extract"] = round(time.monotonic() - t, 2)

            page_result["error_page"] = self._error_page_reason(page_result)
            if page_result["error_page"]:
                log.warning("  오류 페이지로 보여 입장 버튼을 누르지 않음: %s", page_result["error_page"])
            elif (allow_gate and not page_result["offsite_redirect"] and remaining_ms() > 3000
                    and (first_page or not self.gate_disabled)):
                self._try_gate(page, page_result, url, remaining_ms, first_page)

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

    def _extract_all(self, page: Page, page_result: dict, remaining_ms: Callable[[], int]) -> None:
        cfg = self.config
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
        main = next((f for f in page_result["frames"] if f["is_main"]), None)
        page_result["title"] = main["title"] if main else ""

    def _prepare_context(self, context) -> None:
        if self.config.block_heavy_resources:
            context.route(HEAVY_RESOURCE, self._block)

    def _block(self, route) -> None:
        self.blocked_resources += 1
        try:
            route.abort("blockedbyclient")
        except PlaywrightError:
            pass

    def _cloaking_reason(self, page_result: dict, first: bool) -> str:
        mode = self.config.cloaking_check
        if mode == CLOAKING_OFF or page_result.get("error") or self.stop_event.is_set():
            return ""
        suspicion = self._suspicion(page_result)
        if suspicion:
            return suspicion
        if first:
            return "첫 페이지"
        return "모든 페이지 검사" if mode == CLOAKING_ALL else ""

    @staticmethod
    def _suspicion(page_result: dict) -> str:
        from ad_sentinel.detector.keywords import find_contact, find_keywords

        if page_result.get("offsite_redirect"):
            return "다른 사이트로 이동"
        texts = [page_result.get("title") or ""]
        for e in page_result["elements"]:
            if e["type"] in ("hidden", "noscript", "redirect") and (e.get("links") or e["type"] == "redirect"):
                return "숨김 링크·자동 이동"
            if e.get("content"):
                texts.append(e["content"])
        joined = "\n".join(texts)
        words = find_keywords(joined)
        if any(k.weight >= 2 for k in words) or (words and find_contact(joined)):
            return "광고 키워드"
        return ""

    def _check_cloaking(self, browser, page_result: dict, reason: str) -> None:
        url = page_result["final_url"] or page_result["url"]
        log.info("  클로킹 검사(%s): 일반 PC·구글봇·구글 검색 경유·모바일로 각각 열어 비교", reason)
        started = time.monotonic()
        data = cloaking.check(browser, url, USER_AGENT, self.config.page_timeout_ms, self._evaluate,
                              stop=self.stop_event.is_set, prepare=self._prepare_context)
        data["reason"] = reason
        page_result["cloaking"] = data
        failed = [p["label"] for p in data["profiles"] if p["error"]]
        log.info("  클로킹 검사 완료 %.1fs%s", time.monotonic() - started,
                 f" (열지 못함: {', '.join(failed)})" if failed else "")

    def _content_links(self, page_result: dict) -> set[str]:
        records = [r for r in page_result["elements"] if r["type"] == "link" and not is_boilerplate_link(r)]
        return set(self._next_links({**page_result, "elements": records}))

    def _metrics(self, page: Page, timeout_ms: int) -> dict | None:
        try:
            return self._evaluate(page.main_frame, PAGE_METRICS_JS, None, max(1, min(3000, timeout_ms)))
        except PlaywrightError:
            return None

    def _wait_for_change(self, page: Page, before: dict, limit_ms: int, test=content_changed) -> dict | None:
        end = time.monotonic() + limit_ms / 1000
        last, stable, saw_loading = None, 0, False
        floor, still_hash, still_since = None, None, 0.0
        while time.monotonic() < end:
            page.wait_for_timeout(300)
            now = self._metrics(page, int((end - time.monotonic()) * 1000))
            if not now:
                continue
            shrunk = False
            if test is content_changed and _shrunk(before, now):
                floor = now["text"] if floor is None else min(floor, now["text"])
                if now["hash"] != still_hash:
                    still_hash, still_since = now["hash"], time.monotonic()
                grown = now["text"] >= max(floor * 2, floor + 60)
                shrunk = not grown and time.monotonic() - still_since < SHRINK_SETTLE_SEC
                if not grown and not shrunk:
                    now["unsettled"] = True
            if now.get("loading") or shrunk:
                if not saw_loading:
                    reason = "로딩 표시" if now.get("loading") else f"화면 글자 {before['text']}자 → {now['text']}자로 급감"
                    log.info("  로딩 화면으로 보여 대기 중... (%s)", reason)
                saw_loading, stable = True, 0
                now["unsettled"] = True
                last = now
            elif test(before, now):
                if last and abs(now["text"] - last["text"]) < 20 and abs(now["nodes"] - last["nodes"]) < 5:
                    stable += 1
                    if stable >= 3:
                        return now
                else:
                    stable = 0
            last = now
        if last and test(before, last) and (not last.get("loading") or saw_loading):
            if last.get("unsettled"):
                log.warning("  대기 시간(%.0f초) 안에 로딩이 끝나지 않음", limit_ms / 1000)
            return last
        return None

    def _click(self, page: Page, selector: str, timeout_ms: int) -> bool:
        try:
            page.locator(selector).first.click(timeout=max(1, min(3000, timeout_ms)))
            return True
        except PlaywrightError:
            pass
        try:
            return bool(self._evaluate(page.main_frame, JS_CLICK, selector, max(1, min(3000, timeout_ms))))
        except PlaywrightError:
            return False

    def _try_gate(self, page: Page, page_result: dict, url: str, remaining_ms: Callable[[], int],
                  first_page: bool = False) -> None:
        cfg = self.config
        first = first_page and not self.gate_key
        own = {normalize_url(url), page_result["final_url"]}
        links_before = set(self._next_links(page_result)) - own
        content_before = self._content_links(page_result) - own
        if not first and len(content_before) >= cfg.gate_link_threshold:
            return
        options = {"gateWords": GATE_WORDS, "gateParts": GATE_PARTS, "strongWords": STRONG_GATE_WORDS,
                   "dangerWords": DANGER_WORDS, "footerSelector": FOOTER_SELECTOR, "prefer": self.gate_key,
                   "exitPattern": EXIT_PATTERN,
                   "maxCandidates": MAX_GATE_CANDIDATES}
        try:
            candidates = self._evaluate(page.main_frame, FIND_GATE_JS, options, min(5000, remaining_ms()))
        except PlaywrightError as e:
            log.warning("  입장 버튼 찾기 실패: %s", str(e).strip().splitlines()[0])
            return
        if not first or len(content_before) >= cfg.gate_link_threshold:
            skipped = [c["text"] for c in candidates or [] if c["weak"]]
            candidates = [c for c in candidates or [] if not c["weak"]]
            if skipped:
                log.info("  본문 링크가 %d개라 흔한 문구 버튼은 누르지 않음: %s", len(content_before), ", ".join(skipped))
        if not candidates:
            if first:
                log.info("  입장 버튼 후보 없음 (본문 링크 %d개)", len(content_before))
            return

        before_url = page.url
        titles_before = self._titles(page_result)
        shots: list[str] = []
        for n, gate in enumerate(candidates if first else candidates[:1], 1):
            if remaining_ms() < 3000:
                return
            before = self._metrics(page, remaining_ms())
            if not before:
                return
            log.info("  본문 링크 %d개(전체 %d개) → 입장 버튼 후보 '%s' 클릭",
                     len(content_before), len(links_before), gate["text"])
            if not self._click(page, f"[data-ad-sentinel-gate='{gate['index']}']", remaining_ms()):
                log.info("  '%s' 클릭 실패", gate["text"])
                continue
            if first:
                self._screenshot(page, f"gate{n}_clicked", shots)
            after = self._wait_for_change(page, before, min(cfg.gate_wait_ms, max(0, remaining_ms() - 2000)))
            if first:
                self._screenshot(page, f"gate{n}_waited", shots)
            if after:
                unsettled = bool(after.get("unsettled"))
                break
            log.info("  '%s'을 눌렀지만 화면 변화가 없음", gate["text"])
            page_result["gate_attempt"] = {"text": gate["text"], "changed": False}
        else:
            return

        moved_to = normalize_url(page.url) or page.url
        if not first and moved_to != (normalize_url(url) or url) and moved_to != page_result["final_url"]:
            self.gate_rejections += 1
            page_result["gate_rejected"] = {"text": gate["text"], "moved_to": moved_to}
            notice.warning("'%s' 버튼을 다시 눌렀더니 다른 페이지(%s)로 이동해, 그 결과는 버리고 원래 페이지 내용으로 "
                           "점검합니다: %s", gate["text"], moved_to, url)
            if self.gate_rejections >= 3 and not self.gate_disabled:
                self.gate_disabled = True
                self.gate_key = ""
                notice.warning("입장 버튼 재클릭이 계속 다른 페이지로 이동해, 이후 페이지에서는 입장 버튼을 누르지 않습니다.")
            return

        try:
            page.wait_for_load_state("domcontentloaded", timeout=max(1, min(5000, remaining_ms())))
        except PlaywrightError:
            pass
        self._wait_for_render(page, remaining_ms)
        self._reextract(page, page_result, remaining_ms)
        after = self._metrics(page, remaining_ms()) or after

        after_url = normalize_url(page.url) or page.url
        page_result["final_url"] = after_url
        page_result["offsite_redirect"] = not is_same_site(page.url, url, cfg.include_subdomains)
        new_links = set(self._next_links(page_result)) - links_before - own - {after_url}
        page_result["gate"] = {
            "text": gate["text"], "url_before": before_url, "url_after": after_url,
            "url_changed": after_url != (normalize_url(before_url) or before_url),
            "links_before": len(content_before),
            "links_after": len(self._content_links(page_result) - own - {after_url}),
            "new_links": len(new_links),
            "text_before": before["text"], "text_after": after["text"],
            "load_more_clicks": 0,
            "incomplete": unsettled or bool(after.get("loading")),
            "screenshots": shots,
        }
        page_result["gate_attempt"] = None
        if first:
            notice.info("입장 버튼('%s') 클릭 후 점검 계속 (화면 글자 %d자 → %d자, 새 링크 %d개)",
                        gate["text"], before["text"], after["text"], len(new_links))
            if page_result["gate"]["incomplete"]:
                notice.warning("입장 후 화면이 다 불러와지지 않았을 수 있습니다(화면 글자 %d자 → %d자). "
                               "고급 설정에서 페이지당 제한 시간을 늘리거나 '브라우저 창 보이기'로 화면을 비교해 보세요.",
                               before["text"], after["text"])
                page_result["gate"]["block_hints"] = self._block_hints(page, page_result, remaining_ms)
        else:
            log.info("  입장 버튼 다시 클릭 후 점검 계속")
        self.gate_key = gate["key"]

        if cfg.load_more and not page_result["offsite_redirect"]:
            self._load_more(page, page_result, remaining_ms, full=first)
        if first:
            titles = [t for t in self._titles(page_result) if t not in titles_before]
            page_result["gate"]["post_titles"] = len(titles)
            page_result["gate"]["titles_before"] = len(titles_before)
            if titles:
                notice.info("입장 후 새로 나타난 글 제목 %d개를 수집했습니다. (예: %s, 입장 전 화면 제목 %d개는 제외)",
                            len(titles), ", ".join(t[:20] for t in titles[:3]), len(titles_before))
            elif page_result["gate"]["new_links"] or page_result["gate"]["url_changed"]:
                log.info("  입장 후 새 링크 %d개로 게시판 페이지를 따로 점검합니다.", page_result["gate"]["new_links"])
            else:
                notice.warning("입장 후 새로 나타난 글 제목이 없습니다. (입장 전 화면 제목 %d개는 제외) "
                               "피드 게시글을 수집하지 못했을 수 있습니다.", len(titles_before))

    @staticmethod
    def _titles(page_result: dict) -> list[str]:
        return list(dict.fromkeys(e["context_title"] for e in page_result["elements"]
                                  if e.get("context_title") and not e.get("frame_path")))

    def _screenshot(self, page: Page, label: str, shots: list[str]) -> None:
        if not self.config.screenshot_dir:
            return
        folder = Path(self.config.screenshot_dir)
        path = folder / f"{self.run_stamp}_{label}.png"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(path), timeout=5000)
        except (PlaywrightError, OSError) as e:
            log.info("  화면 캡처 실패(%s): %s", label, str(e).strip().splitlines()[0] if str(e).strip() else e)
            return
        shots.append(str(path))
        log.info("  화면 캡처 저장: %s", path)

    def _block_hints(self, page: Page, page_result: dict, remaining_ms: Callable[[], int]) -> list[str]:
        try:
            screen = self._evaluate(page.main_frame, SCREEN_TEXT_JS, None, max(1, min(3000, remaining_ms()))) or ""
        except PlaywrightError:
            screen = ""
        texts = [screen] + [e.get("content") or "" for e in page_result["elements"] if not e.get("frame_path")]
        return _hints(texts)

    def _reextract(self, page: Page, page_result: dict, remaining_ms: Callable[[], int]) -> None:
        old_elements, old_frames = page_result["elements"], page_result["frames"]
        page_result["elements"], page_result["frames"] = [], []
        self._extract_all(page, page_result, remaining_ms)
        page_result["elements"] = _dedupe_records(old_elements + page_result["elements"])
        keys = {(f["frame_url"], tuple(f["frame_path"])) for f in page_result["frames"]}
        page_result["frames"] += [f for f in old_frames if (f["frame_url"], tuple(f["frame_path"])) not in keys]

    def _load_more(self, page: Page, page_result: dict, remaining_ms: Callable[[], int], full: bool = True) -> None:
        cfg = self.config
        budget = cfg.load_more_timeout_sec if full else min(15.0, cfg.load_more_timeout_sec)
        max_steps = cfg.load_more_max_clicks if full else min(3, cfg.load_more_max_clicks)
        self._deadline = max(self._deadline, time.monotonic() + budget + 15)
        stop_at = time.monotonic() + budget
        start_url = page.url
        options = {"dangerWords": DANGER_WORDS}
        clicks, scrolls, misses, reveal = 0, 0, 0, 0
        first_metrics = self._metrics(page, remaining_ms())
        if not first_metrics:
            return
        while clicks + scrolls < max_steps and time.monotonic() < stop_at and remaining_ms() > 3000:
            if self.stop_event.is_set():
                break
            before = self._metrics(page, remaining_ms())
            if not before:
                break
            try:
                more = self._evaluate(page.main_frame, FIND_MORE_JS, options, min(5000, remaining_ms()))
            except PlaywrightError:
                more = None
            reveal = max(reveal, (more or {}).get("reveal", 0))
            if more and more.get("found"):
                if not self._click_js(page, "[data-ad-sentinel-more='1']", remaining_ms()):
                    break
                action = "click"
            elif not full:
                break
            else:
                try:
                    self._evaluate(page.main_frame, "() => window.scrollTo(0, document.documentElement.scrollHeight)",
                                   None, min(3000, remaining_ms()))
                except PlaywrightError:
                    break
                action = "scroll"
            wait = min(5000, max(0, int((stop_at - time.monotonic()) * 1000)))
            after = self._wait_for_change(page, before, wait, test=content_grew)
            if normalize_url(page.url) != normalize_url(start_url):
                log.info("  더보기 중 주소가 바뀌어 멈춤: %s", page.url)
                break
            if not after:
                misses += 1
                if misses >= 2:
                    break
                continue
            misses = 0
            if action == "click":
                clicks += 1
            else:
                scrolls += 1
            log.info("  %s: 화면 글자 %d자", f"더보기 클릭 {clicks}회" if action == "click" else f"스크롤 로딩 {scrolls}회",
                     after["text"])

        if reveal:
            log.info("  이미지 보기·펼치기용 '더보기' %d개는 누르지 않음 (게시글 추가 로딩 버튼이 아님)", reveal)
        if not clicks and not scrolls and full:
            notice.info("더보기·추가 로딩 없음 (게시글 더보기 버튼이 없고, 맨 아래로 스크롤해도 새 글이 나오지 않음)")
        if clicks or scrolls:
            last = self._metrics(page, remaining_ms()) or first_metrics
            self._reextract(page, page_result, remaining_ms)
            page_result["gate"]["load_more_clicks"] = clicks
            page_result["gate"]["load_more_scrolls"] = scrolls
            parts = [f"더보기 {clicks}회 클릭"] if clicks else []
            if scrolls:
                parts.append(f"스크롤 추가 로딩 {scrolls}회")
            (notice.info if full else log.info)("%s, 게시글 영역 추가 수집 (화면 글자 %d자 → %d자)",
                                                 "·".join(parts), first_metrics["text"], last["text"])

    def _click_js(self, page: Page, selector: str, timeout_ms: int) -> bool:
        try:
            return bool(self._evaluate(page.main_frame, JS_CLICK, selector, max(1, min(3000, timeout_ms))))
        except PlaywrightError:
            return False

    def _add_sitemap_urls(self, context, start_url: str, queue: deque, seen: set) -> dict:
        cfg = self.config
        explicit = list(self.sitemap_urls)
        try:
            found = sitemap.discover(context.request, start_url, cfg.max_sitemap_urls, explicit=explicit,
                                     auto=cfg.use_sitemap)
        except Exception as e:
            log.warning("sitemap·RSS 읽기 실패: %s", e)
            return {"files": [], "sources": [], "urls": 0}
        if self.robots and found.robots_txt is not None:
            self.robots.preload(found.origin, found.robots_txt)
        added = 0
        for raw in found.pages:
            u = normalize_url(raw)
            if not u:
                continue
            if found.titles.get(raw):
                self.listed_titles.setdefault(u, found.titles[raw])
            if (u not in seen and is_crawlable(u) and is_safe_to_visit(u)
                    and is_same_site(u, start_url, cfg.include_subdomains)):
                seen.add(u)
                queue.append((u, 1, "sitemap.xml"))
                added += 1
        for src in explicit:
            if not any(s["source"] == "지정" for s in found.sources):
                notice.warning("지정한 sitemap·RSS 주소를 읽지 못했습니다: %s", src)
                break
        info = {"files": [s["url"] for s in found.sources], "sources": found.sources, "urls": added,
                "missing": found.missing}
        if found.sources:
            detail = ", ".join(f"{urlsplit(s['url']).path or '/'} {s['urls']}개" for s in found.sources if s["urls"])
            notice.info("sitemap·RSS에서 주소 %d개를 찾아 점검 목록에 추가했습니다. (%s)", added, detail or "새 주소 없음")
            capacity = max(0, self.total - 1)
            if added > capacity:
                info["limited_to"] = capacity
                notice.info("sitemap 주소 %d개 중 %d개만 점검합니다. (최대 페이지 수 %d 설정, 모두 점검하려면 늘리세요)",
                            added, capacity, self.total)
        else:
            log.info("sitemap·RSS 없음")
        return info

    def _notes(self, mode: str, result: dict) -> list[str]:
        notes = []
        gate = result["meta"].get("gate")
        if gate and gate.get("incomplete"):
            hints = list(gate.get("block_hints") or [])
            for p in result["pages"]:
                hints += _hints([p.get("title") or "", p.get("listed_title") or ""])
            hints = list(dict.fromkeys(hints))
            if hints:
                gate["block_hints"] = hints
                notes.append(f"{BOT_BLOCK_NOTICE} (입장 후 로딩 화면에서 멈춤, 보안 안내 문구: {', '.join(hints[:3])})")
        if result["meta"].get("start_error"):
            notes.append(f"시작 주소가 오류 페이지입니다({result['meta']['start_error']}). 입장 버튼은 누르지 않았습니다. "
                         "주소가 맞는지 브라우저로 확인해 보세요.")
        for screen in result["meta"].get("repeated_screens") or []:
            notes.append(f"게시글 대신 같은 화면이 반복 점검되었습니다: 제목 '{screen['title'] or '(제목 없음)'}'인 화면이 "
                         f"서로 다른 주소 {screen['count']}곳에서 똑같이 나왔습니다. 이 주소들의 실제 내용은 점검되지 않았을 수 있습니다.")
        return notes + self._base_notes(mode, result)

    def _base_notes(self, mode: str, result: dict) -> list[str]:
        cfg = self.config
        pages = result["pages"]
        checked = len(pages)
        if result["meta"].get("stopped_reason") == "blocked":
            return [f"사이트가 요청을 계속 제한해({result['meta']['blocked_reason']}) {checked}페이지까지만 점검하고 멈췄습니다. "
                    f"고급 설정에서 요청 간격을 늘리거나(현재 {self.delay:g}초) 잠시 뒤 다시 점검해 보세요."]
        if mode != "site" or result["meta"]["stopped_by_user"] or not pages:
            return []
        if cfg.max_pages <= 1 or cfg.max_depth == 0:
            return []
        linked = [p for p in pages[1:] if {p["url"], p.get("final_url")} & self.content_linked]
        gate = result["meta"].get("gate")
        if checked >= 2 and not linked and not gate:
            from_sitemap = sum(1 for p in pages[1:] if p.get("found_on") == "sitemap.xml")
            if from_sitemap == checked - 1:
                source = "sitemap.xml에 있는 주소"
            elif from_sitemap:
                source = "sitemap.xml과 약관·안내 같은 고정 링크"
            else:
                source = "약관·안내 같은 고정 링크"
            return [f"{source}로만 {checked}페이지를 점검했습니다. 게시판 페이지를 찾지 못했을 수 있습니다. "
                    "입장 버튼이 있는 사이트라면 입장 후 주소를, 게시판이 있다면 게시판 주소를 시작 주소로 넣어보세요."]
        if checked > cfg.max_pages * 0.2 or cfg.max_pages - checked < 5:
            return []
        if result["meta"].get("sitemap", {}).get("urls"):
            return []
        if gate and (gate["links_after"] >= cfg.gate_link_threshold or gate.get("text_after", 0) > gate.get("text_before", 0)):
            return []
        if gate:
            return [f"입장 버튼을 누른 뒤에도 발견한 링크가 적어 {checked}페이지만 점검했습니다. "
                    "입장 후 주소를 시작 주소로 넣거나, 사이트에 sitemap.xml이 있는지 확인해 보세요."]
        if not self._may_have_missed(pages[0]):
            return []
        return [f"발견한 링크가 적어 {checked}페이지만 점검했습니다. "
                "입장 버튼이 있는 사이트라면 입장 후 주소를 시작 주소로 넣어보세요."]

    def _may_have_missed(self, first: dict) -> bool:
        base = first.get("final_url") or first["url"]
        links = {normalize_url(r.get("href", ""), base) for r in first["elements"]
                 if r["type"] == "link" and not is_boilerplate_link(r)}
        if len(links - {""}) >= self.config.gate_link_threshold:
            return False
        attempt = first.get("gate_attempt") or {}
        return not self.config.enter_gate or attempt.get("changed") is False

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
                    "footerSelector": FOOTER_SELECTOR,
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
            if (url and is_crawlable(url) and is_safe_to_visit(url)
                    and is_same_site(url, cfg.start_url, cfg.include_subdomains)):
                links.append(url)
        return list(dict.fromkeys(links))


def _dedupe_records(records: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for rec in records:
        key = (tuple(rec.get("frame_path", [])), rec.get("selector"), rec["type"], rec.get("content"),
               rec.get("href"), rec.get("src"))
        if key not in seen:
            seen.add(key)
            result.append(rec)
    return result


def _hints(texts: list[str]) -> list[str]:
    found = []
    for text in texts:
        for m in BOT_BLOCK_HINT.finditer(text):
            word = " ".join(m.group(0).split())
            if word not in found:
                found.append(word)
    return found


def _shrunk(before: dict, after: dict) -> bool:
    return after["text"] < 300 and after["text"] < before["text"] * 0.3
