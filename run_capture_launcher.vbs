' ເປີດ capture_bill_launcher.py (ບໍ່ຂຶ້ນ CMD)
Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

' ໂຟນເດີທີ່ໄຟລ໌ນີ້ຢູ່ (ຄວນເປັນ send_bill)
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

venvPython = scriptDir & "\.venv\Scripts\pythonw.exe"
captureLauncher = scriptDir & "\capture_bill_launcher.py"

If fso.FileExists(venvPython) Then
    cmd = """" & venvPython & """ """ & captureLauncher & """"
Else
    ' fallback: ໃຊ້ pythonw ຈາກ PATH
    cmd = "pythonw """ & captureLauncher & """"
End If

WshShell.Run cmd, 0, False

