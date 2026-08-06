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

def convert_json_file_to_spreadsheet(json_filepath, output_file="facebook_users.xlsx", join_details=True):
    """
    Đọc file .json hoặc .jsonl từ ổ đĩa và chuyển đổi sang file Excel (.xlsx) hoặc CSV (.csv).
    """
    if not os.path.exists(json_filepath):
        print(f"Lỗi: Không tìm thấy file '{json_filepath}'")
        return

    processed_rows = []

    # 2. Đọc file theo đúng định dạng (.jsonl đọc từng dòng, .json đọc toàn bộ)
    with open(json_filepath, 'r', encoding='utf-8') as f:
        if json_filepath.endswith('.jsonl'):
            data = (json.loads(line) for line in f if line.strip())
        else:
            data = json.load(f)

        # 3. Xử lý từng đối tượng
        for item in data:
            row = {
                "user_id": f"'{str(item.get('user_id', ''))}",
                "name": item.get("name", ""),
                "link": item.get("link", ""),
                "avatar": item.get("avatar", "")
            }
            
            details = item.get("details", [])
            
            if join_details:
                row["details"] = " | ".join(details)
            else:
                for idx, detail in enumerate(details, start=1):
                    row[f"detail_{idx}"] = detail

            processed_rows.append(row)

    # 4. Xuất ra DataFrame và lưu file
    df = pd.DataFrame(processed_rows)

    if output_file.endswith(".csv"):
        df.to_csv(output_file, index=False, encoding="utf-8-sig")
    elif output_file.endswith(".xlsx"):
        df.to_excel(output_file, index=False)
    else:
        raise ValueError("Định dạng file không hỗ trợ. Vui lòng chọn .xlsx hoặc .csv")

    print(f"Đã chuyển đổi thành công từ '{json_filepath}' sang '{output_file}'!")

class FacebookBot:
    def __init__(self, visualize=False, output_path="users.json", stop_event=None):
        self.driver = None
        self.user_agent = None
        self.output_path = output_path
        self.stop_event = stop_event

        self.visualize = visualize

    def is_stopped(self):
        """Hàm phụ trợ kiểm tra xem người dùng đã bấm nút Dừng hay chưa."""
        return self.stop_event is not None and self.stop_event.is_set()

    def _load_existing_data(self):
        """Đọc file json cũ nếu có để tránh mất dữ liệu khi cào lại."""
        if os.path.exists(self.output_path):
            try:
                with open(self.output_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    print(
                        f"📂 Tìm thấy file cũ! Đã tải sẵn {len(data)} thành viên."
                    )
                    return {item["user_id"]: item for item in data if "user_id" in item}
            except Exception as e:
                print(f"⚠️ Lỗi đọc file cũ ({e}), sẽ tạo mới.")
        return {}

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

    def setup_driver(self, driver_type: str = "undetected"):
        """Cấu hình và khởi tạo Chrome Driver đã tối ưu tốc độ cào dữ liệu"""
        mode = driver_type or getattr(self, "driver_type", "undetected")

        if mode == "standard":
            chrome_options = StandardOptions()
            print("[Selenium Standard] Đang khởi tạo Selenium truyền thống...")
        else:
            chrome_options = uc.ChromeOptions()
            print("[uc.Selenium] Đang khởi tạo Undetected ChromeDriver...")

        # --- TỐI ƯU TỐC ĐỘ: CHẶN TẢI HÌNH ẢNH & TÀI NGUYÊN NẶNG ---
        chrome_options.add_argument("--blink-settings=imagesEnabled=false")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-software-rasterizer")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--disable-logging")

        # --- CÁCH 1: CHỐNG ĐÓNG BẰNG JS KHI MẤT FOCUS / CHE KHUẤT CỬA SỔ ---
        chrome_options.add_argument("--disable-background-timer-throttling")
        chrome_options.add_argument("--disable-backgrounding-occluded-windows")
        chrome_options.add_argument("--disable-renderer-backgrounding")
        
        # Chặn tải ảnh qua Preferences
        prefs = {
            "profile.managed_default_content_settings.images": 2,
            "profile.managed_default_content_settings.stylesheet": 2, # Bật nếu muốn chặn cả CSS
        }
        chrome_options.add_experimental_option("prefs", prefs)

        # --- XỬ LÝ HEADLESS ---
        if not self.visualize:
            chrome_options.add_argument("--window-size=1920,1080")
            if mode == "standard":
                chrome_options.add_argument("--headless=new")
            print(f"[{mode}] Đang chạy ở chế độ CHẠY ẨN (Headless)...")
        else:
            chrome_options.add_argument("--start-maximized")
            print(f"[{mode}] Đang chạy ở chế độ HIỂN THỊ CỬA SỔ...")

        if getattr(self, "user_agent", None):
            chrome_options.add_argument(f"--user-agent={self.user_agent}")

        # Khởi tạo Driver
        if mode == "standard":
            self.driver = webdriver.Chrome(options=chrome_options)
        else:
            self.driver = uc.Chrome(
                options=chrome_options,
                headless=not self.visualize,
                use_subprocess=True,
                version_main=150,
            )


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
        print(driver.get_cookies())
        cookies = {c["name"] for c in driver.get_cookies()}

        # Fast fail
        if "c_user" not in cookies or "xs" not in cookies:
            return False

        # Verify session
        driver.get("https://www.facebook.com/me")

        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

        return True

    def handle_checkpoint(self):
        try:
            btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable(
                    (
                        By.XPATH,
                        "//*[@role='button' and contains(., 'Continue')]"
                    )
                )
            )

            btn.click()

            password_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.NAME, "pass"))
            )

            password_input.clear()
            password_input.send_keys(self.password)
            password_input.send_keys(Keys.RETURN)

            return True

        except Exception as e:
            print(f"❌ Checkpoint failed: {e}")
            return False

    def login_and_save_cookies(self, timeout=120):
        driver = self.driver
        driver.get("https://www.facebook.com/")

        print("🔐 Please log in manually in the browser...")

        start = time.time()

        while time.time() - start < timeout:
            if self.is_logged_in():
                cookies = driver.get_cookies()
                with open(self.cookie_file, "wb") as f:
                    pickle.dump(cookies, f)

                print("✅ Logged in & cookies saved!")
                return True

            time.sleep(2)

        print("❌ Timeout: Login not detected")
        return False

    def login_with_cookies(self, uid: str, cookies: list) -> bool:
        """Hàm phụ trách mở browser, inject cookies để đăng nhập vào Facebook"""
        print(f"[UID: {uid}] Đang khởi tạo trình duyệt...")

        # 1. Khởi tạo driver và ngắt ngay nếu thất bại
        try:
            self.setup_driver()
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

    def ensure_login(self):
        success = self.login_with_cookies()

        if not success:
            print("🔐 Falling back to manual login...")
            self.login_and_save_cookies()

    # -------------------------

    # -------------------------
    # Scan uid from group members
    # --
    def extract_user_id(self, link):
        if not link:
            return None

        # Kiểm tra profile.php trước khi tách dấu ?
        if "profile.php" in link:
            match = re.search(r"id=(\d+)", link)
            if match:
                return match.group(1)

        clean_link = link.split("?")[0]

        if "/user/" in clean_link:
            return clean_link.split("/user/")[1].strip("/")

        match = re.search(r"facebook\.com/(\d+)", clean_link)
        if match:
            return match.group(1)

        username = (
            clean_link.replace("https://www.facebook.com/", "")
            .replace("http://www.facebook.com/", "")
            .strip("/")
        )
        return username if username else None

    # Tách hẳn collect_members thành một phương thức riêng của class
    def _append_checkpoint(self, items):
        """Ghi nối tiếp (append) danh sách member mới vào file jsonl/txt thông qua self.output_path"""
        if not items or not getattr(self, "output_path", None):
            return

        try:
            with open(self.output_path, "a", encoding="utf-8") as f:
                for item in items:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
            print(f"💾 [AutoSave] Đã ghi thêm {len(items)} member mới vào file: {self.output_path}")
        except Exception as e:
            print(f"🚨 Lỗi khi ghi file {self.output_path}: {e}")

    def collect_members(
        self,
        max_uids=0,
        base_scroll_pause=2.5,
        max_retries_per_scroll=4,
        stop_after_no_change=10,
        autosave_every=100,
        gc_interval_seconds=300,
    ):
        driver = self.driver
        collected = {}
        unsaved_batch = []
        no_change_count = 0
        last_gc_time = time.time()

        driver.set_script_timeout(15)

        js_wait_mutation = """
            const callback = arguments[arguments.length - 1];
            const timeoutMs = arguments[0];

            if (document.querySelectorAll('div[role="listitem"]:not([data-scanned="1"])').length > 0) {
                return callback(true);
            }

            let observer = null;
            const timer = setTimeout(() => {
                if (observer) observer.disconnect();
                callback(false);
            }, timeoutMs);

            observer = new MutationObserver((mutations) => {
                if (document.querySelectorAll('div[role="listitem"]:not([data-scanned="1"])').length > 0) {
                    clearTimeout(timer);
                    if (observer) observer.disconnect();
                    callback(true);
                }
            });

            observer.observe(document.body, { childList: true, subtree: true });
        """

        js_extract_members = """
            const items = document.querySelectorAll('div[role="listitem"]:not([data-scanned="1"])');
            const newMembers = [];

            for (let i = 0; i < items.length; i++) {
                const item = items[i];
                item.setAttribute('data-scanned', '1');

                const linkElem = item.querySelector('a[role="link"]');
                if (!linkElem) {
                    item.remove();
                    continue;
                }

                const href = linkElem.href || '';
                if (!href || href.includes('#')) {
                    item.remove();
                    continue;
                }

                const name = linkElem.getAttribute('aria-label') || linkElem.innerText.trim();

                const imgElem = item.querySelector('image, img');
                let avatar = '';
                if (imgElem) {
                    avatar = imgElem.getAttribute('xlink:href') || imgElem.src || '';
                    if (avatar.startsWith('data:image')) avatar = '';
                }

                const rawText = item.innerText || '';
                const textLines = rawText.split(/\\r?\\n/).map(t => t.trim()).filter(Boolean);

                newMembers.push({
                    name: name,
                    link: href,
                    avatar: avatar,
                    details: textLines
                });

                item.remove();
            }

            return newMembers;
        """

        def clear_chrome_mem():
            try:
                driver.execute_cdp_cmd("HeapProfiler.collectGarbage", {})
            except Exception:
                pass

        while not self.is_stopped():
            if max_uids > 0 and len(collected) >= max_uids:
                break

            previous_total = len(collected)
            new_data_found = False

            for retry in range(max_retries_per_scroll):
                if self.is_stopped():
                    break

                # Step 1: Cuộn trang
                try:
                    js_scroll = """
                        window.focus();
                        try {
                            Object.defineProperty(document, 'visibilityState', {get: () => 'visible', configurable: true});
                            Object.defineProperty(document, 'hidden', {get: () => false, configurable: true});
                            document.dispatchEvent(new Event('visibilitychange'));
                        } catch(e) {}
                        window.scrollBy(0, -300);
                    """
                    driver.execute_script(js_scroll)
                    time.sleep(0.2)
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                except Exception:
                    pass

                # Step 2: Chờ DOM xuất hiện phần tử mới
                max_wait_ms = int((base_scroll_pause + (retry * 0.5)) * 1000)
                try:
                    driver.execute_async_script(js_wait_mutation, max_wait_ms)
                except Exception:
                    pass

                if self.stop_event and self.stop_event.is_set():
                    print("⏹️ Nhận lệnh dừng.")
                    break

                # Step 3: Trích xuất dữ liệu
                try:
                    raw_members = driver.execute_script(js_extract_members)
                    if raw_members:
                        for item in raw_members:
                            link = item.get("link", "")
                            if any(path in link for path in ["/photos/", "/stories/", "/reels/", "/watch/", "/members"]):
                                continue

                            user_id = self.extract_user_id(link)
                            if user_id and user_id not in collected:
                                item["user_id"] = user_id
                                collected[user_id] = item
                                unsaved_batch.append(item)

                    if len(collected) > previous_total:
                        new_data_found = True
                        break

                except WebDriverException as e:
                    print(f"🚨 Lỗi Selenium/Mạng: {e.msg}")
                    if "chrome not reachable" in str(e).lower() or "no such session" in str(e).lower():
                        break
                    if self.stop_event and self.stop_event.wait(timeout=5):
                        break

            # Step 4: Kiểm tra trạng thái dừng
            if not new_data_found:
                no_change_count += 1
                print(f"⚠️ Không có dữ liệu mới. Đếm: {no_change_count}/{stop_after_no_change}")
                if no_change_count >= stop_after_no_change:
                    break
            else:
                no_change_count = 0

            # Step 5: Tự động lưu nối tiếp vào file chỉ định theo đường dẫn self.output_path
            if len(unsaved_batch) >= autosave_every:
                self._append_checkpoint(unsaved_batch)
                unsaved_batch.clear()

            # Step 6: Giải phóng bộ nhớ Chrome định kỳ
            if time.time() - last_gc_time > gc_interval_seconds:
                clear_chrome_mem()
                last_gc_time = time.time()

        # Lưu vét nốt số member còn lại trong batch chưa kịp lưu
        if unsaved_batch:
            self._append_checkpoint(unsaved_batch)
            unsaved_batch.clear()

        clear_chrome_mem()
        self.collected = collected
        print(f"✅ Hoàn tất! Tổng cộng thu thập được {len(collected)} member và lưu tại '{self.output_path}'")
        return list(collected.values())

    def perform_search(self, group_id=None, timeout=30, *args, **kwargs):
        if not group_id:
            print("⚠️ Thiếu group_id, bỏ qua tìm kiếm.")
            return []

        max_uids = kwargs.get("max_uids", 0)
        base_scroll_pause = kwargs.get("base_scroll_pause", 2.5)

        # Truy cập thẳng URL tab members
        target_url = f"https://www.facebook.com/groups/{group_id}/members"

        print(f"🌐 Đang truy cập: {target_url}")

        try:
            self.driver.get(target_url)
            # Chờ trang load cơ bản (có thể chờ body hoặc 1 element đặc trưng của group)
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
        except Exception as e:
            print(f"🚨 Không thể truy cập nhóm {group_id}: {e}")
            return [] # Dừng ngay lập tức nếu không mở được trang

        # Tiến hành cào dữ liệu
        users = self.collect_members(max_uids=max_uids, base_scroll_pause=base_scroll_pause) or []

        if not users:
            print("⚠️ Không thu thập được thành viên nào.")
            return []

        print(f"🎯 Hoàn thành! Đã lưu tổng cộng {len(users)} thành viên mới.")

        # Xuất .csv và .xlsx từ file JSON đã lưu
        convert_json_file_to_spreadsheet(json_filepath=self.output_path, output_file=self.output_path.replace(".jsonl", ".csv"))
        convert_json_file_to_spreadsheet(json_filepath=self.output_path, output_file=self.output_path.replace(".jsonl", ".xlsx"))

        return users

    # -------------------------

    def close(self):
        self.driver.quit()

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

                        group_info = {
                            "group_name": title,
                            "group_id": group_id,
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

            time.sleep(10)

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

