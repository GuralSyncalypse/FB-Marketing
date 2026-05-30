from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from concurrent.futures import ThreadPoolExecutor
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException
from openpyxl import Workbook
from queue import Queue, Empty
import threading
import random
import time
import pickle
import os
import re

group_id = '3636784079935693'
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

        self.init_driver(False)

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

    def is_logged_in(self, timeout=5):
        driver = self.driver

        try:
            # Wait for either login form OR logged-in UI
            WebDriverWait(driver, timeout).until(
                lambda d: (
                    d.find_elements(By.NAME, "email") or   # login form
                    d.find_elements(By.XPATH, "//div[@role='navigation']")
                )
            )

            # If login form exists → not logged in
            if driver.find_elements(By.NAME, "email"):
                return False

            # If navigation exists → logged in
            if driver.find_elements(By.XPATH, "//div[@role='navigation']"):
                return True

            return False

        except:
            return False

    def handle_checkpoint(self):
        driver = self.driver
        time.sleep(3)

        # Click Continue
        btn = driver.find_element(
            By.XPATH,
            "//*[@role='button' and contains(., 'Continue')]"
        )
        btn.click()


        # Re-enter password
        password_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "pass"))
        )
        if password_input:
            password_input.clear()
            password_input.send_keys(self.password)
            password_input.send_keys(Keys.RETURN)

            time.sleep(2)

            print("🔐 Re-entered password")

        

    # -------------------------
    # STEP 1: Manual login + save cookies
    # -------------------------
    def load_cookie_data(path):
        if not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except:
            return None

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

    # -------------------------
    # STEP 2: Load cookies
    # -------------------------
    def login_with_cookies(self):
        driver = self.driver
        driver.get("https://www.facebook.com/")

        # ❗ Check if cookie file exists
        if not os.path.exists(self.cookie_file):
            print("⚠️ No cookie file found")
            return False

        try:
            cookies = pickle.load(open(self.cookie_file, "rb"))
        except Exception as e:
            print("❌ Failed to load cookies:", e)
            return False

        for cookie in cookies:
            cookie.pop("sameSite", None)
            try:
                driver.add_cookie(cookie)
            except:
                pass

        driver.refresh()
        time.sleep(3)

        # 👇 HANDLE CHECKPOINT HERE
        if not self.is_logged_in():
            print("⚠️ Not fully logged in")
            self.handle_checkpoint()

        print("✅ Logged in (after checkpoint if needed)")

        time.sleep(random.uniform(0.5, 1))
        return True

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

    def collect_members(self, max_scroll=50):
        driver = self.driver
        collected = set()
        seen_links = set()

        last_index = 0
        xpath = "//div[@role='listitem']//a[@role='link']"

        for i in range(max_scroll):
            print(f"🔄 Scroll {i+1}")

            elements = driver.find_elements(By.XPATH, xpath)

            if not elements:
                print("⚠️ No elements found")
                break

            old_last = elements[-1].get_attribute("href")

            new_elements = elements[last_index:]
            last_index = len(elements)

            for e in new_elements:
                link = e.get_attribute("href")

                if not link or link in seen_links:
                    continue

                if any(x in link for x in ["photo", "story", "reel", "watch"]):
                    continue

                seen_links.add(link)

                user_id = self.extract_user_id(link)
                if user_id:
                    collected.add(user_id)

            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)
            

        print(len(collected))
        return collected

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

        file_path = "users.txt"

        with open(file_path, "w", encoding="utf-8") as f:
            for u in users:
                f.write(f"{u}\n")

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

    def send_message_via_uid(self, uid, content):
        def close_chat():
            try:
                print("[+] Đang đóng chat...")

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

        wait = WebDriverWait(self.driver, 20)

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
                chatbox.send_keys(content)

                print("[+] Đã nhập tin nhắn")

            except Exception as e:
                raise Exception(
                    f"[INPUT_MESSAGE_FAILED] UID={uid}"
                ) from e


            # =========================
            # SEND MESSAGE
            # =========================
            try:
                print("[+] Đang gửi tin nhắn...")

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
    'giang.tien.trung',
    '61579574484979',
    '100005598214623',
    '100085462167190',
    '100005461662862',
    '100090647756824',
    '100073770454108',
    '100005180834862',
    '100091656182252',
    '100068953794888'
]

email = 'gurasyn@gmail.com'
password = 'saile123456!'


if __name__ == "__main__":
    bot = FacebookBot(email, password)
    bot.ensure_login()
    data = []
    start = time.perf_counter()

    input("XX")

    content = 'Hello World!'
    for uid in uids:
        result = bot.send_message_via_uid(uid, content)
        data.append([uid, result])

    end = time.perf_counter()
    create_excel_file(data, ['ID', 'Result'])

    print(f'Total time: {end - start:.2f} seconds')