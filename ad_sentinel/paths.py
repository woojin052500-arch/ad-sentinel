import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def app_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


APP_NAME = "AD-Sentinel"
_data_dir: Path | None = None


def _writable(folder: Path) -> bool:
    probe = folder / ".write_test"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def data_dir() -> Path:
    global _data_dir
    if _data_dir is None:
        base = app_dir()
        if not _writable(base):
            root = os.environ.get("LOCALAPPDATA") or str(Path.home())
            base = Path(root) / APP_NAME
            base.mkdir(parents=True, exist_ok=True)
        _data_dir = base
    return _data_dir


def output_dir() -> Path:
    path = data_dir() / "output"
    path.mkdir(parents=True, exist_ok=True)
    return path


def setup_bundled_browser() -> None:
    bundled = app_dir() / "ms-playwright"
    if bundled.is_dir() and "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled)


def asset_path(name: str) -> Path:
    return Path(__file__).resolve().parent / "assets" / name
