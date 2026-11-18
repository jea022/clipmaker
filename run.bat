@echo off
rem Windows: prepara el entorno la primera vez y abre la web local.
cd /d "%~dp0"
set "PATH=%~dp0bin;%PATH%"
where python >nul 2>nul || (echo Falta Python 3.10 o superior. Instalalo con: winget install Python.Python.3.12 & pause & exit /b 1)
where ffmpeg >nul 2>nul && where ffprobe >nul 2>nul || call :getffmpeg
where ffmpeg >nul 2>nul || (echo No pude preparar ffmpeg. Instalalo a mano con: winget install Gyan.FFmpeg & pause & exit /b 1)
if not exist .venv (
  python -m venv .venv || (pause & exit /b 1)
)
set "FIRST=1"
:serve
fc /b requirements.txt .venv\requirements.installed >nul 2>nul || (
  .venv\Scripts\pip install -q -r requirements.txt || (pause & exit /b 1)
  copy /y requirements.txt .venv\requirements.installed >nul
)
if not exist templates\wganga.json .venv\Scripts\python make_template.py
if defined FIRST (
  start "" http://127.0.0.1:5000
  set "FIRST="
)
.venv\Scripts\python app.py 5000
if errorlevel 42 goto serve
pause
exit /b 0

:getffmpeg
echo Descargando ffmpeg (unos 200 MB, solo esta vez)...
if not exist bin mkdir bin
set "FFZIP=%TEMP%\clipmaker_ffmpeg.zip"
set "FFURL=https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
where curl.exe >nul 2>nul && (curl.exe -L --fail -o "%FFZIP%" "%FFURL%") || (powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri $env:FFURL -OutFile $env:FFZIP")
if not exist "%FFZIP%" (echo Fallo la descarga de ffmpeg. & exit /b 1)
set "CM_ZIP=%FFZIP%"
set "CM_BIN=%~dp0bin"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; $z=[IO.Compression.ZipFile]::OpenRead($env:CM_ZIP); foreach($e in $z.Entries){ if($e.FullName -match '/bin/(ffmpeg|ffprobe)\.exe$'){ [IO.Compression.ZipFileExtensions]::ExtractToFile($e,(Join-Path $env:CM_BIN $e.Name),$true) } }; $z.Dispose()"
del "%FFZIP%" >nul 2>nul
echo ffmpeg listo.
exit /b 0
