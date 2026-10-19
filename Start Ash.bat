@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" run_ash.py
echo.
echo Ash has stopped. Press any key to close this window.
pause >nul
