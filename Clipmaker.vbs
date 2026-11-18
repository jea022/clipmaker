' Windows: abre Clipmaker SIN ventana de consola (doble clic aqui o usa el acceso directo del escritorio).
' La app sigue funcionando aunque cierres el navegador; se cierra con el boton "Cerrar Clipmaker".
Option Explicit

Dim sh, fso, dir, venvw, launcher, ok
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
launcher = """" & dir & "\launcher.py"""
venvw = dir & "\.venv\Scripts\pythonw.exe"

Function PyOk(prefix)
  Dim rc
  On Error Resume Next
  rc = sh.Run("cmd /c " & prefix & " -c ""import sys;sys.exit(0 if sys.version_info>=(3,9) else 1)""", 0, True)
  PyOk = (Err.Number = 0 And rc = 0)
  Err.Clear
  On Error GoTo 0
End Function

ok = True
If fso.FileExists(venvw) Then
  sh.Run """" & venvw & """ " & launcher, 0, False
ElseIf PyOk("py -3") Then
  sh.Run "pyw -3 " & launcher, 0, False
ElseIf PyOk("python") Then
  sh.Run "pythonw " & launcher, 0, False
Else
  ok = False
End If

If Not ok Then
  MsgBox "No encuentro Python 3.9 o superior." & vbCrLf & vbCrLf & _
         "Instalalo abriendo PowerShell y ejecutando:" & vbCrLf & "winget install Python.Python.3.12" & vbCrLf & vbCrLf & _
         "Luego abre Clipmaker otra vez.", 16, "Clipmaker"
End If
