' เปิด Launcher UI (ไม่แสดงหน้าต่าง CMD)
Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = scriptDir & "\run_launcher_ui.bat"
WshShell.Run """" & batPath & """", 0, False
