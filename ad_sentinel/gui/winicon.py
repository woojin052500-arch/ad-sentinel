import sys
import tkinter as tk

APP_USER_MODEL_ID = "ADSentinel.PublicWebAdScanner"

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x10
WM_SETICON = 0x80
ICON_SMALL, ICON_BIG = 0, 1
SM_CXICON, SM_CYICON, SM_CXSMICON, SM_CYSMICON = 11, 12, 49, 50


def is_windows() -> bool:
    return sys.platform == "win32"


def set_dpi_awareness() -> str:
    if not is_windows():
        return ""
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        return "system"
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        return "legacy"
    except (AttributeError, OSError):
        return ""


def set_app_user_model_id(app_id: str = APP_USER_MODEL_ID) -> bool:
    if not is_windows():
        return False
    import ctypes
    try:
        return ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(app_id)) == 0
    except (AttributeError, OSError):
        return False


def set_native_icon(window: tk.Wm, ico_path: str) -> list[int]:
    if not is_windows():
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                  wintypes.UINT]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = wintypes.LPARAM
    try:
        dpi = user32.GetDpiForWindow
        dpi.argtypes = [wintypes.HWND]
        metrics = user32.GetSystemMetricsForDpi
        metrics.argtypes = [ctypes.c_int, wintypes.UINT]
    except AttributeError:
        dpi, metrics = None, None

    hwnd = int(window.wm_frame(), 16)
    handles = []
    for kind, (mx, my) in ((ICON_SMALL, (SM_CXSMICON, SM_CYSMICON)), (ICON_BIG, (SM_CXICON, SM_CYICON))):
        if dpi and metrics:
            window_dpi = dpi(hwnd) or 96
            cx, cy = metrics(mx, window_dpi), metrics(my, window_dpi)
        else:
            cx, cy = user32.GetSystemMetrics(mx), user32.GetSystemMetrics(my)
        handle = user32.LoadImageW(None, ico_path, IMAGE_ICON, cx, cy, LR_LOADFROMFILE)
        if not handle:
            raise OSError(f"아이콘 파일을 읽지 못함(오류 {ctypes.GetLastError()}): {ico_path}")
        user32.SendMessageW(hwnd, WM_SETICON, kind, handle)
        handles.append(handle)
    return handles
