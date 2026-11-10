"""Kho cookie Facebook theo UID — tách khỏi Chrome profile.

Nguyên tắc: cookie là nguồn sự thật, profile Chrome chỉ là bản cache runtime.
Nhờ vậy có thể tạo profile mới từ đầu (fresh) hoặc tạo lại profile (reset)
mà không mất đăng nhập.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

_REQUIRED_COOKIES = ("c_user", "xs")


def normalize_uid(uid: object) -> str:
    """Chuẩn hoá UID và chặn path traversal (UID Facebook chỉ gồm chữ số)."""
    value = str(uid or "").strip()
    if not value or not value.isdigit():
        raise ValueError(f"UID không hợp lệ: {uid!r}")
    return value


def _normalize_cookie(cookie: object) -> dict | None:
    if not isinstance(cookie, dict):
        return None

    name = cookie.get("name")
    value = cookie.get("value")
    if not name or value is None:
        return None

    cleaned = {
        "name": str(name),
        "value": str(value),
        "domain": cookie.get("domain") or ".facebook.com",
        "path": cookie.get("path") or "/",
        "secure": bool(cookie.get("secure", True)),
    }

    # Extension gửi `expirationDate`, Selenium trả `expiry` → chuẩn hoá về một dạng.
    expiry = cookie.get("expirationDate", cookie.get("expiry"))
    if expiry is not None:
        try:
            cleaned["expirationDate"] = float(expiry)
        except (TypeError, ValueError):
            pass

    if cookie.get("httpOnly"):
        cleaned["httpOnly"] = True

    return cleaned


def _normalize_cookie_list(cookies: object) -> list[dict]:
    if isinstance(cookies, dict):
        cookies = [cookies]
    if not isinstance(cookies, (list, tuple)):
        return []
    return [c for c in (_normalize_cookie(item) for item in cookies) if c]


class CookieStore:
    """Lưu/đọc cookie tại `storage/cookies/<uid>.json`."""

    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.root = self.base_dir / "storage" / "cookies"

    def path(self, uid) -> Path:
        return self.root / f"{normalize_uid(uid)}.json"

    def exists(self, uid) -> bool:
        try:
            return self.path(uid).exists()
        except ValueError:
            return False

    def load(self, uid) -> list[dict]:
        try:
            path = self.path(uid)
        except ValueError:
            return []
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            print(f"[CookieStore] Không đọc được {path.name}: {error}")
            return []
        return _normalize_cookie_list(raw)

    def save(self, uid, cookies) -> Path:
        """Ghi cookie nguyên tử (tmp + os.replace), an toàn khi đọc song song."""
        path = self.path(uid)
        cleaned = _normalize_cookie_list(cookies)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, path)
        return path

    def is_usable(self, uid) -> bool:
        names = {cookie["name"] for cookie in self.load(uid)}
        return all(name in names for name in _REQUIRED_COOKIES)

    def seed(self, uid, profile_dir, overwrite_if_newer: bool = True) -> bool:
        """Copy cookie nguồn vào profile Chrome để `_inject_cookies` sử dụng."""
        try:
            src = self.path(uid)
        except ValueError:
            return False
        if not src.exists():
            return False

        dst = Path(profile_dir) / "cookies.json"
        dst.parent.mkdir(parents=True, exist_ok=True)

        if overwrite_if_newer and dst.exists():
            if dst.stat().st_mtime >= src.stat().st_mtime:
                return False

        shutil.copy2(src, dst)
        return True

    def updated_at(self, uid) -> float | None:
        try:
            path = self.path(uid)
        except ValueError:
            return None
        return path.stat().st_mtime if path.exists() else None
