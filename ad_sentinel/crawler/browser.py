"""브라우저 실행.

exe를 받은 사용자 PC에 Playwright 전용 Chromium이 없을 수 있으므로
아래 순서로 실행 가능한 브라우저를 찾는다.

  1. 사용자가 지정한 실행 파일 (설정값 또는 환경변수 AD_SENTINEL_BROWSER)
  2. Playwright Chromium (개발 PC, 또는 exe 옆에 ms-playwright 폴더를 같이 배포한 경우)
  3. Microsoft Edge  ← Windows 11에는 기본 설치되어 있어 대부분 여기서 성공
  4. Google Chrome
"""

import logging
import os

from playwright.sync_api import Browser, Error as PlaywrightError, Playwright

from ad_sentinel.config import CrawlConfig

log = logging.getLogger(__name__)


def launch_browser(pw: Playwright, config: CrawlConfig) -> Browser:
    """사용 가능한 Chromium 계열 브라우저를 찾아 실행한다."""
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
            # 오류 메시지 첫 줄만 남긴다 (Playwright 오류는 매우 길다)
            errors.append(f"- {name}: {str(e).strip().splitlines()[0]}")

    raise RuntimeError(
        "사용할 수 있는 브라우저를 찾지 못했습니다. Microsoft Edge 또는 Chrome을 설치하거나 "
        "브라우저 실행 파일 경로를 지정해 주세요.\n" + "\n".join(errors)
    )
