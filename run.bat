@echo off
REM Starts Stream Clipper (same as the desktop shortcut)
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (echo Run setup.bat first & pause & exit /b 1)
start "" .venv\Scripts\pythonw.exe -m streamclip app
