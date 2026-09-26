import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def app_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def output_dir() -> Path:
    path = app_dir() / "output"
    path.mkdir(parents=True, exist_ok=True)
    return path


def setup_bundled_browser() -> None:
    bundled = app_dir() / "ms-playwright"
    if bundled.is_dir() and "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled)
