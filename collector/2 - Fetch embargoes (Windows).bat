@echo off
cd /d "%~dp0"
title Embargo Desk fetcher
if not exist ".venv\Scripts\python.exe" (
  echo The fetcher isn't set up yet. Double-click "1 - Set up (Windows)" first.
  echo.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" collect.py %*
echo.
pause
