"""Đăng nhập/cookie của FacebookBot.

``AuthMixin`` chỉ là lớp mỏng nối ``services.login_flow`` với state của bot
(``driver``, ``_session``, ``last_start_error``).
"""

from __future__ import annotations

from services.login_flow import (
    inject_cookies,
    login_with_cookies as login_with_cookies_flow,
    persist_cookies,
    session_matches_uid,
    verify_login,
)

from .profiles import get_profile_manager


class AuthMixin:
    """Xác minh phiên và nạp/lưu cookie đăng nhập."""

    def _inject_cookies(self, driver_instance, file_path) -> bool:
        """Nạp cookie từ file vào browser đang mở."""
        return inject_cookies(driver_instance, file_path)

    def _session_cookies_ok(self, uid: str) -> bool:
        """Kiểm tra nhanh cookie hiện tại có thuộc đúng UID không (không điều hướng)."""
        return session_matches_uid(self.driver, uid)

    def _persist_cookies(self, uid: str):
        """Ghi cookie từ browser về kho nguồn để lần chạy sau dùng được."""
        persist_cookies(self.driver, get_profile_manager().cookies, uid)

    def save_cookies(self):
        """Ghi cookie hiện tại của browser về kho nguồn."""
        if not self.driver or not self._session:
            print("❌ Save cookies failed: browser chưa được khởi tạo")
            return False

        path = persist_cookies(
            self.driver,
            get_profile_manager().cookies,
            self._session.uid,
            quiet=True,
        )
        if path is None:
            print("❌ Save cookies failed")
            return False

        print(f"🍪 Cookies updated → {path}")
        return True

    def is_logged_in(self, expected_uid: str = None):
        """Xác minh phiên đăng nhập và (tuỳ chọn) đúng tài khoản."""
        result = verify_login(self.driver, expected_uid=expected_uid)
        if result.error:
            self.last_start_error = result.error
        return result.ok

    def login_with_cookies(self, uid: str, cookies: list) -> bool:
        """Nạp cookie để đăng nhập Facebook trên browser đã mở."""
        print(f"[UID: {uid}] Đang khởi tạo trình duyệt...")
        result = login_with_cookies_flow(self.driver, uid, cookies)
        if result.fatal:
            self.close()  # Đóng driver ngay nếu lỗi giữa chừng
        return result.ok
