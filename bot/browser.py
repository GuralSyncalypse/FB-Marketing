"""Vòng đời browser/profile của FacebookBot.

``BrowserMixin`` giữ phần khởi tạo Chrome, khoá profile theo UID, autosave
checkpoint và dọn dẹp khi đóng. Luồng đăng nhập nằm ở ``bot.auth``.
"""

from __future__ import annotations

import json
import os
import threading
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as StandardOptions

from services.cookie_store import normalize_uid
from services.login_flow import login_session
from services.profile_manager import (
    SessionProfile,
    UidMutex,
    dispose_session,
    wait_for_profile_release,
)

from .paths import APP_DIR
from .profiles import get_profile_manager


class BrowserMixin:
    """Khởi tạo/đóng browser và quản lý profile theo UID."""

    _profile_locks = {}

    _profile_locks_guard = threading.Lock()

    def __init__(
        self,
        visualize=False,
        output_path="users.json",
        stop_event=None,
        on_save_batch=None,
        browser_mode="scan",
        profile_mode=None,
    ):
        self.driver = None
        self.user_agent = None
        self.output_path = output_path
        self.stop_event = stop_event

        self.visualize = visualize
        # `scan` giữ tối ưu hiện có; `analysis` ưu tiên trang Facebook hiển thị đủ.
        self.browser_mode = "analysis" if browser_mode == "analysis" else "scan"

        self.on_save_batch = on_save_batch
        self._buffer = []
        self._profile_lock = None
        self._profile_uid = None
        self.last_start_error = None

        # --- Vòng đời profile / session ---
        self.profile_mode = profile_mode
        self._session = None
        self._uid_mutex = None
        self._profile_path = None
        self.data_dir = None
        self.exports_dir = None
        self.log_dir = None

    def _acquire_profile_lock(self, uid: str) -> bool:
        """Chỉ cho phép một browser session dùng cùng profile UID trong một app."""
        normalized_uid = str(uid).strip()
        if not normalized_uid:
            print("[Profile Lock] Invalid UID.")
            return False

        with self._profile_locks_guard:
            lock = self._profile_locks.setdefault(normalized_uid, threading.Lock())

        if not lock.acquire(blocking=False):
            print(f"[{normalized_uid}] [Profile Lock] UID is already in use.")
            return False

        self._profile_lock = lock
        self._profile_uid = normalized_uid
        return True

    def _release_profile_lock(self):
        """Nhả profile lock do chính instance bot này sở hữu."""
        lock = self._profile_lock
        uid = self._profile_uid
        self._profile_lock = None
        self._profile_uid = None

        if lock:
            try:
                lock.release()
                print(f"[{uid}] [Profile Lock] Released.")
            except RuntimeError:
                pass

    def get_start_error_message(self) -> str:
        messages = {
            "profile_in_use": "UID đang có tác vụ khác. Vui lòng chờ tác vụ hiện tại hoàn tất.",
            "invalid_uid": "UID không hợp lệ.",
            "missing_cookies": "Chưa có cookie cho UID này. Hãy kết nối Extension để gửi lại.",
            "account_mismatch": (
                "Profile đang đăng nhập sai tài khoản so với UID nhận từ Extension. "
                "Hãy reset profile hoặc đăng nhập lại."
            ),
            "profile_prepare_failed": "Không chuẩn bị được profile Chrome. Xem log để biết chi tiết.",
            "browser_start_failed": "Không khởi động được Chrome (profile có thể đang bị giữ).",
            "browser_navigation_failed": "Không truy cập được Facebook. Kiểm tra mạng/proxy.",
            "login_failed": "Đăng nhập thất bại / Checkpoint!",
        }
        return messages.get(self.last_start_error, "Đăng nhập thất bại!")

    def _init_data_dirs(self, uid: str):
        """Mỗi tài khoản có vùng dữ liệu riêng: data/<uid>/..., logs/<uid>/..."""
        self.data_dir = os.path.join(APP_DIR, "data", uid, "raw")
        self.exports_dir = os.path.join(APP_DIR, "data", uid, "exports")
        self.log_dir = os.path.join(APP_DIR, "logs", uid)
        for path in (self.data_dir, self.exports_dir, self.log_dir):
            os.makedirs(path, exist_ok=True)

    def _flush(self, file_name=None):
        """Gửi dữ liệu trong buffer đi lưu và xả rỗng buffer."""
        if self._buffer and self.on_save_batch:
            self.on_save_batch(self._buffer, file_name)
            self._buffer = []

    def is_stopped(self):
        """Hàm phụ trợ kiểm tra xem người dùng đã bấm nút Dừng hay chưa."""
        return self.stop_event is not None and self.stop_event.is_set()

    def _save_checkpoint(self):
        """Ghi dữ liệu hiện tại xuống đĩa (Autosave - Ghi đè file mới)."""
        try:
            temp_path = self.output_path + '.tmp'  # Tạo file tạm để ghi trước

            # Lấy danh sách thành viên trực tiếp từ bộ nhớ đang cào
            data = list(getattr(self, "collected", {}).values())

            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(
                    data,
                    f,
                    ensure_ascii=False,
                    indent=4,
                )

            # Đổi tên file an toàn (ghi đè file chính) tránh mất dữ liệu nếu bị ngắt điện
            os.replace(temp_path, self.output_path)
            print(
                f"💾 [Autosave] Đã lưu an toàn {len(data)} thành viên vào đĩa ({self.output_path})."
            )
        except Exception as e:
            print(f"⚠️ Không thể lưu checkpoint: {e}")

    def start_browser(
        self,
        uid: str,
        user_agent: str = None,
        proxy: str = None,
        session: SessionProfile = None,
    ) -> bool:
        """Khởi tạo Chrome (Selenium Standard) trên profile của UID.

        `session` do ProfileManager tạo (persistent/fresh/reset). Nếu bỏ trống,
        bot tự lấy profile theo cấu hình `storage/config.json`.
        """
        self.last_start_error = None

        try:
            uid = normalize_uid(uid)
        except ValueError:
            self.last_start_error = "invalid_uid"
            return False

        if not self._acquire_profile_lock(uid):
            self.last_start_error = "profile_in_use"
            return False

        # Khóa liên process: hai bản app trên cùng máy không mở trùng profile.
        mutex = UidMutex(uid)
        if not mutex.acquired:
            self.last_start_error = "profile_in_use"
            self._release_profile_lock()
            return False
        self._uid_mutex = mutex

        # --- Chuẩn bị profile (dọn chrome mồ côi + seed cookie) ---
        try:
            profile = session or get_profile_manager().prepare(uid, self.profile_mode)
        except Exception as error:
            print(f"[{uid}] Không chuẩn bị được profile: {error}")
            self._abort_start("profile_prepare_failed")
            return False

        self._session = profile
        self._profile_path = str(profile.path)
        self.user_agent = user_agent
        self._init_data_dirs(uid)

        profile_path = self._profile_path
        cookie_file_path = os.path.join(profile_path, "cookies.json")

        if not os.path.exists(cookie_file_path) and not profile.is_persistent:
            print(
                f"[{uid}] Profile mới nhưng chưa có cookie tại "
                f"storage/cookies/{uid}.json"
            )
            self._abort_start("missing_cookies")
            return False

        ua = user_agent or getattr(self, "user_agent", None)
        visualize = getattr(self, "visualize", True)

        options = StandardOptions()
        options.add_argument(f"--user-data-dir={profile_path}")
        options.add_argument("--disable-blink-features=AutomationControlled")

        if ua:
            options.add_argument(f"--user-agent={ua}")
        if proxy:
            options.add_argument(f"--proxy-server={proxy}")

        # Tối ưu tài nguyên & Anti-Throttling
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-logging")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-renderer-backgrounding")

        # Profile mới không được mở trang welcome của Chrome.
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")

        # Tác vụ tự động không cần media để giảm băng thông/RAM. Giá trị
        # này được Chrome lưu vào profile, vì vậy analysis phải ghi đè rõ
        # về 1 thay vì chỉ bỏ qua preference.
        image_setting = 2 if self.browser_mode == "scan" else 1
        prefs = {"profile.managed_default_content_settings.images": image_setting}
        options.add_experimental_option("prefs", prefs)

        # Headless/UI
        if not visualize:
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--headless=new")
        else:
            options.add_argument("--start-maximized")

        # 3. KHỞI TẠO DRIVER
        print(f"[{uid}] [Selenium] Khởi tạo Chrome (profile={profile.mode.value})...")
        self.driver = None
        try:
            self.driver = webdriver.Chrome(options=options)
        except Exception as e:
            print(f"[{uid}] ❌ Lỗi khởi tạo Chrome Driver: {e}")
            self._abort_start("browser_start_failed")
            return False

        # 4. TRUY CẬP VÀ XỬ LÝ ĐĂNG NHẬP
        try:
            result = login_session(
                self.driver,
                uid,
                cookie_file_path,
                store=get_profile_manager().cookies,
            )
        except Exception as e:
            print(f"[{uid}] ❌ Lỗi trong quá trình điều hướng/truy cập: {e}")
            self._abort_start("browser_navigation_failed")
            return False

        if not result.ok:
            print(f"[{uid}] Đăng nhập thất bại / Checkpoint / Sai tài khoản!")
            self.last_start_error = result.error or "login_failed"
            self.close()
            return False

        return True

    def _abort_start(self, error: str):
        """Đặt lỗi rồi dọn sạch driver/profile/lock."""
        self.last_start_error = error
        self.close()

    def close(self):
        """Đóng browser, chờ Chrome thoát hẳn rồi mới nhả profile.

        Thứ tự quan trọng: nếu nhả lock trước khi chrome.exe chết, task kế tiếp
        sẽ mở lại đúng profile đó và gặp lỗi DevToolsActivePort.
        """
        session = self._session
        profile_path = self._profile_path

        try:
            if self.driver:
                try:
                    self.driver.quit()
                except Exception as error:
                    print(f"[Close] driver.quit lỗi: {error}")
                self.driver = None

            if profile_path and os.path.isdir(profile_path):
                wait_for_profile_release(profile_path, timeout=6)
        finally:
            if session is not None:
                dispose_session(session)
            self._session = None
            self._profile_path = None
            self._release_uid_mutex()
            self._release_profile_lock()

    def _release_uid_mutex(self):
        mutex = self._uid_mutex
        self._uid_mutex = None
        if mutex is not None:
            mutex.release()
