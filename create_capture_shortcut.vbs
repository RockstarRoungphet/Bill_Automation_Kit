' ສ້າງ Shortcut ຢູ່ Desktop ເພື່ອເປີດ capture_bill_launcher.py ດ້ວຍໄອຄອນ send_bill.ico
' ດັບເບິລຄລິກໄຟລ໌ນີ້ 1 ຄັ້ງ ຈະມີໄອຄອນ "Capture Bill Launcher" ຢູ່ Desktop

Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

' ໂຟນເດີທີ່ໄຟລ໌ນີ້ຢູ່ (ຄວນເປັນ send_bill)
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' path ໄປຫາ VBS ທີ່ໃຊ້ເປີດ UI
vbsPath = scriptDir & "\run_capture_launcher.vbs"

' path ໄອຄອນ (ໃຊ້ຮ່ວມກັບ no_api_send_bill_manual)
iconPath = scriptDir & "\no_api_send_bill_manual\send_bill.ico"

' ສ້າງ shortcut ຢູ່ Desktop
Set shortcut = WshShell.CreateShortcut(WshShell.SpecialFolders("Desktop") & "\Capture Bill Launcher.lnk")
shortcut.TargetPath = vbsPath
shortcut.WorkingDirectory = scriptDir
' Description ເປັນອັງກິດໃຫ້ tooltip ອ່ານງ່າຍ
shortcut.Description = "Capture bill screenshots from Google Sheet"
If fso.FileExists(iconPath) Then
    shortcut.IconLocation = iconPath
End If
shortcut.Save()

MsgBox "Create shortcut on Desktop finished." & vbCrLf & "Name: Capture Bill Launcher", 64, "Capture Bill"

