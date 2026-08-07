' ສ້າງ Shortcut ຢູ່ Desktop ເພື່ອເປີດ Launcher UI ດ້ວຍໄອຄອນ send_bill.ico
' ດັບເບິລຄລິກໄຟລ໌ນີ້ 1 ຄັ້ງ ຈະມີໄອຄອນ "Send Bill Launcher" ຢູ່ Desktop
Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

' ໂຟນເດີທີ່ໄຟລ໌ນີ້ຢູ່ (ຄວນເປັນ no_api_send_bill_manual)
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' path ໄປຫາ VBS ທີ່ໃຊ້ຮັນ UI
vbsPath = scriptDir & "\run_launcher_ui.vbs"

' path ໄອຄອນ — ຢູ່ໂຟນເດີດຽວກັບສະຄຣິບ (ຮອງຮັບ clone ໄປ path ໃດກໍ່ໄດ້)
iconPath = scriptDir & "\send_bill.ico"

' ສ້າງ shortcut ຢູ່ Desktop
Set shortcut = WshShell.CreateShortcut(WshShell.SpecialFolders("Desktop") & "\Send Bill Launcher.lnk")
shortcut.TargetPath = vbsPath
shortcut.WorkingDirectory = scriptDir
' ຕັ້ງ Description ເປັນພາສາອັງກິດໃຫ້ tooltip ບໍ່ເພີຍ
shortcut.Description = "Send Bill Manual Launcher"
If fso.FileExists(iconPath) Then
    shortcut.IconLocation = iconPath
End If
shortcut.Save()

MsgBox "Create shortcut on Desktop finished." & vbCrLf & "Name: Send Bill Launcher", 64, "Send Bill Manual"
