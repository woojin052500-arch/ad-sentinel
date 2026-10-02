import logging
import os
import re

from playwright.sync_api import Browser, Error as PlaywrightError, Playwright

from ad_sentinel.config import CrawlConfig

log = logging.getLogger(__name__)

EDGE_DOWNLOAD = "https://www.microsoft.com/edge"
BROWSER_ERROR_TITLE = "브라우저를 실행하지 못했습니다"
LAUNCH_PREFIX = re.compile(r"^[\w.]*launch\W*")


class BrowserLaunchError(RuntimeError):
    pass


def browser_candidates(config: CrawlConfig) -> list[tuple[str, dict]]:
    candidates = []
    exe = config.browser_executable or os.environ.get("AD_SENTINEL_BROWSER", "")
    if exe:
        candidates.append(("지정한 브라우저", {"executable_path": exe}))
    candidates.append(("Microsoft Edge", {"channel": "msedge"}))
    candidates.append(("Google Chrome", {"channel": "chrome"}))
    candidates.append(("Playwright Chromium", {}))
    return candidates


def browser_error_message(errors: list[str]) -> str:
    return (
        "점검에 쓰는 브라우저(Microsoft Edge)를 실행하지 못했습니다.\n\n"
        "이렇게 해 보세요.\n"
        f"1. Microsoft Edge가 설치되어 있는지 확인하세요. Windows 11에는 기본으로 들어 있으며, 없으면 {EDGE_DOWNLOAD} 에서 "
        "설치할 수 있습니다.\n"
        "2. Edge를 한 번 직접 열어 업데이트를 마친 뒤, 이 프로그램을 다시 실행하세요.\n"
        "3. 기관·회사 PC에서 보안 정책으로 Edge 자동 실행이 막혀 있을 수 있습니다. 이때는 전산 담당자에게 문의하세요. "
        "Google Chrome이 설치되어 있으면 Chrome을 대신 사용합니다.\n\n"
        "자세한 오류 (담당자 전달용):\n" + "\n".join(errors)
    )


def launch_browser(pw: Playwright, config: CrawlConfig) -> Browser:
    errors = []
    for name, options in browser_candidates(config):
        try:
            browser = pw.chromium.launch(headless=config.headless, **options)
            log.info("브라우저 실행: %s (버전 %s)", name, browser.version)
            return browser
        except PlaywrightError as e:
            first = str(e).strip().splitlines()[0] if str(e).strip() else ""
            detail = LAUNCH_PREFIX.sub("", first).strip(" :") or "실행 실패"
            errors.append(f"- {name}: {detail}")
    raise BrowserLaunchError(browser_error_message(errors))
