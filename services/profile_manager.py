"""Quản lý profile Chrome theo UID + chế độ khởi tạo.

Chế độ:
- `persistent`: dùng `profiles/<uid>` (mặc định, giữ nguyên profile đang có).
- `fresh`     : tạo `storage/runtime/<uid>-<time>-<rand>`, seed cookie, xoá sau khi xong.
- `reset`     : backup profile bền thành `<uid>.bak-<time>` rồi tạo lại.

Mọi cài đặt đọc từ `storage/config.json` để UI chỉ cần sửa file này.
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from services.cookie_store import CookieStore, normalize_uid

# Chrome/Chromium tạo các file này khi profile đang được giữ.
LOCK_FILES = ("SingletonLock", "SingletonSocket", "SingletonCookie", "lockfile")

DEFAULT_CONFIG = {
    "profile_mode": "persistent",
    "max_browsers": 1,
    "demo_mode": False,
}


# ================= CẤU HÌNH =================
def config_path(base_dir) -> Path:
    return Path(base_dir) / "storage" / "config.json"


def load_config(base_dir) -> dict:
    config = dict(DEFAULT_CONFIG)
    path = config_path(base_dir)
    try:
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                config.update(raw)
    except (OSError, json.JSONDecodeError) as error:
        print(f"[Config] Không đọc được config.json: {error}")
    return config


def save_config(base_dir, **values) -> dict:
    config = load_config(base_dir)
    config.update({key: value for key, value in values.items() if value is not None})

    path = config_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return config


# ================= MODE & SESSION =================
class ProfileMode(str, Enum):
    PERSISTENT = "persistent"
    FRESH = "fresh"
    RESET = "reset"

    @classmethod
    def parse(cls, value, default=None):
        try:
            return cls(str(value).strip().lower())
        except (ValueError, AttributeError, TypeError):
            return default


@dataclass(frozen=True)
class SessionProfile:
    uid: str
    mode: ProfileMode
    path: Path
    cleanup: bool

    @property
    def is_persistent(self) -> bool:
        return not self.cleanup


# ================= KHOÁ LIÊN PROCESS THEO UID =================
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if os.name == "nt" else None


class UidMutex:
    """Mutex theo UID, tự nhả khi process kết thúc.

    Bổ sung cho lock trong bộ nhớ: hai bản app độc lập trên cùng máy vẫn biết nhau.
    """

    def __init__(self, uid):
        self.uid = uid
        self._handle = None
        self.acquired = False

        if _kernel32 is None:
            self.acquired = True
            return

        handle = _kernel32.CreateMutexW(None, False, f"H2FB_profile_{uid}")
        already_exists = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS

        if not handle or already_exists:
            if handle:
                _kernel32.CloseHandle(handle)
            self.acquired = False
            return

        self._handle = handle
        self.acquired = True

    def release(self):
        if self._handle and _kernel32 is not None:
            try:
                _kernel32.CloseHandle(self._handle)
            except Exception:
                pass
        self._handle = None
        self.acquired = False


# ================= QUÉT / DỌN PROCESS CHROME =================
def _run_hidden(args, timeout):
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=creationflags,
    )


def _user_data_dir_from_command_line(command_line: str) -> str | None:
    """Bóc `--user-data-dir=...` khỏi command line Chrome rồi chuẩn hoá path."""
    marker = "--user-data-dir="
    index = command_line.lower().find(marker)
    if index < 0:
        return None

    value = command_line[index + len(marker):]
    if value.startswith('"'):
        value = value[1:].split('"', 1)[0]
    else:
        value = value.split(" ", 1)[0]

    value = value.strip().strip('"').rstrip("\\/")
    if not value:
        return None
    return os.path.normcase(os.path.normpath(value))


def pids_using_profile(profile_path, timeout: int = 20) -> list[int]:
    """Trả về PID của chrome.exe đang mở đúng thư mục profile.

    So khớp tuyệt đối `--user-data-dir`, không dùng substring: `profiles/615`
    không được coi là trùng với `profiles/6157`.
    """
    if os.name != "nt":
        return []

    target = os.path.normcase(
        os.path.normpath(os.path.abspath(str(profile_path))).rstrip("\\/")
    )

    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        raw = _run_hidden(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            timeout,
        ).stdout.strip()
    except Exception as error:
        print(f"[Profile] Không quét được process chrome.exe: {error}")
        return []

    if not raw:
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    if isinstance(data, dict):
        data = [data]

    pids = []
    for process in data:
        command_line = process.get("CommandLine") or ""
        used_dir = _user_data_dir_from_command_line(command_line)
        if used_dir and used_dir.rstrip("\\/") == target:
            try:
                pids.append(int(process.get("ProcessId")))
            except (TypeError, ValueError):
                continue
    return pids


def kill_profile_processes(profile_path, wait_seconds: int = 8) -> bool:
    """Kill toàn bộ cây process đang giữ profile. Trả True nếu đã sạch."""
    pids = pids_using_profile(profile_path)
    if not pids:
        return True

    print(f"[Profile] Kill {len(pids)} process còn giữ {profile_path}: {pids}")
    for pid in pids:
        try:
            _run_hidden(["taskkill", "/PID", str(pid), "/T", "/F"], 20)
        except Exception as error:
            print(f"[Profile] taskkill {pid} lỗi: {error}")

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        time.sleep(0.4)
        if not pids_using_profile(profile_path):
            return True
    return not pids_using_profile(profile_path)


def clear_stale_profile_locks(profile_path):
    """Chỉ gọi sau khi chắc chắn không còn chrome.exe dùng profile."""
    for name in LOCK_FILES:
        try:
            (Path(profile_path) / name).unlink()
        except FileNotFoundError:
            continue
        except OSError as error:
            print(f"[Profile] Không xoá được {name}: {error}")


def ensure_profile_available(profile_path):
    """Dọn chrome mồ côi + lock file cũ trước khi mở profile.

    Chỉ gọi khi caller đã giữ UID mutex, nên mọi chrome.exe tìm thấy
    chắc chắn là process mồ côi từ lần chạy trước.
    """
    path = Path(profile_path)
    if not path.exists():
        return True

    pids = pids_using_profile(path)
    if pids:
        if not kill_profile_processes(path, wait_seconds=6):
            print(
                f"[Profile] chrome.exe vẫn giữ {path} sau khi kill. "
                "Không xoá lock file để tránh mở sai trạng thái."
            )
            return False
    clear_stale_profile_locks(path)
    return True


def wait_for_profile_release(profile_path, timeout: float = 6.0) -> bool:
    """Chờ Chrome thoát sạch sau khi quit; quá hạn thì kill rồi dọn lock."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pids_using_profile(profile_path):
            clear_stale_profile_locks(profile_path)
            return True
        time.sleep(0.4)

    kill_profile_processes(profile_path, wait_seconds=8)
    clear_stale_profile_locks(profile_path)
    return not pids_using_profile(profile_path)


def dispose_session(session: SessionProfile | None):
    if session and session.cleanup:
        shutil.rmtree(str(session.path), ignore_errors=True)


# ================= PROFILE MANAGER =================
class ProfileManager:
    def __init__(self, base_dir, cookie_store: CookieStore | None = None):
        self.base_dir = Path(base_dir)
        self.cookies = cookie_store or CookieStore(self.base_dir)
        # Giữ đúng vị trí profile cũ để không phải đăng nhập lại.
        self.persistent_root = self.base_dir / "profiles"
        self.runtime_root = self.base_dir / "storage" / "runtime"

    def resolve_mode(self, override=None) -> ProfileMode:
        if override:
            mode = ProfileMode.parse(override)
            if mode is not None:
                return mode
        return ProfileMode.parse(
            load_config(self.base_dir).get("profile_mode"),
            ProfileMode.PERSISTENT,
        )

    def prepare(self, uid, mode=None) -> SessionProfile:
        uid = normalize_uid(uid)
        mode = self.resolve_mode(mode)

        if mode is ProfileMode.RESET:
            self._backup_persistent(uid)
            mode = ProfileMode.PERSISTENT

        if mode is ProfileMode.PERSISTENT:
            path = self.persistent_root / uid
            path.mkdir(parents=True, exist_ok=True)
            if not ensure_profile_available(path):
                raise RuntimeError(
                    "Profile vẫn đang bị chrome.exe giữ. Hãy đóng Chrome rồi thử lại."
                )
            self.cookies.seed(uid, path, overwrite_if_newer=True)
            return SessionProfile(uid, ProfileMode.PERSISTENT, path, cleanup=False)

        # FRESH: profile mới tinh, chỉ mang cookie từ kho nguồn.
        path = self.runtime_root / (
            f"{uid}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        )
        path.mkdir(parents=True, exist_ok=True)
        self.cookies.seed(uid, path, overwrite_if_newer=False)
        return SessionProfile(uid, ProfileMode.FRESH, path, cleanup=True)

    def reset(self, uid) -> Path | None:
        """Tạo lại profile bền. Trả về đường dẫn backup (nếu có)."""
        uid = normalize_uid(uid)
        mutex = UidMutex(uid)
        if not mutex.acquired:
            raise RuntimeError("UID đang có tác vụ khác. Không thể reset profile.")

        try:
            # Không cho đổi tên profile khi chrome.exe cũ còn đang ghi vào đó.
            stale_path = self.persistent_root / uid
            if stale_path.exists():
                if not kill_profile_processes(stale_path, wait_seconds=5):
                    raise RuntimeError(
                        "Chrome vẫn đang dùng profile này. Hãy đóng Chrome rồi thử lại."
                    )
                clear_stale_profile_locks(stale_path)

            backup = self._backup_persistent(uid)
            path = self.persistent_root / uid
            path.mkdir(parents=True, exist_ok=True)
            self.cookies.seed(uid, path, overwrite_if_newer=False)
            return backup
        finally:
            mutex.release()

    def _backup_persistent(self, uid) -> Path | None:
        path = self.persistent_root / uid
        if not path.exists():
            return None

        backup = self.persistent_root / (
            f"{uid}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        )
        try:
            path.rename(backup)
        except OSError as error:
            raise RuntimeError(f"Không thể backup profile: {error}") from error

        print(f"[Profile] Đã backup {path.name} → {backup.name}")
        return backup

    def dispose(self, session: SessionProfile | None):
        dispose_session(session)

    def cleanup_runtime(self):
        """Dọn các profile runtime còn sót sau khi app bị kill."""
        if not self.runtime_root.exists():
            return
        for path in self.runtime_root.iterdir():
            if path.is_dir():
                shutil.rmtree(str(path), ignore_errors=True)
