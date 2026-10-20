from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from concurrent.futures import ThreadPoolExecutor
from selenium.webdriver.chrome.options import Options as StandardOptions
from selenium.webdriver.support.ui import WebDriverWait
import undetected_chromedriver as uc
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from openpyxl import Workbook
from queue import Queue, Empty
import threading
import random
import time
import pickle
import os
import re
import json
import urllib.parse
import pandas as pd
import sys

# Console Windows có thể dùng cp1252 khi stdout bị redirect; log tiếng Việt
# không được phép làm sập tiến trình.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) # Thư mục /app

# PyInstaller --onefile giải nén code vào thư mục tạm. Dữ liệu chạy (profile,
# cookie, export, log) phải nằm cạnh file exe thì mới còn sau khi thoát.
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = BASE_DIR

from services.cookie_store import normalize_uid
from services.profile_manager import (
    ProfileManager,
    ProfileMode,
    SessionProfile,
    UidMutex,
    dispose_session,
    kill_profile_processes,
    wait_for_profile_release,
)

_DEFAULT_PROFILE_MANAGER = None
_DEFAULT_PROFILE_MANAGER_LOCK = threading.Lock()


def get_profile_manager() -> ProfileManager:
    """Singleton quản lý profile/cookie trong phạm vi một process."""
    global _DEFAULT_PROFILE_MANAGER
    with _DEFAULT_PROFILE_MANAGER_LOCK:
        if _DEFAULT_PROFILE_MANAGER is None:
            _DEFAULT_PROFILE_MANAGER = ProfileManager(APP_DIR)
        return _DEFAULT_PROFILE_MANAGER


def convert_to_spreadsheet(json_filepath, output_filename=None, output_dir=None):
    """Đọc file .json hoặc .jsonl, xử lý dữ liệu và tự động xuất ra đúng thư mục:

    - Nếu đầu ra là CSV  -> lưu vào './data/processed/csv/'
    - Nếu đầu ra là XLSX -> lưu vào './data/processed/excel/'
    """

    def parse_contribution_score(score_str):
        """Trích xuất số từ chuỗi contribution_score, mặc định là 0 nếu null hoặc rỗng."""
        if not score_str:
            return 0
        match = re.search(r"\d+", str(score_str))
        return int(match.group()) if match else 0

    def parse_boolean_status(status_str, positive_value):
        """Chuyển đổi trạng thái text sang Boolean:

        - Nếu đúng positive_value -> True
        - Nếu null / None / rỗng -> None (Để trống trong Excel/CSV)
        - Nếu là trạng thái ngược lại -> False
        """
        if status_str is None or status_str == "":
            return None
        elif status_str == positive_value:
            return True
        return False

    # 0. KIỂM TRA FILE ĐẦU VÀO
    if not os.path.exists(json_filepath):
        print(f"❌ Lỗi: Không tìm thấy file '{json_filepath}'")
        return

    # Tự động tạo tên file xuất ra nếu người dùng không truyền vào
    base_name = os.path.splitext(os.path.basename(json_filepath))[0]
    if not output_filename:
        output_filename = f"{base_name}_cleaned.csv"  # Mặc định là CSV

    # ---------------------------------------------------------
    # 1. TÍNH TOÁN VÀ TẠO THƯ MỤC ĐẦU RA (DATA/PROCESSED/...)
    # ---------------------------------------------------------
    file_ext = os.path.splitext(output_filename)[1].lower()

    if output_dir:
        final_output_dir = output_dir
    elif file_ext == ".csv":
        final_output_dir = os.path.join(APP_DIR, "data", "processed", "csv")
    elif file_ext == ".xlsx":
        final_output_dir = os.path.join(APP_DIR, "data", "processed", "excel")
    else:
        raise ValueError(
            "❌ Định dạng file không hỗ trợ. Vui lòng chọn file có đuôi .xlsx hoặc .csv"
        )

    # Tự động tạo folder nếu chưa tồn tại
    os.makedirs(final_output_dir, exist_ok=True)

    # Đường dẫn file hoàn chỉnh
    final_output_path = os.path.join(final_output_dir, output_filename)

    # ---------------------------------------------------------
    # 2. ĐỌC FILE .JSON / .JSONL
    # ---------------------------------------------------------
    items = []
    with open(json_filepath, "r", encoding="utf-8") as f:
        if json_filepath.endswith(".jsonl"):
            items = [json.loads(line) for line in f if line.strip()]
        else:
            data = json.load(f)
            items = data if isinstance(data, list) else [data]

    # ---------------------------------------------------------
    # 3. XỬ LÝ TỪNG ĐỐI TƯỢNG
    # ---------------------------------------------------------
    processed_rows = []
    for item in items:
        row = {
            "user_id": str(item.get("id") or item.get("user_id") or ""),
            "name": item.get("name", ""),
            "url": item.get("url") or item.get("link") or "",
            "avatar": item.get("avatar", ""),
            "bio": item.get("bio", ""),
            "follower_count": item.get("follower_count", 0),
            "is_verified": item.get("is_verified", False),
            "category": item.get("category", ""),
            # Các trường xử lý đặc biệt
            "contribution_score": parse_contribution_score(
                item.get("contribution_score")
            ),
            "friendship_status": parse_boolean_status(
                item.get("friendship_status"), "CAN_REQUEST"
            ),
            "subscribe_status": parse_boolean_status(
                item.get("subscribe_status"), "CAN_SUBSCRIBE"
            ),
            "membership_id": str(item.get("membership_id") or ""),
            "join_status_text": item.get("join_status_text", ""),
            "added_by_id": str(item.get("added_by_id") or ""),
            "added_by_name": item.get("added_by_name", ""),
            "added_by_url": item.get("added_by_url", ""),
        }
        processed_rows.append(row)

    # ---------------------------------------------------------
    # 4. XUẤT RA DATAFRAME & LƯU VÀO ĐÚNG FOLDER PROCESSED
    # ---------------------------------------------------------
    df = pd.DataFrame(processed_rows)

    if file_ext == ".csv":
        df.to_csv(
            final_output_path, index=False, encoding="utf-8-sig", na_rep=""
        )
    elif file_ext == ".xlsx":
        df.to_excel(final_output_path, index=False, engine="openpyxl")

    print(
        f"✅ Đã chuyển đổi {len(df)} dòng thành công!"
        f"\n📍 File được lưu tại: {final_output_path}"
    )

class FacebookBot:
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
        driver_type: str = "undetected",
        session: SessionProfile = None,
    ) -> bool:
        """Khởi tạo Chrome trên profile của UID.

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

        mode = driver_type or "undetected"
        ua = user_agent or getattr(self, "user_agent", None)
        visualize = getattr(self, "visualize", True)

        # --- HÀM TẠO OPTIONS (dùng chung UC và Standard) ---
        def _build_options(is_standard=False):
            if is_standard:
                options = StandardOptions()
                options.add_argument(f"--user-data-dir={profile_path}")
                options.add_argument(
                    "--disable-blink-features=AutomationControlled"
                )
            else:
                options = uc.ChromeOptions()

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
                if is_standard:
                    options.add_argument("--headless=new")
            else:
                options.add_argument("--start-maximized")

            return options

        # 3. KHỞI TẠO DRIVER (UC → fallback Standard)
        self.driver = None

        if mode == "undetected":
            try:
                print(
                    f"[{uid}] [uc.Selenium] Khởi tạo UC "
                    f"(profile={profile.mode.value})..."
                )
                self.driver = uc.Chrome(
                    options=_build_options(is_standard=False),
                    user_data_dir=profile_path,
                    headless=not visualize,
                    use_subprocess=True,
                )
            except Exception as e:
                print(f"[{uid}] ⚠️ [uc.Selenium] Khởi tạo thất bại ({e}).")
                print(
                    f"[{uid}] 🔄 Dọn process còn sót rồi chuyển sang "
                    "Selenium Standard..."
                )
                # UC có thể đã spawn chrome.exe trước khi lỗi. Không được mở
                # Standard trên cùng profile khi process cũ còn giữ.
                kill_profile_processes(profile_path, wait_seconds=6)
                wait_for_profile_release(profile_path, timeout=4)
                mode = "standard"

        if mode == "standard" and self.driver is None:
            try:
                print(f"[{uid}] [Selenium Standard] Đang khởi tạo Chế độ Chuẩn...")
                self.driver = webdriver.Chrome(options=_build_options(is_standard=True))
            except Exception as e:
                print(f"[{uid}] ❌ Lỗi khởi tạo Standard Driver: {e}")
                self._abort_start("browser_start_failed")
                return False

        # 4. TRUY CẬP VÀ XỬ LÝ ĐĂNG NHẬP
        try:
            self.driver.get("https://www.facebook.com")
            time.sleep(2)

            # Chỉ nạp cookie khi phiên hiện tại không phải của đúng UID.
            if not self._session_cookies_ok(uid):
                print(
                    f"[{uid}] Chưa có phiên hợp lệ cho UID này. "
                    f"Nạp cookie từ {cookie_file_path}..."
                )
                self._inject_cookies(self.driver, cookie_file_path)
            else:
                print(f"[{uid}] Profile đã có phiên đăng nhập đúng UID.")

            # 5. XÁC MINH TRẠNG THÁI ĐĂNG NHẬP (1 lần duy nhất)
            if not self.is_logged_in(expected_uid=uid):
                print(f"[{uid}] Đăng nhập thất bại / Checkpoint / Sai tài khoản!")
                if self.last_start_error is None:
                    self.last_start_error = "login_failed"
                self.close()
                return False

            self._persist_cookies(uid)
            return True

        except Exception as e:
            print(f"[{uid}] ❌ Lỗi trong quá trình điều hướng/truy cập: {e}")
            self._abort_start("browser_navigation_failed")
            return False

    def _abort_start(self, error: str):
        """Đặt lỗi rồi dọn sạch driver/profile/lock."""
        self.last_start_error = error
        self.close()

    def _inject_cookies(self, driver_instance, file_path) -> bool:
        """Nạp cookie từ file vào browser đang mở."""
        if not os.path.exists(file_path):
            print(f"Không tìm thấy file cookie tại: {file_path}")
            return False

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                cookies = json.load(f)

            driver_instance.get("https://www.facebook.com")
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
                    driver_instance.add_cookie(cookie_dict)
                    success_count += 1
                except Exception as cookie_error:
                    print(f"[Cookie] Bỏ qua cookie lỗi: {cookie_error}")

            driver_instance.refresh()
            time.sleep(2)
            print(f"Đã nạp thành công {success_count}/{len(cookies)} Cookie.")
            return True
        except Exception as e:
            print(f"Lỗi khi đọc/nạp Cookie: {str(e)}")
            return False

    def _session_cookies_ok(self, uid: str) -> bool:
        """Kiểm tra nhanh cookie hiện tại có thuộc đúng UID không (không điều hướng)."""
        try:
            cookies = {
                cookie.get("name"): cookie.get("value")
                for cookie in self.driver.get_cookies()
            }
        except Exception:
            return False
        return cookies.get("c_user") == str(uid) and bool(cookies.get("xs"))

    def _persist_cookies(self, uid: str):
        """Ghi cookie từ browser về kho nguồn để lần chạy sau dùng được."""
        try:
            cookies = self.driver.get_cookies()
        except Exception as error:
            print(f"[{uid}] Không đọc được cookie từ browser: {error}")
            return

        try:
            path = get_profile_manager().cookies.save(uid, cookies)
            print(f"[{uid}] Đã cập nhật cookie nguồn: {path}")
        except Exception as error:
            print(f"[{uid}] Không ghi được cookie nguồn: {error}")


    # -------------------------
    # Module đăng nhập & quản lý Cookie
    # -------------------------
    def save_cookies(self):
        """Ghi cookie hiện tại của browser về kho nguồn."""
        if not self.driver or not self._session:
            print("❌ Save cookies failed: browser chưa được khởi tạo")
            return False

        try:
            path = get_profile_manager().cookies.save(
                self._session.uid, self.driver.get_cookies()
            )
            print(f"🍪 Cookies updated → {path}")
            return True
        except Exception as e:
            print(f"❌ Save cookies failed: {e}")
            return False

    def is_logged_in(self, expected_uid: str = None):
        """Xác minh phiên đăng nhập và (tuỳ chọn) đúng tài khoản."""
        driver = self.driver
        if driver is None:
            return False

        try:
            cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
        except Exception:
            return False

        print(f"Cookie hiện có: {sorted(cookies)}")

        # Fast fail
        if "c_user" not in cookies or "xs" not in cookies:
            return False

        # Không cho phép chạy nhầm tài khoản khi profile còn session người khác.
        if expected_uid and str(cookies["c_user"]) != str(expected_uid):
            self.last_start_error = "account_mismatch"
            print(
                f"[Login] Cookie thuộc UID {cookies['c_user']} "
                f"nhưng cần {expected_uid}."
            )
            return False

        # Verify session
        try:
            driver.get("https://www.facebook.com/me")
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except Exception as e:
            print(f"[Login] Không xác minh được phiên: {e}")
            return False

        current_url = (driver.current_url or "").lower()
        if any(
            marker in current_url
            for marker in ("/login", "/checkpoint", "/recover", "/two_step_verification")
        ):
            print(f"[Login] Bị chuyển hướng xác minh: {current_url}")
            return False

        return True
    
    def login_with_cookies(self, uid: str, cookies: list) -> bool:
        """Hàm phụ trách mở browser, inject cookies để đăng nhập vào Facebook"""
        print(f"[UID: {uid}] Đang khởi tạo trình duyệt...")

        # 1. Khởi tạo driver và ngắt ngay nếu thất bại
        try:
            if not getattr(self, "driver", None):
                print(f"[UID: {uid}] 🚨 Khởi tạo Driver thất bại (driver is None).")
                return False
        except Exception as e:
            print(f"[UID: {uid}] 🚨 Lỗi setup_driver: {e}")
            return False
        
        try:
            # 1. Đi tới Facebook trước khi add cookie
            self.driver.get("https://www.facebook.com")
            time.sleep(2)        

            allowed = {
                "name",
                "value",
                "domain",
                "path",
                "expiry",
                "secure",
                "httpOnly"
            }

            for cookie in cookies:
                cookie = {k: v for k, v in cookie.items() if k in allowed}
                try:
                    print(f"Adding {cookie}")
                    self.driver.add_cookie(cookie)
                except:
                    print(f'Failed: {cookie}')
            
            # 3. Refresh để áp dụng Cookie và vào trạng thái Đăng Nhập
            self.driver.refresh()
            time.sleep(3)

            print(f"[UID: {uid}] Inject cookie hoàn tất. Tiêu đề trang: {self.driver.title}")
            
            success = self.is_logged_in()
            if success:
                print("Hoàn tất đăng nhập!")
            return success

        except Exception as e:
            print(f"[UID: {uid}] Gặp lỗi trong quá trình inject cookie: {e}")
            self.close() # Đóng driver ngay nếu lỗi giữa chừng
            return False

    # -------------------------

    # -------------------------
    # Scan uid from group members
    # --
    def log_raw_response(self, res_data: dict, filename: str = None):
        """
        Log request GraphQL (mặc định: logs/<uid>/requests.jsonl).
        """
        if not filename:
            base = self.log_dir or os.path.join(APP_DIR, "logs")
            os.makedirs(base, exist_ok=True)
            filename = os.path.join(base, "requests.jsonl")
        else:
            folder = os.path.dirname(os.path.abspath(filename))
            if folder:
                os.makedirs(folder, exist_ok=True)

        with open(filename, "a", encoding="utf-8") as f:
            f.write(json.dumps(res_data, ensure_ascii=False) + "\n")
    
    def fetch_group_members(
        self,
        group_id: str,
        cursor: str = None,
        count: int = 10,
        doc_id: str = "27114388448203693",
        friendly_name: str = "GroupsCometMembersPageNewMembersSectionRefetchQuery",
    ) -> dict:
        """Thực thi GraphQL request với doc_id và friendly_name linh hoạt (An toàn 100% thread)."""
        js_script = """
            const done = arguments[arguments.length - 1];
            const groupId = arguments[0];
            const cursor = arguments[1];
            const count = arguments[2];
            const docId = arguments[3];
            const friendlyName = arguments[4];

            try {
                const controller = new AbortController();
                const timeoutId = setTimeout(() => {
                    controller.abort();
                    done({ error: "JS_FETCH_TIMEOUT" });
                }, 10000);

                // 1. LẤY CÁC TOKEN BẢO MẬT (DTSG, USER_ID, LSD)
                let dtsgToken = "", userId = "", lsdToken = "";
                
                try { dtsgToken = (window.require && require('DTSGInitialData').token) || ""; } catch(e){}
                try { userId = (window.require && require('CurrentUserInitialData').USER_ID) || ""; } catch(e){}
                try { lsdToken = (window.require && require('LSD').token) || ""; } catch(e){}

                // Fallback qua Cookie nếu thiếu
                if (!dtsgToken) {
                    const m = document.cookie.match(/fb_dtsg=([^;]+)/);
                    if (m) dtsgToken = decodeURIComponent(m[1]);
                }
                if (!userId) {
                    const m = document.cookie.match(/c_user=([0-9]+)/);
                    if (m) userId = m[1];
                }

                if (!dtsgToken || !userId) {
                    clearTimeout(timeoutId);
                    return done({ error: "MISSING_AUTH_TOKENS" });
                }

                // 2. TÍNH JAZOEST
                let sum = 0;
                for (let i = 0; i < dtsgToken.length; i++) sum += dtsgToken.charCodeAt(i);
                const jazoest = '2' + sum;

                // 3. TỰ ĐỘNG LẤY TELEMETRY TỪ WINDOW (NẾU CÓ) ĐỂ TĂNG CONTENT-LENGTH LÊN 3000+ BYTES
                let rev = "", spinT = "";
                try { rev = (window.SiteData && window.SiteData.client_revision) || ""; } catch(e){}
                try { spinT = (window.Env && window.Env.start_time) || ""; } catch(e){}

                // 4. XÂY DỰNG PAYLOAD HOÀN CHỈNH
                const payloadMap = {
                    'av': userId,
                    '__user': userId,
                    'fb_dtsg': dtsgToken,
                    'jazoest': jazoest,
                    'lsd': lsdToken,
                    'fb_api_caller_class': 'RelayModern',
                    'fb_api_req_friendly_name': friendlyName,
                    'server_timestamps': 'true',
                    'doc_id': docId,
                    'variables': JSON.stringify({
                        'count': count,
                        'cursor': cursor ? cursor : null,
                        'groupID': groupId,
                        'recruitingGroupFilterNonCompliant': false,
                        'scale': 1,
                        'id': groupId
                    }),
                    '__a': '1',
                    '__comet_req': '15'
                };

                if (rev) payloadMap['__rev'] = rev;
                if (spinT) payloadMap['__spin_t'] = spinT;

                const payload = new URLSearchParams(payloadMap);

                // 5. GỬI FETCH CÓ CHỨA CÁC CUSTOM HEADERS X-
                fetch('https://www.facebook.com/api/graphql/', {
                    method: 'POST',
                    headers: { 
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'X-Asbd-Id': '359341',
                        'X-Fb-Friendly-Name': friendlyName,
                        'X-Fb-Lsd': lsdToken
                    },
                    body: payload.toString(),
                    credentials: 'include',
                    signal: controller.signal
                })
                .then(async res => {
                    clearTimeout(timeoutId);
                    const text = await res.text();
                    try {
                        done(JSON.parse(text));
                    } catch(jsonErr) {
                        done({ error: "INVALID_JSON_RESPONSE", raw: text.substring(0, 300) });
                    }
                })
                .catch(err => {
                    clearTimeout(timeoutId);
                    if (err.name === 'AbortError') return;
                    done({ error: err.toString() });
                });

            } catch(topErr) {
                done({ error: "CRITICAL_JS_ERROR: " + topErr.toString() });
            }
        """
        return self.driver.execute_async_script(
            js_script,
            str(group_id),
            cursor,
            count,
            str(doc_id),
            str(friendly_name),
        )

    def get_numeric_group_id(self, group_input: str = None) -> str:
        """
        Giải mã và trả về Numeric Group ID từ mọi nguồn:
        1. group_input là dãy số UID sẵn (VD: '2396395143940094')
        2. group_input là URL chứa dãy số (VD: 'https://.../groups/2396395143940094/')
        3. group_input là URL dạng Tên/Slug (VD: 'https://.../groups/congdongpython/') -> Fetch ngầm JS
        4. group_input = None -> Lấy trực tiếp từ DOM trang Selenium đang mở
        """
        # ------------------------------------------------------------------
        # TRƯỜNG HỢP 1 & 2: Kiểm tra nếu chuỗi truyền vào hoặc URL đã chứa ID dạng số
        # ------------------------------------------------------------------
        if group_input:
            group_input = str(group_input).strip()
            # Nếu truyền vào nguyên dãy số
            if group_input.isdigit():
                return group_input
            
            # Nếu truyền vào URL chứa ID dạng số
            match = re.search(r'/groups/(\d+)', group_input)
            if match:
                return match.group(1)

        # ------------------------------------------------------------------
        # TRƯỜNG HỢP 3: Không truyền URL (hoặc URL truyền vào trùng với trang đang mở)
        # -> Bóc tách trực tiếp từ DOM hiện tại (Tốc độ cao nhất, 0ms request)
        # ------------------------------------------------------------------
        current_url = self.driver.current_url
        if not group_input or group_input in current_url:
            js_dom_script = r"""
                // 1. Quét meta iOS
                const meta = document.querySelector('meta[property="al:ios:url"]');
                if (meta && meta.content) {
                    const m = meta.content.match(/fb:\/\/group\/([0-9]+)/);
                    if (m) return m[1];
                }
                // 2. Tìm trong Relay Store
                try {
                    const routeId = require('CometRouteStore').getRoute().params.groupID;
                    if (routeId) return routeId;
                } catch(e) {}
                // 3. Quét HTML thô
                const html = document.documentElement.innerHTML;
                const m = html.match(/"groupID":"([0-9]+)"/) || html.match(/"target_id":"([0-9]+)"/);
                return m ? m[1] : null;
            """
            try:
                return self.driver.execute_script(js_dom_script)
            except Exception:
                pass

        # ------------------------------------------------------------------
        # TRƯỜNG HỢP 4: URL là Tên/Slug của nhóm KHÁC trang hiện tại
        # -> Gửi fetch() ngầm qua JS lấy HTML bóc tách ID (Không cần driver.get())
        # ------------------------------------------------------------------
        js_async_script = r"""
            const targetUrl = arguments[0];
            const done = arguments[arguments.length - 1];

            fetch(targetUrl, { credentials: 'include' })
                .then(res => res.text())
                .then(html => {
                    const match = html.match(/fb:\/\/group\/([0-9]+)/) ||
                                html.match(/"groupID":"([0-9]+)"/) ||
                                html.match(/"target_id":"([0-9]+)"/);
                    done(match ? match[1] : null);
                })
                .catch(() => done(null));
        """
        self.driver.set_script_timeout(5)
        try:
            return self.driver.execute_async_script(js_async_script, group_input)
        except Exception as e:
            print(f"⚠️ Lỗi fetch ngầm Group ID từ {group_input}: {e}")
            return None
        finally:
            # Khôi phục timeout để không ép fetch_group_members (10s) xuống 5s.
            try:
                self.driver.set_script_timeout(30)
            except Exception:
                pass

    def scrape_group_members(
        self, 
        group_id: str, 
        max_members: int = 5000, 
        batch_size: int = 10, 
        retries: int = 3
    ) -> int:
        def access_group() -> bool:
            target_url = f"https://www.facebook.com/groups/{group_id}/members"
            print(f"🌐 Đang truy cập: {target_url}")
    
            try:
                self.driver.get(target_url)
                WebDriverWait(self.driver, 30).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
            except Exception as e:
                print(f"🚨 Không thể truy cập nhóm {group_id}: {e}")
                return False
    
            return True
        
        if self.is_stopped():
            return 0

        if not group_id:
            print("⚠️ Thiếu group_id, bỏ qua tìm kiếm.")
            return 0

        if not access_group():
            print("🚨 Không thể truy cập nhóm.")
            return 0

        payload = {
            'new_members': {
                'doc_id': 27114388448203693,
                'friendly_name': 'GroupsCometMembersPageNewMembersSectionRefetchQuery'
            },
            'things_in_common': {
                'doc_id': 27277860175202851,
                'friendly_name': 'GroupsCometMembersWithThingsInCommonCardPaginationQuery'
            }    
        }
        collected_uids = set()
        
        cursor = None
        has_next_page = True
        request_index = 1

        unlimited = max_members <= 0
        limit_text = "TẤT CẢ" if unlimited else f"{max_members}"

        file_name = group_id + '.jsonl'
        for key, value in payload.items():
            if self.is_stopped():
                break

            if key != 'new_members':
                continue

            print(f"Đang truy cập API {key}")
            while not self.is_stopped():
                if not (unlimited or len(collected_uids) < max_members):
                    break
            
                print(f"[*] Request #{request_index} | Đã cào: {len(collected_uids)}/{limit_text} UIDs (Cursor: {cursor})...")
                
                # --- CƠ CHẾ RETRY: Thử lại tối đa N lần ---
                attempt = 0
                success = False
                raw_res = {}
                edges = []
                node = {}

                while attempt < retries and not self.is_stopped():
                    attempt += 1
                    raw_res = self.fetch_group_members(group_id, cursor=cursor, count=batch_size, doc_id=value['doc_id'], friendly_name=value['friendly_name'])
                    self.log_raw_response(raw_res)

                    # 1. Xử lý an toàn chống NoneType/Null
                    data = raw_res.get("data") if isinstance(raw_res, dict) else None

                    if isinstance(raw_res, dict) and "error" not in raw_res and isinstance(data, dict):
                        node_data = data.get("node")
                        
                        # Nếu node tồn tại (không bị null do FB block)
                        if isinstance(node_data, dict):
                            if key == 'new_members':
                                node = node_data.get("new_members") or {}
                            elif key == 'things_in_common':
                                node = node_data.get("group_member_discovery") or {}
                            edges = node.get("edges") or []
                            
                            # Flag
                            success = True
                            break  

                    # 2. Tăng thời gian chờ ngẫu nhiên/tăng dần (Exponential Backoff) giúp nhả Rate Limit
                    wait_time = attempt * 3
                    print(f"⚠️ Thử lại sau {wait_time}s (Attempt {attempt}/{retries})...")
                    time.sleep(wait_time)

                # --- NẾU THẤT BẠI SAU N LẦN THỬ: HỦY VÀ THOÁT LUỒNG ---
                if not success:
                    print(f"🚨 [GỢI Ý] Đã thử {retries} lần nhưng API không phản hồi (có thể dính Checkpoint/Rate Limit). Hủy nhóm {group_id}!")
                    break  # Thoát vòng lặp while, chuyển sang group tiếp theo hoặc dừng

                # --- NẾU THÀNH CÔNG NHƯNG RỖNG: ĐÃ HẾT DANH SÁCH NHÓM ---
                if not edges:
                    print("[!] Đã duyệt đến cuối danh sách thành viên của nhóm.")
                    break

                # --- XỬ LÝ DỮ LIỆU KHI THÀNH CÔNG ---
                for edge in edges:
                    m = edge.get("node", {})
                    uid = m.get("id")

                    bio_data = m.get("bio_text") or {}
                    profile_pic = m.get("profile_picture") or {}
                    group_mem = m.get("group_membership") or {}
                    contrib_score = group_mem.get("group_contribution_score_text") or {}

                    # Lấy thông tin gia nhập từ cấp edge (cùng cấp với node/cursor)
                    join_status = edge.get("join_status_text") or {}
                    ranges = join_status.get("ranges") or []
                    added_by_entity = ranges[0].get("entity", {}) if ranges else {}

                    # Lấy trạng thái kết bạn
                    user_renderer = (m.get("user_type_renderer") or {}).get("user") or {}

                    if uid and uid not in collected_uids:
                        collected_uids.add(uid)
                        
                        member_info = {
                            "id": m.get("id"),
                            "name": m.get("name"),
                            "url": m.get("url"),
                            "avatar": profile_pic.get("uri"),

                            # 1. Thông tin cá nhân chi tiết
                            "bio": bio_data.get("text"),
                            "follower_count": m.get("follower_count"),
                            "is_verified": m.get("is_verified"),
                            "category": m.get("profile_plus_category_display_name"),

                            # 2. Hoạt động & Đóng góp trong nhóm
                            "contribution_score": contrib_score.get("text"),
                            "membership_id": group_mem.get("id"),

                            # 3. Lịch sử tham gia & Người giới thiệu
                            "join_status_text": join_status.get("text"),
                            "added_by_id": added_by_entity.get("id"),
                            "added_by_name": added_by_entity.get("short_name"),
                            "added_by_url": added_by_entity.get("url"),

                            # 4. Trạng thái tương tác
                            "subscribe_status": m.get("subscribe_status"),
                            "friendship_status": user_renderer.get("friendship_status")
                        }
                        self._buffer.append(member_info)

                        if not unlimited and len(collected_uids) >= max_members:
                            break
                
                self._flush(file_name)  # Ghi batch ra file jsonl

                if not unlimited and len(collected_uids) >= max_members:
                    print(f"\n[THÀNH CÔNG] Đã thu thập đủ mục tiêu {max_members} UIDs!")
                    break

                # Lấy cursor cho trang tiếp theo
                page_info = node.get("page_info", {})
                has_next_page = page_info.get("has_next_page", False)
                cursor = page_info.get("end_cursor")

                # cursor = null & has_next_page = false -> STOP
                if not cursor and not has_next_page:
                    print("[!] Đã duyệt đến cuối danh sách nhóm.")
                    break

                request_index += 1
                time.sleep(random.uniform(1.5, 2.5))

        if unlimited:
            print(f"\n[HOÀN THÀNH] Đã cào TẤT CẢ {len(collected_uids)} UIDs trong nhóm!")

        # Xuất kết quả (data/<uid>/raw → data/<uid>/exports)
        raw_path = os.path.join(
            self.data_dir or os.path.join(APP_DIR, "data", "raw"),
            f"{group_id}.jsonl",
        )
        if os.path.exists(raw_path):
            convert_to_spreadsheet(
                raw_path, f"{group_id}.xlsx", output_dir=self.exports_dir
            )
            convert_to_spreadsheet(
                raw_path, f"{group_id}.csv", output_dir=self.exports_dir
            )
        else:
            print(f"[Export] Không tìm thấy {raw_path}, bỏ qua xuất Excel/CSV.")

        return len(collected_uids)

    def prepare_post_scan_analysis(
        self,
        scope: str,
        keyword: str = "",
        group_ids=None,
        pause_seconds: int = 1800,
    ) -> dict:
        """Mở phạm vi quét bài và giữ browser để phân tích thủ công Facebook.

        `scope="search"` mở Facebook Search theo từ khóa (phạm vi rộng).
        `scope="groups"` mở group đầu tiên trong danh sách (phạm vi hẹp).
        Hàm chưa trích xuất bài viết; đây là bước chuẩn bị để xác định selector
        và request phù hợp trước khi tích hợp crawler.
        """
        if not self.driver:
            raise RuntimeError("Browser chưa được khởi tạo.")

        normalized_scope = str(scope).strip().lower()
        normalized_groups = [
            str(group_id).strip()
            for group_id in (group_ids or [])
            if str(group_id).strip()
        ]

        if normalized_scope == "search":
            normalized_keyword = keyword.strip()
            if not normalized_keyword:
                raise ValueError("Search tổng quát yêu cầu từ khóa.")
            target_url = (
                "https://www.facebook.com/search/posts/?q="
                f"{urllib.parse.quote_plus(normalized_keyword)}"
            )
            source_label = f"search:{normalized_keyword}"
        elif normalized_scope == "groups":
            if not normalized_groups:
                raise ValueError("Quét theo group yêu cầu ít nhất một group ID.")
            target_url = f"https://www.facebook.com/groups/{normalized_groups[0]}"
            source_label = f"group:{normalized_groups[0]}"
        else:
            raise ValueError("Phạm vi quét không hợp lệ.")

        self.driver.get(target_url)
        wait_seconds = max(0, int(pause_seconds))
        deadline = time.monotonic() + wait_seconds
        print(
            f"[Post Scan] Opened {source_label}. "
            f"Manual analysis pause: {wait_seconds} seconds."
        )

        while time.monotonic() < deadline:
            if self.is_stopped():
                print("[Post Scan] Manual analysis stopped.")
                return {
                    "status": "stopped",
                    "scope": normalized_scope,
                    "source": source_label,
                    "url": target_url,
                }
            try:
                # Khi người dùng đóng Chrome bằng tay, Selenium vẫn giữ object
                # driver nhưng mọi lệnh tới session sẽ ném WebDriverException.
                if not self.driver.window_handles:
                    raise WebDriverException("Browser window is closed.")
            except (WebDriverException, OSError):
                print("[Post Scan] Browser was closed manually.")
                return {
                    "status": "browser_closed",
                    "scope": normalized_scope,
                    "source": source_label,
                    "url": target_url,
                }
            time.sleep(min(1, deadline - time.monotonic()))

        print("[Post Scan] Manual analysis pause completed.")
        return {
            "status": "ready_for_extraction",
            "scope": normalized_scope,
            "source": source_label,
            "url": target_url,
        }

    # -------------------------

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

    def type_content_to_editor(self, editor, content):
        def insert_to_editor(editor, text):
            """Bắn chữ/emoji an toàn qua JS"""
            self.driver.execute_script("""
                var element = arguments[0];
                var text = arguments[1];
                element.focus();
                document.execCommand('insertText', false, text);
                element.dispatchEvent(new Event('input', { bubbles: true }));
            """, editor, text)
        editor.click()
        
        # Tách chuỗi: Giữ riêng emoji và giữ riêng cả dấu xuống dòng \n
        tokens = re.split(r'([\U00010000-\U0010FFFF]|\n)', content)
        
        current_chunk = ""
        target_length = random.randint(15, 35) # Độ dài ký tự ngẫu nhiên cho mỗi cụm
        
        for token in tokens:
            if not token:
                continue
                
            # TRƯỜNG HỢP 1: Gặp dấu xuống dòng
            if token == '\n':
                if current_chunk:
                    insert_to_editor(editor, current_chunk)
                    current_chunk = ""
                
                # Ép ô chatbox xuống dòng bằng Shift + Enter
                editor.send_keys(Keys.SHIFT + Keys.ENTER)
                time.sleep(0.05)
                target_length = random.randint(15, 35) # Reset độ dài ngẫu nhiên
                continue
                
            # TRƯỜNG HỢP 2: Gặp Emoji
            if re.match(r'[\U00010000-\U0010FFFF]', token):
                # Nếu cụm chữ hiện tại + emoji này dài quá target, đẩy cụm cũ đi trước
                if len(current_chunk) + 1 >= target_length:
                    insert_to_editor(editor, current_chunk)
                    current_chunk = token # Emoji sẽ mở đầu cho cụm mới
                    target_length = random.randint(15, 35)
                    time.sleep(random.uniform(0.1, 0.2))
                else:
                    current_chunk += token
                continue
                
            # TRƯỜNG HỢP 3: Chữ thường
            current_chunk += token
            
            # Nếu tích lũy đủ độ dài ngẫu nhiên thì đẩy vào ô chat
            if len(current_chunk) >= target_length:
                insert_to_editor(editor, current_chunk)
                current_chunk = ""
                target_length = random.randint(15, 35)
                time.sleep(random.uniform(0.1, 0.2))
                
        # Đẩy nốt phần nội dung còn lại (nếu có)
        if current_chunk:
            insert_to_editor(editor, current_chunk)

    def send_message_via_uid(self, uid, content, image_paths=None, typing_delay_range=None):
        def human_delay(min_sec=0.5, max_sec=1.5):
            """Tạo khoảng trễ ngẫu nhiên mô phỏng sự suy nghĩ của người dùng"""
            time.sleep(random.uniform(min_sec, max_sec))

        def human_scroll_to(element):
            """Cuộn trang mượt mà và tự nhiên giống người thật"""
            try:
                # Cuộn từ từ đến vị trí element
                desired_y = element.location['y'] - random.randint(150, 250)
                current_y = self.driver.execute_script("return window.pageYOffset;")
                step = 40 if desired_y > current_y else -40
                
                # Cuộn từng bước nhỏ
                for pos in range(current_y, desired_y, step):
                    self.driver.execute_script(f"window.scrollTo(0, {pos});")
                    time.sleep(random.uniform(0.01, 0.03))
                
                # Cuộn chính xác bước cuối
                self.driver.execute_script(f"window.scrollTo(0, {desired_y});")
                human_delay(0.3, 0.7)
            except Exception:
                # Fallback nếu cuộn mượt bị lỗi
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)

        def human_click(element):
            """Click vào một điểm ngẫu nhiên trên nút thay vì click vào tâm"""
            try:
                size = element.size
                # Lấy tọa độ ngẫu nhiên bên trong kích thước của nút (tránh sát rìa)
                offset_x = random.randint(int(size['width'] * 0.2), int(size['width'] * 0.8))
                offset_y = random.randint(int(size['height'] * 0.2), int(size['height'] * 0.8))
                
                # Di chuyển chuột tới phần tử và click với khoảng lệch ngẫu nhiên
                action = ActionChains(self.driver)
                action.move_to_element_with_offset(element, offset_x - (size['width']/2), offset_y - (size['height']/2))
                action.click()
                action.perform()
            except Exception:
                # Fallback nếu ActionChains bị chặn
                element.click()

        def close_chat():
            try:
                human_delay(1.5, 3.5) # Người thật nhìn màn hình một lúc rồi mới tắt
                print("[+] Đang đóng chat...")

                close_button = self.driver.find_element(
                    By.XPATH,
                    '//div[contains(@aria-label, "Close") or contains(@aria-label, "Đóng")]'
                )

                human_click(close_button)
                print("[+] Đã đóng chat")

            except Exception as e:
                print(f"[!] Close chat failed UID={uid}: {e}")

        def find_message_button():
            try:
                message_button = WebDriverWait(self.driver, 4).until(
                    EC.element_to_be_clickable((
                        By.XPATH,
                        '//div[@aria-label="Message" or @aria-label="Nhắn tin"]'
                    ))
                )
                print("[+] Đã tìm thấy nút Message")
                return message_button
            except TimeoutException as e:
                raise Exception(f"[MESSAGE_BUTTON_TIMEOUT] UID={uid}") from e
            except NoSuchElementException as e:
                raise Exception(f"[MESSAGE_BUTTON_NOT_FOUND] UID={uid}") from e
            
        def find_chatbox():
            try:
                chatbox_xpath = '//div[contains(@aria-label, "Write to") or contains(@aria-label, "Viết cho")]'
                chatbox = WebDriverWait(self.driver, 4).until(
                    EC.presence_of_element_located((By.XPATH, chatbox_xpath))
                )
                print("[+] Đã tìm thấy chatbox")
                return chatbox
            except Exception as e:
                print(f"[!] Không tìm thấy chatbox cho UID={uid}. Tiến hành đóng chat...")
                close_chat()
                raise Exception(f"[CHATBOX_TIMEOUT] UID={uid}") from e
            
        def clear_chatbox():
            try:
                print("[+] Đang clear chatbox...")
                human_click(chatbox) # Click vào trước khi xóa giống người thật
                human_delay(0.2, 0.5)
                chatbox.send_keys(Keys.CONTROL, "a")
                human_delay(0.1, 0.3)
                chatbox.send_keys(Keys.DELETE)
                print("[+] Đã clear chatbox")
            except Exception as e:
                print(f"[!] Clear chatbox failed UID={uid}: {e}")

        try:
            # =========================
            # OPEN PROFILE
            # =========================
            try:
                print(f"\n[+] Đang mở trang cá nhân UID: {uid}")
                user_url = f"https://www.facebook.com/{uid}"
                self.driver.get(user_url)
                human_delay(2.0, 4.0) # Chờ trang tải và người dùng "nhìn" giao diện

            except Exception as e:
                raise Exception(f"[OPEN_PROFILE_FAILED] UID={uid}") from e

            # =========================
            # FIND & SCROLL TO MESSAGE BUTTON
            # =========================
            message_button = find_message_button()
            human_scroll_to(message_button)

            # =========================
            # CLICK MESSAGE BUTTON
            # =========================
            try:
                human_click(message_button)
                print("[+] Đã click Message")
                human_delay(1.0, 2.5) # Chờ khung chat bật lên

            except Exception as e:
                raise Exception(f"[MESSAGE_BUTTON_CLICK_FAILED] UID={uid}") from e

            # =========================
            # FIND CHATBOX
            # =========================
            chatbox = find_chatbox()

            # =========================
            # INPUT MESSAGE (Đã có logic của bạn)
            # =========================
            try:
                print(f"[+] Đang nhập tin nhắn: '{content}'")
                human_click(chatbox) # Click kích hoạt khung chat trước khi gõ
                human_delay(0.3, 0.7)
                
                self.type_content_to_editor(chatbox, content)
                if typing_delay_range:
                    human_delay(*typing_delay_range)
                print("[+] Đã nhập tin nhắn")
                human_delay(0.5, 1.2) # Do dự một chút trước khi bấm gửi

            except Exception as e:
                raise Exception(f"[INPUT_MESSAGE_FAILED] UID={uid}") from e

            # =========================
            # SEND MESSAGE
            # =========================
            try:
                print("[+] Đang gửi tin nhắn...")

                # Giả lập nhấn ENTER để gửi tin nhắn một cách tự nhiên
                chatbox.send_keys(Keys.ENTER)
                
                human_delay(1.5, 3.0) # Đợi tin nhắn chuyển trạng thái "Đã gửi"
                print("[🔑] Gửi thành công!")

            except Exception as e:
                raise Exception(f"[SEND_MESSAGE_FAILED] UID={uid}") from e

            clear_chatbox()
            close_chat()
            return True

        except Exception as e:
            print(f"[❌] {e}")
            return False

    def scrape_joined_groups(self):
        """
        Hàm cào danh sách Group đã tham gia từ trang /groups/joins
        Chỉ tập trung tìm kiếm trong vùng nội dung chính (role="main")
        """
        print("🔄 Đang truy cập trang danh sách Nhóm đã tham gia...")
        self.driver.get("https://www.facebook.com/groups/joins")
        time.sleep(4) # Đợi trang tải các group đầu tiên

        # Vòng lặp cuộn trang để tải hết danh sách Group
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        scroll_attempts = 10 
        
        for i in range(scroll_attempts):
            print(f"📜 Đang cuộn trang lần {i+1}/{scroll_attempts}...")
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3) 
            
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                print("🛑 Đã cuộn đến cuối danh sách hoặc không có dữ liệu mới.")
                break
            last_height = new_height

        print("🔍 Bắt đầu trích xuất dữ liệu Group từ vùng nội dung chính...")
        joined_groups = []

        try:
            # 1. Định vị vùng nội dung chính của trang Facebook
            main_container = self.driver.find_element(By.XPATH, "//*[@role='main']")
            
            # 2. Chỉ tìm các khối group item NẰM TRONG vùng role="main" này
            group_items = main_container.find_elements(By.XPATH, ".//div[@role='listitem']")
            print(f"📊 Phát hiện {len(group_items)} khối group item trong khu vực nội dung chính.")

            for item in group_items:
                try:
                    # 3. Tìm thẻ <a> chứa link nhóm bên trong item
                    a_tag = item.find_element(By.XPATH, ".//a[contains(@href, '/groups/')]")
                    url = a_tag.get_attribute("href")
                    
                    # 4. Lấy tên Group (Xử lý fallback nếu thẻ a đầu tiên là ảnh/trống chữ)
                    title = a_tag.text.strip()
                    if not title:
                        all_links = item.find_elements(By.XPATH, ".//a[contains(@href, '/groups/')]")
                        for link in all_links:
                            if link.text.strip():
                                title = link.text.strip()
                                break

                    if title and url:
                        # Trích xuất ID/Alias từ URL
                        match = re.search(r'/groups/([^/]+)', url)
                        group_id = match.group(1) if match else None
                        
                        # Loại bỏ các sub-page mặc định
                        if not group_id or group_id in ["joins", "feed", "discover", "create"]:
                            continue

                        numeric_id = self.get_numeric_group_id(group_id) or group_id
                        resolved_id = str(numeric_id)

                        group_info = {
                            "group_name": title,
                            "group_id": resolved_id,
                            "group_url": f"https://www.facebook.com/groups/{group_id}/"
                        }

                        # Kiểm tra trùng lặp theo ID đã resolve
                        if not any(
                            str(g["group_id"]) == resolved_id for g in joined_groups
                        ):
                            print(f"✅ Đã tìm thấy: {title} (ID: {resolved_id})")
                            joined_groups.append(group_info)
                            
                except Exception:
                    continue

        except Exception as e:
            print(f"❌ Không tìm thấy vùng nội dung chính (role='main'). Lỗi: {e}")
            return []

        print(f"🎉 Đã lọc và trích xuất thành công {len(joined_groups)} nhóm đã tham gia.")
        return joined_groups
    
    def share_post_to_group(self, post_url, content : str, uid=""):
        time.sleep(2)
        self.driver.get(post_url)

        try:
            xpath_dialog = "//div[@role='dialog']"
            time.sleep(2)

            # Tìm phần tử có thuộc tính aria-label cụ thể
            xpath_locator = xpath_dialog + "//div[@aria-label='Gửi nội dung này cho bạn bè hoặc đăng lên trang cá nhân của bạn.']"

            # Sử dụng trong Selenium
            share_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, xpath_locator))
            )
            self.driver.execute_script("arguments[0].click();", share_button)
            print("Đã click nút Share")

            # Sử dụng XPath để đợi một thẻ <a> có chứa UID trong href xuất hiện
            group_btn_xpath = xpath_dialog + '//div[@aria-label="Chia sẻ lên nhóm"]'
            group_btn = WebDriverWait(self.driver, 4).until(
                EC.element_to_be_clickable((By.XPATH, group_btn_xpath))
            )
            self.driver.execute_script("arguments[0].click();", group_btn)
            print("Đã click: Chia sẻ lên nhóm")

            time.sleep(1)

            # Tìm thẻ a chứa uid, nhưng chỉ tìm bên trong cái dialog đang mở
            group_xpath = xpath_dialog + f"//a[contains(@href, '{uid}')]/ancestor::div[@role='listitem']"
            
            try:
                # Đợi tối đa 15 giây cho đến khi phần tử xuất hiện
                group = WebDriverWait(self.driver, 15).until(
                    EC.element_to_be_clickable((By.XPATH, group_xpath))
                )
                print(group.get_attribute("outerHTML"))

                # Click vào link
                ActionChains(self.driver).move_to_element(group).click().perform()
                print(f"Đã tìm thấy và click vào nhóm: {uid}")

            except Exception as e:
                print(f"Không tìm thấy nhóm sau 15s chờ đợi: {e}")
            print("Đã vào trang share group!")

            editor_xpath = xpath_dialog + "//div[@data-lexical-editor='true' and contains(@aria-placeholder, 'Tạo bài viết')]"
            editor = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, editor_xpath))
            )

            # Focus và nhập
            self.type_content_to_editor(editor, content)

            post_btn_xpath = xpath_dialog + "//*[@role='button' and (@aria-label='Đăng' or @aria-label='Post')]"
            post_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, post_btn_xpath))
            )
            
            post_btn.click()

            return True
        except Exception as e:
            print(e)
            return False

    def create_post(self, id, content="", img_paths=[]):
        self.driver.get(f"https://www.facebook.com/groups/{id}")
        post_box_xpath = "//span[contains(text(),'mind') or contains(text(),'nghĩ gì') or contains(text(),'something') or contains(text(),'viết gì')]"

        try:
            post_box = WebDriverWait(self.driver, 5).until( # Tăng lên 5s cho an toàn mạng
                EC.element_to_be_clickable((By.XPATH, post_box_xpath))
            )
            post_box.click()
        except:
            return False
        print("Đã mở hộp đăng bài")

        # Giả lập: Nghỉ ngẫu nhiên, không lần nào giống lần nào để qua mặt AI Facebook
        time.sleep(random.uniform(1.2, 2.5))

        composer = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, "//div[@role='dialog' and @aria-modal='true']")
            )
        )

        print("Đã vào hộp đăng bài")

        # Cô lập Form
        editor = WebDriverWait(composer, 4, poll_frequency=0.1).until(
            EC.visibility_of_element_located((By.XPATH, ".//div[@role='textbox']"))
        )

        editor.click()
        time.sleep(random.uniform(0.5, 1.0))

        print("🚀 Đang tiến hành gõ cụm thông minh kết hợp xử lý Emoji...")

        # Biểu thức chính quy (Regex) để tách văn bản thành mảng gồm các cụm chữ và các icon riêng biệt
        # Nó sẽ tách chuỗi kiểu: "Hello 🌍 mọi người 😍" thành ['Hello ', '🌍', ' mọi người ', '😍']
        tokens = re.split(r'([\U00010000-\U0010FFFF])', content)

        for token in tokens:
            if not token:
                continue
            
            # TRƯỜNG HỢP 1: Nếu token là một Emoji (Ký tự nằm ngoài vùng BMP)
            if re.match(r'[\U00010000-\U0010FFFF]', token):
                # Dùng Javascript để chèn icon vào cuối nội dung hiện tại của thẻ div editor
                self.driver.execute_script("""
                    var element = arguments[0];
                    var emoji = arguments[1];
                    
                    // Chèn emoji vào thẻ div editable
                    element.focus();
                    document.execCommand('insertText', false, emoji);
                    
                    // Kích hoạt sự kiện để Facebook cập nhật trạng thái
                    element.dispatchEvent(new Event('input', { bubbles: true }));
                """, editor, token)
                time.sleep(random.uniform(0.1, 0.3)) # Nghỉ một chút sau khi chèn icon
                
            # TRƯỜNG HỢP 2: Nếu là chữ viết thông thường
            else:
                # Tách chữ thường thành các cụm nhỏ hơn nữa (tầm 15 ký tự) để gõ nhanh
                chunk_size = 15
                chunks = [token[i:i+chunk_size] for i in range(0, len(token), chunk_size)]
                
                for chunk in chunks:
                    editor.send_keys(chunk)
                    time.sleep(random.uniform(0.05, 0.15)) # Tốc độ gõ cụm chữ nhanh

        time.sleep(random.uniform(1.0, 2.0))
        print("✅ Đã gõ xong toàn bộ văn bản và Emoji không một lỗi vết!")

        # BOT
        # self.driver.execute_script("""
        #     var element = arguments[0];
        #     var text = arguments[1];
            
        #     // 1. Gán text (bao gồm cả Emoji) vào thẻ div
        #     element.innerText = text;
            
        #     // 2. Kích hoạt liên tiếp các sự kiện để React/Vue/Angular cập nhật State
        #     element.dispatchEvent(new Event('focus', { bubbles: true }));
        #     element.dispatchEvent(new Event('input', { bubbles: true }));
        #     element.dispatchEvent(new Event('change', { bubbles: true }));
        #     element.dispatchEvent(new Event('blur', { bubbles: true }));
        # """, editor, content)

        # Thêm ảnh
        if not img_paths:
            print("Không tìm thấy ảnh!")
            return

        valid_file = 'image/*,image/heif,image/heic,video/*,video/mp4,video/x-m4v,video/x-matroska,.mkv,.avi,.wmv,.mov,.flv,.webm,.3gp,.3g2,.mts,.m2ts,.vob,.divx,.f4v,.ogv'
        file_input = composer.find_element(
            By.XPATH,
            f".//input[@accept='{valid_file}']"
        )
        
        for img_path in img_paths:
            file_name = img_path.split('\\')[-1]
            file_path = os.path.join(APP_DIR, "bot_media_tmp", file_name)
            file_input.send_keys(file_path)
            # Nghỉ một chút giữa mỗi lần nạp file ảnh tiếp theo
            time.sleep(random.uniform(1.0, 2.0))

        print("Đã nạp toàn bộ ảnh, chờ Facebook xử lý render...")

        # Giả lập: Đợi cho đến khi nút Post thực sự "Bấm được" (Hết trạng thái disabled của FB)
        post_btn = WebDriverWait(composer, 15).until(
            EC.element_to_be_clickable((By.XPATH, ".//div[@aria-label='Post']"))
        )

        # Di chuột mồi đến nút trước khi click (Sử dụng ActionChains nếu cần thiết)
        time.sleep(random.uniform(0.7, 1.5)) 

        # post_btn.click()
        print("Đã đăng bài!")

        # Nút đăng bài
        post_btn = composer.find_element(
            By.XPATH,
            ".//div[@aria-label='Post']"
        )

        #post_btn.click()

        actions = ActionChains(self.driver)
        actions.move_to_element(post_btn).perform() # Rê chuột đến ô đăng bài
        time.sleep(random.uniform(0.3, 0.7))        # Giữ chuột ở đó một tí
        #actions.click(post_btn).perform()                   # Bấm chuột
        
        print("Hoàn tất đăng bài")
        return True

