' run_importer_hidden.vbs - launches run_importer.cmd with NO visible window.
' The scheduled task points here (wscript.exe). Style 0 = hidden; True = wait;
' returns the worker's exit code to Task Scheduler so failures still surface.
Option Explicit
Dim sh, here, rc
Set sh = CreateObject("WScript.Shell")
here = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
rc = sh.Run("cmd /c """ & here & "run_importer.cmd""", 0, True)
WScript.Quit rc
