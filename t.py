from playwright.sync_api import sync_playwright

url = (
    "https://www.facebook.com/ads/library/"
    "?active_status=all"
    "&ad_type=all"
    "&country=VN"
    "&q=iphone"
)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)

    page = browser.new_page()

    page.goto(url)

    # đợi ads load
    page.wait_for_timeout(8000)

    # thử selector phổ biến
    ads = page.locator('div[role="article"]')

    count = ads.count()

    print(f"Ads found: {count}")

    browser.close()