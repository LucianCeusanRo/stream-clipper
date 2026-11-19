@echo off
REM Starts Stream Clipper (same as the desktop shortcut)
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (echo Run setup.bat first & pause & exit /b 1)
powercfg /change standby-timeout-ac 0 >nul 2>nul
start "" .venv\Scripts\pythonw.exe -m streamclip app
