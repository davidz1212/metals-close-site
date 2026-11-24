@echo off
chcp 65001 >nul 2>&1
set MC_DEV_MODE=1
set MC_COOKIE_SECURE=0
set PORT=8765
echo LOCAL DEV MODE - verification codes are shown in the browser.
echo Open http://127.0.0.1:8765 after the server starts.
echo Press CTRL+C to stop.
echo.
"C:\Users\David\.workbuddy\binaries\python\envs\default\Scripts\python.exe" "%~dp0server.py"
if errorlevel 1 pause
