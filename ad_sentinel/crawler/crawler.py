"""1단계 핵심: 같은 사이트의 하위 페이지를 돌며 요소를 수집하는 크롤러.

동작 순서
  1. 시작 URL을 대기열(queue)에 넣는다.
  2. 대기열에서 URL을 하나 꺼내 브라우저(Playwright)로 연다. → 자바스크립트로 그려지는 내용까지 렌더링
  3. 메인 문서와 모든 iframe 문서에서 텍스트·링크·iframe·숨김 요소를 추출한다. (extract_js.py)
  4. 같은 사이트 링크를 대기열에 추가한다.
  5. 최대 페이지 수에 도달하거나 대기열이 빌 때까지 2~4 반복 (너비 우선 탐색, BFS)

GUI(3단계)에서 쓰기 위해
  - on_progress 콜백으로 진행 상황을 알리고
  - stop_event 로 중간에 멈출 수 있게 했다.
"""

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

# 진행 상황 콜백 형식: (방문한 페이지 수, 최대 페이지 수, 현재 URL)
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

    # ------------------------------------------------------------------
    # 전체 크롤링
    # ------------------------------------------------------------------
    def run(self) -> dict:
        """크롤링을 실행하고 결과 전체를 dict로 돌려준다. (storage.save_json 으로 저장)"""
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
            "pages": [],        # 방문한 페이지별 결과
            "skipped": [],      # robots.txt 등으로 방문하지 않은 URL
        }

        queue = deque([(start_url, 0, "")])  # (URL, 깊이, 이 링크를 발견한 페이지)
        seen = {start_url}                    # 대기열에 한 번이라도 들어간 URL (중복 방지)

        setup_bundled_browser()
        with sync_playwright() as pw:
            browser = launch_browser(pw, cfg)
            context = browser.new_context(
                user_agent=USER_AGENT,
                locale="ko-KR",
                viewport={"width": 1366, "height": 900},
                ignore_https_errors=True,  # 인증서가 만료된 공공기관 사이트도 점검할 수 있도록
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

                    # 최종 주소 기록 (리다이렉트로 같은 페이지를 또 방문하지 않도록)
                    if page_result["final_url"]:
                        seen.add(page_result["final_url"])

                    # 다음에 방문할 링크 추가
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

    # ------------------------------------------------------------------
    # 페이지 하나
    # ------------------------------------------------------------------
    def _crawl_page(self, context, url: str, depth: int) -> tuple[dict, list[str]]:
        """페이지 하나를 열어 추출 결과와 '다음에 방문할 링크 목록'을 돌려준다."""
        cfg = self.config
        page_result = {
            "url": url,
            "final_url": "",
            "depth": depth,
            "status": None,
            "title": "",
            "crawled_at": _now(),
            "error": None,
            "offsite_redirect": False,  # 다른 사이트로 넘어갔는지 (해킹된 페이지의 흔한 증상)
            "frames": [],               # 메인 문서 + iframe 문서 목록
            "elements": [],             # 텍스트/링크/iframe/숨김 요소 레코드 (모든 프레임 합침)
        }

        page = context.new_page()
        # 팝업 창과 alert 창이 크롤링을 막지 않도록 자동으로 닫는다
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
        """동적 콘텐츠가 그려질 시간을 준다."""
        cfg = self.config
        try:
            # 네트워크가 잠잠해질 때까지 (광고 스크립트가 끝없이 통신하면 5초에서 끊는다)
            page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightError:
            pass
        try:
            # 스크롤해야 불러오는(lazy loading) 댓글·이미지를 위해 끝까지 내렸다가 올린다
            page.evaluate("window.scrollTo(0, document.body ? document.body.scrollHeight : 0)")
            page.wait_for_timeout(cfg.render_wait_ms)
            page.evaluate("window.scrollTo(0, 0)")
        except PlaywrightError:
            pass

    def _extract_frame(self, frame: Frame, page_result: dict) -> None:
        """프레임(메인 문서 또는 iframe) 하나에서 레코드를 추출해 page_result에 추가."""
        cfg = self.config
        if frame.is_detached():
            return
        frame_path = self._frame_path(frame)
        frame_info = {
            "frame_url": frame.url,
            "frame_path": frame_path,        # 메인 문서에서 이 iframe까지의 선택자 경로
            "is_main": frame.parent_frame is None,
            "title": "",
            "text": "",                      # 프레임 전체의 보이는 텍스트 (2단계 분류용)
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
            # 레코드마다 어느 프레임에서 나왔는지 붙여 둔다 → GUI에서 위치 표시에 사용
            rec["frame_url"] = frame.url
            rec["frame_path"] = frame_path
            page_result["elements"].append(rec)

    def _frame_path(self, frame: Frame) -> list[str]:
        """메인 문서부터 이 프레임을 담은 <iframe>까지의 CSS 선택자 목록.

        예: ["#sidebar > iframe", "body > iframe:nth-of-type(2)"]
            → 메인 문서의 #sidebar > iframe 안의, body > iframe:nth-of-type(2) 안
        메인 문서면 빈 목록.
        """
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
        """추출된 링크 중 다음에 방문할 같은 사이트 페이지 URL만 고른다."""
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
