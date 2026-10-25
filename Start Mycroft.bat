@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" run_mycroft.py
echo.
echo Mycroft has stopped. Press any key to close this window.
pause >nul
