@echo off
setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PLAYWRIGHT_BROWSERS_PATH=
cd /d "%~dp0.."

set "PY="
py -3.12 --version >nul 2>&1 && set "PY=py -3.12"
if not defined PY python --version >nul 2>&1 && set "PY=python"
if not defined PY (
    echo [ERROR] Python 3.12 was not found.
    echo         Install it from https://www.python.org/downloads/ and check "Add python.exe to PATH".
    exit /b 1
)
echo [1/5] Python: %PY%

if not exist ".build-venv\Scripts\python.exe" (
    %PY% -m venv .build-venv || goto :fail
)
set "VPY=.build-venv\Scripts\python.exe"

echo [2/5] Installing packages
"%VPY%" -m pip install --upgrade pip || goto :fail
"%VPY%" -m pip install -r requirements-build.txt || goto :fail

echo [3/5] Building exe with PyInstaller
"%VPY%" -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging\ad_sentinel.spec || goto :fail

echo [4/5] Copying license notices
"%VPY%" packaging\collect_licenses.py dist\AD-Sentinel || goto :fail

echo [5/5] Making zip
for /f %%v in ('"%VPY%" -c "import ad_sentinel; print(ad_sentinel.__version__)"') do set "VER=%%v"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\AD-Sentinel' -DestinationPath 'dist\AD-Sentinel-%VER%-win64.zip' -Force" || goto :fail

echo.
echo Done.
echo   Program : dist\AD-Sentinel\AD-Sentinel.exe
echo   Zip     : dist\AD-Sentinel-%VER%-win64.zip
exit /b 0

:fail
echo.
echo [ERROR] Build failed. See the messages above.
exit /b 1
