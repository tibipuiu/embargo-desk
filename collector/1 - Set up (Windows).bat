@echo off
setlocal
cd /d "%~dp0"
title Embargo Desk fetcher - setup
echo Setting up the Embargo Desk fetcher. The first time takes a few minutes.
echo.

set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY python --version >nul 2>&1 && set "PY=python"
if not defined PY goto nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" || goto oldpython

echo Creating a private Python environment for the fetcher...
%PY% -m venv .venv || goto fail
echo Installing components...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet --disable-pip-version-check || goto fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet --disable-pip-version-check || goto fail
echo Downloading the fetcher's own copy of Chromium, about 150 MB. Your normal browser isn't touched.
".venv\Scripts\python.exe" -m playwright install chromium || goto fail
echo.
echo All set. From now on, double-click "2 - Fetch embargoes (Windows)" to fetch.
echo.
pause
exit /b 0

:nopython
echo Python isn't installed on this computer yet.
echo.
echo Opening python.org. Download and run the installer, and on its first screen
echo tick "Add python.exe to PATH" before clicking Install Now.
echo Then double-click this setup file again.
start "" https://www.python.org/downloads/
echo.
pause
exit /b 1

:oldpython
echo The Python on this computer is too old; the fetcher needs Python 3.10 or newer.
echo Opening python.org so you can install the current version, then run this setup again.
start "" https://www.python.org/downloads/
echo.
pause
exit /b 1

:fail
echo.
echo Setup didn't finish. Take a screenshot of this window and send it to whoever runs Embargo Desk.
echo.
pause
exit /b 1
