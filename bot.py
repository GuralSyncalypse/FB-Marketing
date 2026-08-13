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
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) # Thư mục /app

def convert_to_spreadsheet(json_filepath, output_file="facebook_users.xlsx"):
    """
    Đọc file .json hoặc .jsonl và chuyển đổi sang file Excel (.xlsx) hoặc CSV (.csv).
    """
    def parse_contribution_score(score_str):
        """Trích xuất số từ chuỗi contribution_score, mặc định là 0 nếu null hoặc rỗng."""
        if not score_str:
            return 0
        match = re.search(r'\d+', str(score_str))
        return int(match.group()) if match else 0

    def parse_boolean_status(status_str, positive_value):
        """
        Chuyển đổi trạng thái text sang Boolean:
        - Nếu đúng positive_value -> True
        - Nếu null / None / rỗng -> None (Để trống trong Excel/CSV)
        - Nếu là trạng thái ngược lại -> False
        """
        if status_str is None or status_str == "":
            return None
        elif status_str == positive_value:
            return True
        return False

    if not os.path.exists(json_filepath):
        print(f"Lỗi: Không tìm thấy file '{json_filepath}'")
        return

    items = []

    # 1. Đọc file .json / .jsonl
    with open(json_filepath, 'r', encoding='utf-8') as f:
        if json_filepath.endswith('.jsonl'):
            items = [json.loads(line) for line in f if line.strip()]
        else:
            data = json.load(f)
            items = data if isinstance(data, list) else [data]

    processed_rows = []

    # 2. Xử lý từng đối tượng
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
            "contribution_score": parse_contribution_score(item.get("contribution_score")),
            "friendship_status": parse_boolean_status(item.get("friendship_status"), "CAN_REQUEST"),
            "subscribe_status": parse_boolean_status(item.get("subscribe_status"), "CAN_SUBSCRIBE"),
            
            "membership_id": str(item.get("membership_id") or ""),
            "join_status_text": item.get("join_status_text", ""),
            "added_by_id": str(item.get("added_by_id") or ""),
            "added_by_name": item.get("added_by_name", ""),
            "added_by_url": item.get("added_by_url", "")
        }

        processed_rows.append(row)

    # 3. Xuất ra DataFrame & Lưu file
    df = pd.DataFrame(processed_rows)

    if output_file.endswith(".csv"):
        # na_rep="" đảm bảo các giá trị None/null ghi ra CSV dạng ô trống
        df.to_csv(output_file, index=False, encoding="utf-8-sig", na_rep="")
    elif output_file.endswith(".xlsx"):
        df.to_excel(output_file, index=False, engine="openpyxl")
    else:
        raise ValueError("Định dạng file không hỗ trợ. Vui lòng chọn .xlsx hoặc .csv")

    print(f"Đã chuyển đổi thành công {len(df)} dòng từ '{json_filepath}' sang '{output_file}'!")

class FacebookBot:
    def __init__(self, visualize=False, output_path="users.json", stop_event=None, on_save_batch=None):
        self.driver = None
        self.user_agent = None
        self.output_path = output_path
        self.stop_event = stop_event

        self.visualize = visualize

        self.on_save_batch = on_save_batch
        self._buffer = []

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
    ) -> bool:
        """Khởi tạo Driver (Standard/UC) tích hợp tối ưu tốc độ, Profile cách ly và nạp Cookie bằng hàm con."""

        # --- HÀM CON XỬ LÝ NẠP COOKIE ---
        def _inject_cookies(driver_instance, file_path):
            """Hàm con riêng biệt xử lý đọc file JSON và nạp Cookie vào Driver"""
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    cookies = json.load(f)

                for cookie in cookies:
                    cookie_dict = {
                        "name": cookie.get("name"),
                        "value": cookie.get("value"),
                        "domain": cookie.get("domain", ".facebook.com"),
                        "path": cookie.get("path", "/"),
                        "secure": cookie.get("secure", True),
                    }
                    if "expirationDate" in cookie:
                        cookie_dict["expiry"] = int(cookie["expirationDate"])

                    try:
                        driver_instance.add_cookie(cookie_dict)
                    except Exception:
                        pass

                driver_instance.refresh()
                time.sleep(3)
                print(f"[{uid}] -> Lần đầu chạy: Đã nạp Cookie thành công.")
            except Exception as e:
                print(f"[{uid}] -> Lỗi khi nạp Cookie: {str(e)}")

        self.user_agent = user_agent

        # 1. QUẢN LÝ THƯ MỤC PROFILE VÀ COOKIE
        profile_path = os.path.abspath(f"./profiles/{uid}")
        cookie_file_path = os.path.join(profile_path, "cookies.json")

        mode = driver_type or getattr(self, "driver_type", "undetected")
        ua = user_agent or getattr(self, "user_agent", None)

        # 2. CẤU HÌNH OPTIONS
        if mode == "standard":
            chrome_options = StandardOptions()
            chrome_options.add_argument(f"--user-data-dir={profile_path}")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            print("[Selenium Standard] Đang khởi tạo...")
        else:
            chrome_options = uc.ChromeOptions()
            print("[uc.Selenium] Đang khởi tạo Undetected ChromeDriver...")
            # LƯU Ý: Với uc, KHÔNG add --user-data-dir vào chrome_options ở đây nữa!

        if ua:
            chrome_options.add_argument(f"--user-agent={ua}")
        if proxy:
            chrome_options.add_argument(f"--proxy-server={proxy}")

        chrome_options.add_argument(f"--user-data-dir={profile_path}")
        if ua:
            chrome_options.add_argument(f"--user-agent={ua}")
        if proxy:
            chrome_options.add_argument(f"--proxy-server={proxy}")

        # Tối ưu tốc độ & Chặn tài nguyên nặng
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-software-rasterizer")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--disable-logging")

        # Chống đóng/chậm tiến trình khi mất focus hoặc ẩn cửa sổ
        chrome_options.add_argument("--disable-background-timer-throttling")
        chrome_options.add_argument("--disable-backgrounding-occluded-windows")
        chrome_options.add_argument("--disable-renderer-backgrounding")

        # Chặn tải hình ảnh
        prefs = {"profile.managed_default_content_settings.images": 2}
        chrome_options.add_experimental_option("prefs", prefs)

        # Xử lý Headless / Visual Mode
        visualize = getattr(self, "visualize", True)
        if not visualize:
            chrome_options.add_argument("--window-size=1920,1080")
            if mode == "standard":
                chrome_options.add_argument("--headless=new")
            print(f"[{mode}] Đang chạy ở chế độ ẨN (Headless)...")
        else:
            chrome_options.add_argument("--start-maximized")
            print(f"[{mode}] Đang chạy ở chế độ HIỂN THỊ CỬA SỔ...")

        # 3. KHỞI TẠO DRIVER
        if mode == "standard":
            self.driver = webdriver.Chrome(options=chrome_options)
        else:
            # Truyền user_data_dir trực tiếp vào uc.Chrome và BỎ version_main=150
            self.driver = uc.Chrome(
                options=chrome_options,
                user_data_dir=profile_path,  # Truyền trực tiếp vào đây
                headless=not visualize,
                use_subprocess=True,
                version_main=150
            )

        # 4. MỞ TRANG VÀ GỌI HÀM CON NẠP COOKIE (NẾU CẦN)
        self.driver.get("https://www.facebook.com")
        time.sleep(2)

        _inject_cookies(self.driver, cookie_file_path)

        # 5. XÁC MINH TRẠNG THÁI ĐĂNG NHẬP VÀ TRẢ VỀ KẾT QUẢ
        logged_in = self.is_logged_in()
        if not logged_in:
            self.close()
        return logged_in


    # -------------------------
    # Module đăng nhập & quản lý Cookie
    # -------------------------
    def save_cookies(self):
        try:
            with open(self.cookie_file, "wb") as f:
                pickle.dump(self.driver.get_cookies(), f)

            print("🍪 Cookies updated")
            return True

        except Exception as e:
            print(f"❌ Save cookies failed: {e}")
            return False

    def is_logged_in(self):
        driver = self.driver

        cookies = {c["name"] for c in driver.get_cookies()}
        print(cookies)
        # Fast fail
        if "c_user" not in cookies or "xs" not in cookies:
            return False

        # Verify session
        driver.get("https://www.facebook.com/me")

        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

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
    def log_raw_response(self, res_data: dict, filename: str = "data.jsonl"):
        """
        Log request GraphQL
        """
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

            // 1. BỌC TRY...CATCH TOÀN BỘ ĐỂ ĐẢM BẢO LUÔN GỌI DONE() KHÔNG BỊ TRANG THÁI HẰNG
            try {
                // 2. TẠO ABORT CONTROLLER ĐỂ HỦY FETCH KHI TIMEOUT
                const controller = new AbortController();
                const timeoutId = setTimeout(() => {
                    controller.abort();
                    done({ error: "JS_FETCH_TIMEOUT" });
                }, 10000);

                // 3. LẤY DTSG TOKEN AN TOÀN
                let dtsgToken = "";
                try {
                    dtsgToken = (window.require && require('DTSGInitialData') && require('DTSGInitialData').token) || 
                                (window.require && require('DTSGInitData') && require('DTSGInitData').token) || "";
                } catch(e) {}

                if (!dtsgToken) {
                    try {
                        const match = document.cookie.match(/fb_dtsg=([^;]+)/);
                        if (match) dtsgToken = decodeURIComponent(match[1]);
                    } catch(e) {}
                }

                // 4. LẤY USER ID AN TOÀN
                let userId = "";
                try {
                    userId = (window.require && require('CurrentUserInitialData') && require('CurrentUserInitialData').USER_ID) || "";
                } catch(e) {}

                if (!userId) {
                    try {
                        const match = document.cookie.match(/c_user=([0-9]+)/);
                        if (match) userId = match[1];
                    } catch(e) {}
                }

                if (!dtsgToken || !userId) {
                    clearTimeout(timeoutId);
                    return done({ error: "MISSING_AUTH_TOKENS" });
                }

                // 5. TÍNH JAZOEST TỪ DTSG TOKEN (TRÁNH CƠ CHẾ BẮT BOT CỦA FB)
                let jazoest = "";
                if (dtsgToken) {
                    let sum = 0;
                    for (let i = 0; i < dtsgToken.length; i++) {
                        sum += dtsgToken.charCodeAt(i);
                    }
                    jazoest = '2' + sum;
                }

                const payload = new URLSearchParams({
                    'av': userId,
                    '__user': userId,
                    'fb_dtsg': dtsgToken,
                    'jazoest': jazoest,
                    'fb_api_req_friendly_name': friendlyName,
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
                });

                // 6. THỰC THI FETCH VỚI ABORT SIGNAL
                fetch('https://www.facebook.com/api/graphql/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: payload.toString(),
                    credentials: 'include',
                    signal: controller.signal
                })
                .then(async res => {
                    clearTimeout(timeoutId);
                    const text = await res.text();
                    try {
                        const data = JSON.parse(text);
                        done(data);
                    } catch(jsonErr) {
                        // Nếu phản hồi là HTML (Checkpoint / Bị Block)
                        done({ error: "INVALID_JSON_RESPONSE", raw: text.substring(0, 300) });
                    }
                })
                .catch(err => {
                    clearTimeout(timeoutId);
                    if (err.name === 'AbortError') return; // Đã xử lý ở setTimeout
                    done({ error: err.toString() });
                });

            } catch(topErr) {
                // Đảm bảo nếu có lỗi bất ngờ xảy ra vẫn trả về cho Selenium
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
                    self.log_raw_response(raw_res, filename="requests_log.jsonl")

                    # 1. Xử lý an toàn chống NoneType/Null
                    data = raw_res.get("data") if isinstance(raw_res, dict) else None
                    
                    if "error" not in raw_res and isinstance(data, dict):
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

        # Xuất kết quả
        #convert_to_spreadsheet(f"data/{group_id}.jsonl", f"{group_id}.xlsx")
        #convert_to_spreadsheet(f"data/{group_id}.jsonl", f"{group_id}.csv")

        return len(collected_uids)

    # -------------------------

    def close(self):
        """Hàm đóng trình duyệt an toàn"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

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

    def send_message_via_uid(self, uid, content):
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

                        numeric_id = self.get_numeric_group_id(group_id)
                            
                        group_info = {
                            "group_name": title,
                            "group_id": numeric_id,
                            "group_url": f"https://www.facebook.com/groups/{group_id}/"
                        }
                        
                        # Kiểm tra trùng lặp theo ID
                        if not any(g['group_id'] == group_id for g in joined_groups):
                            print(f"✅ Đã tìm thấy: {title} (ID: {group_id})")
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
            file_path = os.path.join(BASE_DIR, "bot_media_tmp", file_name)
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

