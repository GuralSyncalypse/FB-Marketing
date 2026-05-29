from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from concurrent.futures import ThreadPoolExecutor
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException
from openpyxl import Workbook
from queue import Queue
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
    def send_message_via_uid(self, uid, content):
        def close_chat():
            try:
                print("[+] Đang đóng chat...")

                close_button = wait.until(
                    EC.element_to_be_clickable((
                        By.XPATH,
                        '//div[@aria-label="Close chat"]'
                    ))
                )

                time.sleep(random.uniform(0.5, 1.5))

                close_button.click()

                print("[+] Đã đóng chat")

            except Exception as e:
                print(
                    f"[!] Close chat failed UID={uid}: {e}"
                )


        wait = WebDriverWait(self.driver, 20)

        try:
            # =========================
            # OPEN PROFILE
            # =========================
            try:
                print(f"\n[+] Đang mở trang cá nhân UID: {uid}")

                user_url = f"https://www.facebook.com/messages/t/{uid}"
                self.driver.get(user_url)

            except Exception as e:
                raise Exception(
                    f"[OPEN_PROFILE_FAILED] UID={uid}"
                ) from e

            # =========================
            # FIND MESSAGE BUTTON
            # =========================
            try:
                print("[+] Đang tìm nút 'Nhắn tin'...")

                message_button = wait.until(
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

            # =========================
            # CLICK MESSAGE BUTTON
            # =========================
            try:
                print("[+] Đang click nút Message...")

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
            try:
                print("[+] Đang đợi chatbox...")

                chatbox_xpath = (
                    '//div[contains(@aria-label, "Write to")]'
                )

                chatbox = wait.until(
                    EC.presence_of_element_located((
                        By.XPATH,
                        chatbox_xpath
                    ))
                )

                print("[+] Đã tìm thấy chatbox")

            except TimeoutException as e:
                
                raise Exception(
                    f"[CHATBOX_TIMEOUT] UID={uid}"
                ) from e

            # =========================
            # INPUT MESSAGE
            # =========================
            try:
                print(f"[+] Đang nhập tin nhắn: '{content}'")

                time.sleep(random.uniform(1.5, 3))

                chatbox.send_keys(content)

                print("[+] Đã nhập tin nhắn")

            except Exception as e:
                raise Exception(
                    f"[INPUT_MESSAGE_FAILED] UID={uid}"
                ) from e

            # =========================
            # FIND SEND BUTTON
            # =========================
            try:
                print("[+] Đang tìm nút Gửi...")

                nut_gui_xpath = (
                    '//div[@aria-label="Press enter to send" '
                    'or @aria-label="Nhấn enter để gửi"]'
                )

                send_button = wait.until(
                    EC.element_to_be_clickable((
                        By.XPATH,
                        nut_gui_xpath
                    ))
                )

                print("[+] Đã tìm thấy nút Gửi")

            except TimeoutException as e:
                raise Exception(
                    f"[SEND_BUTTON_TIMEOUT] UID={uid}"
                ) from e

            # =========================
            # SEND MESSAGE
            # =========================
            try:
                print("[+] Đang gửi tin nhắn...")

                # send_button.click()
                #chatbox.click(Keys.ENTER)

                print("[🔑] Gửi thành công!")

            except Exception as e:
                raise Exception(
                    f"[SEND_MESSAGE_FAILED] UID={uid}"
                ) from e

            # =========================
            # CLEAR CHATBOX
            # =========================
            try:
                print("[+] Đang clear chatbox...")

                chatbox.send_keys(Keys.CONTROL, "a")
                chatbox.send_keys(Keys.DELETE)

                print("[+] Đã clear chatbox")

            except Exception as e:
                print(
                    f"[!] Clear chatbox failed UID={uid}: {e}"
                )

            # =========================
            # CLOSE CHAT
            # =========================
            close_chat()

            return True

        except Exception as e:
            print(f"[❌] {e}")
            return False
        
    def send_message_via_uid_direct(self, uid, content):
        wait = WebDriverWait(self.driver, 20)

        try:
            # =========================
            # OPEN PROFILE
            # =========================
            try:
                print(f"\n[+] Đang mở trang cá nhân UID: {uid}")

                user_url = f"https://www.facebook.com/messages/t/{uid}"
                self.driver.get(user_url)

            except Exception as e:
                raise Exception(
                    f"[OPEN_PROFILE_FAILED] UID={uid}"
                ) from e


            # =========================
            # FIND CHATBOX
            # =========================
            try:
                print("[+] Checking Continue button...")

                if not self.one_time_code_exist:
                    try:
                        input("xx")
                        pin_check = WebDriverWait(self.driver, 3).until(
                            EC.presence_of_element_located((
                                By.XPATH,
                                '//input[@autocomplete="one-time-code"]'
                            ))
                        )

                        print('[+] Found PIN input')

                        pin_check.send_keys('100903')
                        time.sleep(3)
                        self.one_time_code_exist = True

                    except:
                        print('[-] PIN input not found')
                        self.one_time_code_exist = True
                

                try:
                    continue_xpath = (
                        '//div[@aria-label="Continue"]'
                    )

                    continue_button = WebDriverWait(self.driver, 3).until(
                        EC.element_to_be_clickable((
                            By.XPATH,
                            continue_xpath
                        ))
                    )

                    continue_button.click()
                    time.sleep(1)
                
                except Exception as e:
                    print("Found no Continue")

                print("[+] Waiting for chatbox...")

                chatbox_xpath = (
                    '//div[contains(@aria-label, "Write to")]'
                )

                chatbox = wait.until(
                    EC.presence_of_element_located((
                        By.XPATH,
                        chatbox_xpath
                    ))
                )

                print("[+] Found chatbox")

            except TimeoutException as e:
                raise Exception(
                    f"[CHATBOX_TIMEOUT] UID={uid}"
                ) from e

            # =========================
            # INPUT MESSAGE
            # =========================
            try:
                print(f"[+] Đang nhập tin nhắn: '{content}'")

                time.sleep(random.uniform(1.5, 3))

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

                print("[🔑] Gửi thành công!")

            except Exception as e:
                raise Exception(
                    f"[SEND_MESSAGE_FAILED] UID={uid}"
                ) from e

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

# Queue chứa UID
uid_queue = Queue()
data = []
for uid in uids:
    uid_queue.put(uid)


# Tạo event global
login_done = threading.Event()


def worker(worker_id):

    bot = FacebookBot('0767214918', 'LProtogen03!')

    if worker_id == 1:

        print(f'[Worker {worker_id}] Login first...')

        bot.ensure_login()

        # Xử lý UID đầu tiên
        uid = uid_queue.get_nowait()

        result = bot.send_message_via_uid_direct(
            uid,
            'Hello'
        )

        data.append([uid, result])

        print(f'[+] First UID done: {uid}')

        uid_queue.task_done()

        # Báo cho main thread biết đã xong
        login_done.set()

    while not uid_queue.empty():

        try:
            uid = uid_queue.get_nowait()

        except:
            break

        try:
            print(f'Worker {worker_id} sending to {uid}')

            result = bot.send_message_via_uid_direct(
                uid,
                'Hello'
            )

            data.append([uid, result])

        except Exception as e:
            print(f'Error {uid}: {e}')

        finally:
            uid_queue.task_done()

    bot.driver.quit()


if __name__ == "__main__":
    # bot = FacebookBot('0767214918', 'LProtogen03!')

    # bot.ensure_login()

    start = time.perf_counter()
    # for uid in uids:
    #     bot.send_message_via_uid_direct(uid, 'Hello')
    # 3 browser chạy song song
    with ThreadPoolExecutor(max_workers=3) as executor:

        # Worker đầu tiên chạy trước
        first_worker = executor.submit(worker, 1)

        # Đợi worker 1 xử lý xong phase đầu
        login_done.wait()

        print('[+] Starting other workers...')

        # Worker còn lại chạy sau
        for i in range(2, 4):
            executor.submit(worker, i)

    end = time.perf_counter()
    #create_excel_file(data, ['ID', 'Result'])

    print(f'Total time: {end - start:.2f} seconds')