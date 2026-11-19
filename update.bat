@echo off
REM Update Stream Clipper from its official GitHub releases (no git needed). Your data, settings, TikTok login,
REM .venv and bin\ are never touched. The download is checked against the release's SHA256SUMS.txt.
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
set "VPY=%~dp0.venv\Scripts\python.exe"
if not exist "%VPY%" (echo [!] Run setup.bat first & pause & exit /b 1)
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8777/api/state) | Out-Null; exit 1 } catch { exit 0 }"
if errorlevel 1 (
  echo [!] Stream Clipper is running. Close it first ^(or use the "Update" button in the app^).
  pause & exit /b 1
)
"%VPY%" -m streamclip update %*
set "RC=%ERRORLEVEL%"
pause
exit /b %RC%
