@echo off
rem Windows: crea el acceso directo "Clipmaker" en el escritorio. Abre la app SIN ventana de consola.
set "CM_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$q=[char]34;" ^
  "$d=[Environment]::GetFolderPath('Desktop');" ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Clipmaker.lnk'));" ^
  "$s.TargetPath=(Join-Path $env:SystemRoot 'System32\wscript.exe');" ^
  "$s.Arguments=($q + (Join-Path $env:CM_DIR 'Clipmaker.vbs') + $q);" ^
  "$s.WorkingDirectory=$env:CM_DIR;" ^
  "$s.IconLocation=(Join-Path $env:CM_DIR 'static\clipmaker.ico');" ^
  "$s.Description='Clipmaker';" ^
  "$s.Save();" ^
  "Write-Host ('Acceso directo creado en ' + $d)"
if errorlevel 1 (echo No se pudo crear el acceso directo.) else (echo Listo. Busca "Clipmaker" en tu escritorio. Se abre sin ventana negra.)
pause
