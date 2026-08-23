#!/usr/bin/env python3
"""
Launcher UI ສຳລັບຖ່າຍຮູບບິນ (capture_bill_screenshot.py)
- ເປີດໜ້າຕ່າງສະແດງ log
- ມີປຸ່ມເຮັດ capture_bill_screenshot.py ດ້ວຍ Python ທີ່ກຳລັງຮັນ UI ຢູ່
"""

import os
import queue
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
CAPTURE_SCRIPT = PROJECT_DIR / "capture_bill_screenshot.py"
ICON_PATH = PROJECT_DIR / "no_api_send_bill_manual" / "send_bill.ico"
# ຖ້າມີ auth.json ຫຼື ANOUSITH_USER/PASSWORD ໃນ .env ຈະໃຊ້โหมดສ່ວນຕົວກ່ອນ
AUTH_JSON = PROJECT_DIR / "auth.json"
ENV_FILE = PROJECT_DIR / ".env"


def _env_value(key: str) -> str:
    val = (os.environ.get(key) or "").strip()
    if val:
        return val
    if not ENV_FILE.is_file():
        return ""
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == key:
                return v.strip().strip("'\"")
    except Exception:
        return ""
    return ""


def _anousith_can_use_private() -> bool:
    if AUTH_JSON.is_file():
        return True
    return bool(_env_value("ANOUSITH_USER") and _env_value("ANOUSITH_PASSWORD"))


def capture_worker(proc: subprocess.Popen, out_queue: queue.Queue):
    """ອ່ານ stdout/stderr ຈາກ process ແລ້ວໃສ່ໃນ queue"""
    try:
        for line in proc.stdout:
            out_queue.put(line.decode("utf-8", errors="replace"))
    except Exception:
        pass
    out_queue.put(None)


def main():
    out_queue: queue.Queue = queue.Queue()
    process_ref = {"proc": None}

    root = tk.Tk()
    root.title("ຖ່າຍຮູບບິນ — Launcher")
    root.minsize(480, 360)
    root.geometry("600x440")

    # ຕັ້ງ icon ໃນ Windows ຖ້າມີໄຟລ໌
    if sys.platform == "win32" and ICON_PATH.is_file():
        try:
            root.iconbitmap(str(ICON_PATH))
        except Exception:
            pass

    status_frame = ttk.LabelFrame(root, text="")
    status_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)
    status_text = scrolledtext.ScrolledText(
        status_frame,
        wrap=tk.WORD,
        height=16,
        font=("Consolas", 10),
        exportselection=True,
    )
    status_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    def _focus_is_editable() -> bool:
        w = root.focus_get()
        return w is not None and w is not status_text and w.winfo_class() in (
            "Entry",
            "TEntry",
            "Text",
            "TCombobox",
        )

    def copy_log(event=None):
        if _focus_is_editable():
            return None
        try:
            text = status_text.get("sel.first", "sel.last")
        except tk.TclError:
            text = ""
        if not text:
            return None
        root.clipboard_clear()
        root.clipboard_append(text)
        return "break"

    def select_all_log(event=None):
        if _focus_is_editable():
            return None
        status_text.tag_add("sel", "1.0", "end-1c")
        status_text.mark_set(tk.INSERT, "1.0")
        return "break"

    def _block_log_edit(event):
        ctrl = bool(event.state & 0x4)
        vk = int(getattr(event, "keycode", 0) or 0)
        ch = event.char or ""
        if ctrl and (ch == "\x01" or vk == 65):
            return select_all_log(event)
        if ctrl and (ch == "\x03" or vk == 67):
            return copy_log(event)
        if not ctrl and event.keysym not in (
            "Left",
            "Right",
            "Up",
            "Down",
            "Home",
            "End",
            "Prior",
            "Next",
            "Shift_L",
            "Shift_R",
            "Control_L",
            "Control_R",
            "Alt_L",
            "Alt_R",
        ):
            return "break"
        return None

    status_text.bind("<Key>", _block_log_edit)
    status_text.bind("<<Paste>>", lambda e: "break")
    status_text.bind("<<Cut>>", lambda e: "break")

    for seq in ("<Control-c>", "<Control-C>", "<Control-Insert>"):
        status_text.bind(seq, copy_log)
        root.bind_all(seq, copy_log, add="+")
    for seq in ("<Control-a>", "<Control-A>"):
        status_text.bind(seq, select_all_log)
        root.bind_all(seq, select_all_log, add="+")

    log_menu = tk.Menu(status_text, tearoff=0)
    log_menu.add_command(label="Copy", command=lambda: copy_log())
    log_menu.add_command(label="Select all", command=select_all_log)

    def show_log_menu(event):
        try:
            log_menu.tk_popup(event.x_root, event.y_root)
        finally:
            log_menu.grab_release()
        return "break"

    status_text.bind("<Button-3>", show_log_menu)

    def append_status(msg: str):
        status_text.insert(tk.END, msg)
        status_text.see(tk.END)

    def poll_queue():
        try:
            while True:
                line = out_queue.get_nowait()
                if line is None:
                    btn_run.config(state=tk.NORMAL)
                    process_ref["proc"] = None
                    break
                append_status(line if line.endswith("\n") else line + "\n")
        except queue.Empty:
            pass
        root.after(200, poll_queue)

    def run_capture():
        if process_ref["proc"] is not None:
            messagebox.showinfo("ແຈ້ງ", "capture_bill_screenshot.py ກຳລັງຮັນຢູ່ແລ້ວ")
            return
        if not CAPTURE_SCRIPT.is_file():
            messagebox.showerror("ຜິດພາດ", f"ບໍ່ພົບໄຟລ໌: {CAPTURE_SCRIPT}")
            return
        append_status("\n--- ເລີ່ມຖ່າຍຮູບບິນຈາກ Google Sheet ---\n")
        cmd = [sys.executable, "-u", str(CAPTURE_SCRIPT)]
        if _anousith_can_use_private():
            cmd.append("--private")
            if AUTH_JSON.is_file():
                cmd.extend(["--storage-state", str(AUTH_JSON)])
                append_status("โหมด: ໜ້າສ່ວນຕົວ (auth.json)\n")
            else:
                append_status("โหมด: ໜ້າສ່ວນຕົວ (auto-login จาก .env)\n")
        else:
            append_status(
                "โหมด: ໜ້າສາທາລະນະ — ยังไม่มี auth.json และยังไม่ตั้ง ANOUSITH_USER/PASSWORD\n"
            )
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            proc = subprocess.Popen(
                cmd,
                cwd=str(PROJECT_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                env=env,
            )
            process_ref["proc"] = proc
            btn_run.config(state=tk.DISABLED)
            t = threading.Thread(target=capture_worker, args=(proc, out_queue), daemon=True)
            t.start()
        except Exception as e:
            append_status(f"ເກີດຜິດພາດ: {e}\n")
            messagebox.showerror("ຜິດພາດ", str(e))

    def on_closing():
        if process_ref["proc"] is not None:
            try:
                process_ref["proc"].terminate()
            except Exception:
                pass
        root.destroy()

    root.after(200, poll_queue)

    btn_frame = ttk.Frame(root)
    btn_frame.pack(fill=tk.X, padx=8, pady=6)
    btn_run = ttk.Button(btn_frame, text="ເຮັດ capture_bill_screenshot.py", command=run_capture)
    btn_run.pack(side=tk.LEFT, padx=(0, 8))

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()

