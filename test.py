from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
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

    def is_logged_in(self):
        try:
            self.driver.find_element(By.XPATH, "//div[@role='feed']")
            return True
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
    def login_and_save_cookies(self):
        driver = self.driver
        driver.get("https://www.facebook.com/")

        time.sleep(2)

        email_input = driver.find_element(By.NAME, "email")
        password_input = driver.find_element(By.NAME, "pass")

        email_input.send_keys(self.email)
        password_input.send_keys(self.password)
        password_input.send_keys(Keys.RETURN)

        print("👉 Complete 2FA if required...")

        # Save cookies
        cookies = driver.get_cookies()
        with open(self.cookie_file, "wb") as f:
            pickle.dump(cookies, f)

        print("✅ Cookies saved!")

    # -------------------------
    # STEP 2: Load cookies
    # -------------------------
    def login_with_cookies(self):
        driver = self.driver
        driver.get("https://www.facebook.com/")

        cookies = pickle.load(open(self.cookie_file, "rb"))

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

        # Final check
        if "login" in driver.current_url:
            print("❌ Still not logged in")
            return False

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

        last_count = 0

        for i in range(max_scroll):
            print(f"🔄 Scroll {i+1}")

            elements = driver.find_elements(
                By.XPATH,
                "//div[@role='listitem']//a[@role='link']"
            )

            new_count = 0

            for e in elements:
                link = e.get_attribute("href")

                if not link or link in seen_links:
                    continue

                seen_links.add(link)

                user_id = self.extract_user_id(link)
                if user_id:
                    collected.add(user_id)
                    new_count += 1

            print(f"➕ New this round: {new_count}")
            print(f"✅ Total: {len(collected)}")

            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")



            if len(collected) == last_count:
                print("⛔ No new users → stopping")
                break

            last_count = len(collected)


        return list(collected)

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

        # 👇 Collect during scroll
        users = self.collect_members()

        for u in users:
            print(u)

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