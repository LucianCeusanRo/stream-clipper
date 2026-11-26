@echo off
REM Rebuilds "Stream Clipper.exe" (the launcher with the icon) on Windows. Optional: releases ship it ready-made.
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (echo [!] Run setup.bat first & pause & exit /b 1)
"%PY%" -m pip install --quiet ziglang || (echo [!] cannot install ziglang & pause & exit /b 1)
cd launcher
"%PY%" -m ziglang cc -target x86_64-windows-gnu -O2 -s -municode -Wl,--subsystem,windows launcher.c launcher.rc -o "..\Stream Clipper.exe" -lshell32 -luser32 -ladvapi32 || (echo [!] build failed & pause & exit /b 1)
cd ..
del /q *.pdb 2>nul
echo DONE: "Stream Clipper.exe"
pause
