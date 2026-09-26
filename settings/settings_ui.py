# -*- coding: utf-8 -*-
"""Settings window for Bill_Automation_Kit (tkinter)."""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional

from settings.config_io import (
    ConfigIO,
    StatusItem,
    PAGE_REPLY_TEXT_KEYS,
    collect_keyword_media_refs,
    format_keyword_list,
    normalize_keyword_replies,
    parse_keyword_list,
)
from settings.unicode_input import bind_unicode_editing
from settings.graph_page import GraphPageError, fetch_page_by_id, list_pages_from_user_token
from settings.media_thumbnail_panel import KeywordMediaPanel, MediaThumbnailPanel
from settings.searchable_page_picker import SearchablePagePicker
from settings.thin_entry import ThinEntry, create_thin_entry
from settings.ui_scrollbar import create_vertical_scrollbar
from settings.underline_tab_bar import UnderlineTabBar
from settings.open_browser_profile import (
    FACEBOOK_INBOX_URL,
    HAL_LOGIN_URL,
    WHATSAPP_WEB_URL,
    open_persistent_login,
)

_DEFAULT_SUBSCRIBED = [
    "messages",
    "messaging_postbacks",
    "message_echoes",
]

_WHITE = "#ffffff"
_BORDER = "#dadce0"
_BORDER_INPUT = "#e8eaed"
_TEXT = "#202124"
_HOVER = "#f1f3f4"
_NOTEBOOK_STYLE = "Settings.TNotebook"


class _HoverTip:
    """Tooltip ตอนชี้เมาส์ — ใช้แทนป้ายคำอธิบายยาว."""

    def __init__(self, widget: tk.Misc, text: str, delay_ms: int = 450) -> None:
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after: Optional[str] = None
        self._tip: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", self._leave, add="+")
        widget.bind("<ButtonPress>", self._leave, add="+")

    def _enter(self, _e: Any = None) -> None:
        self._cancel()
        self._after = self.widget.after(self.delay_ms, self._show)

    def _leave(self, _e: Any = None) -> None:
        self._cancel()
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None

    def _cancel(self) -> None:
        if self._after:
            self.widget.after_cancel(self._after)
            self._after = None

    def _show(self) -> None:
        if self._tip is not None or not self.text:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        tip.configure(bg=_BORDER)
        tk.Label(
            tip,
            text=self.text,
            justify=tk.LEFT,
            background=_WHITE,
            foreground=_TEXT,
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=_BORDER,
            font=("Segoe UI", 9),
            wraplength=420,
            padx=8,
            pady=6,
        ).pack()
        self._tip = tip


class SettingsWindow:
    def __init__(self, parent: tk.Misc, root_path: Path):
        self.parent = parent
        self.io = ConfigIO(root_path)
        self.io.ensure_seeded()
        self.win = tk.Toplevel(parent)
        self.win.withdraw()
        self.win.title("Settings — Bill Automation Kit")
        self.win.minsize(740, 640)
        self.win.transient(parent)
        self._apply_minimal_style()

        self._page_rows: List[Dict[str, Any]] = []
        self._show_tokens = tk.BooleanVar(value=False)
        self.var_user_token = tk.StringVar()
        self.var_business_page_id = tk.StringVar()
        self._browser_login_thread: threading.Thread | None = None
        self._browser_login_poll_id: str | None = None

        container = ttk.Frame(self.win)
        container.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self._container = container

        tab_labels = [
            "1. Checklist",
            "2. Google Sheet",
            "3. เพจ Facebook",
            "4. Webhook / ngrok",
            "5. ขนส่ง",
            "6. Welcome",
            "7. Browser Profile",
        ]
        nb = ttk.Notebook(container, style=_NOTEBOOK_STYLE)
        self._tab_bar = UnderlineTabBar(container, nb, tab_labels)
        self._tab_bar.pack(fill=tk.X, pady=(0, 4))
        nb.pack(fill=tk.BOTH, expand=True)

        self.tab_check = ttk.Frame(nb)
        self.tab_sheet = ttk.Frame(nb)
        self.tab_pages = ttk.Frame(nb)
        self.tab_webhook = ttk.Frame(nb)
        self.tab_carrier = ttk.Frame(nb)
        self.tab_welcome = ttk.Frame(nb)
        self.tab_browser = ttk.Frame(nb)
        for frame, label in zip(
            (
                self.tab_check,
                self.tab_sheet,
                self.tab_pages,
                self.tab_webhook,
                self.tab_carrier,
                self.tab_welcome,
                self.tab_browser,
            ),
            tab_labels,
        ):
            nb.add(frame, text="")

        self._build_checklist()
        self._build_sheet()
        self._build_pages()
        self._build_webhook()
        self._build_carrier()
        self._build_welcome()
        self._build_browser_profile()

        bottom = ttk.Frame(self.win)
        bottom.pack(fill=tk.X, padx=8, pady=(0, 8))
        ttk.Button(bottom, text="รีเฟรช Checklist", command=self.refresh_checklist).pack(
            side=tk.LEFT
        )
        ttk.Button(bottom, text="บันทึกทั้งหมด", command=self.save_all).pack(
            side=tk.RIGHT, padx=(0, 8)
        )

        self.refresh_checklist()
        self._install_defocus_on_click()
        self.win.grab_set()

    def _apply_minimal_style(self) -> None:
        self.win.configure(bg=_WHITE)
        style = ttk.Style(self.win)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=_WHITE, foreground=_TEXT, fieldbackground=_WHITE)
        style.configure("TFrame", background=_WHITE)
        style.configure("TLabel", background=_WHITE, foreground=_TEXT)
        style.configure("TCheckbutton", background=_WHITE, foreground=_TEXT)
        try:
            style.layout(
                _NOTEBOOK_STYLE,
                [("Notebook.client", {"sticky": "nswe"})],
            )
            style.layout(f"{_NOTEBOOK_STYLE}.Tab", [])
        except tk.TclError:
            pass
        style.configure(
            _NOTEBOOK_STYLE,
            background=_WHITE,
            borderwidth=0,
            relief="flat",
            lightcolor=_WHITE,
            darkcolor=_WHITE,
            bordercolor=_WHITE,
            tabmargins=(0, 0, 0, 0),
        )
        style.configure(
            "TLabelframe",
            background=_WHITE,
            foreground=_TEXT,
            bordercolor=_BORDER,
            lightcolor=_WHITE,
            darkcolor=_BORDER,
            relief="solid",
            borderwidth=1,
        )
        style.configure("TLabelframe.Label", background=_WHITE, foreground=_TEXT)
        style.configure(
            "TButton",
            background=_WHITE,
            foreground=_TEXT,
            bordercolor=_WHITE,
            lightcolor=_WHITE,
            darkcolor=_WHITE,
            relief="flat",
            borderwidth=0,
            padding=(8, 4),
            focuscolor=_WHITE,
        )
        style.map(
            "TButton",
            background=[("active", _HOVER), ("pressed", _HOVER)],
            bordercolor=[("active", _HOVER), ("pressed", _HOVER)],
            relief=[("pressed", "flat"), ("active", "flat")],
            foreground=[("disabled", "#9aa0a6")],
        )
        try:
            style.layout(
                "TButton",
                [
                    (
                        "Button.padding",
                        {
                            "sticky": "nswe",
                            "children": [("Button.label", {"sticky": "nswe"})],
                        },
                    )
                ],
            )
        except tk.TclError:
            pass
        style.configure(
            "TEntry",
            fieldbackground=_WHITE,
            background=_WHITE,
            foreground=_TEXT,
            bordercolor=_BORDER_INPUT,
            lightcolor=_BORDER_INPUT,
            darkcolor=_BORDER_INPUT,
            insertcolor=_TEXT,
            borderwidth=1,
            relief="flat",
            padding=3,
        )
        style.map(
            "TEntry",
            bordercolor=[("focus", _BORDER_INPUT), ("!focus", _BORDER_INPUT)],
            lightcolor=[("focus", _BORDER_INPUT), ("!focus", _BORDER_INPUT)],
            darkcolor=[("focus", _BORDER_INPUT), ("!focus", _BORDER_INPUT)],
        )
        style.configure(
            "TCombobox",
            fieldbackground=_WHITE,
            background=_WHITE,
            foreground=_TEXT,
            bordercolor=_BORDER_INPUT,
            lightcolor=_BORDER_INPUT,
            darkcolor=_BORDER_INPUT,
            arrowcolor=_TEXT,
            borderwidth=1,
            relief="flat",
            padding=3,
        )
        style.map(
            "TCombobox",
            bordercolor=[("focus", _BORDER_INPUT), ("!focus", _BORDER_INPUT)],
            lightcolor=[("focus", _BORDER_INPUT), ("!focus", _BORDER_INPUT)],
            darkcolor=[("focus", _BORDER_INPUT), ("!focus", _BORDER_INPUT)],
        )
        style.configure(
            "Treeview",
            background=_WHITE,
            fieldbackground=_WHITE,
            foreground=_TEXT,
            bordercolor=_BORDER_INPUT,
            lightcolor=_WHITE,
            darkcolor=_BORDER_INPUT,
            borderwidth=1,
            relief="flat",
            rowheight=22,
        )
        style.configure(
            "Treeview.Heading",
            background=_WHITE,
            foreground=_TEXT,
            bordercolor=_BORDER_INPUT,
            relief="flat",
        )
        style.map(
            "Treeview",
            background=[("selected", _HOVER)],
            foreground=[("selected", _TEXT)],
        )

    def _tip(self, widget: tk.Misc, text: str) -> None:
        _HoverTip(widget, text)

    def _section(
        self,
        parent: tk.Misc,
        title: str,
        tip: Optional[str] = None,
        **pack_kwargs: Any,
    ) -> ttk.Frame:
        outer = ttk.Frame(parent)
        if pack_kwargs:
            outer.pack(**pack_kwargs)
        head = ttk.Label(outer, text=title)
        head.pack(anchor=tk.W, pady=(0, 4))
        if tip:
            self._tip(head, tip)
        inner = ttk.Frame(outer)
        inner.pack(fill=tk.X)
        return inner

    def _style_text(self, widget: tk.Text) -> None:
        widget.configure(
            background=_WHITE,
            foreground=_TEXT,
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=_BORDER_INPUT,
            highlightcolor=_BORDER_INPUT,
            insertbackground=_TEXT,
        )

        def _keep_border(_event: object = None) -> None:
            widget.configure(
                highlightbackground=_BORDER_INPUT,
                highlightcolor=_BORDER_INPUT,
            )

        widget.bind("<FocusIn>", _keep_border, add="+")
        widget.bind("<FocusOut>", _keep_border, add="+")

    def _thin_entry(
        self,
        parent: tk.Misc,
        *,
        textvariable: Optional[tk.StringVar] = None,
        width: int = 20,
        show: Optional[str] = None,
    ) -> ThinEntry:
        return create_thin_entry(
            parent, textvariable=textvariable, width=width, show=show
        )

    def _is_text_input(self, widget: tk.Misc | None) -> bool:
        if widget is None:
            return False
        w: tk.Misc | None = widget
        while w is not None:
            if isinstance(w, (tk.Entry, tk.Text, tk.Listbox, ThinEntry)):
                return True
            try:
                w = w.master
            except (AttributeError, tk.TclError):
                break
        return False

    def _on_background_click(self, event: tk.Event) -> None:
        if self._is_text_input(event.widget):
            return
        try:
            focus = self.win.focus_get()
        except (KeyError, tk.TclError):
            focus = None
        if focus and self._is_text_input(focus):
            self.win.focus_set()

    def _install_defocus_on_click(self) -> None:
        targets = [
            self.win,
            self._container,
            self.tab_check,
            self.tab_sheet,
            self.tab_pages,
            self.tab_webhook,
            self.tab_carrier,
            self.tab_welcome,
            self.tab_browser,
        ]
        if hasattr(self, "_welcome_canvas"):
            targets.append(self._welcome_canvas)
        for widget in targets:
            widget.bind("<Button-1>", self._on_background_click, add="+")

    def _style_embedded_text(self, widget: tk.Text) -> None:
        widget.configure(
            background=_WHITE,
            foreground=_TEXT,
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
            insertbackground=_TEXT,
        )
        bind_unicode_editing(
            widget,
            after_change=lambda w=widget: self._autosize_welcome_text(w),
        )

    # ----- Checklist -----

    def _build_checklist(self) -> None:
        frm = self.tab_check
        head = ttk.Label(frm, text="สถานะการตั้งค่า")
        head.pack(anchor=tk.W, padx=10, pady=8)
        self._tip(
            head,
            "รายการสีแดง/ขาดต้องแก้ก่อนใช้งานส่งบิล (Token)",
        )
        self.check_box = tk.Text(frm, height=18, wrap=tk.WORD, font=("Consolas", 10))
        self._style_text(self.check_box)
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
        self._thin_entry(grid, textvariable=self.var_sheet_id, width=56).grid(
            row=0, column=1, sticky=tk.EW, pady=4, padx=(8, 0)
        )

        ttk.Label(grid, text="ชื่อชีต (คั่นด้วย ,):").grid(
            row=1, column=0, sticky=tk.W, pady=4
        )
        names = sheet.get("sheet_names") or []
        self.var_sheet_names = tk.StringVar(value=", ".join(names))
        self._thin_entry(grid, textvariable=self.var_sheet_names, width=56).grid(
            row=1, column=1, sticky=tk.EW, pady=4, padx=(8, 0)
        )
        grid.columnconfigure(1, weight=1)

        cred_frm = self._section(
            frm,
            "Google Service Account JSON",
            "บันทึกไปที่ no_api_send_bill และ no_api_send_bill_manual (sync ค่าเดียวกัน)",
            fill=tk.X,
            padx=10,
            pady=8,
        )
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

        import_frm = self._section(
            frm,
            "นำเข้าจาก Long-Lived User Token",
            "วาง Long-Lived User Token แล้วกดดึงรายการเพจ — "
            "ระบบจะดึงชื่อเพจ / Page ID / Page Token ให้เลือกนำเข้า "
            "(ไม่เก็บ User Token ลงไฟล์)",
            fill=tk.X,
            padx=10,
            pady=(8, 4),
        )
        row = ttk.Frame(import_frm)
        row.pack(fill=tk.X, padx=8, pady=8)
        ttk.Label(row, text="User Token").pack(side=tk.LEFT)
        self._thin_entry(row, textvariable=self.var_user_token, width=52, show="*").pack(
            side=tk.LEFT, padx=8, fill=tk.X, expand=True
        )
        ttk.Button(
            row, text="ดึงรายการเพจ…", command=self._fetch_pages_from_user_token
        ).pack(side=tk.LEFT)

        biz = self._section(
            frm,
            "เพจ Business (ดึงด้วย Page ID)",
            "ถ้าเพจไม่โผล่จาก「ดึงรายการเพจ」 — ใส่ Page ID แล้วกดดึงเพจนี้ "
            "(ใช้ User Token ช่องด้านบน)",
            fill=tk.X,
            padx=10,
            pady=(0, 4),
        )
        brow = ttk.Frame(biz)
        brow.pack(fill=tk.X, padx=8, pady=8)
        ttk.Label(brow, text="Page ID").pack(side=tk.LEFT)
        self._thin_entry(brow, textvariable=self.var_business_page_id, width=28).pack(
            side=tk.LEFT, padx=8
        )
        ttk.Button(
            brow, text="ดึงเพจนี้…", command=self._fetch_page_by_page_id
        ).pack(side=tk.LEFT)

        top = ttk.Frame(frm)
        top.pack(fill=tk.X, padx=10, pady=8)
        ttk.Label(top, text="รายการเพจที่บันทึก (page_token.json)").pack(side=tk.LEFT)
        ttk.Checkbutton(
            top,
            text="แสดง token",
            variable=self._show_tokens,
            command=self._reload_page_tree_display,
        ).pack(side=tk.RIGHT)

        cols = ("name", "page_id", "token", "enabled")
        self.pages_tree = ttk.Treeview(
            frm, columns=cols, show="headings", height=12, selectmode="browse"
        )
        self.pages_tree.heading("name", text="page_name")
        self.pages_tree.heading("page_id", text="page_id")
        self.pages_tree.heading("token", text="access_token")
        self.pages_tree.heading("enabled", text="enabled")
        self.pages_tree.column("name", width=160)
        self.pages_tree.column("page_id", width=140)
        self.pages_tree.column("token", width=260)
        self.pages_tree.column("enabled", width=60)
        self.pages_tree.pack(fill=tk.BOTH, expand=True, padx=10)

        bf = ttk.Frame(frm)
        bf.pack(fill=tk.X, padx=10, pady=(0, 8))
        ttk.Button(bf, text="ลบแถวที่เลือก", command=self._delete_page_row).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(
            bf, text="สลับ enabled", command=self._toggle_selected_enabled
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(bf, text="บันทึกเพจ", command=self.save_pages).pack(side=tk.RIGHT)

        self._page_rows = self.io.load_page_tokens()
        self._strip_placeholder_pages()
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

    def _toggle_selected_enabled(self) -> None:
        sel = self.pages_tree.selection()
        if not sel:
            return
        try:
            idx = int(sel[0])
        except ValueError:
            return
        if 0 <= idx < len(self._page_rows):
            cur = self._page_rows[idx].get("enabled", True) is not False
            self._page_rows[idx]["enabled"] = not cur
            self._reload_page_tree_display()
            self.pages_tree.selection_set(str(idx))

    def _strip_placeholder_pages(self) -> None:
        """Remove template placeholder rows from the in-memory page list."""
        cleaned: List[Dict[str, Any]] = []
        for p in self._page_rows:
            pid = str(p.get("page_id") or "").strip()
            name = str(p.get("page_name") or "").strip()
            if pid in ("", "YOUR_FACEBOOK_PAGE_ID") or pid.upper().startswith("YOUR_"):
                continue
            if name in ("", "YourPageName"):
                continue
            cleaned.append(p)
        self._page_rows = cleaned

    def _merge_imported_pages(self, pages: List[Dict[str, str]]) -> int:
        """Upsert by page_id. Returns number of rows added or updated."""
        self._strip_placeholder_pages()
        by_id = {
            str(p.get("page_id") or ""): i
            for i, p in enumerate(self._page_rows)
            if p.get("page_id")
        }
        changed = 0
        for src in pages:
            pid = str(src.get("page_id") or "").strip()
            name = str(src.get("page_name") or "").strip()
            token = str(src.get("access_token") or "").strip()
            if not pid or not token:
                continue
            if pid in ("", "YOUR_FACEBOOK_PAGE_ID") or pid.upper().startswith("YOUR_"):
                continue
            entry = {
                "page_name": name,
                "page_id": pid,
                "access_token": token,
                "enabled": True,
                "subscribed_fields": list(_DEFAULT_SUBSCRIBED),
            }
            if pid in by_id:
                idx = by_id[pid]
                prev = self._page_rows[idx]
                entry["enabled"] = prev.get("enabled", True) is not False
                entry["subscribed_fields"] = prev.get(
                    "subscribed_fields", list(_DEFAULT_SUBSCRIBED)
                )
                self._page_rows[idx] = entry
            else:
                by_id[pid] = len(self._page_rows)
                self._page_rows.append(entry)
            changed += 1
        self._reload_page_tree_display()
        return changed

    def _fetch_page_by_page_id(self) -> None:
        token = self.var_user_token.get().strip()
        page_id = self.var_business_page_id.get().strip()
        if not token:
            messagebox.showwarning(
                "ข้อมูลไม่ครบ",
                "วาง Long-Lived User Token ในช่องด้านบนก่อน",
                parent=self.win,
            )
            return
        if not page_id:
            messagebox.showwarning(
                "ข้อมูลไม่ครบ",
                "ใส่ Page ID ของเพจ Business",
                parent=self.win,
            )
            return
        self.win.config(cursor="watch")
        self.win.update_idletasks()
        try:
            page = fetch_page_by_id(token, page_id)
        except GraphPageError as e:
            messagebox.showerror("ดึงเพจไม่สำเร็จ", str(e), parent=self.win)
            return
        except Exception as e:
            messagebox.showerror("ดึงเพจไม่สำเร็จ", str(e), parent=self.win)
            return
        finally:
            self.win.config(cursor="")

        n = self._merge_imported_pages([page])
        pname = page.get("page_name") or page_id
        messagebox.showinfo(
            "นำเข้าแล้ว",
            f"เพิ่ม/อัปเดตเพจ «{pname}» ({n} แถว) — กด「บันทึกเพจ」เพื่อเขียนลงไฟล์",
            parent=self.win,
        )

    def _fetch_pages_from_user_token(self) -> None:
        token = self.var_user_token.get().strip()
        if not token:
            messagebox.showwarning(
                "ข้อมูลไม่ครบ",
                "วาง Long-Lived User Token ก่อน",
                parent=self.win,
            )
            return
        self.win.config(cursor="watch")
        self.win.update_idletasks()
        try:
            pages = list_pages_from_user_token(token)
        except GraphPageError as e:
            messagebox.showerror("ดึงเพจไม่สำเร็จ", str(e), parent=self.win)
            return
        except Exception as e:
            messagebox.showerror("ดึงเพจไม่สำเร็จ", str(e), parent=self.win)
            return
        finally:
            self.win.config(cursor="")

        if not pages:
            messagebox.showwarning(
                "ไม่พบเพจ",
                "Token นี้ไม่มีเพจที่อ่านได้",
                parent=self.win,
            )
            return
        selected = self._show_page_pick_dialog(pages)
        if not selected:
            return
        n = self._merge_imported_pages(selected)
        messagebox.showinfo(
            "นำเข้าแล้ว",
            f"เพิ่ม/อัปเดต {n} เพจในตาราง — กด「บันทึกเพจ」เพื่อเขียนลงไฟล์",
            parent=self.win,
        )

    def _show_page_pick_dialog(
        self, pages: List[Dict[str, str]]
    ) -> Optional[List[Dict[str, str]]]:
        existing = {
            str(p.get("page_id") or "")
            for p in self._page_rows
            if p.get("page_id")
        }
        dlg = tk.Toplevel(self.win)
        dlg.title("เลือกเพจที่จะนำเข้า")
        dlg.geometry("640x420")
        dlg.configure(bg=_WHITE)
        dlg.transient(self.win)
        dlg.grab_set()

        head = ttk.Label(dlg, text="เลือกเพจที่จะนำเข้า")
        head.pack(anchor=tk.W, padx=10, pady=8)
        self._tip(head, "Page Token จะถูกเก็บ — ไม่เก็บ User Token")

        cols = ("sel", "name", "page_id", "token")
        tree = ttk.Treeview(
            dlg, columns=cols, show="headings", height=14, selectmode="none"
        )
        tree.heading("sel", text="เลือก")
        tree.heading("name", text="ชื่อเพจ")
        tree.heading("page_id", text="Page ID")
        tree.heading("token", text="Page Token")
        tree.column("sel", width=50, anchor=tk.CENTER)
        tree.column("name", width=180)
        tree.column("page_id", width=140)
        tree.column("token", width=220)
        tree.pack(fill=tk.BOTH, expand=True, padx=10)

        checked: Dict[str, bool] = {}
        for i, p in enumerate(pages):
            iid = str(i)
            pid = p.get("page_id") or ""
            # default: select pages not already in the table
            checked[iid] = pid not in existing
            mark = "☑" if checked[iid] else "☐"
            tree.insert(
                "",
                tk.END,
                iid=iid,
                values=(
                    mark,
                    p.get("page_name") or "",
                    pid,
                    self._mask_token(str(p.get("access_token") or "")),
                ),
            )

        def toggle(_event=None) -> None:
            sel = tree.selection()
            if not sel:
                return
            iid = sel[0]
            checked[iid] = not checked.get(iid, False)
            vals = list(tree.item(iid, "values"))
            vals[0] = "☑" if checked[iid] else "☐"
            tree.item(iid, values=vals)

        def select_all(state: bool) -> None:
            for iid in tree.get_children():
                checked[iid] = state
                vals = list(tree.item(iid, "values"))
                vals[0] = "☑" if state else "☐"
                tree.item(iid, values=vals)

        tree.bind("<ButtonRelease-1>", toggle)
        tree.bind("<space>", toggle)

        result: Dict[str, Any] = {"pages": None}

        def do_import() -> None:
            chosen = [
                pages[int(iid)]
                for iid in tree.get_children()
                if checked.get(iid) and iid.isdigit() and int(iid) < len(pages)
            ]
            if not chosen:
                messagebox.showwarning(
                    "ยังไม่เลือก", "เลือกอย่างน้อย 1 เพจ", parent=dlg
                )
                return
            result["pages"] = chosen
            dlg.destroy()

        btn = ttk.Frame(dlg)
        btn.pack(fill=tk.X, padx=10, pady=8)
        ttk.Button(btn, text="เลือกทั้งหมด", command=lambda: select_all(True)).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(btn, text="ไม่เลือกเลย", command=lambda: select_all(False)).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(btn, text="ยกเลิก", command=dlg.destroy).pack(side=tk.RIGHT)
        ttk.Button(btn, text="นำเข้าที่เลือก", command=do_import).pack(
            side=tk.RIGHT, padx=(0, 8)
        )

        self.win.wait_window(dlg)
        return result["pages"]

    def save_pages(self) -> bool:
        try:
            self._strip_placeholder_pages()
            self.io.save_pages(self._page_rows)
            messagebox.showinfo(
                "บันทึก",
                "บันทึก page_token.json และ page_name_to_id แล้ว",
                parent=self.win,
            )
            self.refresh_checklist()
            if hasattr(self, "_page_picker"):
                self._refresh_welcome_page_list()
            return True
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e), parent=self.win)
            return False

    # ----- Webhook -----

    def _build_webhook(self) -> None:
        frm = self.tab_webhook
        wh = self.io.load_webhook_fields()
        box = self._section(
            frm,
            "Webhook / ngrok",
            "ค่าจะถูก merge ลง .env และ user_settings.json (ไม่ลบ key อื่นใน .env)",
            fill=tk.X,
            padx=10,
            pady=10,
        )
        grid = ttk.Frame(box)
        grid.pack(fill=tk.X, padx=8, pady=8)

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
            self._thin_entry(grid, textvariable=var, width=50).grid(
                row=i, column=1, sticky=tk.EW, padx=8, pady=4
            )
        grid.columnconfigure(1, weight=1)

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

    # ----- Carrier -----

    def _build_carrier(self) -> None:
        frm = self.tab_carrier
        fields = self.io.load_carrier_fields()
        head = ttk.Label(frm, text="บัญชีล็อกอินเว็บขนส่ง")
        head.pack(anchor=tk.W, padx=10, pady=8)
        self._tip(
            head,
            "สำหรับถ่ายบิล — บันทึกลง .env (ไม่ขึ้น git) "
            "ไม่บังคับถ้าใช้แค่ส่งบิล Token/Playwright",
        )

        self.var_anousith_user = tk.StringVar(value=fields.get("ANOUSITH_USER") or "")
        self.var_anousith_pass = tk.StringVar(value=fields.get("ANOUSITH_PASSWORD") or "")
        self.var_hal_user = tk.StringVar(value=fields.get("HAL_USER") or "")
        self.var_hal_pass = tk.StringVar(value=fields.get("HAL_PASSWORD") or "")

        an = self._section(frm, "Anousith", fill=tk.X, padx=10, pady=6)
        ag = ttk.Frame(an)
        ag.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(ag, text="User").grid(row=0, column=0, sticky=tk.W, pady=4)
        self._thin_entry(ag, textvariable=self.var_anousith_user, width=40).grid(
            row=0, column=1, sticky=tk.EW, padx=8, pady=4
        )
        ttk.Label(ag, text="Password").grid(row=1, column=0, sticky=tk.W, pady=4)
        self._thin_entry(ag, textvariable=self.var_anousith_pass, width=40, show="*").grid(
            row=1, column=1, sticky=tk.EW, padx=8, pady=4
        )
        ag.columnconfigure(1, weight=1)

        hal = self._section(frm, "HAL Express", fill=tk.X, padx=10, pady=6)
        hg = ttk.Frame(hal)
        hg.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(hg, text="User").grid(row=0, column=0, sticky=tk.W, pady=4)
        self._thin_entry(hg, textvariable=self.var_hal_user, width=40).grid(
            row=0, column=1, sticky=tk.EW, padx=8, pady=4
        )
        ttk.Label(hg, text="Password").grid(row=1, column=0, sticky=tk.W, pady=4)
        self._thin_entry(hg, textvariable=self.var_hal_pass, width=40, show="*").grid(
            row=1, column=1, sticky=tk.EW, padx=8, pady=4
        )
        hg.columnconfigure(1, weight=1)

        ttk.Button(frm, text="บันทึกขนส่ง", command=self.save_carrier).pack(
            anchor=tk.E, padx=10, pady=12
        )

    def save_carrier(self) -> bool:
        try:
            self.io.save_carrier_fields(
                self.var_anousith_user.get(),
                self.var_anousith_pass.get(),
                self.var_hal_user.get(),
                self.var_hal_pass.get(),
            )
            messagebox.showinfo("บันทึก", "บันทึกบัญชีขนส่งลง .env แล้ว", parent=self.win)
            self.refresh_checklist()
            return True
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e), parent=self.win)
            return False

    def save_carrier_silent(self) -> bool:
        try:
            self.io.save_carrier_fields(
                self.var_anousith_user.get(),
                self.var_anousith_pass.get(),
                self.var_hal_user.get(),
                self.var_hal_pass.get(),
            )
            return True
        except Exception as e:
            messagebox.showerror("ขนส่ง", str(e), parent=self.win)
            return False

    # ----- Welcome -----

    def _autosize_welcome_text(
        self, widget: tk.Text, min_lines: int = 2, max_lines: int = 30
    ) -> None:
        widget.update_idletasks()
        try:
            count = widget.count("1.0", "end-1c", "displaylines")
            if not count:
                lines = min_lines
            else:
                lines = int(count[0]) if isinstance(count, tuple) else int(count)
                if lines < 1:
                    lines = min_lines
        except (tk.TclError, ValueError, TypeError):
            lines = min_lines
        widget.configure(height=max(min_lines, min(max_lines, lines)))

    def _reflow_welcome_texts(self) -> None:
        for widget in getattr(self, "_welcome_texts", {}).values():
            self._autosize_welcome_text(widget)

    def _schedule_welcome_reflow(self) -> None:
        after_id = getattr(self, "_welcome_reflow_after", None)
        if after_id:
            self.win.after_cancel(after_id)
        self._welcome_reflow_after = self.win.after_idle(self._reflow_welcome_texts)

    def _make_welcome_text(self, parent: tk.Misc, *, bordered: bool) -> tk.Text:
        txt = tk.Text(
            parent,
            height=2,
            width=1,
            wrap=tk.WORD,
            font=("Segoe UI", 9),
        )
        if bordered:
            self._style_embedded_text(txt)
        else:
            self._style_text(txt)
            bind_unicode_editing(
                txt,
                after_change=lambda w=txt: self._autosize_welcome_text(w),
            )
        self._bind_welcome_text_autosize(txt)
        return txt

    def _bind_welcome_text_autosize(self, widget: tk.Text) -> None:
        def _on_modified(_event=None) -> None:
            try:
                if widget.edit_modified():
                    self._autosize_welcome_text(widget)
                    widget.edit_modified(False)
            except tk.TclError:
                pass

        widget.bind("<<Modified>>", _on_modified)

    def _welcome_page_name(self) -> str:
        return (self.var_welcome_page.get() or "").strip()

    def _build_welcome(self) -> None:
        frm = self.tab_welcome
        cfg = self.io.load_page_reply_config()
        g = cfg.get("globals") or {}

        self.var_promo_off = tk.BooleanVar(value=bool(g.get("promo_auto_send_disabled")))
        self.var_msg_off = tk.BooleanVar(value=bool(g.get("messenger_auto_replies_disabled")))
        self.var_generic_off = tk.BooleanVar(value=bool(g.get("generic_reply_disabled")))

        top = self._section(
            frm,
            "ทั้งระบบ",
            "ตั้งค่า auto-reply ทั้งระบบ — ข้อความและสื่อด้านล่างเป็นรายเพจ",
            fill=tk.X,
            padx=10,
            pady=(8, 4),
        )
        ttk.Checkbutton(
            top,
            text="ปิด auto-reply Messenger (welcome / ราคา / คีย์เวิร์ด)",
            variable=self.var_msg_off,
        ).pack(anchor=tk.W, padx=8, pady=2)
        ttk.Checkbutton(
            top,
            text="ปิดข้อความ generic เมื่อไม่ตรงคีย์เวิร์ด",
            variable=self.var_generic_off,
        ).pack(anchor=tk.W, padx=8, pady=2)
        ttk.Checkbutton(
            top,
            text="ปิดส่งโปรโมอัตโนมัติ (send_promo_within_24h)",
            variable=self.var_promo_off,
        ).pack(anchor=tk.W, padx=8, pady=(2, 6))

        pick = ttk.Frame(frm)
        pick.pack(fill=tk.X, padx=10, pady=6)
        ttk.Label(pick, text="เพจ").pack(side=tk.LEFT)
        self.var_welcome_page = tk.StringVar()
        self._page_picker = SearchablePagePicker(
            pick,
            self.var_welcome_page,
            on_select=self._load_welcome_page,
            width=32,
        )
        self._page_picker.pack(side=tk.LEFT, padx=8)
        ttk.Button(pick, text="รีเฟรชรายชื่อเพจ", command=self._refresh_welcome_page_list).pack(
            side=tk.LEFT
        )

        self.var_welcome_hint = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.var_welcome_hint, wraplength=720).pack(
            anchor=tk.W, padx=10
        )

        scroll_outer = ttk.Frame(frm)
        scroll_outer.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        self._welcome_canvas = tk.Canvas(scroll_outer, highlightthickness=0, bg="#ffffff")
        welcome_vsb = create_vertical_scrollbar(
            scroll_outer,
            command=self._welcome_canvas.yview,
        )
        self._welcome_canvas.configure(yscrollcommand=welcome_vsb.set)
        self._welcome_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        welcome_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._welcome_body = ttk.Frame(self._welcome_canvas)
        self._welcome_canvas_window = self._welcome_canvas.create_window(
            (0, 0), window=self._welcome_body, anchor=tk.NW
        )
        self._welcome_body.bind(
            "<Configure>",
            lambda _e: self._welcome_canvas.configure(
                scrollregion=self._welcome_canvas.bbox("all")
            ),
        )
        self._welcome_canvas.bind(
            "<Configure>",
            self._on_welcome_canvas_configure,
        )
        self._welcome_canvas.bind(
            "<Enter>",
            lambda _e: self._welcome_canvas.bind_all(
                "<MouseWheel>", self._on_welcome_mousewheel
            ),
        )
        self._welcome_canvas.bind(
            "<Leave>",
            lambda _e: self._welcome_canvas.unbind_all("<MouseWheel>"),
        )

        labels = {
            "welcome_text": "welcome_text (ต้อนรับ — ว่างได้ถ้าจะส่งแค่รูป)",
            "price_reply": "price_reply (ตอบราคา)",
            "promo_text": "promo_text (โปรโม)",
            "cod_reply": "cod_reply (เก็บปลายทาง)",
            "order_reply": "order_reply (สั่งซื้อ)",
        }
        media_after = {
            "welcome_text": "welcome",
            "price_reply": "price",
            "promo_text": "promo",
        }
        self._welcome_texts: Dict[str, tk.Text] = {}
        self._welcome_media_panels: Dict[str, MediaThumbnailPanel] = {}
        self._welcome_reflow_after: Optional[str] = None
        row = 0
        for key in PAGE_REPLY_TEXT_KEYS:
            ttk.Label(self._welcome_body, text=labels.get(key, key)).grid(
                row=row, column=0, sticky=tk.W, pady=(8, 0)
            )
            row += 1
            if key in media_after:
                kind = media_after[key]
                box = tk.Frame(
                    self._welcome_body,
                    bg=_WHITE,
                    highlightthickness=1,
                    highlightbackground=_BORDER_INPUT,
                    highlightcolor=_BORDER_INPUT,
                )
                box.grid(row=row, column=0, sticky=tk.EW, pady=(0, 4))
                box.columnconfigure(0, weight=1)
                txt = self._make_welcome_text(box, bordered=True)
                txt.pack(fill=tk.X, padx=4, pady=(4, 2))
                self._welcome_texts[key] = txt
                panel = MediaThumbnailPanel(
                    box,
                    kind,
                    self.io,
                    self._welcome_page_name,
                )
                panel.pack(fill=tk.X, padx=4, pady=(0, 4))
                self._welcome_media_panels[kind] = panel
            else:
                txt = self._make_welcome_text(self._welcome_body, bordered=False)
                txt.grid(row=row, column=0, sticky=tk.EW, pady=(0, 4))
                self._welcome_texts[key] = txt
            row += 1
        self._welcome_body.columnconfigure(0, weight=1)

        self._keyword_reply_rows: List[Dict[str, Any]] = []
        ttk.Label(
            self._welcome_body,
            text="ตอบตามคีย์เวิร์ด (กำหนดเอง)",
        ).grid(row=row, column=0, sticky=tk.W, pady=(16, 0))
        row += 1
        ttk.Label(
            self._welcome_body,
            text="ตั้งคีย์เวิร์ดหลายแบบต่อ 1 คำตอบ (คั่นด้วย , หรือขึ้นบรรทัดใหม่) — หลังบันทึกต้องรีสตาร์ท webhook",
            wraplength=720,
        ).grid(row=row, column=0, sticky=tk.W, pady=(0, 4))
        row += 1
        self._keyword_replies_rows_frame = ttk.Frame(self._welcome_body)
        self._keyword_replies_rows_frame.grid(row=row, column=0, sticky=tk.EW)
        row += 1
        kw_btn_row = ttk.Frame(self._welcome_body)
        kw_btn_row.grid(row=row, column=0, sticky=tk.W, pady=(4, 8))
        ttk.Button(
            kw_btn_row,
            text="+ เพิ่มคีย์เวิร์ด",
            command=lambda: self._add_keyword_reply_row(),
        ).pack(side=tk.LEFT)

        bf = ttk.Frame(frm)
        bf.pack(fill=tk.X, padx=10, pady=(0, 8))
        ttk.Button(bf, text="บันทึก Welcome", command=self.save_welcome).pack(side=tk.RIGHT)

        self._welcome_loaded_page = ""
        self._refresh_welcome_page_list()
        self._schedule_welcome_reflow()

    def _clear_keyword_reply_rows(self) -> None:
        for row in getattr(self, "_keyword_reply_rows", []):
            frame = row.get("frame")
            if frame is not None:
                frame.destroy()
        self._keyword_reply_rows = []
        self._schedule_welcome_reflow()

    def _add_keyword_reply_row(
        self,
        keywords: str = "",
        reply: str = "",
        media: Optional[List[str]] = None,
    ) -> None:
        card = tk.Frame(
            self._keyword_replies_rows_frame,
            bg=_WHITE,
            highlightthickness=1,
            highlightbackground=_BORDER_INPUT,
            highlightcolor=_BORDER_INPUT,
        )
        card.pack(fill=tk.X, pady=(0, 8))
        card.columnconfigure(0, weight=1)

        header = ttk.Frame(card)
        header.pack(fill=tk.X, padx=4, pady=(4, 0))
        ttk.Label(header, text="ชุดคีย์เวิร์ด").pack(side=tk.LEFT)
        ttk.Button(
            header,
            text="ลบ",
            width=4,
            command=lambda c=card: self._remove_keyword_reply_row(c),
        ).pack(side=tk.RIGHT)

        ttk.Label(card, text="คีย์เวิร์ด (คั่นด้วย , หรือขึ้นบรรทัดใหม่)").pack(
            anchor=tk.W, padx=4, pady=(4, 0)
        )
        kw_txt = self._make_welcome_text(card, bordered=False)
        kw_txt.pack(fill=tk.X, padx=4, pady=(0, 2))
        if keywords:
            kw_txt.insert("1.0", keywords)
            self._autosize_welcome_text(kw_txt)

        ttk.Label(card, text="ข้อความตอบกลับ").pack(anchor=tk.W, padx=4, pady=(4, 0))
        reply_box = tk.Frame(
            card,
            bg=_WHITE,
            highlightthickness=1,
            highlightbackground=_BORDER_INPUT,
            highlightcolor=_BORDER_INPUT,
        )
        reply_box.pack(fill=tk.X, padx=4, pady=(0, 4))
        reply_box.columnconfigure(0, weight=1)
        reply_txt = self._make_welcome_text(reply_box, bordered=True)
        reply_txt.pack(fill=tk.X, padx=4, pady=(4, 2))
        if reply:
            reply_txt.insert("1.0", reply)
            self._autosize_welcome_text(reply_txt)

        media_names: List[str] = list(media or [])
        media_panel = KeywordMediaPanel(
            reply_box,
            self.io,
            self._welcome_page_name,
            media_names,
        )
        media_panel.pack(fill=tk.X, padx=4, pady=(0, 4))
        media_panel.refresh()

        row_data = {
            "frame": card,
            "keywords": kw_txt,
            "reply": reply_txt,
            "media_names": media_names,
            "media_panel": media_panel,
        }
        self._keyword_reply_rows.append(row_data)
        self._schedule_welcome_reflow()

    def _remove_keyword_reply_row(self, card: tk.Frame) -> None:
        self._keyword_reply_rows = [
            r for r in self._keyword_reply_rows if r.get("frame") is not card
        ]
        card.destroy()
        self._schedule_welcome_reflow()

    def _keyword_replies_from_ui(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for row in getattr(self, "_keyword_reply_rows", []):
            kw_widget = row.get("keywords")
            reply_widget = row.get("reply")
            if kw_widget is None or reply_widget is None:
                continue
            keywords = parse_keyword_list(kw_widget.get("1.0", tk.END))
            reply = reply_widget.get("1.0", tk.END).rstrip("\n").strip()
            media_names = list(row.get("media_names") or [])
            if keywords and (reply or media_names):
                entry: Dict[str, Any] = {"keywords": keywords, "reply": reply}
                if media_names:
                    entry["media"] = media_names
                rows.append(entry)
        return rows

    def _load_keyword_replies_into_ui(self, data: Dict[str, Any]) -> None:
        self._clear_keyword_reply_rows()
        rules = normalize_keyword_replies(data.get("keyword_replies"))
        for rule in rules:
            self._add_keyword_reply_row(
                format_keyword_list(rule.get("keywords") or []),
                str(rule.get("reply") or ""),
                list(rule.get("media") or []),
            )

    def _reload_keyword_media_panels(self) -> None:
        for row in getattr(self, "_keyword_reply_rows", []):
            panel = row.get("media_panel")
            if panel is not None:
                panel.refresh()

    def _on_welcome_canvas_configure(self, event: tk.Event) -> None:
        self._welcome_canvas.itemconfigure(
            self._welcome_canvas_window, width=event.width
        )
        self._schedule_welcome_reflow()

    def _on_welcome_mousewheel(self, event) -> None:
        if event.delta:
            self._welcome_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _welcome_globals(self) -> Dict[str, Any]:
        return {
            "promo_auto_send_disabled": self.var_promo_off.get(),
            "messenger_auto_replies_disabled": self.var_msg_off.get(),
            "generic_reply_disabled": self.var_generic_off.get(),
        }

    def _welcome_fields_from_ui(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for key, widget in self._welcome_texts.items():
            out[key] = widget.get("1.0", tk.END).rstrip("\n")
        return out

    def _real_page_names_for_welcome(self) -> List[str]:
        return self.io.real_page_names(self._page_rows)

    def _refresh_welcome_page_list(self) -> None:
        names = self._real_page_names_for_welcome()
        self._page_picker.set_values(names)
        if names:
            cur = self.var_welcome_page.get()
            if cur not in names:
                self.var_welcome_page.set(names[0])
            self._load_welcome_page()
        else:
            self.var_welcome_page.set("")
            self.var_welcome_hint.set(
                "ยังไม่มีเพจจริงในตาราง — ไปแท็บเพจ Facebook นำเข้าแล้วบันทึกเพจก่อน"
            )
            for widget in self._welcome_texts.values():
                widget.delete("1.0", tk.END)
                self._autosize_welcome_text(widget)
            self._clear_keyword_reply_rows()
            self._welcome_loaded_page = ""
            self._reload_media_panels()

    def _load_welcome_page(self) -> None:
        name = self.var_welcome_page.get().strip()
        cfg = self.io.load_page_reply_config()
        pages = cfg.get("pages") or {}
        data = pages.get(name) if isinstance(pages.get(name), dict) else {}
        for key, widget in self._welcome_texts.items():
            widget.delete("1.0", tk.END)
            widget.insert("1.0", str(data.get(key) or ""))
            self._autosize_welcome_text(widget)
        self._load_keyword_replies_into_ui(data)
        self.var_welcome_hint.set("" if name else "")
        self._welcome_loaded_page = name
        self._reload_media_panels()

    def _reload_media_panels(self) -> None:
        for panel in getattr(self, "_welcome_media_panels", {}).values():
            panel.refresh()
        self._reload_keyword_media_panels()

    def _gc_keyword_media_for_page(self, page_name: str, rules: List[Dict[str, Any]]) -> None:
        try:
            refs = collect_keyword_media_refs(rules)
            self.io.gc_unused_keyword_media(page_name, refs)
        except ValueError:
            pass

    def save_welcome(self) -> bool:
        name = self.var_welcome_page.get().strip()
        if not name:
            messagebox.showwarning(
                "ยังไม่มีเพจ",
                "นำเข้าเพจในแท็บเพจ Facebook ก่อน",
                parent=self.win,
            )
            return False
        try:
            keyword_rules = self._keyword_replies_from_ui()
            self.io.save_page_reply_config(
                self._welcome_globals(),
                name,
                self._welcome_fields_from_ui(),
                keyword_replies=keyword_rules,
            )
            self._gc_keyword_media_for_page(name, keyword_rules)
            self._reload_keyword_media_panels()
            self._welcome_loaded_page = name
            messagebox.showinfo(
                "บันทึก",
                f"บันทึก Welcome ของเพจ «{name}» ลง page_reply_config.json แล้ว\n\n"
                "รีสตาร์ท webhook server เพื่อให้คีย์เวิร์ดใหม่มีผล",
                parent=self.win,
            )
            return True
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e), parent=self.win)
            return False

    def save_welcome_silent(self) -> bool:
        name = self.var_welcome_page.get().strip()
        try:
            keyword_rules = self._keyword_replies_from_ui() if name else []
            self.io.save_page_reply_config(
                self._welcome_globals(),
                name or None,
                self._welcome_fields_from_ui() if name else None,
                keyword_replies=keyword_rules if name else None,
            )
            if name:
                self._gc_keyword_media_for_page(name, keyword_rules)
                self._reload_keyword_media_panels()
            return True
        except Exception as e:
            messagebox.showerror("Welcome", str(e), parent=self.win)
            return False

    # ----- all -----

    def save_all(self) -> None:
        ok = True
        ok = self.save_sheet_silent() and ok
        ok = self.save_pages_silent() and ok
        ok = self.save_webhook_silent() and ok
        ok = self.save_carrier_silent() and ok
        ok = self.save_welcome_silent() and ok
        ok = self.save_browser_profile_silent() and ok
        self.refresh_checklist()
        self._refresh_welcome_page_list()
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
            self._strip_placeholder_pages()
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

    # ----- Browser Profile -----

    def _build_browser_profile(self) -> None:
        frm = self.tab_browser
        us = self.io.load_user_settings()
        self.var_fb_profile = tk.StringVar(
            value=us.get("facebook_user_data_dir") or "no_api_send_bill/browser_profile"
        )
        self.var_hal_profile = tk.StringVar(
            value=us.get("hal_user_data_dir") or "hal_browser_profile"
        )

        box = self._section(
            frm,
            "Path",
            "โฟลเดอร์เก็บ session เบราว์เซอร์ (cookies) สำหรับส่งบิล Facebook, WhatsApp Web "
            "(ใช้ Facebook profile เดียวกัน — scan QR) และถ่ายบิล HAL — "
            "กดปุ่มเปิดเบราว์เซอร์ ล็อกอินให้เสร็จ แล้วปิดหน้าต่าง — session อยู่ในโฟลเดอร์นี้ "
            "(อย่า commit โฟลเดอร์ profile)",
            fill=tk.X,
            padx=10,
            pady=6,
        )
        g = ttk.Frame(box)
        g.pack(fill=tk.X, padx=8, pady=8)

        ttk.Label(g, text="Facebook profile").grid(row=0, column=0, sticky=tk.W, pady=4)
        self._thin_entry(g, textvariable=self.var_fb_profile, width=48).grid(
            row=0, column=1, sticky=tk.EW, padx=8, pady=4
        )
        ttk.Button(g, text="Browse…", command=self._browse_fb_profile).grid(
            row=0, column=2, padx=4, pady=4
        )

        ttk.Label(g, text="HAL profile").grid(row=1, column=0, sticky=tk.W, pady=4)
        self._thin_entry(g, textvariable=self.var_hal_profile, width=48).grid(
            row=1, column=1, sticky=tk.EW, padx=8, pady=4
        )
        ttk.Button(g, text="Browse…", command=self._browse_hal_profile).grid(
            row=1, column=2, padx=4, pady=4
        )
        g.columnconfigure(1, weight=1)

        btns = ttk.Frame(frm)
        btns.pack(fill=tk.X, padx=10, pady=12)
        self.btn_fb_login = ttk.Button(
            btns,
            text="เปิดเบราว์เซอร์ Facebook (ล็อกอิน)",
            command=self._open_facebook_login,
        )
        self.btn_fb_login.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_hal_login = ttk.Button(
            btns,
            text="เปิดเบราว์เซอร์ HAL (ล็อกอิน)",
            command=self._open_hal_login,
        )
        self.btn_hal_login.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_wa_login = ttk.Button(
            btns,
            text="เปิดเบราว์เซอร์ WhatsApp (ล็อกอิน)",
            command=self._open_whatsapp_login,
        )
        self.btn_wa_login.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btns, text="บันทึก Browser Profile", command=self.save_browser_profile).pack(
            side=tk.RIGHT
        )

    def _browse_fb_profile(self) -> None:
        initial = self.io.resolve_user_data_path(self.var_fb_profile.get())
        if not initial.is_dir():
            initial = self.io.root
        chosen = filedialog.askdirectory(
            parent=self.win,
            title="เลือกโฟลเดอร์ Facebook browser profile",
            initialdir=str(initial),
        )
        if chosen:
            self.var_fb_profile.set(self.io.to_stored_user_data_path(chosen))

    def _browse_hal_profile(self) -> None:
        initial = self.io.resolve_user_data_path(self.var_hal_profile.get())
        if not initial.is_dir():
            initial = self.io.root
        chosen = filedialog.askdirectory(
            parent=self.win,
            title="เลือกโฟลเดอร์ HAL browser profile",
            initialdir=str(initial),
        )
        if chosen:
            self.var_hal_profile.set(self.io.to_stored_user_data_path(chosen))

    def save_browser_profile(self) -> bool:
        try:
            self.io.save_browser_profile_fields(
                self.var_fb_profile.get(),
                self.var_hal_profile.get(),
            )
            us = self.io.load_user_settings()
            self.var_fb_profile.set(us["facebook_user_data_dir"])
            self.var_hal_profile.set(us["hal_user_data_dir"])
            messagebox.showinfo(
                "บันทึก",
                "บันทึก user_settings.json + HAL_USER_DATA_DIR ใน .env แล้ว",
                parent=self.win,
            )
            self.refresh_checklist()
            return True
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e), parent=self.win)
            return False

    def save_browser_profile_silent(self) -> bool:
        try:
            self.io.save_browser_profile_fields(
                self.var_fb_profile.get(),
                self.var_hal_profile.get(),
            )
            return True
        except Exception as e:
            messagebox.showerror("Browser Profile", str(e), parent=self.win)
            return False

    def _open_facebook_login(self) -> None:
        self._open_profile_login(
            self.var_fb_profile.get() or "no_api_send_bill/browser_profile",
            FACEBOOK_INBOX_URL,
            "Facebook",
            anchor=getattr(self, "btn_fb_login", None),
        )

    def _open_hal_login(self) -> None:
        self._open_profile_login(
            self.var_hal_profile.get() or "hal_browser_profile",
            HAL_LOGIN_URL,
            "HAL",
            anchor=getattr(self, "btn_hal_login", None),
        )

    def _open_whatsapp_login(self) -> None:
        self._open_profile_login(
            self.var_fb_profile.get() or "no_api_send_bill/browser_profile",
            WHATSAPP_WEB_URL,
            "WhatsApp",
            anchor=getattr(self, "btn_wa_login", None),
        )

    def _set_browser_login_busy(self, busy: bool) -> None:
        for btn in (
            getattr(self, "btn_fb_login", None),
            getattr(self, "btn_hal_login", None),
            getattr(self, "btn_wa_login", None),
        ):
            if btn is None:
                continue
            try:
                if busy:
                    btn.state(["disabled"])
                else:
                    btn.state(["!disabled"])
            except tk.TclError:
                btn.config(state=tk.DISABLED if busy else tk.NORMAL)

    def _cancel_browser_login_poll(self) -> None:
        poll_id = self._browser_login_poll_id
        if not poll_id:
            return
        try:
            self.win.after_cancel(poll_id)
        except Exception:
            pass
        self._browser_login_poll_id = None

    def _schedule_browser_login_poll(self) -> None:
        self._cancel_browser_login_poll()

        def _poll() -> None:
            t = self._browser_login_thread
            if t is None or not t.is_alive():
                self._browser_login_thread = None
                self._set_browser_login_busy(False)
                self._browser_login_poll_id = None
                return
            self._browser_login_poll_id = self.win.after(400, _poll)

        self._browser_login_poll_id = self.win.after(400, _poll)

    def _open_profile_login(
        self,
        path_value: str,
        url: str,
        label: str,
        anchor: tk.Misc | None = None,
    ) -> None:
        t = self._browser_login_thread
        if t is not None and t.is_alive():
            messagebox.showinfo(
                "กำลังเปิดอยู่",
                "เบราว์เซอร์ล็อกอินยังเปิดอยู่ — ปิดหน้าต่างนั้นก่อน",
                parent=self.win,
            )
            return
        profile = self.io.resolve_user_data_path(path_value)
        self._set_browser_login_busy(True)
        err: list = []

        from settings.window_place import under_xy

        btn = anchor if anchor is not None else self.win
        try:
            pos = under_xy(
                btn,
                parent=self.win,
                gap=4,
                pad=0,
                left_align_parent=True,
            )
        except Exception:
            pos = None

        def worker() -> None:
            try:
                open_persistent_login(profile, url, window_position=pos)
            except Exception as e:
                err.append(e)
            finally:

                def done() -> None:
                    self._cancel_browser_login_poll()
                    self._browser_login_thread = None
                    self._set_browser_login_busy(False)
                    if err:
                        messagebox.showerror("ผิดพลาด", str(err[0]), parent=self.win)

                try:
                    self.win.after(0, done)
                except Exception:
                    pass

        self._browser_login_thread = threading.Thread(target=worker, daemon=True)
        self._browser_login_thread.start()
        self._schedule_browser_login_poll()


def open_settings_window(
    parent: tk.Misc,
    project_root: Path,
    anchor: tk.Misc | None = None,
) -> SettingsWindow:
    from settings.window_place import show_placed_toplevel

    sw = SettingsWindow(parent, Path(project_root))
    show_placed_toplevel(
        sw.win,
        anchor if anchor is not None else parent,
        parent=parent,
        width=820,
        height=760,
    )
    return sw
