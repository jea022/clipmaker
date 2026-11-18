@echo off
rem Windows: crea el acceso directo "Clipmaker" en el escritorio.
set "CM_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d=[Environment]::GetFolderPath('Desktop');" ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Clipmaker.lnk'));" ^
  "$s.TargetPath=(Join-Path $env:CM_DIR 'run.bat');" ^
  "$s.WorkingDirectory=$env:CM_DIR;" ^
  "$s.IconLocation=(Join-Path $env:CM_DIR 'static\clipmaker.ico');" ^
  "$s.Description='Clipmaker';" ^
  "$s.Save();" ^
  "Write-Host ('Acceso directo creado en ' + $d)"
if errorlevel 1 (echo No se pudo crear el acceso directo.) else (echo Listo. Busca "Clipmaker" en tu escritorio.)
pause
