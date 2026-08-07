# -*- coding: utf-8 -*-
"""Settings window for Bill_Automation_Kit (tkinter)."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional

from settings.config_io import ConfigIO, StatusItem


class SettingsWindow:
    def __init__(self, parent: tk.Misc, root_path: Path):
        self.parent = parent
        self.io = ConfigIO(root_path)
        self.io.ensure_seeded()
        self.win = tk.Toplevel(parent)
        self.win.title("Settings — Bill Automation Kit")
        self.win.geometry("720x560")
        self.win.minsize(640, 480)
        self.win.transient(parent)

        self._page_rows: List[Dict[str, Any]] = []
        self._show_tokens = tk.BooleanVar(value=False)

        nb = ttk.Notebook(self.win)
        nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self.tab_check = ttk.Frame(nb)
        self.tab_sheet = ttk.Frame(nb)
        self.tab_pages = ttk.Frame(nb)
        self.tab_webhook = ttk.Frame(nb)
        nb.add(self.tab_check, text="1. Checklist")
        nb.add(self.tab_sheet, text="2. Google Sheet")
        nb.add(self.tab_pages, text="3. เพจ Facebook")
        nb.add(self.tab_webhook, text="4. Webhook / ngrok")

        self._build_checklist()
        self._build_sheet()
        self._build_pages()
        self._build_webhook()

        bottom = ttk.Frame(self.win)
        bottom.pack(fill=tk.X, padx=8, pady=(0, 8))
        ttk.Button(bottom, text="รีเฟรช Checklist", command=self.refresh_checklist).pack(
            side=tk.LEFT
        )
        ttk.Button(bottom, text="ปิด", command=self.win.destroy).pack(side=tk.RIGHT)
        ttk.Button(bottom, text="บันทึกทั้งหมด", command=self.save_all).pack(
            side=tk.RIGHT, padx=(0, 8)
        )

        self.refresh_checklist()
        self.win.grab_set()

    # ----- Checklist -----

    def _build_checklist(self) -> None:
        frm = self.tab_check
        ttk.Label(
            frm,
            text="สถานะการตั้งค่า — รายการสีแดง/ขาดต้องแก้ก่อนใช้งานส่งบิล (Token)",
            wraplength=680,
        ).pack(anchor=tk.W, padx=10, pady=8)
        self.check_box = tk.Text(frm, height=18, wrap=tk.WORD, font=("Consolas", 10))
        self.check_box.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.check_box.tag_configure("ok", foreground="#0a7a2f")
        self.check_box.tag_configure("bad", foreground="#b00020")
        self.check_box.tag_configure("soft", foreground="#a05a00")
        self.check_box.configure(state=tk.DISABLED)

    def refresh_checklist(self) -> None:
        st = self.io.check_setup_status()
        self.check_box.configure(state=tk.NORMAL)
        self.check_box.delete("1.0", tk.END)
        for item in st.items:
            item: StatusItem
            mark = "OK " if item.ok else "!! "
            tag = "ok" if item.ok else ("bad" if item.critical else "soft")
            crit = "" if item.critical else " (ไม่บังคับสำหรับส่งบิล browser)"
            self.check_box.insert(tk.END, f"{mark}{item.label}{crit}\n", tag)
        if st.all_critical_ok:
            self.check_box.insert(tk.END, "\nพร้อมใช้งาน critical setup แล้ว\n", "ok")
        else:
            self.check_box.insert(tk.END, "\nยังขาด:\n", "bad")
            for lab in st.missing_labels():
                self.check_box.insert(tk.END, f"  - {lab}\n", "bad")
        self.check_box.configure(state=tk.DISABLED)

    # ----- Sheet -----

    def _build_sheet(self) -> None:
        frm = self.tab_sheet
        sheet = self.io.load_sheet_config()
        grid = ttk.Frame(frm)
        grid.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(grid, text="Sheet ID:").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.var_sheet_id = tk.StringVar(value=sheet.get("sheet_id") or "")
        ttk.Entry(grid, textvariable=self.var_sheet_id, width=56).grid(
            row=0, column=1, sticky=tk.EW, pady=4, padx=(8, 0)
        )

        ttk.Label(grid, text="ชื่อชีต (คั่นด้วย ,):").grid(
            row=1, column=0, sticky=tk.W, pady=4
        )
        names = sheet.get("sheet_names") or []
        self.var_sheet_names = tk.StringVar(value=", ".join(names))
        ttk.Entry(grid, textvariable=self.var_sheet_names, width=56).grid(
            row=1, column=1, sticky=tk.EW, pady=4, padx=(8, 0)
        )
        grid.columnconfigure(1, weight=1)

        cred_frm = ttk.LabelFrame(frm, text="Google Service Account JSON")
        cred_frm.pack(fill=tk.X, padx=10, pady=8)
        has = self.io.creds_path.is_file()
        self.var_creds_status = tk.StringVar(
            value=(
                f"พบไฟล์: {self.io.creds_path}"
                if has
                else "ยังไม่มี google_credentials.json — เลือกไฟล์ด้านล่าง"
            )
        )
        ttk.Label(cred_frm, textvariable=self.var_creds_status, wraplength=640).pack(
            anchor=tk.W, padx=8, pady=6
        )
        ttk.Button(
            cred_frm, text="เลือกไฟล์ credentials .json…", command=self._browse_creds
        ).pack(anchor=tk.W, padx=8, pady=(0, 8))

        ttk.Button(frm, text="บันทึก Google Sheet", command=self.save_sheet).pack(
            anchor=tk.E, padx=10, pady=8
        )
        ttk.Label(
            frm,
            text="บันทึกไปที่ no_api_send_bill และ no_api_send_bill_manual (sync ค่าเดียวกัน)",
            foreground="#555",
        ).pack(anchor=tk.W, padx=10)

    def _browse_creds(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.win,
            title="เลือก google_credentials.json",
            filetypes=[("JSON", "*.json"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            dest = self.io.copy_google_credentials(Path(path))
            self.var_creds_status.set(f"คัดลอกแล้ว: {dest}")
            messagebox.showinfo("บันทึก", f"คัดลอก credentials ไปที่:\n{dest}", parent=self.win)
            self.refresh_checklist()
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e), parent=self.win)

    def save_sheet(self) -> bool:
        sid = self.var_sheet_id.get().strip()
        names = [n.strip() for n in self.var_sheet_names.get().split(",") if n.strip()]
        try:
            self.io.save_sheet_config(sid, names)
            messagebox.showinfo("บันทึก", "บันทึก Google Sheet แล้ว", parent=self.win)
            self.refresh_checklist()
            return True
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e), parent=self.win)
            return False

    # ----- Pages -----

    def _build_pages(self) -> None:
        frm = self.tab_pages
        top = ttk.Frame(frm)
        top.pack(fill=tk.X, padx=10, pady=8)
        ttk.Label(top, text="รายการเพจ (page_token.json + ซิงก์ page_name_to_id)").pack(
            side=tk.LEFT
        )
        ttk.Checkbutton(
            top,
            text="แสดง token",
            variable=self._show_tokens,
            command=self._reload_page_tree_display,
        ).pack(side=tk.RIGHT)

        cols = ("name", "page_id", "token", "enabled")
        self.pages_tree = ttk.Treeview(
            frm, columns=cols, show="headings", height=10, selectmode="browse"
        )
        self.pages_tree.heading("name", text="page_name")
        self.pages_tree.heading("page_id", text="page_id")
        self.pages_tree.heading("token", text="access_token")
        self.pages_tree.heading("enabled", text="enabled")
        self.pages_tree.column("name", width=140)
        self.pages_tree.column("page_id", width=140)
        self.pages_tree.column("token", width=260)
        self.pages_tree.column("enabled", width=60)
        self.pages_tree.pack(fill=tk.BOTH, expand=True, padx=10)

        edit = ttk.LabelFrame(frm, text="แก้ไขแถวที่เลือก / เพิ่มใหม่")
        edit.pack(fill=tk.X, padx=10, pady=8)
        self.var_p_name = tk.StringVar()
        self.var_p_id = tk.StringVar()
        self.var_p_token = tk.StringVar()
        self.var_p_enabled = tk.BooleanVar(value=True)
        eg = ttk.Frame(edit)
        eg.pack(fill=tk.X, padx=6, pady=4)
        ttk.Label(eg, text="ชื่อเพจ").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(eg, textvariable=self.var_p_name, width=24).grid(
            row=0, column=1, padx=4
        )
        ttk.Label(eg, text="Page ID").grid(row=0, column=2, sticky=tk.W)
        ttk.Entry(eg, textvariable=self.var_p_id, width=22).grid(row=0, column=3, padx=4)
        ttk.Label(eg, text="Token").grid(row=1, column=0, sticky=tk.W, pady=4)
        ttk.Entry(eg, textvariable=self.var_p_token, width=50).grid(
            row=1, column=1, columnspan=2, sticky=tk.EW, pady=4, padx=4
        )
        ttk.Checkbutton(eg, text="enabled", variable=self.var_p_enabled).grid(
            row=1, column=3, sticky=tk.W
        )

        bf = ttk.Frame(frm)
        bf.pack(fill=tk.X, padx=10, pady=(0, 8))
        ttk.Button(bf, text="โหลดจากแถวที่เลือก", command=self._load_selected_page).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(bf, text="เพิ่ม / อัปเดตแถว", command=self._upsert_page_row).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(bf, text="ลบแถวที่เลือก", command=self._delete_page_row).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(bf, text="บันทึกเพจ", command=self.save_pages).pack(side=tk.RIGHT)

        self.pages_tree.bind("<<TreeviewSelect>>", lambda _e: self._load_selected_page())
        self._page_rows = self.io.load_page_tokens()
        self._reload_page_tree_display()

    def _mask_token(self, token: str) -> str:
        t = token or ""
        if self._show_tokens.get() or len(t) < 8:
            return t
        return t[:4] + "…" + t[-4:] if len(t) > 12 else "****"

    def _reload_page_tree_display(self) -> None:
        tree = self.pages_tree
        for iid in tree.get_children():
            tree.delete(iid)
        for i, p in enumerate(self._page_rows):
            tree.insert(
                "",
                tk.END,
                iid=str(i),
                values=(
                    p.get("page_name") or "",
                    p.get("page_id") or "",
                    self._mask_token(str(p.get("access_token") or "")),
                    "yes" if p.get("enabled", True) else "no",
                ),
            )

    def _load_selected_page(self) -> None:
        sel = self.pages_tree.selection()
        if not sel:
            return
        try:
            idx = int(sel[0])
        except ValueError:
            return
        if idx < 0 or idx >= len(self._page_rows):
            return
        p = self._page_rows[idx]
        self.var_p_name.set(p.get("page_name") or "")
        self.var_p_id.set(p.get("page_id") or "")
        self.var_p_token.set(p.get("access_token") or "")
        self.var_p_enabled.set(p.get("enabled", True) is not False)

    def _upsert_page_row(self) -> None:
        name = self.var_p_name.get().strip()
        pid = self.var_p_id.get().strip()
        token = self.var_p_token.get().strip()
        enabled = self.var_p_enabled.get()
        if not name and not pid:
            messagebox.showwarning("ข้อมูลไม่ครบ", "ใส่ page_name หรือ page_id", parent=self.win)
            return
        entry = {
            "page_name": name,
            "page_id": pid,
            "access_token": token,
            "enabled": enabled,
            "subscribed_fields": [
                "messages",
                "messaging_postbacks",
                "message_echoes",
            ],
        }
        sel = self.pages_tree.selection()
        if sel:
            try:
                idx = int(sel[0])
                if 0 <= idx < len(self._page_rows):
                    # keep token if user left field empty while editing masked intent: require re-paste
                    self._page_rows[idx] = entry
                    self._reload_page_tree_display()
                    return
            except ValueError:
                pass
        # update by matching name or id
        for i, p in enumerate(self._page_rows):
            if (name and p.get("page_name") == name) or (pid and p.get("page_id") == pid):
                self._page_rows[i] = entry
                self._reload_page_tree_display()
                return
        self._page_rows.append(entry)
        self._reload_page_tree_display()

    def _delete_page_row(self) -> None:
        sel = self.pages_tree.selection()
        if not sel:
            return
        try:
            idx = int(sel[0])
        except ValueError:
            return
        if 0 <= idx < len(self._page_rows):
            del self._page_rows[idx]
            self._reload_page_tree_display()

    def save_pages(self) -> bool:
        try:
            self.io.save_pages(self._page_rows)
            messagebox.showinfo(
                "บันทึก",
                "บันทึก page_token.json และ page_name_to_id แล้ว",
                parent=self.win,
            )
            self.refresh_checklist()
            return True
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e), parent=self.win)
            return False

    # ----- Webhook -----

    def _build_webhook(self) -> None:
        frm = self.tab_webhook
        wh = self.io.load_webhook_fields()
        grid = ttk.Frame(frm)
        grid.pack(fill=tk.X, padx=10, pady=10)

        self.var_verify = tk.StringVar(value=wh.get("WEBHOOK_VERIFY_TOKEN") or "")
        self.var_port = tk.StringVar(value=wh.get("PORT") or "5000")
        self.var_ngrok = tk.StringVar(value=wh.get("NGROK_DOMAIN") or "")
        self.var_base = tk.StringVar(value=wh.get("BASE_URL") or "")

        rows = [
            ("WEBHOOK_VERIFY_TOKEN", self.var_verify),
            ("PORT", self.var_port),
            ("NGROK_DOMAIN (เช่น xxx.ngrok-free.dev)", self.var_ngrok),
            ("BASE_URL (ว่างได้ — จะสร้างจาก domain)", self.var_base),
        ]
        for i, (lab, var) in enumerate(rows):
            ttk.Label(grid, text=lab).grid(row=i, column=0, sticky=tk.W, pady=4)
            ttk.Entry(grid, textvariable=var, width=50).grid(
                row=i, column=1, sticky=tk.EW, padx=8, pady=4
            )
        grid.columnconfigure(1, weight=1)

        ttk.Label(
            frm,
            text="ค่าจะถูก merge ลง .env และ user_settings.json (ไม่ลบ key อื่นใน .env)",
            foreground="#555",
            wraplength=680,
        ).pack(anchor=tk.W, padx=10)
        ttk.Button(frm, text="บันทึก Webhook / ngrok", command=self.save_webhook).pack(
            anchor=tk.E, padx=10, pady=12
        )

    def save_webhook(self) -> bool:
        try:
            self.io.save_webhook_fields(
                self.var_verify.get(),
                self.var_port.get(),
                self.var_ngrok.get(),
                self.var_base.get(),
            )
            messagebox.showinfo("บันทึก", "บันทึก .env + user_settings แล้ว", parent=self.win)
            self.refresh_checklist()
            return True
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e), parent=self.win)
            return False

    # ----- all -----

    def save_all(self) -> None:
        ok = True
        ok = self.save_sheet_silent() and ok
        ok = self.save_pages_silent() and ok
        ok = self.save_webhook_silent() and ok
        self.refresh_checklist()
        if ok:
            messagebox.showinfo("บันทึก", "บันทึกการตั้งค่าทั้งหมดแล้ว", parent=self.win)
        else:
            messagebox.showwarning(
                "บางส่วนไม่สำเร็จ",
                "บันทึกบางส่วนล้มเหลว — ดู error ก่อนหน้า",
                parent=self.win,
            )

    def save_sheet_silent(self) -> bool:
        try:
            names = [n.strip() for n in self.var_sheet_names.get().split(",") if n.strip()]
            self.io.save_sheet_config(self.var_sheet_id.get().strip(), names)
            return True
        except Exception as e:
            messagebox.showerror("Sheet", str(e), parent=self.win)
            return False

    def save_pages_silent(self) -> bool:
        try:
            self.io.save_pages(self._page_rows)
            return True
        except Exception as e:
            messagebox.showerror("เพจ", str(e), parent=self.win)
            return False

    def save_webhook_silent(self) -> bool:
        try:
            self.io.save_webhook_fields(
                self.var_verify.get(),
                self.var_port.get(),
                self.var_ngrok.get(),
                self.var_base.get(),
            )
            return True
        except Exception as e:
            messagebox.showerror("Webhook", str(e), parent=self.win)
            return False


def open_settings_window(parent: tk.Misc, project_root: Path) -> SettingsWindow:
    return SettingsWindow(parent, Path(project_root))
