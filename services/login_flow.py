"""Luồng đăng nhập Facebook trên một Selenium driver.

Module chỉ làm việc với driver, file cookie và một cookie store (duck typing),
không biết tới `FacebookBot`/`ProfileManager`. Nhờ vậy có thể kiểm thử bằng
driver giả mà không cần mở Chrome.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

from selenium.webdriver.support.ui import WebDriverWait

FACEBOOK_HOME = "https://www.facebook.com"
FACEBOOK_ME = "https://www.facebook.com/me"
COOKIE_FILE_NAME = "cookies.json"

# Các URL Facebook dùng để chặn hoặc yêu cầu xác minh phiên.
VERIFICATION_PATH_MARKERS = (
    "/login",
    "/checkpoint",
    "/recover",
    "/two_step_verification",
)

# Selenium chỉ chấp nhận các trường này khi add_cookie.
_ALLOWED_COOKIE_FIELDS = {
    "name",
    "value",
    "domain",
    "path",
    "expiry",
    "secure",
    "httpOnly",
}


@dataclass(frozen=True)
class LoginResult:
    """Kết quả một bước đăng nhập.

    `error` dùng đúng mã lỗi mà `FacebookBot.get_start_error_message()` hiểu.
    `fatal=True` nghĩa là browser đang ở trạng thái hỏng và nên được đóng.
    """

    ok: bool
    error: str | None = None
    fatal: bool = False


def read_driver_cookies(driver) -> dict[str, str]:
    """Đọc cookie hiện tại của driver dưới dạng {name: value}."""
    return {
        cookie.get("name"): cookie.get("value")
        for cookie in driver.get_cookies()
    }


def session_matches_uid(driver, uid: str) -> bool:
    """Kiểm tra nhanh phiên hiện tại có đúng UID không (không điều hướng)."""
    try:
        cookies = read_driver_cookies(driver)
    except Exception:
        return False
    return cookies.get("c_user") == str(uid) and bool(cookies.get("xs"))


def inject_cookies(driver, file_path: str) -> bool:
    """Nạp cookie từ file JSON vào browser đang mở."""
    if not os.path.exists(file_path):
        print(f"Không tìm thấy file cookie tại: {file_path}")
        return False

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            cookies = json.load(file)

        driver.get(FACEBOOK_HOME)
        time.sleep(1)

        success_count = 0
        for cookie in cookies:
            cookie_dict = {
                "name": cookie.get("name"),
                "value": cookie.get("value"),
                "domain": cookie.get("domain", ".facebook.com"),
                "path": cookie.get("path", "/"),
                "secure": cookie.get("secure", True),
            }

            expiry = cookie.get("expirationDate", cookie.get("expiry"))
            if expiry is not None:
                try:
                    cookie_dict["expiry"] = int(float(expiry))
                except (ValueError, TypeError):
                    pass

            try:
                driver.add_cookie(cookie_dict)
                success_count += 1
            except Exception as cookie_error:
                print(f"[Cookie] Bỏ qua cookie lỗi: {cookie_error}")

        driver.refresh()
        time.sleep(2)
        print(f"Đã nạp thành công {success_count}/{len(cookies)} Cookie.")
        return True
    except Exception as error:
        print(f"Lỗi khi đọc/nạp Cookie: {error}")
        return False


def verify_login(driver, expected_uid: str | None = None) -> LoginResult:
    """Xác minh phiên đăng nhập và (tuỳ chọn) đúng tài khoản."""
    if driver is None:
        return LoginResult(False)

    try:
        cookies = read_driver_cookies(driver)
    except Exception:
        return LoginResult(False)

    print(f"Cookie hiện có: {sorted(cookies)}")

    # Fast fail
    if "c_user" not in cookies or "xs" not in cookies:
        return LoginResult(False)

    # Không cho phép chạy nhầm tài khoản khi profile còn session người khác.
    if expected_uid and str(cookies["c_user"]) != str(expected_uid):
        print(
            f"[Login] Cookie thuộc UID {cookies['c_user']} "
            f"nhưng cần {expected_uid}."
        )
        return LoginResult(False, "account_mismatch")

    # Verify session
    try:
        driver.get(FACEBOOK_ME)
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except Exception as error:
        print(f"[Login] Không xác minh được phiên: {error}")
        return LoginResult(False)

    current_url = (driver.current_url or "").lower()
    if any(marker in current_url for marker in VERIFICATION_PATH_MARKERS):
        print(f"[Login] Bị chuyển hướng xác minh: {current_url}")
        return LoginResult(False)

    return LoginResult(True)


def login_with_cookies(driver, uid: str, cookies: list) -> LoginResult:
    """Nạp danh sách cookie cho trước rồi xác minh đăng nhập."""
    if driver is None:
        print(f"[UID: {uid}] 🚨 Khởi tạo Driver thất bại (driver is None).")
        return LoginResult(False)

    try:
        # Đi tới Facebook trước khi add cookie.
        driver.get(FACEBOOK_HOME)
        time.sleep(2)

        for cookie in cookies:
            filtered = {
                key: value
                for key, value in cookie.items()
                if key in _ALLOWED_COOKIE_FIELDS
            }
            try:
                print(f"Adding {filtered}")
                driver.add_cookie(filtered)
            except Exception:
                print(f"Failed: {filtered}")

        # Refresh để áp dụng cookie và vào trạng thái đăng nhập.
        driver.refresh()
        time.sleep(3)

        print(
            f"[UID: {uid}] Inject cookie hoàn tất. "
            f"Tiêu đề trang: {driver.title}"
        )

        result = verify_login(driver)
        if result.ok:
            print("Hoàn tất đăng nhập!")
        return result

    except Exception as error:
        print(f"[UID: {uid}] Gặp lỗi trong quá trình inject cookie: {error}")
        return LoginResult(False, "login_failed", fatal=True)


def persist_cookies(
    driver,
    store,
    uid: str,
    *,
    quiet: bool = False,
) -> str | None:
    """Ghi cookie hiện tại của browser về kho nguồn.

    `store` chỉ cần có method `save(uid, cookies) -> path`.
    Trả về đường dẫn đã lưu, hoặc None nếu không đọc/ghi được.
    """
    try:
        cookies = driver.get_cookies()
    except Exception as error:
        print(f"[{uid}] Không đọc được cookie từ browser: {error}")
        return None

    try:
        path = store.save(uid, cookies)
    except Exception as error:
        print(f"[{uid}] Không ghi được cookie nguồn: {error}")
        return None

    if not quiet:
        print(f"[{uid}] Đã cập nhật cookie nguồn: {path}")
    return str(path)


def login_session(
    driver,
    uid: str,
    cookie_file_path: str,
    store=None,
) -> LoginResult:
    """Đảm bảo driver đang có phiên đăng nhập đúng `uid`.

    Luồng: mở Facebook → dùng lại phiên nếu cookie khớp UID, ngược lại nạp
    cookie từ file → xác minh → lưu cookie về kho nguồn.
    """
    driver.get(FACEBOOK_HOME)
    time.sleep(2)

    # Chỉ nạp cookie khi phiên hiện tại không phải của đúng UID.
    if session_matches_uid(driver, uid):
        print(f"[{uid}] Profile đã có phiên đăng nhập đúng UID.")
    else:
        print(
            f"[{uid}] Chưa có phiên hợp lệ cho UID này. "
            f"Nạp cookie từ {cookie_file_path}..."
        )
        inject_cookies(driver, cookie_file_path)

    result = verify_login(driver, expected_uid=uid)
    if not result.ok:
        return result

    if store is not None:
        persist_cookies(driver, store, uid)
    return result
