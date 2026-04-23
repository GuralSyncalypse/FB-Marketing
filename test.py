from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import random
import time
import pickle
import os
import re

urls = [
    'https://www.facebook.com/groups/772363718813700'
]

class FacebookBot:
    def __init__(self, email, password):
        self.email = email
        self.password = password
        self.driver = webdriver.Chrome()
        self.cookie_file = "fb_cookies.pkl"

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

            try:
                WebDriverWait(driver, 10).until(
                    lambda d: (
                        elems := d.find_elements(By.XPATH, xpath)
                    ) and elems[-1].get_attribute("href") != old_last
                )
            except:
                print("⚠️ No new content → stop scrolling")
                break

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


# -------------------------
# RUN
# -------------------------
if __name__ == "__main__":
    username = '0767214918'
    password = 'LProtogen03!'
    bot = FacebookBot(username, password)

    bot.ensure_login()
    bot.perform_search()

    input("Press Enter to exit...")
    bot.close()