from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from concurrent.futures import ThreadPoolExecutor
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException, StaleElementReferenceException
from openpyxl import Workbook
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
from queue import Queue, Empty
import threading
import random
import time
import pickle
import os
import re
import json

group_id = 'KillingFloorClanESP'
urls = [
    f'https://www.facebook.com/groups/{group_id}'
]

class FacebookBot:
    def __init__(self, email, password):
        self.one_time_code_exist = False
        self.email = email
        self.password = password
        self.driver = None
        self.cookie_file = "fb_cookies.pkl"

        self.init_driver(True)

    def init_driver(self, optimized):
        options = webdriver.ChromeOptions()
        if optimized:
            options.add_argument("--headless")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")

            prefs = {
                "profile.managed_default_content_settings.images": 2
            }
            options.add_experimental_option("prefs", prefs)     
            options.page_load_strategy = "eager"

        
        options.add_argument("--disable-notifications")

        driver = webdriver.Chrome(options=options)
        driver.maximize_window()

        self.driver = driver

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

    def login_with_cookies(self):
        driver = self.driver

        if not os.path.exists(self.cookie_file):
            print("⚠️ Cookie file not found")
            return False

        try:
            with open(self.cookie_file, "rb") as f:
                cookies = pickle.load(f)
        except Exception as e:
            print(f"❌ Failed to load cookies: {e}")
            return False

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

        driver.refresh()

        # Login thành công ngay
        if self.is_logged_in():
            print("✅ Logged in via cookies")
            self.save_cookies()
            return True

        try:
            self.handle_checkpoint()
        except Exception as e:
            print(f"❌ Checkpoint error: {e}")

        if self.is_logged_in():
            print("✅ Logged in after checkpoint")
            self.save_cookies()
            return True

        print("❌ Login failed")
        return False

    # -------------------------
    # STEP 3: Smart login
    # -------------------------
    def ensure_login(self):
        success = self.login_with_cookies()

        if not success:
            print("🔐 Falling back to manual login...")
            self.login_and_save_cookies()

    def extract_user_id(self, link):
        if not link:
            return None

        # Remove query params
        link = link.split("?")[0]

        # Case 1: /user/123
        if "/user/" in link:
            return link.split("/user/")[1].strip("/")

        # Case 2: profile.php?id=123
        if "profile.php" in link:
            match = re.search(r"id=(\d+)", link)
            if match:
                return match.group(1)

        # Case 3: direct numeric path /123456789/
        match = re.search(r"facebook\.com/(\d+)", link)
        if match:
            return match.group(1)

        # Case 4: username (fallback)
        username = link.replace("https://www.facebook.com/", "").strip("/")
        return username if username else None

    def collect_members(self, max_scroll=9999):
        driver = self.driver
        collected = {}  # Dùng dict với key là user_id để tự động lọc trùng dữ liệu
        seen_links = set()

        # Script JS gom trọn bộ dữ liệu của từng member item trong DOM
        js_extract_members = """
            return Array.from(document.querySelectorAll('div[role="listitem"]')).map(item => {
                const linkElem = item.querySelector('a[role="link"][aria-label]');
                if (!linkElem) return null;

                const name = linkElem.getAttribute('aria-label') || '';
                const href = linkElem.getAttribute('href') || '';

                // Lấy link ảnh đại diện
                const imgElem = item.querySelector('image, img');
                let avatar = '';
                if (imgElem) {
                    avatar = imgElem.getAttribute('xlink:href') || imgElem.getAttribute('src') || '';
                }

                // Lấy toàn bộ văn bản (Role, Bạn chung, Thời gian gia nhập...)
                const textLines = item.innerText ? item.innerText.split('\\n').map(t => t.trim()).filter(Boolean) : [];

                return {
                    name: name,
                    link: href,
                    avatar: avatar,
                    details: textLines
                };
            }).filter(item => item !== null);
        """

        last_height = driver.execute_script("return document.body.scrollHeight")
        no_change_count = 0

        for i in range(max_scroll):
            print(f"🔄 Scroll {i+1}")

            # Lấy danh sách chứa đầy đủ thông tin từ JavaScript
            raw_members = driver.execute_script(js_extract_members)

            if not raw_members and i == 0:
                print("⚠️ No elements found at all")
                break

            for item in raw_members:
                link = item.get("link")

                if not link or link in seen_links:
                    continue

                # Bỏ qua các đường link bài viết/stories/reels
                if any(x in link for x in ["photo", "story", "reel", "watch"]):
                    continue

                seen_links.add(link)

                user_id = self.extract_user_id(link)
                if user_id:
                    # Gán thêm user_id vào object thông tin
                    item["user_id"] = user_id
                    
                    # Lưu vào dict (nếu trùng user_id sẽ tự ghi đè/bỏ qua)
                    collected[user_id] = item

            # Cuộn xuống cuối trang
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)

            # Kiểm tra điều kiện dừng cuộn
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                no_change_count += 1
                if no_change_count >= 3:
                    print("✅ Đã đến cuối danh sách, dừng thuật toán.")
                    break
            else:
                no_change_count = 0
                last_height = new_height

        # Chuyển Dict thành List dữ liệu hoàn chỉnh
        result_list = list(collected.values())
        print(f"🎯 Hoàn thành! Thu thập được: {len(result_list)} thành viên.")
        return result_list

    def perform_search(self):
        driver = self.driver

        driver.get(urls[0])
        time.sleep(2)

        members_tab = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//a[contains(@href, 'members')]"
            ))
        )

        members_tab.click()
        time.sleep(3)

        users = self.collect_members()

        file_path = "users.json"

        # Lưu dữ liệu dưới dạng JSON chuẩn UTF-8
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=4)

        print(f"✅ Saved {len(users)} users to {file_path}")

    def close(self):
        self.driver.quit()

    
    # Gửi tin
    def log_time(self, label, start):
        print(
            f"[TIME] {label}: "
            f"{time.perf_counter() - start:.3f}s"
        )

    def send_message_via_uid_logged(self, uid, content):
        total_start = time.perf_counter()

        wait = WebDriverWait(self.driver, 20)

        def close_chat():
            t = time.perf_counter()

            try:
                close_button = wait.until(
                    EC.element_to_be_clickable((
                        By.XPATH,
                        '//div[@aria-label="Close chat"]'
                    ))
                )

                time.sleep(random.uniform(0.5, 1.5))

                close_button.click()

            except Exception as e:
                print(
                    f"[!] Close chat failed UID={uid}: {e}"
                )

            finally:
                self.log_time("CLOSE_CHAT", t)

        def find_message_button():
            t = time.perf_counter()

            try:
                message_button = WebDriverWait(
                    self.driver,
                    2
                ).until(
                    EC.element_to_be_clickable((
                        By.XPATH,
                        '//div[@aria-label="Message" or @aria-label="Nhắn tin"]'
                    ))
                )

                print("[+] Đã tìm thấy nút Message")

                return message_button

            except TimeoutException as e:
                raise Exception(
                    f"[MESSAGE_BUTTON_TIMEOUT] UID={uid}"
                ) from e

            finally:
                self.log_time("FIND_MESSAGE_BUTTON", t)

        def find_chatbox():
            t = time.perf_counter()

            try:
                chatbox_xpath = (
                    '//div[contains(@aria-label, "Write to")]'
                )

                chatbox = WebDriverWait(
                    self.driver,
                    2
                ).until(
                    EC.presence_of_element_located(
                        (By.XPATH, chatbox_xpath)
                    )
                )

                print("[+] Đã tìm thấy chatbox")

                return chatbox

            except TimeoutException as e:
                close_chat()

                raise Exception(
                    f"[CHATBOX_TIMEOUT] UID={uid}"
                ) from e

            finally:
                self.log_time("FIND_CHATBOX", t)

        try:
            # =========================
            # OPEN PROFILE
            # =========================
            t = time.perf_counter()

            print(f"\n[+] Đang mở trang cá nhân UID: {uid}")

            user_url = f"https://www.facebook.com/{uid}"

            self.driver.get(user_url)

            self.log_time("OPEN_PROFILE", t)

            # =========================
            # FIND MESSAGE BUTTON
            # =========================
            message_button = find_message_button()

            # =========================
            # CLICK MESSAGE BUTTON
            # =========================
            t = time.perf_counter()

            self.driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});",
                message_button
            )

            message_button.click()

            self.log_time("CLICK_MESSAGE_BUTTON", t)

            # =========================
            # FIND CHATBOX
            # =========================
            chatbox = find_chatbox()

            # =========================
            # INPUT MESSAGE
            # =========================
            t = time.perf_counter()

            time.sleep(random.uniform(0.2, 0.5))

            chatbox.send_keys(content)


            self.log_time("INPUT_MESSAGE", t)

            # =========================
            # SEND MESSAGE
            # =========================
            t = time.perf_counter()


            time.sleep(random.uniform(0.5, 1.5))

            self.log_time("SEND_MESSAGE", t)

            # =========================
            # CLEAR CHATBOX
            # =========================
            t = time.perf_counter()

            try:
                chatbox.send_keys(Keys.CONTROL, "a")
                chatbox.send_keys(Keys.DELETE)
            except Exception as e:
                print(
                    f"[!] Clear chatbox failed UID={uid}: {e}"
                )

            self.log_time("CLEAR_CHATBOX", t)

            # =========================
            # CLOSE CHAT
            # =========================
            close_chat()

            print(
                f"[TOTAL] UID={uid}: "
                f"{time.perf_counter() - total_start:.3f}s"
            )

            return True

        except Exception as e:
            print(f"[❌] {e}")

            print(
                f"[TOTAL] UID={uid}: "
                f"{time.perf_counter() - total_start:.3f}s"
            )

            return False


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
        def close_chat():
            try:
                print("[+] Đang đóng chat...")
                input("")

                close_button = self.driver.find_element(
                    By.XPATH,
                    '//div[@aria-label="Close chat"]'
                )

                close_button.click()

                print("[+] Đã đóng chat")

            except Exception as e:
                print(
                    f"[!] Close chat failed UID={uid}: {e}"
                )

        def find_message_button():
            try:
                message_button = WebDriverWait(self.driver, 2).until(
                    EC.element_to_be_clickable((
                        By.XPATH,
                        '//div[@aria-label="Message" or @aria-label="Nhắn tin"]'
                    ))
                )

                print("[+] Đã tìm thấy nút Message")

            except TimeoutException as e:
                raise Exception(
                    f"[MESSAGE_BUTTON_TIMEOUT] UID={uid}"
                ) from e
            
            except NoSuchElementException as e:
                raise Exception(
                    f"[MESSAGE_BUTTON_NOT_FOUND] UID={uid}"
                ) from e
            
            return message_button
            
        def find_chatbox():
            try:
                chatbox_xpath = (
                    '//div[contains(@aria-label, "Write to")]'
                )

                chatbox = WebDriverWait(self.driver, 3).until(
                    EC.presence_of_element_located(
                        (By.XPATH, chatbox_xpath)
                    )
                )

                print("[+] Đã tìm thấy chatbox")

            except TimeoutException as e:
                close_chat()
                raise Exception(
                    f"[CHATBOX_TIMEOUT] UID={uid}"
                ) from e
            
            return chatbox

        def clear_chatbox():
            try:
                print("[+] Đang clear chatbox...")

                chatbox.send_keys(Keys.CONTROL, "a")
                chatbox.send_keys(Keys.DELETE)

                print("[+] Đã clear chatbox")

            except Exception as e:
                print(
                    f"[!] Clear chatbox failed UID={uid}: {e}"
                )

        try:
            # =========================
            # OPEN PROFILE
            # =========================
            try:
                print(f"\n[+] Đang mở trang cá nhân UID: {uid}")

                user_url = f"https://www.facebook.com/{uid}"
                self.driver.get(user_url)

            except Exception as e:
                raise Exception(
                    f"[OPEN_PROFILE_FAILED] UID={uid}"
                ) from e

            # =========================
            # FIND MESSAGE BUTTON
            # =========================
            message_button = find_message_button()

            
            # =========================
            # CLICK MESSAGE BUTTON
            # =========================
            try:
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});",
                    message_button
                )

                message_button.click()

                print("[+] Đã click Message")

            except ElementClickInterceptedException as e:
                raise Exception(
                    f"[MESSAGE_BUTTON_CLICK_BLOCKED] UID={uid}"
                ) from e

            except Exception as e:
                raise Exception(
                    f"[MESSAGE_BUTTON_CLICK_FAILED] UID={uid}"
                ) from e

            # =========================
            # FIND CHATBOX
            # =========================
            chatbox = find_chatbox()

            # =========================
            # INPUT MESSAGE
            # =========================
            try:
                print(f"[+] Đang nhập tin nhắn: '{content}'")

                time.sleep(random.uniform(0.2, 0.5))
                self.type_content_to_editor(chatbox, content)

                print("[+] Đã nhập tin nhắn")
                input("")

            except Exception as e:
                raise Exception(
                    f"[INPUT_MESSAGE_FAILED] UID={uid}"
                ) from e


            # =========================
            # SEND MESSAGE
            # =========================
            try:
                print("[+] Đang gửi tin nhắn...")

                input("")
                # send_button.click()
                #chatbox.click(Keys.ENTER)
                time.sleep(random.uniform(0.5, 1.5))

                print("[🔑] Gửi thành công!")

            except Exception as e:
                raise Exception(
                    f"[SEND_MESSAGE_FAILED] UID={uid}"
                ) from e


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
    
    def create_post(self, img_paths=[]):
        self.driver.get("https://www.facebook.com/me")
        post_box_xpath = "//span[contains(text(),'mind') or contains(text(),'nghĩ gì') or contains(text(),'something') or contains(text(),'viết gì')]"


        input()
        post_box = self.driver.find_element(By.XPATH, post_box_xpath)
        post_box.click()

        time.sleep(2)


        input()
        composer = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, "//div[@role='dialog' and @aria-modal='true']")
            )
        )

        print(composer.get_attribute("outerHTML")[:200])
        # Cô lập Form
        input()
        editor = composer.find_element(
            By.XPATH,
            ".//div[@role='textbox']"
        )

        editor.click()
        editor.send_keys("ABC!!!")

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
            print(f"Thêm ảnh {img_path}")
            file_input.send_keys(img_path)


    def scan_posts(self, search_string, num_posts=15, keywords=None, on_data=None, output_queue=None, stop_event=None) -> list:
        search_box = WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located(
                (By.XPATH, "//input[@type='search' and @role='combobox']")
            )
        )

        search_box.click()

        time.sleep(1)
        search_box.send_keys(search_string)

        time.sleep(1)
        search_box.send_keys(Keys.ENTER)

        checkbox = WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//input[@role='switch' and (@aria-label='Bài viết mới đây' or @aria-label='Recent posts')]"
            ))
        )
        checkbox.click()
        time.sleep(5)

        
        # elements = self.driver.find_elements(
        #     By.XPATH,
        #     "//*[@role='feed']//*[@data-virtualized]"
        # )

        # for el in elements[:2]:
        #     print(el.get_attribute("data-virtualized"))

        # Watcher
        seen = set()
        latest_count = 0

        def emit(payload):
            """
            Đẩy dữ liệu ra ngoài theo 2 kiểu:
            - callback `on_data(payload)`
            - queue `output_queue.put(payload)`
            """
            if on_data:
                on_data(payload)

            if output_queue:
                output_queue.put(payload)

        def parse_visible_post_html(html):
            if BeautifulSoup is None:
                return {
                    "root_name": None,
                    "text": "",
                    "links": [],
                    "images": [],
                    "attrs": {},
                    "prettify": "",
                    "error": "beautifulsoup4 is not installed",
                }

            soup = BeautifulSoup(html or "", "html.parser")

            links = []
            for a in soup.find_all("a", href=True):
                links.append({
                    "text": a.get_text(" ", strip=True),
                    "href": a.get("href"),
                })

            images = []
            for img in soup.find_all("img"):
                images.append({
                    "alt": img.get("alt"),
                    "src": img.get("src"),
                })

            
            element = soup.find(attrs={"data-ad-rendering-role": "story_message"})

            if element:
                # 1. Lấy toàn bộ text và xóa khoảng trắng thừa
                text = element.get_text(separator="\n", strip=True)
                
                # 2. Chuyển về chữ thường để lọc không phân biệt hoa thường
                text_lower = text.lower()
                
                # 3. Kiểm tra xem có chứa ĐỒNG THỜI cả 2 từ khóa hay không
                if "cần" in text_lower and "bobo" in text_lower:
                    print("🟢 PHÁT HIỆN BÀI ĐĂNG PHÙ HỢP:")
                    print(text)
                    print("-" * 30)
                else:
                    # Bài viết không chứa đủ từ khóa, bỏ qua không in
                    pass

            return {
                "root_name": soup.name,
                "text": soup.get_text(" ", strip=True),
                "links": links,
                "images": images,
                "attrs": dict(soup.attrs) if getattr(soup, "attrs", None) else {},
                "prettify": soup.prettify(),
            }

        def normalize_keywords(value):
            if value is None:
                return []

            if isinstance(value, str):
                items = [value]
            else:
                items = list(value)

            normalized = []
            for item in items:
                if item is None:
                    continue
                text = str(item).strip().lower()
                if text:
                    normalized.append(text)
            return normalized

        def post_matches_keywords(post_text, post_html, keyword_list):
            if not keyword_list:
                return True

            haystack = f"{post_text}\n{post_html}".lower()
            return all(keyword in haystack for keyword in keyword_list)

        normalized_keywords = normalize_keywords(keywords)

        while True:
            if stop_event and stop_event.is_set():
                emit({
                    "type": "stopped",
                    "reason": "stop_event",
                    "latest_count": latest_count,
                })
                break

            posts = self.driver.find_elements(
                By.XPATH,
                "//*[@role='feed']//*[@data-virtualized]"
            )

            count = len(posts)
            latest_count = count

            visible_posts = []
            for index, post in enumerate(posts[:num_posts], start=1):
                # Xử lý thông tin bài đăng
                try:
                    html = post.get_attribute("outerHTML") or ""
                    parsed_html = parse_visible_post_html(html)
                    text = parsed_html["text"]
                except Exception as e:
                    text = ""
                    html = ""
                    parsed_html = {
                        "root_name": None,
                        "text": "",
                    "links": [],
                    "images": [],
                    "attrs": {},
                    "prettify": "",
                        "error": str(e),
                    }

                if not post_matches_keywords(text, html, normalized_keywords):
                    continue

                # Lưu vào list
                visible_posts.append({
                    "index": index,
                    "text": text,
                    "html": html,
                    "parsed_html": parsed_html,
                    "matched_keywords": normalized_keywords,
                })

            emit({
                "type": "scan_update",
                "search_string": search_string,
                "count": count,
                "visible_posts": visible_posts,
                "matched_count": len(visible_posts),
                "keywords": normalized_keywords,
            })

            # Nếu số lượng bài bé hơn num_posts thì tiếp tục cuộn
            if count < num_posts:
                self.driver.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight);"
                )

                time.sleep(3)
            else:
                time.sleep(30)
                self.driver.refresh()
                time.sleep(5)
        



def create_excel_file(data, headers, filename="results.xlsx"):
    wb = Workbook()
    ws = wb.active
    ws.title = "Results"

    # Headers
    ws.append(headers)

    # Data rows
    for row in data:
        ws.append(row)

    wb.save(filename)

    print(f"Excel file '{filename}' created successfully.")

# -------------------------
# RUN
# -------------------------
uids = [
    '100013059309976',
    '100001613059371',
    '100008061095208',
    '100009400587023'
]

email = 'gurasyn@gmail.com'
password = 'saile123456!'

def main():
    start = time.perf_counter()

    
    bot = FacebookBot(email, password)
    bot.ensure_login()

    link = 'https://www.facebook.com/share/v/1HjuUTp6Po/'
    content = f'''
        🚀 THE WIN CITY - ĐÓN SÓNG HẠ TẦNG KHU TÂY SÀI GÒN

        📈 Cú hích hạ tầng: Vành đai 3, 4, cao tốc TP.HCM - Mộc Bài thúc đẩy Đức Hòa - Hậu Nghĩa hóa "rồng" công nghiệp & logistics.
        🏙️ The Win City: Tọa lạc vị trí chiến lược, đón trọn tiềm năng tăng trưởng liên vùng.

        ▶️ Thông tin chi tiết: {link}
    '''

    bot.perform_search()


    bot.close()

    end = time.perf_counter()
    print(f'Total time: {end - start:.2f} seconds')


if __name__ == "__main__":
    main()
