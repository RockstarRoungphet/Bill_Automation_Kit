#!/usr/bin/env python3
"""
Launcher UI — ໜ້າຕ່າງສຳລັບຮັນ run_manual.py ແລະ send_bill_signal.ahk
ສະແດງສະຖານະຈາກ run_manual.py ແບບ real-time
"""
import ctypes
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import List, Optional

try:
    import tkinter as tk
    from tkinter import ttk, scrolledtext, messagebox
except ImportError:
    print("ຕ້ອງໃຊ້ Python ທີ່ມີ tkinter (ໃນ Windows ມັກຈະມີໃຫ້ແລ້ວ)")
    sys.exit(1)

try:
    import pystray
    from PIL import Image
except ImportError:
    pystray = None  # type: ignore
    Image = None  # type: ignore

PROJECT_DIR = Path(__file__).resolve().parent
RUN_MANUAL = PROJECT_DIR / "run_manual.py"
AHK_SCRIPT = PROJECT_DIR / "send_bill_signal.ahk"
ICON_PATH = PROJECT_DIR / "send_bill.ico"

# ສ່ວນຂອງຖ່າຍຮູບບິນ (capture_bill_screenshot.py) ຢູ່ໂຟນເດີແມ່ (Testing / send_bill)
PROJECT_ROOT = PROJECT_DIR.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

WINDOW_TITLE = "Bill Automation Kit"
_INSTANCE_MUTEX = None
_MUTEX_NAME = "Local\\BillAutomationKit_Launcher"


def _activate_existing_window(title: str) -> bool:
    if sys.platform != "win32":
        return False
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return False
    SW_RESTORE = 9
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    return True


def _ensure_single_instance() -> bool:
    """Keep one launcher. If already running, show that window and return False."""
    global _INSTANCE_MUTEX
    if sys.platform != "win32":
        return True
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    _INSTANCE_MUTEX = handle
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        _activate_existing_window(WINDOW_TITLE)
        return False
    return True


class _Win32Tray:
    """Windows notification-area icon (taskbar ^ overflow). No extra pip package."""

    WM_TRAY = 0x0400 + 20
    ID_SHOW = 1001
    ID_EXIT = 1002

    def __init__(self, tooltip: str, ico_path: Path, on_show, on_exit, on_click=None):
        self.tooltip = tooltip
        self.ico_path = ico_path
        self.on_show = on_show
        self.on_exit = on_exit
        self.on_click = on_click or on_show
        self._hwnd = None
        self._ready = threading.Event()
        self._wndproc = None
        self._nid = None

    def start(self) -> bool:
        threading.Thread(target=self._run, daemon=True).start()
        if not self._ready.wait(timeout=3):
            return False
        return bool(self._hwnd)

    def stop(self) -> None:
        if self._hwnd:
            try:
                ctypes.windll.user32.PostMessageW(self._hwnd, 0x0010, 0, 0)  # WM_CLOSE
            except Exception:
                pass

    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        kernel32 = ctypes.windll.kernel32

        LRESULT = ctypes.c_ssize_t
        WPARAM = ctypes.c_size_t
        LPARAM = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
        user32.DefWindowProcW.restype = LRESULT
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.restype = LRESULT

        class WNDCLASS(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        class NOTIFYICONDATA(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128),
            ]

        NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x01, 0x02, 0x04
        NIM_ADD, NIM_DELETE = 0, 2
        WM_LBUTTONUP, WM_RBUTTONUP = 0x0202, 0x0205
        WM_DESTROY, WM_CLOSE, WM_COMMAND = 0x0002, 0x0010, 0x0111
        TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x0002, 0x0100

        def _load_icon():
            if self.ico_path.is_file():
                h = user32.LoadImageW(
                    None,
                    str(self.ico_path),
                    1,
                    0,
                    0,
                    0x00000010 | 0x00000040,
                )
                if h:
                    return h
            return user32.LoadIconW(None, ctypes.c_wchar_p(32512)) or user32.LoadIconW(
                None, 32512
            )

        hicon = _load_icon()
        hinst = kernel32.GetModuleHandleW(None)
        class_name = "BillKitTrayWnd"

        def _wndproc(hwnd, msg, wparam, lparam):
            if msg == self.WM_TRAY:
                if lparam == WM_LBUTTONUP:
                    self.on_click()
                    return 0
                if lparam == WM_RBUTTONUP:
                    menu = user32.CreatePopupMenu()
                    user32.AppendMenuW(menu, 0, self.ID_SHOW, "Show")
                    user32.AppendMenuW(menu, 0, self.ID_EXIT, "Exit")
                    pt = wintypes.POINT()
                    user32.GetCursorPos(ctypes.byref(pt))
                    user32.SetForegroundWindow(hwnd)
                    cmd = user32.TrackPopupMenu(
                        menu,
                        TPM_RIGHTBUTTON | TPM_RETURNCMD,
                        pt.x,
                        pt.y,
                        0,
                        hwnd,
                        None,
                    )
                    user32.DestroyMenu(menu)
                    if cmd == self.ID_SHOW:
                        self.on_show()
                    elif cmd == self.ID_EXIT:
                        self.on_exit()
                    return 0
            if msg == WM_COMMAND:
                if wparam == self.ID_SHOW:
                    self.on_show()
                elif wparam == self.ID_EXIT:
                    self.on_exit()
                return 0
            if msg in (WM_CLOSE, WM_DESTROY):
                if self._nid is not None:
                    try:
                        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
                    except Exception:
                        pass
                    self._nid = None
                if msg == WM_CLOSE:
                    user32.DestroyWindow(hwnd)
                    return 0
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc = WNDPROC(_wndproc)
        wc = WNDCLASS()
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinst
        wc.lpszClassName = class_name
        if not user32.RegisterClassW(ctypes.byref(wc)):
            if ctypes.GetLastError() not in (0, 1410):  # already registered
                self._ready.set()
                return

        hwnd = user32.CreateWindowExW(
            0, class_name, "BillKitTray", 0, 0, 0, 0, 0, None, None, hinst, None
        )
        self._hwnd = hwnd
        if not hwnd:
            self._ready.set()
            return

        nid = NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        nid.hWnd = hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = self.WM_TRAY
        nid.hIcon = hicon
        nid.szTip = self.tooltip[:127]
        self._nid = nid
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


try:
    from settings.config_io import ConfigIO, check_setup_status
    from settings.settings_ui import open_settings_window
except ImportError:
    ConfigIO = None  # type: ignore
    check_setup_status = None  # type: ignore
    open_settings_window = None  # type: ignore

CAPTURE_SCRIPT = PROJECT_ROOT / "capture_bill_screenshot.py"
HAL_CAPTURE_SCRIPT = PROJECT_ROOT / "capture_bill_hal.py"
AUTH_JSON = PROJECT_ROOT / "auth.json"
ENV_FILE = PROJECT_ROOT / ".env"


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


def _anousith_private_cmd_args() -> list:
    """Always prefer private Anousith capture when session or .env login exists."""
    args = ["--private"]
    if AUTH_JSON.is_file():
        args.extend(["--storage-state", str(AUTH_JSON)])
    return args


def _anousith_can_use_private() -> bool:
    if AUTH_JSON.is_file():
        return True
    return bool(_env_value("ANOUSITH_USER") and _env_value("ANOUSITH_PASSWORD"))


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
PAGE_TOKEN_FILE = PROJECT_ROOT / "page_token.json"
DEFAULT_FB_PROFILE = "no_api_send_bill/browser_profile"


def _load_real_page_names() -> List[str]:
    """Page names from page_token.json (skip placeholders / disabled)."""
    if not PAGE_TOKEN_FILE.is_file():
        return []
    try:
        raw = json.loads(PAGE_TOKEN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    pages = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])
    names: List[str] = []
    seen = set()
    for p in pages:
        if not isinstance(p, dict) or p.get("enabled") is False:
            continue
        name = str(p.get("page_name") or "").strip()
        pid = str(p.get("page_id") or "").strip()
        if not name or name == "YourPageName":
            continue
        if not pid or pid in ("YOUR_FACEBOOK_PAGE_ID",) or pid.upper().startswith("YOUR_"):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def _prompt_stock_available_pages(parent) -> Optional[List[str]]:
    """Modal page picker for ແຈ້ງມີສິນຄ້າ.

    Returns:
      None — cancelled
      [] — send all pages (omit --pages)
      ["A", "B"] — filter to those pages
    """
    from settings.thin_entry import create_thin_entry
    from settings.ui_scrollbar import create_vertical_scrollbar

    _WHITE = "#ffffff"
    _HOVER = "#f1f3f4"
    _TEXT = "#202124"
    _FONT = ("Segoe UI", 9)

    page_names = _load_real_page_names()
    if not page_names:
        messagebox.showerror(
            "ຜິດພາດ",
            "ບໍ່ພົບເພຈໃນ page_token.json\nເພີ່ມເພຈໃນ Settings ກ່ອນ",
            parent=parent,
        )
        return None

    result: dict = {"value": None}
    win = tk.Toplevel(parent)
    win.title("ເລືອກເພຈ — ແຈ້ງມີສິນຄ້າ")
    win.transient(parent)
    win.geometry("420x460")
    win.resizable(False, True)
    win.configure(bg=_WHITE)

    style = ttk.Style(win)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("PagePick.TFrame", background=_WHITE)
    style.configure("PagePick.TLabel", background=_WHITE, foreground=_TEXT)
    style.configure(
        "PagePick.TButton",
        background=_WHITE,
        foreground=_TEXT,
        bordercolor=_WHITE,
        lightcolor=_WHITE,
        darkcolor=_WHITE,
        relief="flat",
        borderwidth=0,
        padding=(4, 2),
        focuscolor=_WHITE,
    )
    style.map(
        "PagePick.TButton",
        background=[("active", _HOVER), ("pressed", _HOVER)],
        bordercolor=[("active", _HOVER), ("pressed", _HOVER)],
    )

    outer = ttk.Frame(win, style="PagePick.TFrame")
    outer.pack(fill=tk.BOTH, expand=True)

    ttk.Label(
        outer,
        text="ເລືອກສົ່ງທັງໝົດ ຫຼື ຕິກເພຈທີ່ຕ້ອງການ:",
        style="PagePick.TLabel",
    ).pack(anchor=tk.W, padx=12, pady=(12, 6))

    search_row = ttk.Frame(outer, style="PagePick.TFrame")
    search_row.pack(fill=tk.X, padx=12, pady=(0, 6))
    ttk.Label(search_row, text="Search", style="PagePick.TLabel").pack(side=tk.LEFT)
    search_var = tk.StringVar()
    search_entry = create_thin_entry(search_row, textvariable=search_var, width=28)
    search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

    tool = ttk.Frame(outer, style="PagePick.TFrame")
    tool.pack(fill=tk.X, padx=12, pady=(0, 6))

    canvas_fr = ttk.Frame(outer, style="PagePick.TFrame")
    canvas_fr.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)
    canvas = tk.Canvas(canvas_fr, highlightthickness=0, bd=0, bg=_WHITE)
    scroll = create_vertical_scrollbar(canvas_fr, command=canvas.yview)
    inner = tk.Frame(canvas, bg=_WHITE)
    inner.bind(
        "<Configure>",
        lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
    )
    canvas_window = canvas.create_window((0, 0), window=inner, anchor=tk.NW)

    def _sync_inner_width(event: object = None) -> None:
        canvas.itemconfigure(canvas_window, width=canvas.winfo_width())

    canvas.bind("<Configure>", _sync_inner_width)
    canvas.configure(yscrollcommand=scroll.set)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _on_mousewheel(event) -> None:
        delta = 0
        if getattr(event, "delta", 0):
            delta = -1 if event.delta > 0 else 1
        elif getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        if delta:
            canvas.yview_scroll(delta, "units")

    canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
    canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

    vars_by_name: dict = {}
    rows_by_name: dict = {}

    def _set_row_bg(row: tk.Frame, cb: tk.Checkbutton, color: str) -> None:
        row.configure(bg=color)
        cb.configure(bg=color, activebackground=color)

    for name in page_names:
        var = tk.BooleanVar(value=True)
        vars_by_name[name] = var
        row = tk.Frame(inner, bg=_WHITE)
        row.pack(fill=tk.X, anchor=tk.W)
        cb = tk.Checkbutton(
            row,
            text=name,
            variable=var,
            anchor=tk.W,
            justify=tk.LEFT,
            font=_FONT,
            fg=_TEXT,
            bg=_WHITE,
            activeforeground=_TEXT,
            activebackground=_WHITE,
            selectcolor=_WHITE,
            highlightthickness=0,
            bd=0,
            relief=tk.FLAT,
        )
        cb.pack(fill=tk.X, padx=4, pady=3)

        def _enter(_e, r=row, c=cb) -> None:
            _set_row_bg(r, c, _HOVER)

        def _leave(_e, r=row, c=cb) -> None:
            _set_row_bg(r, c, _WHITE)

        row.bind("<Enter>", _enter)
        row.bind("<Leave>", _leave)
        cb.bind("<Enter>", _enter)
        cb.bind("<Leave>", _leave)
        rows_by_name[name] = row

    def _apply_search(*_args) -> None:
        query = (search_var.get() or "").strip().lower()
        for name in page_names:
            row = rows_by_name[name]
            row.pack_forget()
            if (not query) or (query in name.lower()):
                row.pack(fill=tk.X, anchor=tk.W)
        canvas.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))

    search_var.trace_add("write", _apply_search)

    def _select_all() -> None:
        for v in vars_by_name.values():
            v.set(True)

    def _clear_all() -> None:
        for v in vars_by_name.values():
            v.set(False)

    ttk.Button(tool, text="ເລືອກທັງໝົດ", style="PagePick.TButton", command=_select_all).pack(
        side=tk.LEFT
    )
    ttk.Button(
        tool, text="ເອົາອອກທັງໝົດ", style="PagePick.TButton", command=_clear_all
    ).pack(side=tk.LEFT, padx=(8, 0))

    btn_row = ttk.Frame(outer, style="PagePick.TFrame")
    btn_row.pack(fill=tk.X, padx=12, pady=(8, 12))

    def _cancel() -> None:
        try:
            canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass
        result["value"] = None
        win.destroy()

    def _start() -> None:
        selected = [n for n, v in vars_by_name.items() if v.get()]
        if not selected:
            messagebox.showwarning(
                "ແຈ້ງ",
                "ເລືອກຢ່າງໜ້ອຍ 1 ເພຈ ຫຼື ກົດເລືອກທັງໝົດ",
                parent=win,
            )
            return
        try:
            canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass
        if len(selected) == len(page_names):
            result["value"] = []
        else:
            result["value"] = selected
        win.destroy()

    ttk.Button(btn_row, text="ເລີ່ມສົ່ງ", style="PagePick.TButton", command=_start).pack(
        side=tk.RIGHT
    )
    ttk.Button(btn_row, text="ຍົກເລີກ", style="PagePick.TButton", command=_cancel).pack(
        side=tk.RIGHT, padx=(0, 8)
    )

    win.protocol("WM_DELETE_WINDOW", _cancel)
    win.grab_set()
    search_entry.focus_set()
    win.wait_window()
    return result["value"]


def _facebook_user_data_dir() -> Path:
    """Resolve Facebook Playwright profile from user_settings.json."""
    if USER_SETTINGS_FILE.is_file():
        try:
            import json

            data = json.loads(USER_SETTINGS_FILE.read_text(encoding="utf-8"))
            raw = str((data or {}).get("facebook_user_data_dir") or "").strip()
            if raw:
                p = Path(raw)
                if not p.is_absolute():
                    p = PROJECT_ROOT / p
                return p.resolve()
        except Exception:
            pass
    return (PROJECT_ROOT / DEFAULT_FB_PROFILE).resolve()


def _no_api_user_data_args() -> list:
    return ["--user-data-dir", str(_facebook_user_data_dir())]


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


def _win_user_path_dirs() -> list[Path]:
    """User PATH from the registry — Explorer/pythonw often miss newly installed tools."""
    dirs: list[Path] = []
    if sys.platform != "win32":
        return dirs
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            raw, _ = winreg.QueryValueEx(key, "Path")
        for part in str(raw or "").split(";"):
            part = part.strip()
            if part:
                dirs.append(Path(os.path.expandvars(part)))
    except Exception:
        pass
    return dirs


def _ngrok_candidate_files() -> list[Path]:
    local = Path(os.environ.get("LOCALAPPDATA") or "")
    home = Path.home()
    pf = Path(os.environ.get("ProgramFiles") or r"C:\Program Files")
    out: list[Path] = [
        NGROK_EXE,
        local / "ngrok" / "ngrok.exe",
        local / "Microsoft" / "WinGet" / "Links" / "ngrok.exe",
        pf / "ngrok" / "ngrok.exe",
        home / "Desktop" / "ngrok.exe",
        home / "OneDrive" / "Desktop" / "ngrok.exe",
    ]
    pkg = local / "Microsoft" / "WinGet" / "Packages"
    if pkg.is_dir():
        try:
            out.extend(pkg.glob("**/ngrok.exe"))
        except Exception:
            pass
    for d in _win_user_path_dirs():
        out.append(d / "ngrok.exe")
        out.append(d / "ngrok")
    return out


def _shortcut_target(lnk: Path) -> Path | None:
    if sys.platform != "win32" or not lnk.is_file():
        return None
    try:
        escaped = str(lnk).replace("'", "''")
        ps = (
            f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{escaped}');"
            "Write-Output $s.TargetPath"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        target = (r.stdout or "").strip().strip('"')
        if target:
            p = Path(target)
            if p.is_file():
                return p
    except Exception:
        return None
    return None


def _resolve_ngrok_executable() -> Path | None:
    """Find ngrok even when Desktop-launched pythonw has a stale PATH."""
    seen: set[str] = set()

    def _ok(p: Path | None) -> Path | None:
        if p is None:
            return None
        try:
            resolved = p.resolve()
        except Exception:
            return None
        if not resolved.is_file():
            return None
        key = str(resolved).lower()
        if key in seen:
            return None
        seen.add(key)
        return resolved

    hit = _ok(NGROK_EXE)
    if hit:
        return hit
    for name in ("ngrok.exe", "ngrok"):
        found = shutil.which(name)
        hit = _ok(Path(found) if found else None)
        if hit:
            return hit
    for cand in _ngrok_candidate_files():
        hit = _ok(cand)
        if hit:
            return hit
    for desktop in (Path.home() / "Desktop", Path.home() / "OneDrive" / "Desktop"):
        if not desktop.is_dir():
            continue
        try:
            for lnk in desktop.glob("*ngrok*.lnk"):
                hit = _ok(_shortcut_target(lnk))
                if hit:
                    return hit
        except Exception:
            continue
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
            for line in proc.stdout:
                decoded = line.decode("utf-8", errors="replace")
                out_queue.put(("capture_all", decoded))
            proc.wait()
            if proc.returncode != 0:
                any_failed = True
                out_queue.put(("capture_all", f"❌ {title} ไม่สำเร็จ (exit {proc.returncode})\n"))
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


def pipeline_worker(steps, env: dict, out_queue: queue.Queue, source: str = "pipeline"):
    """Run titled commands in order and stream logs. Continue after a step fails.

    After a successful Token step with RESIDUALS=0, skip the next Playwright step.
    """
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    skip_next_playwright = False
    try:
        for title, cmd, cwd in steps:
            if skip_next_playwright and str(title).startswith("Playwright"):
                out_queue.put(
                    (
                        source,
                        "⏭️ ข้าม Playwright — Token ไม่มีรายการค้าง (RESIDUALS=0)\n",
                    )
                )
                skip_next_playwright = False
                continue
            skip_next_playwright = False
            out_queue.put((source, f"\n=== {title} ===\n"))
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                env=env,
                creationflags=creation_flags,
            )
            step_text = ""
            for line in proc.stdout:
                decoded = line.decode("utf-8", errors="replace")
                step_text += decoded
                out_queue.put((source, decoded))
            proc.wait()
            if proc.returncode != 0:
                out_queue.put(
                    (source, f"❌ {title} ไม่สำเร็จ (exit {proc.returncode})\n")
                )
            elif str(title).startswith("Token"):
                for raw_line in step_text.splitlines():
                    if raw_line.strip() == "RESIDUALS=0":
                        skip_next_playwright = True
                        break
    except Exception as e:
        out_queue.put((source, f"❌ Pipeline error: {e}\n"))
    out_queue.put((source, None))


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
    if not _ensure_single_instance():
        return

    out_queue = queue.Queue()
    process_ref = {
        "proc": None, "ahk": None,
        "capture_all": None,
        "pipeline": None,
        "no_api": None, "no_api_notify": None, "no_api_stock_out": None, "no_api_stock_available": None,
        "webhook": None, "ngrok": None,
        "api_bill": None, "api_notify": None, "api_stock_out": None, "api_stock_available": None,
    }
    action_buttons: list = []

    root = tk.Tk()
    root.title(WINDOW_TITLE)
    root.minsize(360, 320)
    root.geometry("720x480")
    root.configure(bg="white")
    if sys.platform == "win32" and ICON_PATH.is_file():
        try:
            root.iconbitmap(str(ICON_PATH))
        except Exception:
            pass

    _WHITE = "#ffffff"
    _TEXT = "#202124"
    _HOVER = "#f1f3f4"
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("TFrame", background=_WHITE)
    style.configure("TLabel", background=_WHITE, foreground=_TEXT)
    style.configure("Section.TLabel", background=_WHITE, foreground=_TEXT)
    style.configure(
        "TButton",
        background=_WHITE,
        foreground=_TEXT,
        bordercolor=_WHITE,
        lightcolor=_WHITE,
        darkcolor=_WHITE,
        relief="flat",
        borderwidth=0,
        padding=(4, 2),
        focuscolor=_WHITE,
    )
    style.map(
        "TButton",
        background=[("active", _HOVER), ("pressed", _HOVER)],
        bordercolor=[("active", _HOVER), ("pressed", _HOVER)],
        relief=[("pressed", "flat"), ("active", "flat")],
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
    style.configure("Notify.TButton", padding=(6, 2, 16, 2))

    toolbar = ttk.Frame(root)
    toolbar.pack(side=tk.TOP, fill=tk.X, padx=4, pady=2)

    # ພື້ນທີ່ສະແດງສະຖານະ
    status_frame = ttk.Frame(root)
    status_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)
    status_title = ttk.Label(status_frame, text="Activity", style="Section.TLabel")
    status_title.pack(anchor=tk.W, padx=4, pady=(0, 4))
    status_text = scrolledtext.ScrolledText(
        status_frame,
        wrap=tk.WORD,
        width=1,
        height=8,
        font=("Consolas", 10),
        bg="white",
        relief=tk.SOLID,
        borderwidth=1,
        highlightthickness=0,
        exportselection=True,
    )
    status_text.pack(fill=tk.BOTH, expand=True)

    def _focus_is_editable() -> bool:
        w = root.focus_get()
        return w is not None and w is not status_text and w.winfo_class() in (
            "Entry",
            "TEntry",
            "Text",
            "TCombobox",
        )

    def _block_log_edit(event):
        ctrl = bool(event.state & 0x4)
        vk = int(getattr(event, "keycode", 0) or 0)
        ch = event.char or ""
        # IME (Hangul/Thai/Lao) reports keysym Hangul_* instead of a/c; use virtual-key / control char.
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

    def poll_queue():
        try:
            while True:
                source, line = out_queue.get_nowait()
                if line is None:
                    if source == "run":
                        btn_helper.config(state=tk.NORMAL)
                        process_ref["proc"] = None
                    elif source == "capture_all":
                        process_ref["capture_all"] = None
                    elif source == "pipeline":
                        process_ref["pipeline"] = None
                        for b in action_buttons:
                            try:
                                b.config(state=tk.NORMAL)
                            except Exception:
                                pass
                    elif source == "webhook":
                        process_ref["webhook"] = None
                        _check_webhook_stopped()
                    elif source == "ngrok":
                        process_ref["ngrok"] = None
                        _check_webhook_stopped()
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

    def _set_action_buttons(state) -> None:
        for b in action_buttons:
            try:
                b.config(state=state)
            except Exception:
                pass

    def _capture_pipeline_steps():
        python_exec = _get_python_for_capture()
        anousith_cmd = [python_exec, "-u", str(CAPTURE_SCRIPT)]
        if _anousith_can_use_private():
            anousith_cmd.extend(_anousith_private_cmd_args())
        hal_cmd = [python_exec, "-u", str(HAL_CAPTURE_SCRIPT), "--parallel-pages", "10"]
        return [
            ("Capture Anousith", anousith_cmd, PROJECT_ROOT),
            ("Capture HAL", hal_cmd, PROJECT_ROOT),
        ]

    def _start_pipeline(label: str, steps) -> None:
        if process_ref["pipeline"] is not None:
            messagebox.showinfo("ແຈ້ງ", "ກຳລັງຮັນຢູ່ແລ້ວ")
            return
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        process_ref["pipeline"] = True
        _set_action_buttons(tk.DISABLED)
        append_status(f"\n{label}\n")
        threading.Thread(
            target=pipeline_worker,
            args=(steps, env, out_queue, "pipeline"),
            daemon=True,
        ).start()

    def run_send_bill():
        if not CAPTURE_SCRIPT.is_file() or not HAL_CAPTURE_SCRIPT.is_file():
            messagebox.showerror("ຜິດພາດ", f"ບໍ່ພົບໄຟລ໌ຖ່າຍບິນ")
            return
        if not SEND_BILL_API_SCRIPT.is_file() or not NO_API_SCRIPT.is_file():
            messagebox.showerror("ຜິດພາດ", "ບໍ່ພົບສະຄຣິບສົ່ງບິນ")
            return
        api_py = _get_python_for_api()
        pw_py = _get_python_for_no_api()
        steps = _capture_pipeline_steps() + [
            (
                "Token ສົ່ງບິນ",
                [api_py, "-u", str(SEND_BILL_API_SCRIPT), "--sheet"],
                PROJECT_ROOT,
            ),
            (
                "Playwright ສົ່ງບິນ",
                [pw_py, "-u", str(NO_API_SCRIPT), "--sheet"] + _no_api_user_data_args(),
                NO_API_SEND_BILL_DIR,
            ),
        ]
        _start_pipeline(
            "ເລີ່ມສົ່ງບິນ: ຖ່າຍຮູບ → Token → Playwright (ລາຍການທີ່ Token ສົ່ງບໍ່ໄດ້)",
            steps,
        )

    def run_notify_pipeline(kind: str, token_flag: str, pw_flag: str, title: str) -> None:
        if not SEND_BILL_API_SCRIPT.is_file() or not NO_API_SCRIPT.is_file():
            messagebox.showerror("ຜິດພາດ", "ບໍ່ພົບສະຄຣິບແຈ້ງ")
            return

        pages_args: List[str] = []
        if kind == "stock_available":
            chosen = _prompt_stock_available_pages(root)
            if chosen is None:
                return
            if chosen:
                pages_csv = ",".join(chosen)
                pages_args = ["--pages", pages_csv]
                append_status(f"ກອງເພຈ: {pages_csv}\n")
            else:
                append_status("ສົ່ງທັງໝົດເພຈ\n")

        api_py = _get_python_for_api()
        pw_py = _get_python_for_no_api()
        steps = [
            (
                f"Token {title}",
                [api_py, "-u", str(SEND_BILL_API_SCRIPT), "--sheet", token_flag] + pages_args,
                PROJECT_ROOT,
            ),
            (
                f"Playwright {title}",
                [pw_py, "-u", str(NO_API_SCRIPT), "--sheet", pw_flag] + pages_args + _no_api_user_data_args(),
                NO_API_SEND_BILL_DIR,
            ),
        ]
        _start_pipeline(f"ເລີ່ມ{title}: Token → Playwright", steps)

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
        if _anousith_can_use_private():
            anousith_cmd.extend(_anousith_private_cmd_args())
            if AUTH_JSON.is_file():
                append_status("Anousith mode: private + auth.json\n")
            else:
                append_status("Anousith mode: private + auto-login จาก .env\n")
        else:
            append_status(
                "Anousith mode: public — ยังไม่มี auth.json และยังไม่ตั้ง ANOUSITH_USER/PASSWORD\n"
            )

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
            cmd = [python_exec, "-u", str(NO_API_SCRIPT), "--sheet"] + _no_api_user_data_args()
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
            cmd = [
                python_exec,
                "-u",
                str(NO_API_SCRIPT),
                "--sheet",
                "--notify-delivered",
            ] + _no_api_user_data_args()
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
            cmd = [
                python_exec,
                "-u",
                str(NO_API_SCRIPT),
                "--sheet",
                "--notify-stock-out",
            ] + _no_api_user_data_args()
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
            cmd = [
                python_exec,
                "-u",
                str(NO_API_SCRIPT),
                "--sheet",
                "--notify-stock-available",
            ] + _no_api_user_data_args()
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
            _set_webhook_icon(False)
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
            local_hint = Path(os.environ.get("LOCALAPPDATA") or "") / "ngrok" / "ngrok.exe"
            messagebox.showerror(
                "ຜິດພາດ",
                "ບໍ່ພົບ ngrok\n\n"
                f"ວາງ ngrok.exe ທີ່:\n{NGROK_EXE}\n"
                f"ຫຼື {local_hint}\n"
                "ຫຼືໄອຄອນ Desktop ຊື່ ngrok\n\n"
                "ຫຼືຕິດຕັ້ງ: winget install ngrok.ngrok\n"
                "ຫຼືຮັນ INSTALL.bat ອີກຄັ້ງ (ຈະພະຍາຍາມຕິດຕັ້ງ ngrok ໃຫ້)",
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

        _set_webhook_icon(True)
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

    tray_icon = {"icon": None}
    hiding_to_tray = {"on": False}

    def hide_to_tray() -> None:
        hiding_to_tray["on"] = True
        root.withdraw()

    def show_from_tray() -> None:
        def _show() -> None:
            hiding_to_tray["on"] = False
            root.deiconify()
            root.lift()
            root.focus_force()

        try:
            root.after(0, _show)
        except Exception:
            _show()

    def toggle_from_tray() -> None:
        def _toggle() -> None:
            try:
                is_shown = root.state() == "normal" and bool(root.winfo_viewable())
            except tk.TclError:
                is_shown = False
            if is_shown:
                hide_to_tray()
            else:
                hiding_to_tray["on"] = False
                root.deiconify()
                root.lift()
                root.focus_force()

        try:
            root.after(0, _toggle)
        except Exception:
            _toggle()

    def quit_launcher() -> None:
        icon = tray_icon["icon"]
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass
            tray_icon["icon"] = None
        for key in process_ref:
            p = process_ref[key]
            if isinstance(p, subprocess.Popen):
                try:
                    p.terminate()
                except Exception:
                    pass
        root.destroy()

    def exit_app() -> None:
        try:
            root.after(0, quit_launcher)
        except Exception:
            quit_launcher()

    def on_unmap(event) -> None:
        if event.widget is not root:
            return
        if hiding_to_tray["on"]:
            return
        try:
            if root.state() == "iconic":
                hide_to_tray()
        except tk.TclError:
            pass

    def start_tray() -> None:
        if sys.platform == "win32":
            tray = _Win32Tray(
                "Bill Automation Kit",
                ICON_PATH,
                show_from_tray,
                exit_app,
                on_click=toggle_from_tray,
            )
            if tray.start():
                tray_icon["icon"] = tray
                return
        if pystray is None or Image is None:
            return
        try:
            img = Image.open(ICON_PATH) if ICON_PATH.is_file() else Image.new("RGBA", (16, 16), (32, 32, 32, 255))
        except Exception:
            return
        menu = pystray.Menu(
            pystray.MenuItem("Show / Hide", lambda: toggle_from_tray(), default=True),
            pystray.MenuItem("Show", lambda: show_from_tray()),
            pystray.MenuItem("Exit", lambda: exit_app()),
        )
        icon = pystray.Icon("BillAutomationKit", img, "Bill Automation Kit", menu)
        tray_icon["icon"] = icon
        threading.Thread(target=icon.run, daemon=True).start()

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
        if state["installed"] and state["enabled"]:
            btn_auto_cleanup_toggle.config(text="Auto Cleanup enabled", state=tk.NORMAL)
        elif state["installed"] and not state["enabled"]:
            btn_auto_cleanup_toggle.config(text="Auto Cleanup disabled", state=tk.NORMAL)
        else:
            btn_auto_cleanup_toggle.config(
                text="Auto Cleanup disabled",
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

    _btn_pad = {"side": tk.LEFT, "padx": 0}

    # ປຸ່ມແຖວດຽວ: webhook icon → ສົ່ງບິນ → ແຈ້ງ → ຕົວຊ່ວຍ → cleanup → Settings

    def _edit_notify_message(kind: str, title: str) -> None:
        if ConfigIO is None:
            messagebox.showerror("ຜິດພາດ", "ບໍ່ພົບ settings module", parent=root)
            return
        io = ConfigIO(PROJECT_ROOT)
        msgs = io.load_notify_messages()
        win = tk.Toplevel(root)
        win.title(f"ແກ້ໄຂຂໍ້ຄວາມ — {title}")
        win.transient(root)
        win.resizable(True, True)
        win.geometry("480x220")
        ttk.Label(win, text=f"ຂໍ້ຄວາມທີ່ສົ່ງໃຫ້ລູກຄ້າ ({title})").pack(
            anchor=tk.W, padx=10, pady=(10, 4)
        )
        txt = tk.Text(win, wrap=tk.WORD, height=6, font=("Segoe UI", 10))
        txt.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        txt.insert("1.0", msgs.get(kind) or "")
        btn_row = ttk.Frame(win)
        btn_row.pack(fill=tk.X, padx=10, pady=(4, 10))

        def _save() -> None:
            body = txt.get("1.0", "end-1c")
            current = io.load_notify_messages()
            current[kind] = body
            io.save_notify_messages(
                current.get("delivered") or "",
                current.get("stock_out") or "",
                current.get("stock_available") or "",
            )
            win.destroy()
            messagebox.showinfo("ບັນທຶກ", "ບັນທຶກຂໍ້ຄວາມແລ້ວ", parent=root)

        ttk.Button(btn_row, text="ບັນທຶກ", command=_save).pack(side=tk.RIGHT)
        ttk.Button(btn_row, text="ຍົກເລີກ", command=win.destroy).pack(side=tk.RIGHT, padx=(0, 8))
        win.grab_set()
        txt.focus_set()

    try:
        style.configure("Notify.TButton", padding=(6, 2, 16, 2))
    except Exception:
        pass

    def _notify_button_group(parent, label: str, kind: str, token_flag: str, pw_flag: str):
        wrap = ttk.Frame(parent)
        action = ttk.Button(
            wrap,
            text=label,
            style="Notify.TButton",
            command=lambda: run_notify_pipeline(kind, token_flag, pw_flag, label),
        )
        action.pack()

        kebab = tk.Canvas(wrap, width=10, height=22, highlightthickness=0, bd=0, bg=_WHITE)
        hovering = {"on": False}

        def _button_bg(active: bool = False) -> str:
            try:
                st = ("active",) if active else ()
                return style.lookup("TButton", "background", st) or _WHITE
            except Exception:
                return _HOVER if active else _WHITE

        def _draw_dots() -> None:
            kebab.delete("dots")
            kebab.configure(bg=_button_bg(hovering["on"]))
            if not hovering["on"]:
                return
            kebab.update_idletasks()
            w = int(kebab.winfo_width() or 10)
            h = int(kebab.winfo_height() or 22)
            cx = max(w // 2, 5)
            mid = max(h // 2, 11)
            r = 1.3
            gap = 5
            for y in (mid - gap, mid, mid + gap):
                kebab.create_oval(
                    cx - r, y - r, cx + r, y + r, fill="#333333", outline="#333333", tags="dots"
                )

        def _set_hover(on: bool) -> None:
            hovering["on"] = on
            if on:
                kebab.place(in_=action, relx=1.0, rely=0.5, x=-2, anchor="e")
            else:
                kebab.place_forget()
            _draw_dots()

        kebab.bind("<Button-1>", lambda _e: _edit_notify_message(kind, label))
        wrap.bind("<Enter>", lambda _e: _set_hover(True))
        wrap.bind("<Leave>", lambda _e: _set_hover(False))
        action.bind("<Enter>", lambda _e: _set_hover(True))
        kebab.bind("<Enter>", lambda _e: _set_hover(True))

        wrap.pack(**_btn_pad)
        return action

    webhook_tip = {"text": "ເລີ່ມ Server", "win": None}
    btn_webhook = ttk.Button(toolbar, text="START", command=toggle_webhook)

    def _set_webhook_icon(running: bool) -> None:
        btn_webhook.config(text="STOP" if running else "START")
        webhook_tip["text"] = "ຢຸດ Server" if running else "ເລີ່ມ Server"

    def _webhook_tip_show(_e=None) -> None:
        if webhook_tip["win"] is not None:
            return
        tw = tk.Toplevel(root)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(
            f"+{btn_webhook.winfo_rootx()}+{btn_webhook.winfo_rooty() + btn_webhook.winfo_height() + 4}"
        )
        tk.Label(
            tw,
            text=webhook_tip["text"],
            bg="#ffffe0",
            fg="#111111",
            relief=tk.SOLID,
            borderwidth=1,
            font=("Segoe UI", 9),
            padx=6,
            pady=2,
        ).pack()
        webhook_tip["win"] = tw

    def _webhook_tip_hide(_e=None) -> None:
        tw = webhook_tip["win"]
        webhook_tip["win"] = None
        if tw is not None:
            tw.destroy()

    _set_webhook_icon(False)
    btn_webhook.bind("<Enter>", _webhook_tip_show)
    btn_webhook.bind("<Leave>", _webhook_tip_hide)
    btn_webhook.pack(**_btn_pad)

    btn_send_bill = ttk.Button(toolbar, text="ສົ່ງບິນ", command=run_send_bill)
    btn_send_bill.pack(**_btn_pad)
    btn_notify_delivered = _notify_button_group(
        toolbar,
        "ແຈ້ງຮອດແລ້ວ",
        "delivered",
        "--notify-delivered",
        "--notify-delivered",
    )
    btn_notify_stock_out = _notify_button_group(
        toolbar,
        "ແຈ້ງສິນຄ້າໝົດ",
        "stock_out",
        "--notify-stock-out",
        "--notify-stock-out",
    )
    btn_notify_stock_available = _notify_button_group(
        toolbar,
        "ແຈ້ງມີສິນຄ້າ",
        "stock_available",
        "--notify-stock-available",
        "--notify-stock-available",
    )
    btn_helper = ttk.Button(toolbar, text="ຕົວຊ່ວຍສົ່ງບິນ", command=run_helper)
    btn_helper.pack(**_btn_pad)
    btn_auto_cleanup_toggle = ttk.Button(
        toolbar,
        text="Auto Cleanup disabled",
        command=toggle_auto_cleanup_task,
    )
    btn_auto_cleanup_toggle.pack(**_btn_pad)
    btn_settings = ttk.Button(toolbar, text="Settings", command=open_settings)
    btn_settings.pack(**_btn_pad)
    action_buttons.extend(
        [
            btn_send_bill,
            btn_notify_delivered,
            btn_notify_stock_out,
            btn_notify_stock_available,
        ]
    )

    refresh_auto_cleanup_status()

    root.after(400, maybe_first_run_settings)

    start_tray()
    if tray_icon["icon"] is not None:
        root.bind("<Unmap>", on_unmap)
    root.protocol("WM_DELETE_WINDOW", quit_launcher)
    root.mainloop()


if __name__ == "__main__":
    main()
