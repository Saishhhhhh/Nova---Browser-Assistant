@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" run_nova.py
echo.
echo Nova has stopped. Press any key to close this window.
pause >nul
