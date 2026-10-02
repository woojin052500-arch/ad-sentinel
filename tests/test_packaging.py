import os
import sys
from pathlib import Path

import pytest

from ad_sentinel import paths
from ad_sentinel.config import CrawlConfig
from ad_sentinel.crawler.browser import EDGE_DOWNLOAD, browser_candidates, browser_error_message

ROOT = Path(__file__).resolve().parent.parent
SPEC = (ROOT / "packaging" / "ad_sentinel.spec").read_text(encoding="utf-8")


def test_edge_is_tried_first(monkeypatch):
    monkeypatch.delenv("AD_SENTINEL_BROWSER", raising=False)
    names = [name for name, _ in browser_candidates(CrawlConfig())]
    assert names == ["Microsoft Edge", "Google Chrome", "Playwright Chromium"]
    assert browser_candidates(CrawlConfig())[0][1] == {"channel": "msedge"}
    names = [name for name, _ in browser_candidates(CrawlConfig(browser_executable="C:/chrome.exe"))]
    assert names[0] == "지정한 브라우저"


def test_browser_error_message_is_korean_and_actionable():
    message = browser_error_message(["- Microsoft Edge: not found"])
    assert message.startswith("점검에 쓰는 브라우저(Microsoft Edge)를 실행하지 못했습니다.")
    assert EDGE_DOWNLOAD in message and "전산 담당자" in message and "- Microsoft Edge: not found" in message


def test_data_dir_falls_back_when_app_folder_is_read_only(monkeypatch, tmp_path):
    locked = tmp_path / "Program Files" / "AD-Sentinel"
    locked.mkdir(parents=True)
    monkeypatch.setattr(paths, "app_dir", lambda: locked)
    monkeypatch.setattr(paths, "_writable", lambda folder: folder != locked)
    monkeypatch.setattr(paths, "_data_dir", None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert paths.data_dir() == tmp_path / "local" / "AD-Sentinel"
    assert paths.output_dir() == tmp_path / "local" / "AD-Sentinel" / "output"
    assert paths.output_dir().is_dir()


def test_data_dir_is_next_to_exe_when_writable(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "_data_dir", None)
    assert paths.data_dir() == tmp_path
    assert not (tmp_path / ".write_test").exists()


def test_frozen_app_dir_is_exe_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "AD-Sentinel.exe"))
    assert paths.app_dir() == tmp_path


@pytest.mark.parametrize("needle", [
    '"ad_sentinel" / "assets"', '"ad_sentinel" / "detector" / "data"', 'collect_data_files("sv_ttk")',
    '"demo_server"', '"tests"', "console=False", "upx=False", '"icon.ico"', "COLLECT(",
])
def test_spec_settings(needle):
    assert needle in SPEC


@pytest.mark.parametrize("name", ["requirements.txt", "requirements-dev.txt", "requirements-build.txt",
                                  "packaging/build.bat"])
def test_build_inputs_are_ascii_for_cp949_windows(name):
    data = (ROOT / name).read_bytes()
    assert data.isascii()


def test_build_bat_uses_crlf_and_utf8_mode():
    data = (ROOT / "packaging" / "build.bat").read_bytes()
    assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")
    assert b"PYTHONUTF8=1" in data and b"collect_licenses.py" in data and b"ad_sentinel.spec" in data


def test_bundled_data_files_exist():
    for rel in ["ad_sentinel/assets/icon.ico", "ad_sentinel/detector/data/confusables.txt",
                "ad_sentinel/detector/data/LICENSE-UNICODE.txt", "THIRD_PARTY_NOTICES.txt"]:
        assert (ROOT / rel).is_file(), rel


def test_attach_console_keeps_existing_streams():
    import main

    before = sys.stdout, sys.stderr
    main.attach_console()
    assert (sys.stdout, sys.stderr) == before


def test_attach_console_without_streams(monkeypatch):
    import main

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(sys, "platform", "linux")
    main.attach_console()
    assert sys.stdout is not None and sys.stderr is not None
    print("ok")
    sys.stdout.close()
