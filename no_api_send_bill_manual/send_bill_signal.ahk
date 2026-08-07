; AutoHotkey v2 — ສົ່ງສັນຍານໄປ run_manual.py
; Ctrl+V       = ຂັ້ນຕໍ່ໄປ (ວາງ = ເຮັດຂັ້ນຖັດໄປ)
; Enter        = ຂັ້ນຕໍ່ໄປ (ເປີດລິ້ງ)
; ດັບເບິລຄລິກ = ຂັ້ນຕໍ່ໄປ (ຢືນຢັນວ່າສົ່ງແລ້ວ)
; ທຣິເປິລຄລິກ = ບໍ່ພົບຜົນ
; Ctrl+Z       = ຍ້ອນກັບ 1 ຂັ້ນ

#Requires AutoHotkey v2.0
#SingleInstance Force

PORT := 29582
BASE := "http://127.0.0.1:" . PORT
click_count := 0
click_timer := 0

SendSignal(path) {
    try {
        whr := ComObject("WinHttp.WinHttpRequest.5.1")
        whr.Open("GET", BASE . path, false)
        whr.Send()
    }
}

~^v:: SendSignal("/next")
~Enter:: SendSignal("/next")
~^z:: SendSignal("/undo")

~LButton:: {
    global click_count, click_timer
    if (A_TimeSincePriorHotkey != "" && A_TimeSincePriorHotkey < 450 && A_PriorHotkey = "~LButton")
        click_count++
    else
        click_count := 1
    if (click_timer) {
        SetTimer(click_timer, 0)
        click_timer := 0
    }
    if (click_count >= 3) {
        SendSignal("/not_found")
        click_count := 0
    } else
        click_timer := SetTimer(OnClickTimer, -450)
}

OnClickTimer() {
    global click_count, click_timer
    click_timer := 0
    if (click_count >= 2)
        SendSignal("/next")
    click_count := 0
}
