import ctypes
from types import SimpleNamespace

import pytest

pytest.importorskip("tkinter")

from ad_sentinel.gui import winicon  # noqa: E402


class FakeFunc:
    def __init__(self, result, calls, name):
        self.result, self.calls, self.name = result, calls, name

    def __call__(self, *args):
        self.calls.append((self.name, args))
        return self.result(*args) if callable(self.result) else self.result


def _fake_windll(calls):
    def lib(**funcs):
        return SimpleNamespace(**{name: FakeFunc(result, calls, name) for name, result in funcs.items()})

    return SimpleNamespace(
        user32=lib(LoadImageW=lambda *a: 1000 + a[3], SendMessageW=0, GetDpiForWindow=144,
                   GetSystemMetricsForDpi=lambda index, dpi: {49: 16, 50: 16, 11: 32, 12: 32}[index] * dpi // 96,
                   GetSystemMetrics=0, SetProcessDPIAware=1),
        shcore=lib(SetProcessDpiAwareness=0),
        shell32=lib(SetCurrentProcessExplicitAppUserModelID=0),
    )


def test_non_windows_does_nothing(monkeypatch):
    monkeypatch.setattr(winicon, "is_windows", lambda: False)
    assert winicon.set_dpi_awareness() == ""
    assert winicon.set_app_user_model_id() is False
    assert winicon.set_native_icon(None, "icon.ico") == []


def test_windows_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(winicon, "is_windows", lambda: True)
    monkeypatch.setattr(ctypes, "windll", _fake_windll(calls), raising=False)
    monkeypatch.setattr(ctypes, "GetLastError", lambda: 0, raising=False)

    assert winicon.set_dpi_awareness() == "system"
    assert ("SetProcessDpiAwareness", (1,)) in calls
    assert winicon.set_app_user_model_id() is True
    app_id = next(args[0] for name, args in calls if name == "SetCurrentProcessExplicitAppUserModelID")
    assert app_id.value == winicon.APP_USER_MODEL_ID

    window = SimpleNamespace(wm_frame=lambda: "0x1a2b")
    handles = winicon.set_native_icon(window, r"C:\사용자\아이콘\icon.ico")
    loads = [args for name, args in calls if name == "LoadImageW"]
    assert [(a[1], a[3], a[4], a[5]) for a in loads] == [(r"C:\사용자\아이콘\icon.ico", 24, 24, winicon.LR_LOADFROMFILE),
                                                        (r"C:\사용자\아이콘\icon.ico", 48, 48, winicon.LR_LOADFROMFILE)]
    sends = [args for name, args in calls if name == "SendMessageW"]
    assert sends == [(0x1A2B, winicon.WM_SETICON, winicon.ICON_SMALL, 1024),
                     (0x1A2B, winicon.WM_SETICON, winicon.ICON_BIG, 1048)]
    assert handles == [1024, 1048]
