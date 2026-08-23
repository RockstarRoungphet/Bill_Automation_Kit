# -*- coding: utf-8 -*-
"""Load/save local config files for Bill_Automation_Kit Settings UI.

Does not depend on production Automation_Work. Paths are relative to project root.
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PLACEHOLDER_SHEET = "YOUR_GOOGLE_SHEET_ID"
PLACEHOLDER_PAGE_ID = "YOUR_FACEBOOK_PAGE_ID"
PLACEHOLDER_TOKEN = "YOUR_PAGE_ACCESS_TOKEN"
PLACEHOLDER_PAGE_NAME = "YourPageName"

ENV_KEYS_SETTINGS = (
    "WEBHOOK_VERIFY_TOKEN",
    "PORT",
    "NGROK_DOMAIN",
    "BASE_URL",
)

ENV_KEYS_CARRIER = (
    "ANOUSITH_USER",
    "ANOUSITH_PASSWORD",
    "HAL_USER",
    "HAL_PASSWORD",
)

PAGE_REPLY_TOP_KEYS = (
    "promo_send_after_hours",
    "promo_send_before_hours",
    "promo_auto_send_disabled",
    "messenger_auto_replies_disabled",
    "generic_reply_disabled",
)

PAGE_REPLY_TEXT_KEYS = (
    "welcome_text",
    "price_reply",
    "promo_text",
    "cod_reply",
    "order_reply",
)

PAGE_MEDIA_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
PAGE_MEDIA_VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}
PAGE_MEDIA_ALL_EXT = PAGE_MEDIA_IMAGE_EXT | PAGE_MEDIA_VIDEO_EXT
PAGE_MEDIA_KINDS = ("welcome", "promo")

META_MAP_KEYS = (
    "__business_pages",
    "__initial_selected_item_id",
    "__delay_between_orders_min",
    "__delay_between_orders_max",
    "__delay_between_pages_min_sec",
    "__delay_between_pages_max_sec",
)


def project_root_from_settings_module() -> Path:
    return Path(__file__).resolve().parent.parent


@dataclass
class StatusItem:
    id: str
    ok: bool
    label: str
    critical: bool = True


@dataclass
class SetupStatus:
    items: List[StatusItem] = field(default_factory=list)

    @property
    def all_critical_ok(self) -> bool:
        return all(i.ok for i in self.items if i.critical)

    def missing_labels(self) -> List[str]:
        return [i.label for i in self.items if i.critical and not i.ok]


class ConfigIO:
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else project_root_from_settings_module()
        self.templates = self.root / "config_templates"
        self.env_path = self.root / ".env"
        self.env_example = self.root / ".env.example"
        self.page_token_path = self.root / "page_token.json"
        self.user_settings_path = self.root / "user_settings.json"
        self.page_reply_path = self.root / "page_reply_config.json"
        self.creds_path = self.root / "no_api_send_bill" / "config" / "google_credentials.json"
        self.sheet_no_api = self.root / "no_api_send_bill" / "config" / "sheet_config.json"
        self.sheet_manual = self.root / "no_api_send_bill_manual" / "config" / "sheet_config.json"
        self.map_no_api = self.root / "no_api_send_bill" / "config" / "page_name_to_id.json"
        self.map_manual = self.root / "no_api_send_bill_manual" / "config" / "page_name_to_id.json"

    # --- low-level JSON ---

    def load_json(self, path: Path, default: Any = None) -> Any:
        if not path.is_file():
            return default if default is not None else {}
        try:
            raw = path.read_text(encoding="utf-8").strip()
            if not raw:
                return default if default is not None else {}
            return json.loads(raw)
        except (json.JSONDecodeError, OSError):
            return default if default is not None else {}

    def save_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            bak = path.with_suffix(path.suffix + ".bak")
            try:
                shutil.copy2(path, bak)
            except OSError:
                pass
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def seed_from_template(self, dest: Path, template_name: str) -> bool:
        """Copy template → dest if dest missing. Return True if seeded."""
        if dest.is_file():
            return False
        src = self.templates / template_name
        if not src.is_file():
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return True

    def ensure_seeded(self) -> None:
        pairs = [
            (self.sheet_no_api, "sheet_config.example.json"),
            (self.sheet_manual, "sheet_config.example.json"),
            (self.map_no_api, "page_name_to_id.example.json"),
            (self.map_manual, "page_name_to_id.example.json"),
            (self.page_token_path, "page_token.example.json"),
            (self.user_settings_path, "user_settings.example.json"),
            (self.page_reply_path, "page_reply_config.example.json"),
        ]
        for dest, name in pairs:
            self.seed_from_template(dest, name)
        if not self.env_path.is_file() and self.env_example.is_file():
            shutil.copy2(self.env_example, self.env_path)
        # After seed, keep dual credentials_path conventions
        for path, cred_rel in (
            (self.sheet_no_api, "config/google_credentials.json"),
            (self.sheet_manual, "../no_api_send_bill/config/google_credentials.json"),
        ):
            if not path.is_file():
                continue
            sc = self.load_json(path, {})
            if not isinstance(sc, dict):
                continue
            if sc.get("credentials_path") != cred_rel:
                sc["credentials_path"] = cred_rel
                self.save_json(path, sc)

    # --- .env ---

    def load_dotenv_map(self) -> Dict[str, str]:
        path = self.env_path if self.env_path.is_file() else self.env_example
        out: Dict[str, str] = {}
        if not path.is_file():
            return out
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            out[k.strip()] = v.strip()
        return out

    def merge_dotenv(self, updates: Dict[str, str]) -> None:
        """Merge keys into .env; preserve comments and other keys."""
        if not self.env_path.is_file() and self.env_example.is_file():
            shutil.copy2(self.env_example, self.env_path)
        if self.env_path.is_file():
            bak = self.env_path.with_suffix(".env.bak")
            try:
                shutil.copy2(self.env_path, bak)
            except OSError:
                pass
            lines = self.env_path.read_text(encoding="utf-8").splitlines()
        else:
            lines = []

        updates = {k: str(v) if v is not None else "" for k, v in updates.items()}
        seen = set()
        new_lines: List[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k = stripped.split("=", 1)[0].strip()
                if k in updates:
                    new_lines.append(f"{k}={updates[k]}")
                    seen.add(k)
                    continue
            new_lines.append(line)
        for k, v in updates.items():
            if k not in seen:
                new_lines.append(f"{k}={v}")
        self.env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # --- sheet ---

    def load_sheet_config(self) -> Dict[str, Any]:
        self.ensure_seeded()
        data = self.load_json(self.sheet_no_api, {})
        if not isinstance(data, dict):
            data = {}
        names = data.get("sheet_names") or []
        if isinstance(names, str):
            names = [n.strip() for n in names.split(",") if n.strip()]
        return {
            "sheet_id": str(data.get("sheet_id") or ""),
            "sheet_names": list(names),
            "credentials_path": str(data.get("credentials_path") or "config/google_credentials.json"),
        }

    def save_sheet_config(self, sheet_id: str, sheet_names: List[str]) -> None:
        sheet_id = (sheet_id or "").strip()
        names = [n.strip() for n in sheet_names if (n or "").strip()]
        if not names:
            names = ["ອໍເດີ່"]
        no_api = {
            "sheet_id": sheet_id,
            "sheet_names": names,
            "credentials_path": "config/google_credentials.json",
        }
        manual = {
            "sheet_id": sheet_id,
            "sheet_names": names,
            "credentials_path": "../no_api_send_bill/config/google_credentials.json",
        }
        self.save_json(self.sheet_no_api, no_api)
        self.save_json(self.sheet_manual, manual)

    def copy_google_credentials(self, source: Path) -> Path:
        source = Path(source)
        if not source.is_file():
            raise FileNotFoundError(str(source))
        self.creds_path.parent.mkdir(parents=True, exist_ok=True)
        if self.creds_path.is_file():
            try:
                shutil.copy2(self.creds_path, self.creds_path.with_suffix(".json.bak"))
            except OSError:
                pass
        shutil.copy2(source, self.creds_path)
        return self.creds_path

    # --- pages / tokens ---

    def load_page_tokens(self) -> List[Dict[str, Any]]:
        self.ensure_seeded()
        raw = self.load_json(self.page_token_path, [])
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            return []
        pages = []
        for p in raw:
            if not isinstance(p, dict):
                continue
            pages.append(
                {
                    "page_id": str(p.get("page_id") or ""),
                    "page_name": str(p.get("page_name") or ""),
                    "access_token": str(p.get("access_token") or ""),
                    "enabled": p.get("enabled", True) is not False,
                    "subscribed_fields": p.get(
                        "subscribed_fields",
                        ["messages", "messaging_postbacks", "message_echoes"],
                    ),
                }
            )
        return pages

    def load_page_map_meta(self) -> Dict[str, Any]:
        data = self.load_json(self.map_no_api, {})
        if not isinstance(data, dict):
            data = {}
        meta = {}
        for k in META_MAP_KEYS:
            if k in data:
                meta[k] = data[k]
        if "__business_pages" not in meta:
            meta["__business_pages"] = []
        if "__initial_selected_item_id" not in meta:
            meta["__initial_selected_item_id"] = ""
        return meta

    def save_pages(
        self,
        pages: List[Dict[str, Any]],
        map_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        token_list = []
        name_map: Dict[str, Any] = {}
        meta = map_meta if map_meta is not None else self.load_page_map_meta()
        for k in META_MAP_KEYS:
            if k in meta:
                name_map[k] = meta[k]

        for p in pages:
            name = str(p.get("page_name") or "").strip()
            pid = str(p.get("page_id") or "").strip()
            token = str(p.get("access_token") or "").strip()
            if not name and not pid and not token:
                continue
            entry = {
                "page_id": pid,
                "page_name": name,
                "access_token": token,
                "enabled": p.get("enabled", True) is not False,
            }
            fields = p.get("subscribed_fields")
            if fields:
                entry["subscribed_fields"] = fields
            else:
                entry["subscribed_fields"] = [
                    "messages",
                    "messaging_postbacks",
                    "message_echoes",
                ]
            token_list.append(entry)
            if name and pid and pid not in (PLACEHOLDER_PAGE_ID, ""):
                name_map[name] = pid

        self.save_json(self.page_token_path, token_list)
        self.save_json(self.map_no_api, name_map)
        self.save_json(self.map_manual, dict(name_map))

    # --- user_settings + webhook view ---

    def load_user_settings(self) -> Dict[str, Any]:
        self.ensure_seeded()
        data = self.load_json(self.user_settings_path, {})
        if not isinstance(data, dict):
            data = {}
        return {
            "ngrok_domain": str(data.get("ngrok_domain") or ""),
            "webhook_port": int(data.get("webhook_port") or 5000),
            "facebook_user_data_dir": str(
                data.get("facebook_user_data_dir") or "no_api_send_bill/browser_profile"
            ),
            "hal_user_data_dir": str(data.get("hal_user_data_dir") or "hal_browser_profile"),
        }

    def load_webhook_fields(self) -> Dict[str, str]:
        env = self.load_dotenv_map()
        us = self.load_user_settings()
        domain = (
            env.get("NGROK_DOMAIN")
            or us.get("ngrok_domain")
            or ""
        ).strip()
        if domain.startswith("http"):
            domain = domain.split("://", 1)[-1].strip("/")
        base = env.get("BASE_URL") or ""
        if not base and domain:
            base = f"https://{domain}"
        port = env.get("PORT") or str(us.get("webhook_port") or 5000)
        return {
            "WEBHOOK_VERIFY_TOKEN": env.get("WEBHOOK_VERIFY_TOKEN") or "my_verify_token_12345",
            "PORT": str(port),
            "NGROK_DOMAIN": domain,
            "BASE_URL": base,
        }

    def save_webhook_fields(
        self,
        verify_token: str,
        port: str,
        ngrok_domain: str,
        base_url: str = "",
    ) -> None:
        verify_token = (verify_token or "").strip()
        port = (port or "5000").strip() or "5000"
        ngrok_domain = (ngrok_domain or "").strip()
        ngrok_domain = re.sub(r"^https?://", "", ngrok_domain).strip("/")
        base_url = (base_url or "").strip()
        if not base_url and ngrok_domain:
            base_url = f"https://{ngrok_domain}"

        self.merge_dotenv(
            {
                "WEBHOOK_VERIFY_TOKEN": verify_token,
                "PORT": port,
                "NGROK_DOMAIN": ngrok_domain,
                "BASE_URL": base_url,
            }
        )
        us = self.load_user_settings()
        us["ngrok_domain"] = ngrok_domain
        try:
            us["webhook_port"] = int(port)
        except ValueError:
            us["webhook_port"] = 5000
        self.save_json(self.user_settings_path, us)

    # --- browser profile paths ---

    def resolve_user_data_path(self, rel_or_abs: str) -> Path:
        """Resolve a stored path relative to kit root (or absolute as-is)."""
        raw = (rel_or_abs or "").strip()
        if not raw:
            return self.root.resolve()
        p = Path(raw)
        if not p.is_absolute():
            p = self.root / p
        return p.resolve()

    def to_stored_user_data_path(self, rel_or_abs: str) -> str:
        """Store as relative (posix) under kit root when possible; else absolute."""
        resolved = self.resolve_user_data_path(rel_or_abs)
        try:
            return resolved.relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return str(resolved)

    def save_browser_profile_fields(self, facebook_dir: str, hal_dir: str) -> None:
        fb_stored = self.to_stored_user_data_path(
            facebook_dir or "no_api_send_bill/browser_profile"
        )
        hal_stored = self.to_stored_user_data_path(hal_dir or "hal_browser_profile")
        us = self.load_user_settings()
        us["facebook_user_data_dir"] = fb_stored
        us["hal_user_data_dir"] = hal_stored
        self.save_json(self.user_settings_path, us)
        abs_hal = str(self.resolve_user_data_path(hal_stored))
        self.merge_dotenv({"HAL_USER_DATA_DIR": abs_hal})

    # --- carrier (.env) ---

    def load_carrier_fields(self) -> Dict[str, str]:
        env = self.load_dotenv_map()
        return {k: str(env.get(k) or "") for k in ENV_KEYS_CARRIER}

    def save_carrier_fields(
        self,
        anousith_user: str,
        anousith_password: str,
        hal_user: str,
        hal_password: str,
    ) -> None:
        self.merge_dotenv(
            {
                "ANOUSITH_USER": (anousith_user or "").strip(),
                "ANOUSITH_PASSWORD": (anousith_password or "").strip(),
                "HAL_USER": (hal_user or "").strip(),
                "HAL_PASSWORD": (hal_password or "").strip(),
            }
        )

    def real_page_names(self, pages: Optional[List[Dict[str, Any]]] = None) -> List[str]:
        rows = pages if pages is not None else self.load_page_tokens()
        names: List[str] = []
        seen = set()
        for p in rows:
            name = str(p.get("page_name") or "").strip()
            pid = str(p.get("page_id") or "").strip()
            if not name or name == PLACEHOLDER_PAGE_NAME:
                continue
            if pid in ("", PLACEHOLDER_PAGE_ID) or pid.upper().startswith("YOUR_"):
                continue
            if name in seen:
                continue
            seen.add(name)
            names.append(name)
        return names

    # --- page_reply_config.json ---

    def load_page_reply_config(self) -> Dict[str, Any]:
        self.ensure_seeded()
        raw = self.load_json(self.page_reply_path, {})
        if not isinstance(raw, dict):
            raw = {}
        globals_out: Dict[str, Any] = {
            "promo_send_after_hours": raw.get("promo_send_after_hours", 6),
            "promo_send_before_hours": raw.get("promo_send_before_hours", 23),
            "promo_auto_send_disabled": bool(raw.get("promo_auto_send_disabled")),
            "messenger_auto_replies_disabled": bool(
                raw.get("messenger_auto_replies_disabled")
            ),
            "generic_reply_disabled": bool(raw.get("generic_reply_disabled")),
        }
        pages: Dict[str, Dict[str, Any]] = {}
        for k, v in raw.items():
            if k in PAGE_REPLY_TOP_KEYS:
                continue
            if k == PLACEHOLDER_PAGE_NAME:
                continue
            if not isinstance(v, dict):
                continue
            pages[str(k)] = dict(v)
        return {"globals": globals_out, "pages": pages, "raw": raw}

    def save_page_reply_config(
        self,
        globals_in: Dict[str, Any],
        page_name: Optional[str] = None,
        page_fields: Optional[Dict[str, str]] = None,
    ) -> None:
        """Merge global flags and optionally one page's text fields. Keep other pages."""
        self.ensure_seeded()
        raw = self.load_json(self.page_reply_path, {})
        if not isinstance(raw, dict):
            raw = {}

        out: Dict[str, Any] = dict(raw)
        if "promo_send_after_hours" in out:
            pass
        else:
            out["promo_send_after_hours"] = 6
        if "promo_send_before_hours" not in out:
            out["promo_send_before_hours"] = 23
        out["promo_auto_send_disabled"] = bool(
            globals_in.get("promo_auto_send_disabled")
        )
        out["messenger_auto_replies_disabled"] = bool(
            globals_in.get("messenger_auto_replies_disabled")
        )
        out["generic_reply_disabled"] = bool(globals_in.get("generic_reply_disabled"))

        name = (page_name or "").strip()
        if name and name != PLACEHOLDER_PAGE_NAME and page_fields is not None:
            existing = out.get(name)
            if not isinstance(existing, dict):
                existing = {}
            merged = dict(existing)
            for key in PAGE_REPLY_TEXT_KEYS:
                if key in page_fields:
                    merged[key] = str(page_fields.get(key) or "")
            out[name] = merged

        # Keep placeholder only if no real page keys besides top-level
        self.save_json(self.page_reply_path, out)

    # --- per-page media (product_images / promo_images) ---

    @staticmethod
    def _natural_sort_key(filename: str) -> List:
        base = Path(filename).name
        return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", base)]

    def _safe_page_folder_name(self, page_name: str) -> str:
        name = (page_name or "").strip()
        if not name or name == PLACEHOLDER_PAGE_NAME:
            raise ValueError("ยังไม่ได้เลือกเพจ")
        if "/" in name or "\\" in name or name in (".", ".."):
            raise ValueError("ชื่อเพจไม่ถูกต้อง")
        return name

    def page_media_dir(self, kind: str, page_name: str) -> Path:
        kind = (kind or "").strip().lower()
        if kind not in PAGE_MEDIA_KINDS:
            raise ValueError(f"ชนิดสื่อไม่รู้จัก: {kind}")
        folder = "product_images" if kind == "welcome" else "promo_images"
        return self.root / folder / self._safe_page_folder_name(page_name)

    def list_page_media(self, kind: str, page_name: str) -> List[Dict[str, str]]:
        """Return files in send order: [{name, kind, path}, ...] kind=image|video."""
        folder = self.page_media_dir(kind, page_name)
        if not folder.is_dir():
            return []
        rows: List[Dict[str, str]] = []
        names = sorted(
            (p.name for p in folder.iterdir() if p.is_file()),
            key=self._natural_sort_key,
        )
        for name in names:
            ext = Path(name).suffix.lower()
            if ext in PAGE_MEDIA_IMAGE_EXT:
                mkind = "image"
            elif ext in PAGE_MEDIA_VIDEO_EXT:
                mkind = "video"
            else:
                continue
            rows.append(
                {
                    "name": name,
                    "kind": mkind,
                    "path": str(folder / name),
                }
            )
        return rows

    def _next_media_index(self, folder: Path) -> int:
        highest = 0
        if folder.is_dir():
            for p in folder.iterdir():
                if not p.is_file():
                    continue
                m = re.match(r"^(\d+)", p.stem)
                if m:
                    highest = max(highest, int(m.group(1)))
        return highest + 1

    def add_page_media(
        self, kind: str, page_name: str, source_paths: List[Path]
    ) -> List[str]:
        """Copy sources into the page folder as 01.ext, 02.ext, ... Return dest names."""
        folder = self.page_media_dir(kind, page_name)
        folder.mkdir(parents=True, exist_ok=True)
        added: List[str] = []
        idx = self._next_media_index(folder)
        for src in source_paths:
            src = Path(src)
            if not src.is_file():
                continue
            ext = src.suffix.lower()
            if ext not in PAGE_MEDIA_ALL_EXT:
                continue
            dest_name = f"{idx:02d}{ext}"
            dest = folder / dest_name
            while dest.exists():
                idx += 1
                dest_name = f"{idx:02d}{ext}"
                dest = folder / dest_name
            shutil.copy2(src, dest)
            added.append(dest_name)
            idx += 1
        if not added:
            raise ValueError("ไม่มีไฟล์รูป/วิดีโอที่รองรับ")
        return added

    def delete_page_media(
        self, kind: str, page_name: str, filenames: List[str]
    ) -> int:
        folder = self.page_media_dir(kind, page_name)
        deleted = 0
        for raw in filenames:
            name = Path(raw).name
            if not name or name in (".", ".."):
                continue
            path = folder / name
            try:
                resolved = path.resolve()
                folder_resolved = folder.resolve()
            except OSError:
                continue
            if resolved.parent != folder_resolved:
                continue
            if path.is_file():
                path.unlink()
                deleted += 1
        return deleted

    # --- setup status ---

    @staticmethod
    def _is_placeholder_sheet(sid: str) -> bool:
        s = (sid or "").strip()
        return (not s) or s.upper().startswith("YOUR_") or s == PLACEHOLDER_SHEET

    @staticmethod
    def _token_looks_real(token: str) -> bool:
        t = (token or "").strip()
        if not t or t == PLACEHOLDER_TOKEN or t.upper().startswith("YOUR_"):
            return False
        return len(t) >= 20

    def check_setup_status(self) -> SetupStatus:
        self.ensure_seeded()
        items: List[StatusItem] = []

        sheet = self.load_sheet_config()
        sid = sheet.get("sheet_id") or ""
        items.append(
            StatusItem(
                "sheet_id",
                not self._is_placeholder_sheet(sid),
                "Google Sheet ID (ไม่ใช่ placeholder)",
                critical=True,
            )
        )
        items.append(
            StatusItem(
                "credentials",
                self.creds_path.is_file(),
                f"Google credentials: {self.creds_path.relative_to(self.root)}",
                critical=True,
            )
        )

        pages = self.load_page_tokens()
        has_page = any(
            self._token_looks_real(p.get("access_token", ""))
            and str(p.get("page_id") or "") not in ("", PLACEHOLDER_PAGE_ID)
            and not str(p.get("page_id") or "").upper().startswith("YOUR_")
            for p in pages
        )
        items.append(
            StatusItem(
                "page_token",
                has_page,
                "อย่างน้อย 1 เพจที่มี Page ID + Access Token จริง",
                critical=True,
            )
        )

        env = self.load_dotenv_map()
        vt = (env.get("WEBHOOK_VERIFY_TOKEN") or "").strip()
        items.append(
            StatusItem(
                "verify_token",
                bool(vt),
                "WEBHOOK_VERIFY_TOKEN ใน .env",
                critical=True,
            )
        )

        wh = self.load_webhook_fields()
        domain = (wh.get("NGROK_DOMAIN") or "").strip()
        domain_ok = bool(domain) and "your-subdomain" not in domain.lower()
        items.append(
            StatusItem(
                "ngrok",
                domain_ok,
                "ngrok domain (user_settings / NGROK_DOMAIN)",
                critical=False,
            )
        )

        items.append(
            StatusItem(
                "env_file",
                self.env_path.is_file(),
                ".env มีไฟล์แล้ว",
                critical=True,
            )
        )

        has_anousith = bool((env.get("ANOUSITH_USER") or "").strip())
        has_hal = bool((env.get("HAL_USER") or "").strip())
        items.append(
            StatusItem(
                "carrier",
                has_anousith or has_hal,
                "บัญชีขนส่ง Anousith/HAL ใน .env (ถ้าใช้ถ่ายบิล)",
                critical=False,
            )
        )

        return SetupStatus(items=items)


def check_setup_status(root: Optional[Path] = None) -> SetupStatus:
    return ConfigIO(root).check_setup_status()
