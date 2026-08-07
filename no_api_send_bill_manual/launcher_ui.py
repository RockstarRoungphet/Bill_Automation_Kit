#!/usr/bin/env python3
"""
Launcher UI — ໜ້າຕ່າງສຳລັບຮັນ run_manual.py ແລະ send_bill_signal.ahk
ສະແດງສະຖານະຈາກ run_manual.py ແບບ real-time
"""
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import ttk, scrolledtext, messagebox
except ImportError:
    print("ຕ້ອງໃຊ້ Python ທີ່ມີ tkinter (ໃນ Windows ມັກຈະມີໃຫ້ແລ້ວ)")
    sys.exit(1)

PROJECT_DIR = Path(__file__).resolve().parent
RUN_MANUAL = PROJECT_DIR / "run_manual.py"
AHK_SCRIPT = PROJECT_DIR / "send_bill_signal.ahk"

# ສ່ວນຂອງຖ່າຍຮູບບິນ (capture_bill_screenshot.py) ຢູ່ໂຟນເດີແມ່ (Testing / send_bill)
PROJECT_ROOT = PROJECT_DIR.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from settings.config_io import check_setup_status
    from settings.settings_ui import open_settings_window
except ImportError:
    check_setup_status = None  # type: ignore
    open_settings_window = None  # type: ignore

CAPTURE_SCRIPT = PROJECT_ROOT / "capture_bill_screenshot.py"
HAL_CAPTURE_SCRIPT = PROJECT_ROOT / "capture_bill_hal.py"
AUTH_JSON = PROJECT_ROOT / "auth.json"
WINDOWS_SCRIPTS_DIR = PROJECT_ROOT / "scripts" / "windows"
AUTO_CLEANUP_INSTALLER = WINDOWS_SCRIPTS_DIR / "install_monthly_cleanup_task.ps1"
AUTO_CLEANUP_TASK_NAME = "Cleanup bill_images monthly"

# no_api_send_bill: ສົ່ງບິນອັດຕະໂນມັດດ້ວຍ Playwright (ໂຟນເດີ no_api_send_bill)
NO_API_SEND_BILL_DIR = PROJECT_ROOT / "no_api_send_bill"
NO_API_SCRIPT = NO_API_SEND_BILL_DIR / "scripts" / "open_inbox_and_send.py"

# API-based scripts (Token)
WEBHOOK_SCRIPT = PROJECT_ROOT / "messenger_webhook_server.py"
SEND_BILL_API_SCRIPT = PROJECT_ROOT / "send_bill_from_sheet.py"
NGROK_EXE = PROJECT_ROOT / "ngrok.exe"
USER_SETTINGS_FILE = PROJECT_ROOT / "user_settings.json"


def _load_ngrok_domain() -> str:
    """Domain from env / user_settings.json only — never hardcode a personal ngrok host."""
    env = (os.environ.get("NGROK_DOMAIN") or "").strip()
    if env:
        return env.removeprefix("https://").removeprefix("http://").strip("/")
    base = (os.environ.get("BASE_URL") or "").strip()
    if base.startswith("http"):
        return base.split("://", 1)[-1].strip("/")
    if USER_SETTINGS_FILE.is_file():
        try:
            import json
            data = json.loads(USER_SETTINGS_FILE.read_text(encoding="utf-8"))
            d = str(data.get("ngrok_domain") or "").strip()
            if d:
                return d.removeprefix("https://").removeprefix("http://").strip("/")
        except Exception:
            pass
    return ""


NGROK_DOMAIN = _load_ngrok_domain()


def _resolve_ngrok_executable() -> Path | None:
    """Prefer repo-root ngrok.exe (gitignored); else ngrok on PATH (e.g. winget)."""
    if NGROK_EXE.is_file():
        return NGROK_EXE
    for name in ("ngrok.exe", "ngrok"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def _get_python_for_api() -> str:
    """Python from the root .venv for API-based scripts (webhook, send_bill_from_sheet)."""
    if sys.platform == "win32":
        for name in ("python.exe", "pythonw.exe"):
            p = PROJECT_ROOT / ".venv" / "Scripts" / name
            if p.is_file():
                return str(p)
    return sys.executable


def _get_python_for_capture() -> str:
    """
    ເລືອກ Python ທີ່ໃຊ້ຮັນ capture_bill_screenshot.py
    - ໃນ Windows: ພະຍາຍາມໃຊ້ .venv ທີ່ໂຟນເດີຫຼັກ (send_bill\\.venv) ກ່ອນ
    - ຖ້າບໍ່ມີ: ໃຊ້ sys.executable (Python ທີ່ຮັນ launcher_ui.py)
    """
    if sys.platform == "win32":
        root_venv_scripts = PROJECT_ROOT / ".venv" / "Scripts"
        candidates = ["pythonw.exe", "python.exe"]
        for name in candidates:
            p = root_venv_scripts / name
            if p.is_file():
                return str(p)
    return sys.executable


def _get_python_for_no_api() -> str:
    """
    ເລືອກ Python ທີ່ໃຊ້ຮັນ no_api_send_bill (open_inbox_and_send.py)
    - ໃນ Windows: ພະຍາຍາມໃຊ້ .venv ໃນ no_api_send_bill ກ່ອນ (ມີ Playwright)
    - ຖ້າບໍ່ມີ: ໃຊ້ sys.executable
    """
    if sys.platform == "win32":
        venv_scripts = NO_API_SEND_BILL_DIR / ".venv" / "Scripts"
        for name in ("python.exe", "pythonw.exe"):
            p = venv_scripts / name
            if p.is_file():
                return str(p)
        root_venv = PROJECT_ROOT / ".venv" / "Scripts"
        for name in ("python.exe", "pythonw.exe"):
            p = root_venv / name
            if p.is_file():
                return str(p)
    return sys.executable


def find_ahk_exe():
    """หา AutoHotkey (UX / v2) บน Windows"""
    if sys.platform != "win32":
        return None
    program_files = Path(os.environ.get("ProgramFiles", "C:\\Program Files"))
    candidates = [
        program_files / "AutoHotkey" / "UX" / "AutoHotkeyUX.exe",
        program_files / "AutoHotkey" / "v2" / "AutoHotkey64.exe",
        program_files / "AutoHotkey" / "v2" / "AutoHotkey32.exe",
        program_files / "AutoHotkey" / "v2" / "AutoHotkeyU64.exe",
        Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")) / "AutoHotkey" / "v2" / "AutoHotkey64.exe",
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    return None


def run_manual_worker(proc: subprocess.Popen, out_queue: queue.Queue):
    """อ่าน stdout/stderr จาก run_manual.py แล้วใส่ใน queue"""
    try:
        for line in proc.stdout:
            out_queue.put(("run", line.decode("utf-8", errors="replace")))
    except Exception:
        pass
    out_queue.put(("run", None))


def capture_all_worker(commands, cwd: Path, env: dict, out_queue: queue.Queue):
    """Run multiple capture commands sequentially and stream combined logs.

    ไม่หยุดที่ขั้นแรกถ้า exit ไม่เป็น 0 — Anousith กับ HAL กรองคนละ carrier (คอลัมน์ G)
    จึงต้องรันทั้งคู่แม้อีกฝั่งจะไม่มี tracking ใน Sheet
    """
    try:
        any_failed = False
        for title, cmd in commands:
            out_queue.put(("capture_all", f"\n=== {title} ===\n"))
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                env=env,
            )
            saw_hal_no_id = False
            for line in proc.stdout:
                decoded = line.decode("utf-8", errors="replace")
                if title == "Capture HAL" and "ไม่มี ID" in decoded:
                    saw_hal_no_id = True
                out_queue.put(("capture_all", decoded))
            proc.wait()
            if proc.returncode != 0:
                any_failed = True
                if title == "Capture HAL" and saw_hal_no_id:
                    out_queue.put(("capture_all", "ℹ️ HAL: ไม่มี ID (ไม่มีรายการให้ถ่าย)\n"))
                else:
                    out_queue.put(("capture_all", f"❌ {title} failed (exit {proc.returncode})\n"))
                # ไม่ break — รันขั้นถัดไป (เช่น HAL หลัง Anousith ไม่มีแถวອານຸສິດ)
        if any_failed:
            out_queue.put(
                (
                    "capture_all",
                    "\nℹ️ Capture All: ບາງຂັ້ນຕອນບໍ່ສຳເລັດ — ກວດເບິ່ງຂໍ້ຄວາມຂ້າງເທິງ\n",
                )
            )
    except Exception as e:
        out_queue.put(("capture_all", f"❌ Capture All error: {e}\n"))
    out_queue.put(("capture_all", None))


def no_api_worker(proc: subprocess.Popen, out_queue: queue.Queue):
    """อ่าน stdout/stderr จาก open_inbox_and_send.py (no_api_send_bill) แล้วใส่ใน queue"""
    try:
        for line in proc.stdout:
            out_queue.put(("no_api", line.decode("utf-8", errors="replace")))
    except Exception:
        pass
    out_queue.put(("no_api", None))


def no_api_notify_worker(proc: subprocess.Popen, out_queue: queue.Queue):
    """อ่าน stdout/stderr จาก open_inbox_and_send.py --notify-delivered แล้วใส่ใน queue"""
    try:
        for line in proc.stdout:
            out_queue.put(("no_api_notify", line.decode("utf-8", errors="replace")))
    except Exception:
        pass
    out_queue.put(("no_api_notify", None))


def no_api_stock_out_worker(proc: subprocess.Popen, out_queue: queue.Queue):
    """อ่าน stdout/stderr จาก open_inbox_and_send.py --notify-stock-out แล้วใส่ใน queue"""
    try:
        for line in proc.stdout:
            out_queue.put(("no_api_stock_out", line.decode("utf-8", errors="replace")))
    except Exception:
        pass
    out_queue.put(("no_api_stock_out", None))


def no_api_stock_available_worker(proc: subprocess.Popen, out_queue: queue.Queue):
    """อ่าน stdout/stderr จาก open_inbox_and_send.py --notify-stock-available แล้วใส่ใน queue"""
    try:
        for line in proc.stdout:
            out_queue.put(("no_api_stock_available", line.decode("utf-8", errors="replace")))
    except Exception:
        pass
    out_queue.put(("no_api_stock_available", None))


def _generic_worker(source: str, proc: subprocess.Popen, out_queue: queue.Queue):
    try:
        for line in proc.stdout:
            out_queue.put((source, line.decode("utf-8", errors="replace")))
    except Exception:
        pass
    out_queue.put((source, None))


def _run_sync_command(cmd, cwd: Path | None = None):
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creation_flags,
    )


def main():
    out_queue = queue.Queue()
    process_ref = {
        "proc": None, "ahk": None,
        "capture_all": None,
        "no_api": None, "no_api_notify": None, "no_api_stock_out": None, "no_api_stock_available": None,
        "webhook": None, "ngrok": None,
        "api_bill": None, "api_notify": None, "api_stock_out": None, "api_stock_available": None,
    }

    root = tk.Tk()
    root.title("ໜ້າຕ່າງຄວບຄຸມ")
    root.minsize(680, 460)
    root.geometry("720x500")
    root.configure(bg="white")

    style = ttk.Style(root)
    try:
        if sys.platform == "win32":
            # Keep native rounded button look on Windows.
            style.theme_use("vista")
    except Exception:
        pass
    style.configure("TFrame", background="white")
    style.configure("TLabel", background="white")
    style.configure("Section.TLabel", background="white")
    style.configure("TButton", padding=(8, 3))

    # ພື້ນທີ່ສະແດງສະຖານະ
    status_frame = ttk.Frame(root)
    status_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)
    status_title = ttk.Label(status_frame, text="Activity", style="Section.TLabel")
    status_title.pack(anchor=tk.W, padx=4, pady=(0, 4))
    status_text = scrolledtext.ScrolledText(
        status_frame,
        wrap=tk.WORD,
        height=14,
        font=("Consolas", 10),
        state=tk.DISABLED,
        bg="white",
        relief=tk.SOLID,
        borderwidth=1,
        highlightthickness=0,
    )
    status_text.pack(fill=tk.BOTH, expand=True)

    def append_status(msg: str):
        status_text.configure(state=tk.NORMAL)
        # Progress lines (e.g. "ถ่ายได้ N/Total รายการ") should not spam new lines in UI.
        # Terminal \r is unreliable inside a Tkinter text widget, so we replace the last
        # progress line instead of appending.
        def _is_progress_line(s: str) -> bool:
            s = (s or "").lstrip("\r").strip()
            return s.startswith("ถ่ายได้ ") and "รายการ" in s

        for part in (msg or "").split("\r"):
            if not part:
                continue
            if _is_progress_line(part):
                try:
                    last_line = status_text.get("end-2l linestart", "end-2l lineend")
                    if _is_progress_line(last_line):
                        # delete last line including its trailing newline
                        status_text.delete("end-2l linestart", "end-1l linestart")
                except Exception:
                    pass
            status_text.insert(tk.END, part)
        status_text.see(tk.END)
        status_text.configure(state=tk.DISABLED)

    def poll_queue():
        try:
            while True:
                source, line = out_queue.get_nowait()
                if line is None:
                    if source == "run":
                        btn_helper.config(state=tk.NORMAL)
                        process_ref["proc"] = None
                    elif source == "capture_all":
                        btn_capture_all.config(state=tk.NORMAL)
                        process_ref["capture_all"] = None
                    elif source == "no_api":
                        btn_no_api.config(state=tk.NORMAL)
                        process_ref["no_api"] = None
                    elif source == "no_api_notify":
                        btn_no_api_notify.config(state=tk.NORMAL)
                        process_ref["no_api_notify"] = None
                    elif source == "no_api_stock_out":
                        btn_no_api_stock_out.config(state=tk.NORMAL)
                        process_ref["no_api_stock_out"] = None
                    elif source == "no_api_stock_available":
                        btn_no_api_stock_available.config(state=tk.NORMAL)
                        process_ref["no_api_stock_available"] = None
                    elif source == "webhook":
                        process_ref["webhook"] = None
                        _check_webhook_stopped()
                    elif source == "ngrok":
                        process_ref["ngrok"] = None
                        _check_webhook_stopped()
                    elif source == "api_bill":
                        btn_api_bill.config(state=tk.NORMAL)
                        process_ref["api_bill"] = None
                    elif source == "api_notify":
                        btn_api_notify.config(state=tk.NORMAL)
                        process_ref["api_notify"] = None
                    elif source == "api_stock_out":
                        btn_api_stock_out.config(state=tk.NORMAL)
                        process_ref["api_stock_out"] = None
                    elif source == "api_stock_available":
                        btn_api_stock_available.config(state=tk.NORMAL)
                        process_ref["api_stock_available"] = None
                    continue
                # Keep raw output; scripts may stream progress updates intentionally.
                append_status(line)
        except queue.Empty:
            pass
        root.after(200, poll_queue)

    def run_run_manual():
        if process_ref["proc"] is not None:
            messagebox.showinfo("ແຈ້ງ", "run_manual.py ກຳລັງຮັນຢູ່ແລ້ວ")
            return
        if not RUN_MANUAL.is_file():
            messagebox.showerror("ຜິດພາດ", f"ບໍ່ພົບໄຟລ໌: {RUN_MANUAL}")
            return
        append_status("\nເລີ່ມຮັນ run_manual.py\n")
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            proc = subprocess.Popen(
                [sys.executable, "-u", str(RUN_MANUAL)],
                cwd=str(PROJECT_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                env=env,
            )
            process_ref["proc"] = proc
            btn_helper.config(state=tk.DISABLED)
            t = threading.Thread(target=run_manual_worker, args=(proc, out_queue), daemon=True)
            t.start()
        except Exception as e:
            append_status(f"ເກີດຜິດພາດ: {e}\n")
            messagebox.showerror("ຜິດພາດ", str(e))

    def run_ahk():
        if not AHK_SCRIPT.is_file():
            messagebox.showerror("ຜິດພາດ", f"ບໍ່ພົບໄຟລ໌: {AHK_SCRIPT}")
            return
        if sys.platform == "win32":
            ahk_exe = find_ahk_exe()
            if ahk_exe:
                try:
                    ahk_proc = subprocess.Popen(
                        [ahk_exe, str(AHK_SCRIPT)],
                        cwd=str(PROJECT_DIR),
                    )
                    process_ref["ahk"] = ahk_proc
                except Exception as e:
                    messagebox.showerror("ຜິດພາດ", str(e))
            else:
                messagebox.showerror(
                    "ຜິດພາດ",
                    "ບໍ່ພົບ AutoHotkey v2 ໃນ path ມາດຕະຖານ\n"
                    + "ຕິດຕັ້ງທີ່ C:\\Program Files\\AutoHotkey\\v2 ກ່ອນ ຫຼືແກ້ path ໃນ launcher_ui.py",
                )
        else:
            messagebox.showinfo("ແຈ້ງ", "ປຸ່ມຮັນ AHK ໃຊ້ໄດ້ແຕ່ໃນ Windows ເທົ່ານັ້ນ")

    def run_helper():
        """ຕົວຊ່ວຍສົ່ງບິນ: ຮັນ run_manual.py ແລະ send_bill_signal.ahk"""
        run_run_manual()
        run_ahk()

    def run_capture_all():
        """Run Anousith + HAL capture sequentially with one click."""
        if process_ref["capture_all"] is not None:
            messagebox.showinfo("ແຈ້ງ", "Capture All ກຳລັງຮັນຢູ່ແລ້ວ")
            return
        if not CAPTURE_SCRIPT.is_file() or not HAL_CAPTURE_SCRIPT.is_file():
            messagebox.showerror("ຜິດພາດ", f"ບໍ່ພົບໄຟລ໌: {CAPTURE_SCRIPT} ຫຼື {HAL_CAPTURE_SCRIPT}")
            return

        append_status(
            "\nເລີ່ມ Capture All: Anousith -> HAL (ແຍກຕາມຄອລຳ G: ອານຸສິດ / ຮຸ່ງອາລຸນ)\n"
        )
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        python_exec = _get_python_for_capture()

        anousith_cmd = [python_exec, "-u", str(CAPTURE_SCRIPT)]
        if AUTH_JSON.is_file():
            anousith_cmd.extend(["--private", "--storage-state", str(AUTH_JSON)])
            append_status("Anousith mode: private + auth.json (fast)\n")
        else:
            append_status("Anousith mode: public\n")

        hal_cmd = [python_exec, "-u", str(HAL_CAPTURE_SCRIPT), "--parallel-pages", "10"]
        append_status("HAL mode: auto-login + PNG only (parallel pages: 10)\n")

        commands = [
            ("Capture Anousith", anousith_cmd),
            ("Capture HAL", hal_cmd),
        ]

        btn_capture_all.config(state=tk.DISABLED)
        process_ref["capture_all"] = True
        t = threading.Thread(
            target=capture_all_worker,
            args=(commands, PROJECT_ROOT, env, out_queue),
            daemon=True,
        )
        t.start()

    def run_no_api_send_bill():
        """ຮັນ no_api_send_bill (open_inbox_and_send.py --sheet) ສົ່ງບິນອັດຕະໂນມັດດ້ວຍ Playwright"""
        if process_ref["no_api"] is not None:
            messagebox.showinfo("ແຈ້ງ", "no_api_send_bill ກຳລັງຮັນຢູ່ແລ້ວ")
            return
        if not NO_API_SCRIPT.is_file():
            messagebox.showerror("ຜິດພາດ", f"ບໍ່ພົບໄຟລ໌: {NO_API_SCRIPT}")
            return

        append_status("\nເລີ່ມຮັນ no_api_send_bill (open_inbox_and_send.py --sheet)\n")
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            python_exec = _get_python_for_no_api()
            cmd = [python_exec, "-u", str(NO_API_SCRIPT), "--sheet"]
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc = subprocess.Popen(
                cmd,
                cwd=str(NO_API_SEND_BILL_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                env=env,
                creationflags=creation_flags,
            )
            process_ref["no_api"] = proc
            btn_no_api.config(state=tk.DISABLED)
            t = threading.Thread(target=no_api_worker, args=(proc, out_queue), daemon=True)
            t.start()
        except Exception as e:
            append_status(f"ເກີດຜິດພາດ: {e}\n")
            messagebox.showerror("ຜິດພາດ", str(e))

    def run_no_api_notify_delivered():
        """ຮັນ open_inbox_and_send.py --sheet --notify-delivered (ແຈ້ງຮອດແລ້ວ)"""
        if process_ref["no_api_notify"] is not None:
            messagebox.showinfo("ແຈ້ງ", "ແຈ້ງຮອດແລ້ວ ກຳລັງຮັນຢູ່ແລ້ວ")
            return
        if not NO_API_SCRIPT.is_file():
            messagebox.showerror("ຜິດພາດ", f"ບໍ່ພົບໄຟລ໌: {NO_API_SCRIPT}")
            return

        append_status("\nເລີ່ມຮັນ ແຈ້ງຮອດແລ້ວ (open_inbox_and_send.py --sheet --notify-delivered)\n")
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            python_exec = _get_python_for_no_api()
            cmd = [python_exec, "-u", str(NO_API_SCRIPT), "--sheet", "--notify-delivered"]
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc = subprocess.Popen(
                cmd,
                cwd=str(NO_API_SEND_BILL_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                env=env,
                creationflags=creation_flags,
            )
            process_ref["no_api_notify"] = proc
            btn_no_api_notify.config(state=tk.DISABLED)
            t = threading.Thread(target=no_api_notify_worker, args=(proc, out_queue), daemon=True)
            t.start()
        except Exception as e:
            append_status(f"ເກີດຜິດພາດ: {e}\n")
            messagebox.showerror("ຜິດພາດ", str(e))

    def run_no_api_notify_stock_out():
        """ຮັນ open_inbox_and_send.py --sheet --notify-stock-out (ແຈ້ງສິນຄ້າໝົດ)"""
        if process_ref["no_api_stock_out"] is not None:
            messagebox.showinfo("ແຈ້ງ", "ແຈ້ງສິນຄ້າໝົດ ກຳລັງຮັນຢູ່ແລ້ວ")
            return
        if not NO_API_SCRIPT.is_file():
            messagebox.showerror("ຜິດພາດ", f"ບໍ່ພົບໄຟລ໌: {NO_API_SCRIPT}")
            return

        append_status("\nເລີ່ມຮັນ ແຈ້ງສິນຄ້າໝົດ (open_inbox_and_send.py --sheet --notify-stock-out)\n")
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            python_exec = _get_python_for_no_api()
            cmd = [python_exec, "-u", str(NO_API_SCRIPT), "--sheet", "--notify-stock-out"]
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc = subprocess.Popen(
                cmd,
                cwd=str(NO_API_SEND_BILL_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                env=env,
                creationflags=creation_flags,
            )
            process_ref["no_api_stock_out"] = proc
            btn_no_api_stock_out.config(state=tk.DISABLED)
            t = threading.Thread(target=no_api_stock_out_worker, args=(proc, out_queue), daemon=True)
            t.start()
        except Exception as e:
            append_status(f"ເກີດຜິດພາດ: {e}\n")
            messagebox.showerror("ຜິດພາດ", str(e))

    def run_no_api_notify_stock_available():
        """ຮັນ open_inbox_and_send.py --sheet --notify-stock-available (ແຈ້ງມີສິນຄ້າ)"""
        if process_ref["no_api_stock_available"] is not None:
            messagebox.showinfo("ແຈ້ງ", "ແຈ້ງມີສິນຄ້າ ກຳລັງຮັນຢູ່ແລ້ວ")
            return
        if not NO_API_SCRIPT.is_file():
            messagebox.showerror("ຜິດພາດ", f"ບໍ່ພົບໄຟລ໌: {NO_API_SCRIPT}")
            return

        append_status("\nເລີ່ມຮັນ ແຈ້ງມີສິນຄ້າ (open_inbox_and_send.py --sheet --notify-stock-available)\n")
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            python_exec = _get_python_for_no_api()
            cmd = [python_exec, "-u", str(NO_API_SCRIPT), "--sheet", "--notify-stock-available"]
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc = subprocess.Popen(
                cmd,
                cwd=str(NO_API_SEND_BILL_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                env=env,
                creationflags=creation_flags,
            )
            process_ref["no_api_stock_available"] = proc
            btn_no_api_stock_available.config(state=tk.DISABLED)
            t = threading.Thread(target=no_api_stock_available_worker, args=(proc, out_queue), daemon=True)
            t.start()
        except Exception as e:
            append_status(f"ເກີດຜິດພາດ: {e}\n")
            messagebox.showerror("ຜິດພາດ", str(e))

    # --- API-based button handlers ---

    def _check_webhook_stopped():
        """Reset button when both webhook + ngrok have stopped."""
        if process_ref["webhook"] is None and process_ref["ngrok"] is None:
            btn_webhook.config(text="ເລີ່ມ Webhook + ngrok")
            append_status("Webhook + ngrok ຢຸດແລ້ວ\n")

    def _stop_webhook():
        for key in ("webhook", "ngrok"):
            p = process_ref.get(key)
            if p is not None:
                try:
                    p.terminate()
                except Exception:
                    pass

    def toggle_webhook():
        """Toggle start/stop for webhook server + ngrok."""
        if process_ref["webhook"] is not None or process_ref["ngrok"] is not None:
            append_status("\nກຳລັງຢຸດ Webhook + ngrok...\n")
            _stop_webhook()
            return

        python_exec = _get_python_for_api()
        if not WEBHOOK_SCRIPT.is_file():
            messagebox.showerror("ຜິດພາດ", f"ບໍ່ພົບ: {WEBHOOK_SCRIPT}")
            return
        ngrok_exe = _resolve_ngrok_executable()
        if ngrok_exe is None:
            messagebox.showerror(
                "ຜິດພາດ",
                f"ບໍ່ພົບ ngrok — ວາງ {NGROK_EXE} ຫຼື ຕິດຕັ້ງ ngrok ໃຫ້ຢູ່ PATH (winget install ngrok.ngrok)",
            )
            return

        ngrok_domain = _load_ngrok_domain()
        if not ngrok_domain:
            messagebox.showerror(
                "ຜິດພາດ",
                "ຍັງບໍ່ຕັ້ງ ngrok domain.\n"
                "ວິທີ: ສ້າງ user_settings.json (ເບິ່ງ config_templates/user_settings.example.json)\n"
                "ຫຼືຕັ້ງ env NGROK_DOMAIN / BASE_URL",
            )
            return

        append_status("\nເລີ່ມ Webhook server + ngrok...\n")
        if ngrok_exe != NGROK_EXE:
            append_status(f"ngrok: {ngrok_exe} (PATH)\n")
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

        try:
            wh_proc = subprocess.Popen(
                [python_exec, "-u", str(WEBHOOK_SCRIPT)],
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                env=env,
                creationflags=creation_flags,
            )
            process_ref["webhook"] = wh_proc
            threading.Thread(
                target=_generic_worker, args=("webhook", wh_proc, out_queue), daemon=True,
            ).start()
        except Exception as e:
            append_status(f"ເກີດຜິດພາດ webhook: {e}\n")
            return

        try:
            # ngrok v3: --domain deprecated; ใช้ --url แทน
            ng_cmd = [
                str(ngrok_exe),
                "http",
                "5000",
                "--url",
                f"https://{ngrok_domain}",
            ]
            ng_proc = subprocess.Popen(
                ng_cmd,
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                creationflags=creation_flags,
            )
            process_ref["ngrok"] = ng_proc
            threading.Thread(
                target=_generic_worker, args=("ngrok", ng_proc, out_queue), daemon=True,
            ).start()
        except Exception as e:
            append_status(f"ເກີດຜິດພາດ ngrok: {e}\n")
            _stop_webhook()
            return

        btn_webhook.config(text="ຢຸດ Webhook + ngrok")
        append_status(f"ngrok domain: https://{ngrok_domain}\n")

    def run_api_send_bill():
        """ສົ່ງບິນຜ່ານ Token (send_bill_from_sheet.py --sheet)"""
        if process_ref["api_bill"] is not None:
            messagebox.showinfo("ແຈ້ງ", "ສົ່ງບິນ (Token) ກຳລັງຮັນຢູ່ແລ້ວ")
            return
        if not SEND_BILL_API_SCRIPT.is_file():
            messagebox.showerror("ຜິດພາດ", f"ບໍ່ພົບ: {SEND_BILL_API_SCRIPT}")
            return

        append_status("\nເລີ່ມສົ່ງບິນ (Token) — send_bill_from_sheet.py --sheet\n")
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            python_exec = _get_python_for_api()
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc = subprocess.Popen(
                [python_exec, "-u", str(SEND_BILL_API_SCRIPT), "--sheet"],
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                env=env,
                creationflags=creation_flags,
            )
            process_ref["api_bill"] = proc
            btn_api_bill.config(state=tk.DISABLED)
            threading.Thread(
                target=_generic_worker, args=("api_bill", proc, out_queue), daemon=True,
            ).start()
        except Exception as e:
            append_status(f"ເກີດຜິດພາດ: {e}\n")

    def run_api_notify_delivered():
        """ແຈ້ງຮອດແລ້ວຜ່ານ Token (send_bill_from_sheet.py --sheet --notify-delivered)"""
        if process_ref["api_notify"] is not None:
            messagebox.showinfo("ແຈ້ງ", "ແຈ້ງຮອດແລ້ວ (Token) ກຳລັງຮັນຢູ່ແລ້ວ")
            return
        if not SEND_BILL_API_SCRIPT.is_file():
            messagebox.showerror("ຜິດພາດ", f"ບໍ່ພົບ: {SEND_BILL_API_SCRIPT}")
            return

        append_status("\nເລີ່ມແຈ້ງຮອດແລ້ວ (Token) — send_bill_from_sheet.py --sheet --notify-delivered\n")
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            python_exec = _get_python_for_api()
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc = subprocess.Popen(
                [python_exec, "-u", str(SEND_BILL_API_SCRIPT), "--sheet", "--notify-delivered"],
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                env=env,
                creationflags=creation_flags,
            )
            process_ref["api_notify"] = proc
            btn_api_notify.config(state=tk.DISABLED)
            threading.Thread(
                target=_generic_worker, args=("api_notify", proc, out_queue), daemon=True,
            ).start()
        except Exception as e:
            append_status(f"ເກີດຜິດພາດ: {e}\n")

    def run_api_notify_stock_out():
        """ແຈ້ງສິນຄ້າໝົດຜ່ານ Token (send_bill_from_sheet.py --sheet --notify-stock-out)"""
        if process_ref["api_stock_out"] is not None:
            messagebox.showinfo("ແຈ້ງ", "ແຈ້ງສິນຄ້າໝົດ (Token) ກຳລັງຮັນຢູ່ແລ້ວ")
            return
        if not SEND_BILL_API_SCRIPT.is_file():
            messagebox.showerror("ຜິດພາດ", f"ບໍ່ພົບ: {SEND_BILL_API_SCRIPT}")
            return

        append_status("\nເລີ່ມແຈ້ງສິນຄ້າໝົດ (Token) — send_bill_from_sheet.py --sheet --notify-stock-out\n")
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            python_exec = _get_python_for_api()
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc = subprocess.Popen(
                [python_exec, "-u", str(SEND_BILL_API_SCRIPT), "--sheet", "--notify-stock-out"],
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                env=env,
                creationflags=creation_flags,
            )
            process_ref["api_stock_out"] = proc
            btn_api_stock_out.config(state=tk.DISABLED)
            threading.Thread(
                target=_generic_worker, args=("api_stock_out", proc, out_queue), daemon=True,
            ).start()
        except Exception as e:
            append_status(f"ເກີດຜິດພາດ: {e}\n")

    def run_api_notify_stock_available():
        """ແຈ້ງມີສິນຄ້າຜ່ານ Token (send_bill_from_sheet.py --sheet --notify-stock-available)"""
        if process_ref["api_stock_available"] is not None:
            messagebox.showinfo("ແຈ້ງ", "ແຈ້ງມີສິນຄ້າ (Token) ກຳລັງຮັນຢູ່ແລ້ວ")
            return
        if not SEND_BILL_API_SCRIPT.is_file():
            messagebox.showerror("ຜິດພາດ", f"ບໍ່ພົບ: {SEND_BILL_API_SCRIPT}")
            return

        append_status("\nເລີ່ມແຈ້ງມີສິນຄ້າ (Token) — send_bill_from_sheet.py --sheet --notify-stock-available\n")
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            python_exec = _get_python_for_api()
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc = subprocess.Popen(
                [python_exec, "-u", str(SEND_BILL_API_SCRIPT), "--sheet", "--notify-stock-available"],
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                env=env,
                creationflags=creation_flags,
            )
            process_ref["api_stock_available"] = proc
            btn_api_stock_available.config(state=tk.DISABLED)
            threading.Thread(
                target=_generic_worker, args=("api_stock_available", proc, out_queue), daemon=True,
            ).start()
        except Exception as e:
            append_status(f"ເກີດຜິດພາດ: {e}\n")

    def on_closing():
        for key in process_ref:
            p = process_ref[key]
            if isinstance(p, subprocess.Popen):
                try:
                    p.terminate()
                except Exception:
                    pass
        root.destroy()

    def query_auto_cleanup_task_status() -> dict:
        if sys.platform != "win32":
            return {
                "installed": False,
                "enabled": False,
                "status_text": "Auto cleanup: Windows only",
                "next_run": "",
            }

        query_cmd = ["schtasks.exe", "/Query", "/TN", AUTO_CLEANUP_TASK_NAME, "/V", "/FO", "LIST"]
        result = _run_sync_command(query_cmd)
        if result.returncode != 0:
            return {
                "installed": False,
                "enabled": False,
                "status_text": "Auto cleanup: Not installed",
                "next_run": "",
            }

        info = {}
        for raw in (result.stdout or "").splitlines():
            if ":" not in raw:
                continue
            key, value = raw.split(":", 1)
            info[key.strip().lower()] = value.strip()

        status = info.get("status", "")
        enabled = status.lower() != "disabled"
        next_run = info.get("next run time", "N/A")
        return {
            "installed": True,
            "enabled": enabled,
            "status_text": f"Auto cleanup: {'Enabled' if enabled else 'Disabled'} | Next: {next_run}",
            "next_run": next_run,
        }

    def refresh_auto_cleanup_status():
        state = query_auto_cleanup_task_status()
        auto_cleanup_status_var.set(state["status_text"])
        if state["installed"] and state["enabled"]:
            btn_auto_cleanup_toggle.config(text="Disable Auto Cleanup", state=tk.NORMAL)
        elif state["installed"] and not state["enabled"]:
            btn_auto_cleanup_toggle.config(text="Enable Auto Cleanup", state=tk.NORMAL)
        else:
            btn_auto_cleanup_toggle.config(
                text="Enable Auto Cleanup",
                state=tk.NORMAL if sys.platform == "win32" else tk.DISABLED,
            )

    def enable_auto_cleanup_task():
        if sys.platform != "win32":
            messagebox.showinfo("Info", "Auto cleanup is available on Windows only.")
            return
        if not AUTO_CLEANUP_INSTALLER.is_file():
            messagebox.showerror("Error", f"Installer script not found:\n{AUTO_CLEANUP_INSTALLER}")
            return

        append_status("\n[AutoCleanup] Installing/updating monthly task...\n")
        install_cmd = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(AUTO_CLEANUP_INSTALLER),
        ]
        install_result = _run_sync_command(install_cmd, cwd=PROJECT_ROOT)
        if install_result.stdout:
            append_status(install_result.stdout)
        if install_result.returncode != 0:
            err = (install_result.stderr or install_result.stdout or "Unknown error").strip()
            append_status(f"[AutoCleanup] install failed: {err}\n")
            messagebox.showerror("Error", f"Enable auto cleanup failed (install step):\n{err}")
            refresh_auto_cleanup_status()
            return

        enable_cmd = ["schtasks.exe", "/Change", "/TN", AUTO_CLEANUP_TASK_NAME, "/ENABLE"]
        enable_result = _run_sync_command(enable_cmd)
        if enable_result.returncode != 0:
            err = (enable_result.stderr or enable_result.stdout or "Unknown error").strip()
            append_status(f"[AutoCleanup] enable failed: {err}\n")
            messagebox.showerror("Error", f"Enable auto cleanup failed:\n{err}")
        else:
            append_status("[AutoCleanup] Enabled monthly cleanup task.\n")
        refresh_auto_cleanup_status()

    def disable_auto_cleanup_task():
        if sys.platform != "win32":
            messagebox.showinfo("Info", "Auto cleanup is available on Windows only.")
            return
        disable_cmd = ["schtasks.exe", "/Change", "/TN", AUTO_CLEANUP_TASK_NAME, "/DISABLE"]
        disable_result = _run_sync_command(disable_cmd)
        if disable_result.returncode != 0:
            err = (disable_result.stderr or disable_result.stdout or "Unknown error").strip()
            append_status(f"[AutoCleanup] disable failed: {err}\n")
            messagebox.showerror("Error", f"Disable auto cleanup failed:\n{err}")
        else:
            append_status("[AutoCleanup] Disabled monthly cleanup task.\n")
        refresh_auto_cleanup_status()

    def toggle_auto_cleanup_task():
        state = query_auto_cleanup_task_status()
        if state["installed"] and state["enabled"]:
            disable_auto_cleanup_task()
        else:
            enable_auto_cleanup_task()

    root.after(200, poll_queue)

    # Settings + first-run
    def open_settings():
        if open_settings_window is None:
            messagebox.showerror(
                "ຜິດພາດ",
                "ບໍ່ພົບ settings module — ກວດວ່າມີໂຟນເດີ settings ໃນໂປຣເຈັກ",
            )
            return
        open_settings_window(root, PROJECT_ROOT)

    def maybe_first_run_settings():
        if check_setup_status is None:
            return
        try:
            st = check_setup_status(PROJECT_ROOT)
        except Exception as e:
            append_status(f"[Settings] check failed: {e}\n")
            return
        if not st.all_critical_ok:
            missing = "\n".join(f"• {x}" for x in st.missing_labels()[:8])
            messagebox.showinfo(
                "Setup needed",
                "ຍັງຕ້ອງຕັ້ງຄ່າກ່ອນໃຊ້ງານ (Settings):\n\n"
                f"{missing}\n\n"
                "ກະລຸນາກອກຂໍ້ມູນໃນໜ້າຕ່າງ Settings ແລ້ວກົດບັນທຶກ",
            )
            open_settings()

    # แถว Settings
    lbl0 = ttk.Label(root, text="Setup:", font=("", 9, "bold"))
    lbl0.pack(anchor=tk.W, padx=10, pady=(6, 0))
    btn_frame0 = ttk.Frame(root)
    btn_frame0.pack(fill=tk.X, padx=8, pady=2)
    btn_settings = ttk.Button(btn_frame0, text="Settings…", command=open_settings)
    btn_settings.pack(side=tk.LEFT, padx=(0, 8))
    ttk.Label(
        btn_frame0,
        text="Sheet / เพจ·Token / Webhook·ngrok",
        foreground="#555",
    ).pack(side=tk.LEFT)

    # ປຸ່ມແຖວ 1: Browser-based (Playwright / Manual)
    lbl1 = ttk.Label(root, text="Browser (Playwright):", font=("", 9, "bold"))
    lbl1.pack(anchor=tk.W, padx=10, pady=(6, 0))
    btn_frame = ttk.Frame(root)
    btn_frame.pack(fill=tk.X, padx=8, pady=2)
    btn_helper = ttk.Button(btn_frame, text="ຕົວຊ່ວຍສົ່ງບິນ", command=run_helper)
    btn_helper.pack(side=tk.LEFT, padx=(0, 8))
    btn_capture_all = ttk.Button(btn_frame, text="ຖ່າຍຮູບບິນ", command=run_capture_all)
    btn_capture_all.pack(side=tk.LEFT, padx=(0, 8))
    btn_no_api = ttk.Button(btn_frame, text="ສົ່ງບິນ", command=run_no_api_send_bill)
    btn_no_api.pack(side=tk.LEFT, padx=(0, 8))
    btn_no_api_notify = ttk.Button(btn_frame, text="ແຈ້ງຮອດແລ້ວ", command=run_no_api_notify_delivered)
    btn_no_api_notify.pack(side=tk.LEFT, padx=(0, 8))
    btn_no_api_stock_out = ttk.Button(btn_frame, text="ແຈ້ງສິນຄ້າໝົດ", command=run_no_api_notify_stock_out)
    btn_no_api_stock_out.pack(side=tk.LEFT, padx=(0, 8))
    btn_no_api_stock_available = ttk.Button(btn_frame, text="ແຈ້ງມີສິນຄ້າ", command=run_no_api_notify_stock_available)
    btn_no_api_stock_available.pack(side=tk.LEFT)

    # ປຸ່ມແຖວ 2: API-based (Token)
    lbl2 = ttk.Label(root, text="API (Token):", font=("", 9, "bold"))
    lbl2.pack(anchor=tk.W, padx=10, pady=(8, 0))
    btn_frame2 = ttk.Frame(root)
    btn_frame2.pack(fill=tk.X, padx=8, pady=2)
    btn_webhook = ttk.Button(btn_frame2, text="ເລີ່ມ Webhook + ngrok", command=toggle_webhook)
    btn_webhook.pack(side=tk.LEFT, padx=(0, 8))
    btn_api_bill = ttk.Button(btn_frame2, text="ສົ່ງບິນ (Token)", command=run_api_send_bill)
    btn_api_bill.pack(side=tk.LEFT, padx=(0, 8))
    btn_api_notify = ttk.Button(btn_frame2, text="ແຈ້ງຮອດແລ້ວ (Token)", command=run_api_notify_delivered)
    btn_api_notify.pack(side=tk.LEFT, padx=(0, 8))
    btn_api_stock_out = ttk.Button(btn_frame2, text="ແຈ້ງສິນຄ້າໝົດ (Token)", command=run_api_notify_stock_out)
    btn_api_stock_out.pack(side=tk.LEFT, padx=(0, 8))
    btn_api_stock_available = ttk.Button(btn_frame2, text="ແຈ້ງມີສິນຄ້າ (Token)", command=run_api_notify_stock_available)
    btn_api_stock_available.pack(side=tk.LEFT)

    # ປຸ່ມແຖວ 3: Auto cleanup bill_images
    lbl3 = ttk.Label(root, text="Maintenance:", font=("", 9, "bold"))
    lbl3.pack(anchor=tk.W, padx=10, pady=(8, 0))
    btn_frame3 = ttk.Frame(root)
    btn_frame3.pack(fill=tk.X, padx=8, pady=2)
    btn_auto_cleanup_toggle = ttk.Button(
        btn_frame3,
        text="Enable Auto Cleanup",
        command=toggle_auto_cleanup_task,
    )
    btn_auto_cleanup_toggle.pack(side=tk.LEFT, padx=(0, 8))
    auto_cleanup_status_var = tk.StringVar(value="Auto cleanup: checking...")
    lbl_auto_cleanup_status = ttk.Label(btn_frame3, textvariable=auto_cleanup_status_var)
    lbl_auto_cleanup_status.pack(side=tk.LEFT)

    refresh_auto_cleanup_status()

    root.after(400, maybe_first_run_settings)

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
