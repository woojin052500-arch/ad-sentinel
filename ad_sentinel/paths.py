"""실행 경로 관련 도우미.

PyInstaller로 만든 exe는 실행 시 임시 폴더(sys._MEIPASS)에 압축을 풀기 때문에
'소스 파일 기준 경로'와 'exe가 놓인 폴더'가 다르다.
경로 계산을 이 파일 한 곳에서만 하도록 모아 두면 패키징 때 수정할 곳이 줄어든다.
"""

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """PyInstaller로 패키징된 exe로 실행 중이면 True."""
    return getattr(sys, "frozen", False)


def app_dir() -> Path:
    """사용자에게 보이는 프로그램 폴더.

    - exe 실행 시: exe 파일이 있는 폴더
    - 소스 실행 시: 프로젝트 최상위 폴더
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def output_dir() -> Path:
    """결과 JSON을 저장할 폴더 (없으면 만든다)."""
    path = app_dir() / "output"
    path.mkdir(parents=True, exist_ok=True)
    return path


def setup_bundled_browser() -> None:
    """exe 옆에 브라우저 폴더(ms-playwright)를 같이 배포한 경우 Playwright가 그것을 쓰도록 설정.

    배포 폴더 예시:
        AD-Sentinel/
        ├── AD-Sentinel.exe
        └── ms-playwright/chromium-xxxx/...

    폴더가 없으면 아무것도 하지 않는다. (이 경우 browser.py가 Windows 기본 Edge/Chrome을 찾는다)
    """
    bundled = app_dir() / "ms-playwright"
    if bundled.is_dir() and "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled)
