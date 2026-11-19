@echo off
chcp 65001 >nul
title Stream Clipper - console (for troubleshooting)
cd /d "%~dp0"
call .venv\Scripts\activate.bat
powercfg /change standby-timeout-ac 0 >nul 2>nul
:loop
python -m streamclip app
echo The app stopped. Restarting in 30 seconds (Ctrl+C to stop for good)...
timeout /t 30
goto loop
