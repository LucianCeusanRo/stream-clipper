@echo off
REM ================================================================
REM  Stream Clipper - setup (once). No winget, no "py", no admin rights.
REM  Works from any folder/drive, also with spaces in the path.
REM
REM    setup.bat                 full setup (what you run by hand)
REM    setup.bat step NAME       one step, no pauses (used by the Windows installer)
REM                              NAME = python, ffmpeg, deno, venv, packages, browser, model, check
REM ================================================================
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if not exist "config.yaml" copy /y "config.example.yaml" "config.yaml" >nul
set "APP=%~dp0"
set "APPD=%~dp0."
set "BIN=%~dp0bin"
set "HELP=%~dp0tools\setup_helpers.ps1"
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS%" set "PS=powershell"
set "DL=%TEMP%\streamclip_setup"
set "VPY=%APP%.venv\Scripts\python.exe"
if not exist "%DL%" mkdir "%DL%"
if not exist "%BIN%" mkdir "%BIN%"
REM programs downloaded by setup (ffmpeg, deno) live in bin\ -> visible to everything started from here
set "PATH=%BIN%;%PATH%"

if /i "%~1"=="step" (
  call :s_%~2
  exit /b %ERRORLEVEL%
)

echo ================================================
echo   STREAM CLIPPER - setup (only once)
echo   Folder: %APP%
echo ================================================
call :s_python   || goto failed
call :s_ffmpeg   || goto failed
call :s_deno
call :s_venv     || goto failed
call :s_packages || goto failed
call :s_browser
call :s_model
call :s_check
echo [*] Running the self-test...
"%VPY%" -m streamclip selftest --quick
if errorlevel 1 echo [!] Some tests failed - please open an issue on GitHub with the text of this window.
echo [*] Creating the "Stream Clipper" desktop shortcut...
set "LNK=%APP%Stream Clipper.exe"
if not exist "%LNK%" set "LNK=%APP%run.bat"
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%HELP%" -Action shortcut -Target "%LNK%" -WorkDir "%APPD%" -Icon "%APP%assets\icon.ico"
if errorlevel 1 echo [!] Could not create the shortcut - start run.bat from the folder instead.
echo.
echo ================================================
echo  DONE! Open "Stream Clipper" from your desktop.
echo  First time: open Settings and set your language.
echo ================================================
pause
exit /b 0
:failed
echo.
echo [!] Setup stopped (see the message above). Fix it and run setup.bat again.
pause
exit /b 1

REM ---------------------------------------------------------------
:s_python
set "PY="
call :find_python
if defined PY goto py_ok
echo [*] Python not found. Downloading the official Python 3.12 (python.org, ~27 MB)...
set "PYINST=%DL%\python-3.12.10-amd64.exe"
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%HELP%" -Action download -Url "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" -Out "%PYINST%"
if errorlevel 1 (echo [!] Could not download Python. Get it from https://www.python.org/downloads/release/python-31210/ and run setup again. & exit /b 1)
echo [*] Installing Python 3.12 for your user only (no admin, 1-3 minutes)...
start "" /wait "%PYINST%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 InstallLauncherAllUsers=0 Include_test=0 Include_doc=0
call :find_python
if not defined PY (echo [!] Python was installed but I cannot find it. Run setup again, maybe after a restart. & exit /b 1)
:py_ok
echo [OK] Python: %PY%
exit /b 0

:s_ffmpeg
if exist "%BIN%\ffmpeg.exe" if exist "%BIN%\ffprobe.exe" goto ff_ok
echo [*] Downloading ffmpeg (gyan.dev, ~115 MB, with NVENC for NVIDIA cards)...
set "FFZ=%DL%\ffmpeg.zip"
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%HELP%" -Action download -Url "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -Out "%FFZ%"
if not errorlevel 1 goto ff_unzip
echo [*] gyan.dev failed, trying GitHub (BtbN, ~200 MB)...
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%HELP%" -Action download -Url "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" -Out "%FFZ%"
if errorlevel 1 (echo [!] Could not download ffmpeg. Check your internet/antivirus. & exit /b 1)
:ff_unzip
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%HELP%" -Action extract -Zip "%FFZ%" -Dest "%BIN%" -Names "ffmpeg.exe,ffprobe.exe"
if errorlevel 1 (echo [!] Could not unpack ffmpeg. & exit /b 1)
del /q "%FFZ%" >nul 2>nul
:ff_ok
echo [OK] ffmpeg: %BIN%\ffmpeg.exe
exit /b 0

:s_deno
REM yt-dlp needs a JavaScript runtime for some YouTube streams
if exist "%BIN%\deno.exe" goto deno_ok
echo [*] Downloading Deno (GitHub, ~40 MB)...
set "DZ=%DL%\deno.zip"
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%HELP%" -Action download -Url "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip" -Out "%DZ%"
if errorlevel 1 goto deno_warn
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%HELP%" -Action extract -Zip "%DZ%" -Dest "%BIN%" -Names "deno.exe"
if errorlevel 1 goto deno_warn
del /q "%DZ%" >nul 2>nul
:deno_ok
echo [OK] Deno: %BIN%\deno.exe
exit /b 0
:deno_warn
echo [!] Deno could not be downloaded. The app works, but YouTube may refuse some streams. Run setup again later.
exit /b 0

:s_venv
call :find_python
if not defined PY (echo [!] Python not found - run the python step first. & exit /b 1)
if not exist "%VPY%" goto venv_make
"%VPY%" -c "import sys" >nul 2>nul
if not errorlevel 1 goto venv_ok
echo [*] Broken .venv (different Python?) - recreating it...
rmdir /s /q "%APP%.venv"
:venv_make
echo [*] Creating the Python environment (.venv)...
"%PY%" -m venv "%APP%.venv"
if errorlevel 1 (echo [!] Could not create .venv with %PY% & exit /b 1)
:venv_ok
exit /b 0

:s_packages
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install -r "%APP%requirements.txt"
if not errorlevel 1 exit /b 0
echo [*] Retrying the package install once...
"%VPY%" -m pip install -r "%APP%requirements.txt"
if errorlevel 1 (echo [!] Installing the packages failed. Check your internet and run setup again. & exit /b 1)
exit /b 0

:s_browser
echo [*] Installing the browser used for optional TikTok posting (Chromium)...
"%VPY%" -m playwright install chromium
if errorlevel 1 echo [!] Chromium was not installed - Google Chrome will be used if you have it.
exit /b 0

:s_model
echo [*] Downloading the Whisper large-v3 model (~3 GB, only once)...
"%VPY%" -c "from streamclip.util import setup_cuda_dlls; setup_cuda_dlls(); from faster_whisper import WhisperModel; WhisperModel('large-v3', device='cpu', compute_type='int8'); print('model OK')"
if errorlevel 1 echo [!] The model was not downloaded now - it downloads automatically the first time it is needed.
exit /b 0

:s_check
echo [*] Checking the graphics card (CUDA + NVENC)...
"%VPY%" -c "from streamclip.util import setup_cuda_dlls; setup_cuda_dlls(); import ctranslate2; print('CUDA GPUs:', ctranslate2.get_cuda_device_count())"
"%BIN%\ffmpeg.exe" -v error -f lavfi -i color=black:s=256x256:d=0.5 -c:v h264_nvenc -f null - >nul 2>nul
if errorlevel 1 (echo [!] NVENC not available - the CPU will be used, slower) else (echo [OK] NVENC works)
exit /b 0

REM ===============================================================
REM  Finding Python: registry, the usual folders, "py", "where python"
REM ===============================================================
:find_python
if defined PY goto have_python

echo [*] Nu gasesc Python pe PC. Descarc Python 3.12 oficial (python.org, ~27 MB)...
set "PYINST=%DL%\python-3.12.10-amd64.exe"
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%HELP%" -Action download -Url "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" -Out "%PYINST%"
if errorlevel 1 goto fail_python_dl
echo [*] Instalez Python 3.12 doar pentru utilizatorul tau (fara admin, 1-3 minute)...
start "" /wait "%PYINST%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 InstallLauncherAllUsers=0 Include_test=0 Include_doc=0
REM chiar daca instalatorul raspunde "Another version is already installed" (0x80070666), cautam din nou
call :find_python
if defined PY goto have_python
goto fail_python

:have_python
echo [OK] Python: %PY%
"%PY%" -V

REM ---------------------------------------------------------------
REM  2) ffmpeg (cu NVENC) -> bin\
REM ---------------------------------------------------------------
if exist "%BIN%\ffmpeg.exe" if exist "%BIN%\ffprobe.exe" goto have_ffmpeg
echo [*] Descarc ffmpeg (gyan.dev, ~115 MB, cu NVENC pentru placa NVIDIA)...
set "FFZ=%DL%\ffmpeg.zip"
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%HELP%" -Action download -Url "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -Out "%FFZ%"
if not errorlevel 1 goto ffmpeg_unzip
echo [*] gyan.dev nu merge, incerc GitHub (BtbN, ~200 MB)...
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%HELP%" -Action download -Url "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" -Out "%FFZ%"
if errorlevel 1 goto fail_ffmpeg
:ffmpeg_unzip
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%HELP%" -Action extract -Zip "%FFZ%" -Dest "%BIN%" -Names "ffmpeg.exe,ffprobe.exe"
if errorlevel 1 goto fail_ffmpeg
del /q "%FFZ%" >nul 2>nul
:have_ffmpeg
echo [OK] ffmpeg: %BIN%\ffmpeg.exe

REM ---------------------------------------------------------------
REM  3) Deno (yt-dlp are nevoie de un runtime JavaScript pentru YouTube) -> bin\
REM ---------------------------------------------------------------
if exist "%BIN%\deno.exe" goto have_deno
echo [*] Descarc Deno (GitHub, ~40 MB)...
set "DZ=%DL%\deno.zip"
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%HELP%" -Action download -Url "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip" -Out "%DZ%"
if errorlevel 1 goto warn_deno
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%HELP%" -Action extract -Zip "%DZ%" -Dest "%BIN%" -Names "deno.exe"
if errorlevel 1 goto warn_deno
del /q "%DZ%" >nul 2>nul
:have_deno
echo [OK] Deno: %BIN%\deno.exe
goto after_deno
:warn_deno
echo [!] Deno nu s-a putut descarca. Programul merge, dar YouTube poate refuza unele live-uri. Ruleaza setup.bat din nou mai tarziu.
:after_deno

REM ---------------------------------------------------------------
REM  4) mediul Python al programului (.venv) + pachete
REM ---------------------------------------------------------------
set "VPY=%APP%.venv\Scripts\python.exe"
if not exist "%VPY%" goto make_venv
"%VPY%" -c "import sys" >nul 2>nul
if not errorlevel 1 goto have_venv
echo [*] .venv stricat (alt Python?) - il refac...
rmdir /s /q "%APP%.venv"
:make_venv
echo [*] Creez mediul Python (.venv)...
"%PY%" -m venv "%APP%.venv"
if errorlevel 1 goto fail_venv
:have_venv
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install -r "%APP%requirements.txt"
if not errorlevel 1 goto pip_ok
echo [*] Reincerc instalarea pachetelor o data...
"%VPY%" -m pip install -r "%APP%requirements.txt"
if errorlevel 1 goto fail_pip
:pip_ok
echo [*] Instalez browserul pentru postare (Chromium)...
"%VPY%" -m playwright install chromium
if errorlevel 1 echo [!] Chromium nu s-a instalat - programul va folosi Google Chrome daca il ai.

echo [*] Descarc modelul Whisper large-v3 (~3 GB, o singura data)...
"%VPY%" -c "from streamclip.util import setup_cuda_dlls; setup_cuda_dlls(); from faster_whisper import WhisperModel; WhisperModel('large-v3', device='cpu', compute_type='int8'); print('model OK')"
if errorlevel 1 echo [!] Modelul nu s-a descarcat acum - se descarca automat la prima pornire.

echo [*] Verific placa video (CUDA + NVENC)...
"%VPY%" -c "from streamclip.util import setup_cuda_dlls; setup_cuda_dlls(); import ctranslate2; print('GPU-uri CUDA:', ctranslate2.get_cuda_device_count())"
"%BIN%\ffmpeg.exe" -v error -f lavfi -i color=black:s=256x256:d=0.5 -c:v h264_nvenc -f null - >nul 2>nul
if errorlevel 1 goto no_nvenc
echo [OK] NVENC merge
goto after_nvenc
:no_nvenc
echo [!] NVENC indisponibil - se foloseste procesorul, mai lent
:after_nvenc

echo [*] Verific ca totul merge (test automat)...
"%VPY%" -m streamclip selftest --quick
if errorlevel 1 echo [!] Unele teste au picat - deschide un issue pe GitHub cu textul ferestrei.

echo [*] Creez scurtatura "Stream Clipper" pe Desktop...
set "LNK=%APP%Stream Clipper.exe"
if not exist "%LNK%" set "LNK=%APP%run.bat"
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%HELP%" -Action shortcut -Target "%LNK%" -WorkDir "%APPD%" -Icon "%APP%assets\icon.ico"
if errorlevel 1 echo [!] Nu am putut crea scurtatura - porneste direct run.bat din folder.

echo.
echo ================================================
echo  GATA! Deschide "Stream Clipper" de pe Desktop.
echo  Prima data: apasa "Login TikTok" in aplicatie.
echo ================================================
pause
exit /b 0

REM ===============================================================
REM  Cautare Python: registru, caile obisnuite, "py", "where python"
REM ===============================================================
:find_python
set "PY="
REM registry (python.org installers always write this, even when Python is not on PATH)
for %%V in (3.12 3.11 3.13) do call :try_reg_ver %%V
if defined PY exit /b 0
call :try_py "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
call :try_py "%ProgramFiles%\Python312\python.exe"
call :try_py "C:\Program Files\Python312\python.exe"
call :try_py "C:\Python312\python.exe"
call :try_py "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
call :try_py "%ProgramFiles%\Python311\python.exe"
call :try_py "C:\Python311\python.exe"
call :try_py "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
call :try_py "%ProgramFiles%\Python313\python.exe"
call :try_py "C:\Python313\python.exe"
if defined PY exit /b 0
REM py launcher, if present
for /f "usebackq delims=" %%P in (`py -3.12 -c "import sys;print(sys.executable)" 2^>nul`) do call :try_py "%%P"
if defined PY exit /b 0
REM anything called python.exe on PATH (skips the Microsoft Store stub)
for /f "usebackq delims=" %%P in (`where python 2^>nul`) do call :try_py "%%P"
exit /b 0

:try_reg_ver
call :try_reg "HKCU\Software\Python\PythonCore\%~1\InstallPath"
call :try_reg "HKLM\Software\Python\PythonCore\%~1\InstallPath"
call :try_reg "HKLM\Software\WOW6432Node\Python\PythonCore\%~1\InstallPath"
exit /b 0

:try_reg
REM %1 = registry key. Reads ExecutablePath, else the default value (= folder). Works on any Windows language.
if defined PY exit /b 0
set "RP="
for /f "delims=" %%L in ('reg query "%~1" /v ExecutablePath 2^>nul ^| findstr /c:"REG_SZ"') do set "RL=%%L"& call :regval
if defined RP call :try_py "%RP%"
if defined PY exit /b 0
set "RP="
for /f "delims=" %%L in ('reg query "%~1" /ve 2^>nul ^| findstr /c:"REG_SZ"') do set "RL=%%L"& call :regval
if not defined RP exit /b 0
if "%RP:~-1%"=="\" set "RP=%RP:~0,-1%"
call :try_py "%RP%\python.exe"
exit /b 0

:regval
REM keep what comes after "REG_SZ", without the leading spaces/tabs
set "RP=%RL:*REG_SZ=%"
:regval_trim
if not defined RP exit /b 0
if "%RP:~0,1%"==" " set "RP=%RP:~1%"& goto regval_trim
if "%RP:~0,1%"=="	" set "RP=%RP:~1%"& goto regval_trim
exit /b 0

:try_py
if defined PY exit /b 0
if "%~1"=="" exit /b 0
if not exist "%~1" exit /b 0
echo "%~1" | findstr /i "WindowsApps" >nul && exit /b 0
"%~1" -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) and sys.maxsize > 2**32 else 1)" >nul 2>nul
if errorlevel 1 exit /b 0
set "PY=%~1"
exit /b 0

