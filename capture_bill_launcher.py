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
# ຖ້າມີ auth.json ໃນໂຟນເດີໂປຣເຈັກ ຈະໃຊ້โหมดສ່ວນຕົວ (--private --storage-state) ເພື່ອຖ່າຍໄວ
AUTH_JSON = PROJECT_DIR / "auth.json"


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
        status_frame, wrap=tk.WORD, height=16, font=("Consolas", 10), state=tk.DISABLED
    )
    status_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    def append_status(msg: str):
        status_text.configure(state=tk.NORMAL)
        status_text.insert(tk.END, msg)
        status_text.see(tk.END)
        status_text.configure(state=tk.DISABLED)

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
        if AUTH_JSON.is_file():
            cmd.extend(["--private", "--storage-state", str(AUTH_JSON)])
            append_status("โหมด: ໜ້າສ່ວນຕົວ (ໄວ — ໃຊ້ auth.json)\n")
        else:
            append_status("โหมด: ໜ້າສາທາລະນະ (ທີ່ລະບິນ — ຖ້າຕ້ອງການໄວ ວາງ auth.json ໄວ້ໃນໂຟນເດີໂປຣເຈັກ)\n")
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

