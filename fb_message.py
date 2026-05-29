from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import random

# --- CẤU HÌNH THÔNG TIN ---
FB_UID = "61579574484979"  # Thay bằng UID người nhận
TIN_NHAN = "Xin chào! Đây là tin nhắn tự động từ Selenium."

# Khởi tạo WebDriver (ở đây dùng Chrome)
options = webdriver.ChromeOptions()
options.add_argument("--disable-notifications")  # Tắt thông báo phiền phức
driver = webdriver.Chrome(options=options)
driver.maximize_window()

try:
    # 1. ĐĂNG NHẬP FACEBOOK
    # Cách tốt nhất là bạn nên dùng Profile đã đăng nhập sẵn hoặc nạp Cookie.
    # Ở đây demo cách vào trang login truyền thống:
    driver.get("https://www.facebook.com")
    
    print("Vui lòng đăng nhập vào Facebook trên trình duyệt đang mở...")

    # Nếu muốn tự động hoàn toàn, bạn có thể tự thêm điền email/pass vào đây.
    input("Nhấn phím Enter sau khi đã đăng nhập xong...")

    # 2. ĐI ĐẾN HỘP THOẠI VỚI UID
    print(f"Đang mở hộp thoại với UID: {FB_UID}")
    user_url = f"https://www.facebook.com/{FB_UID}"
    driver.get(user_url)
    
    # Đợi hộp thoại chat tải xong (chờ khung nhập tin nhắn xuất hiện)
    # Facebook thường dùng thuộc tính role="textbox" cho ô nhập liệu Messenger
    wait = WebDriverWait(driver, 20)

    try:
        # 1. Tìm và click vào NÚT Nhắn tin có aria-label="Message" hoặc "Nhắn tin"
        print("Đang tìm nút Nhắn tin trên trang cá nhân...")
        
        # Xpath này quét cả 2 ngôn ngữ Anh/Việt cho chắc chắn nhé bạn
        nut_nhan_tin = wait.until(
            EC.element_to_be_clickable((By.XPATH, '//div[@aria-label="Message" or @aria-label="Nhắn tin"]'))
        )
        nut_nhan_tin.click()
        print("Đã click vào nút Nhắn tin!")

    except Exception as e:
        print(f"Không tìm thấy nút hoặc lỗi khi nhắn tin: {e}")
    
    # Giữ lại giao diện vài giây để kiểm tra kết quả
    time.sleep(5)

    input("Enter để tắt...")

except Exception as e:
    print(f"Có lỗi xảy ra: {e}")

finally:
    # Đóng trình duyệt
    driver.quit()