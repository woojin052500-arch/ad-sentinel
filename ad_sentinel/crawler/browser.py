import logging
import os

from playwright.sync_api import Browser, Error as PlaywrightError, Playwright

from ad_sentinel.config import CrawlConfig

log = logging.getLogger(__name__)


def launch_browser(pw: Playwright, config: CrawlConfig) -> Browser:
    candidates = []
    exe = config.browser_executable or os.environ.get("AD_SENTINEL_BROWSER", "")
    if exe:
        candidates.append(("지정한 브라우저", {"executable_path": exe}))
    candidates.append(("Playwright Chromium", {}))
    candidates.append(("Microsoft Edge", {"channel": "msedge"}))
    candidates.append(("Google Chrome", {"channel": "chrome"}))

    errors = []
    for name, options in candidates:
        try:
            browser = pw.chromium.launch(headless=config.headless, **options)
            log.info("브라우저 실행: %s (버전 %s)", name, browser.version)
            return browser
        except PlaywrightError as e:
            errors.append(f"- {name}: {str(e).strip().splitlines()[0]}")

    raise RuntimeError(
        "사용할 수 있는 브라우저를 찾지 못했습니다. Microsoft Edge 또는 Chrome을 설치하거나 "
        "브라우저 실행 파일 경로를 지정해 주세요.\n" + "\n".join(errors)
    )
