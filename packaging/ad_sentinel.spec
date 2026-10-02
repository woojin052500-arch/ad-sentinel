import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).resolve().parent
NAME = "AD-Sentinel"
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "ad_sentinel" / "__init__.py").read_text(encoding="utf-8")).group(1)

datas = [
    (str(ROOT / "ad_sentinel" / "assets"), "ad_sentinel/assets"),
    (str(ROOT / "ad_sentinel" / "detector" / "data"), "ad_sentinel/detector/data"),
]
datas += collect_data_files("sv_ttk")

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=["sv_ttk"],
    excludes=["demo_server", "tests", "pytest", "_pytest", "PIL", "numpy", "IPython", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)


def version_info():
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                     VarFileInfo, VarStruct, VSVersionInfo)

    numbers = tuple(int(x) for x in (VERSION.split(".") + ["0", "0", "0"])[:4])
    strings = [
        StringStruct("CompanyName", "AD Sentinel"),
        StringStruct("FileDescription", "AD Sentinel - 공공 웹사이트 불법광고 점검 도구"),
        StringStruct("FileVersion", VERSION),
        StringStruct("InternalName", NAME),
        StringStruct("OriginalFilename", NAME + ".exe"),
        StringStruct("ProductName", "AD Sentinel"),
        StringStruct("ProductVersion", VERSION),
        StringStruct("LegalCopyright", "AD Sentinel"),
    ]
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[StringFileInfo([StringTable("041204B0", strings)]), VarFileInfo([VarStruct("Translation", [0x0412, 1200])])],
    )


exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    icon=str(ROOT / "ad_sentinel" / "assets" / "icon.ico"),
    version=version_info() if sys.platform == "win32" else None,
    console=False,
    disable_windowed_traceback=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=NAME)
