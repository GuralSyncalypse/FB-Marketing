# Đánh giá sơ bộ `main.py` và thư mục `views`

## Phạm vi

Tài liệu này ghi nhận kết quả rà soát `main.py` và các màn hình trong `views/`, tập trung vào luồng Tkinter, Selenium, lưu trạng thái và xử lý thread.

Kiểm tra cú pháp hiện tại đạt `COMPILE_OK`. Chưa thực hiện chạy Facebook/Selenium thực tế vì cần môi trường Chrome, profile và tài khoản tương ứng.

## Các vấn đề chính

### 1. Truy cập Tkinter từ background thread — mức cao

Local HTTP server gọi callback `App.on_server_received()` từ thread riêng. Hàm này đang cập nhật trực tiếp các widget Tkinter, gọi `load_data()`, `update_group_selection()` và refresh view. Tkinter chỉ an toàn khi thao tác widget trên main thread; tình trạng này có thể gây treo hoặc lỗi ngẫu nhiên.

Các màn hình cũng còn đọc dữ liệu giao diện trong worker:

- `views/dev_screen.py` đọc Entry, Treeview và User Agent trong luồng Selenium.
- `views/uid_scan_screen.py` đọc `IntVar` trong luồng quét.
- `main.py` thay đổi `groups_data` trong worker trong khi UI có thể đang đọc.

Trạng thái hoàn tất:

- [x] Callback HTTP server chỉ đưa dữ liệu vào hàng đợi thread-safe; main thread xử lý hàng đợi và cập nhật Tkinter.
- [x] Quét UID snapshot `max_members` và `retries` trước khi tạo worker thread.
- [ ] Đề xuất: Dev Mode vẫn cần một đợt riêng để snapshot Entry/Treeview trước khi chạy Selenium.

### Cải thiện UI theo phạm vi hiện tại — đã xử lý

- [x] Nút `Quét` trong popup Danh sách nhóm được bật lại trong `finally`, kể cả khi đăng nhập lỗi, UID bận hoặc worker exception.
- [x] UID được đặt chỉ đọc; ứng dụng giữ luồng nghiệp vụ chỉ nhận UID từ Extension và thông báo rõ khi chưa kết nối Extension.
- [x] Mỗi lượt Quét UID mới xóa bảng kết quả và `scan_results` cũ trước khi bắt đầu.

### 2. Cleanup Selenium chưa đồng nhất — mức cao — đã xử lý phần an toàn cơ bản

Một số màn hình đã kiểm tra driver trước khi đóng, nhưng Dev Mode vẫn gọi `self.current_bot.close()` trực tiếp trong `finally`. Nếu khởi tạo thất bại hoặc driver đã bị đóng từ nút Stop, cleanup có thể phát sinh lỗi thứ cấp và che lỗi gốc.

`main.py.__on_close()` cũng cần bảo đảm `destroy()` luôn được gọi kể cả khi lưu dữ liệu thất bại.

Trạng thái hoàn tất:

- [x] Dev Mode chỉ đóng bot khi instance tồn tại và không để lỗi cleanup che lỗi chính.
- [x] UID Scan khởi tạo `bot_obj = None` trước khối `try`, nên `finally` an toàn nếu tạo bot thất bại.
- [x] `main.py.__on_close()` gọi `destroy()` trong `finally`, kể cả khi lưu dữ liệu lỗi.
- [ ] Đề xuất: tập trung hóa cleanup Selenium vào một helper chung khi có đợt refactor riêng.

### 3. Dùng chung Chrome profile giữa nhiều luồng — mức cao

## Phân tích chi tiết

`bot.FacebookBot.start_browser()` luôn tạo profile theo UID:

```text
./profiles/<UID>
```

Các màn hình đều gọi cùng cơ chế này:

- `main.py`: quét danh sách group.
- `views/dev_screen.py`: share bài.
- `views/post_screen.py`: đăng bài.
- `views/sms_screen.py`: gửi tin nhắn.
- `views/uid_scan_screen.py`: quét UID.

Vì vậy, nếu hai tác vụ cùng chạy cho một UID, cả hai Selenium process sẽ cố mở cùng `user-data-dir`. Chrome thường chỉ cho phép một process sở hữu profile tại một thời điểm. Process thứ hai có thể thoát ngay với lỗi:

```text
DevToolsActivePort file doesn't exist
```

Lỗi này cũng có thể xảy ra sau khi app bị tắt bất thường và Chrome cũ vẫn còn chạy, hoặc profile bị khóa/hỏng. Cơ chế fallback từ Undetected Chrome sang Selenium Standard hiện vẫn dùng cùng profile, nên không giải quyết được profile lock.

Ngoài ra, `undetected_chromedriver` đang được gọi với `version_main=150`. Nếu Chrome trên máy khách có major version khác, UC có thể không khởi động được dù profile không bị khóa.

## Tình huống tái hiện

1. Mở Dev Mode cho UID A.
2. Trong lúc tác vụ chưa kết thúc, mở SMS hoặc Quét UID cho cùng UID A.
3. Hai bot cùng dùng `profiles/A`.
4. Một Chrome process không mở được profile; log thường xuất hiện lỗi DevToolsActivePort.

Tình huống tương tự xảy ra nếu đóng app bằng Task Manager rồi mở lại ngay.

## Hướng thiết kế đề xuất

### Phương án khuyến nghị: khóa profile theo UID

Tạo một cơ chế quản lý profile tập trung trong `bot.py` hoặc module riêng:

```text
profile_lock[uid]
```

Khi bắt đầu `start_browser()`:

1. Thử lấy lock theo UID.
2. Nếu UID đang được sử dụng, từ chối task mới và báo rõ: `UID đang có tác vụ khác`.
3. Chỉ nhả lock sau khi `driver.quit()` hoàn tất.

Ưu điểm: giữ nguyên cookies/profile lâu dài và tránh hai Chrome dùng chung dữ liệu.

### Trạng thái tích hợp hiện tại

Đã tích hợp lock theo UID trong `bot.FacebookBot`. Mỗi instance gọi `start_browser()` phải lấy lock không chờ; nếu UID đang bận thì hàm trả về `False` và không khởi tạo Chrome. `close()` luôn nhả lock, kể cả khi driver không tạo thành công.

Lock này hoạt động cho mọi task trong cùng một instance ứng dụng, nên 10 UID có thể chạy song song nhưng cùng một UID chỉ có một task.

Trạng thái hoàn tất:

- [x] Dev, Post, SMS, Quét Group và Quét UID hiển thị thông báo `UID đang có tác vụ khác` thay cho `Đăng nhập thất bại` khi lock từ chối task.
- [ ] Đề xuất: bổ sung hàng đợi task theo UID nếu muốn tự chạy task kế tiếp thay vì yêu cầu người dùng thử lại.

Giới hạn cần lưu ý: lock hiện tại là lock trong bộ nhớ của một process. Nếu người dùng mở hai bản ứng dụng độc lập trên cùng máy, hai process vẫn không biết nhau. Nếu cần bảo vệ trường hợp đó, nên bổ sung file lock hoặc OS mutex theo UID; đây là đề xuất cho giai đoạn tiếp theo, chưa tích hợp để tránh thay đổi cơ chế triển khai hiện tại.

### Phương án thay thế: profile runtime riêng cho từng task

Giữ profile gốc làm nguồn cookies, nhưng mỗi task dùng thư mục riêng:

```text
profiles/<UID>/                 # dữ liệu chính
profiles_runtime/<UID>/<task>   # profile Chrome đang chạy
```

Cookies cần được nạp vào runtime profile trước khi mở Chrome. Cách này cho phép chạy song song, nhưng đồng bộ cookies và trạng thái đăng nhập phức tạp hơn.

## Thứ tự ưu tiên xử lý

1. Không cho phép chạy đồng thời nhiều task cùng UID.
2. Bỏ `version_main=150` cố định hoặc tự phát hiện major version Chrome.
3. Khi fallback Standard, không dùng lại profile đang bị khóa.
4. Cleanup profile/driver trong `finally` an toàn.
5. Thêm log rõ: UID, task, profile path, driver mode và Chrome version.
6. Chỉ xóa các file khóa khi chắc chắn không còn `chrome.exe` sử dụng profile; không xóa `cookies.json` mặc định.

## Cách xử lý tạm thời trên máy khách

1. Đóng ứng dụng.
2. Kết thúc toàn bộ `chrome.exe` còn chạy.
3. Thử đổi tên `profiles/<UID>` thành `profiles/<UID>.bak`.
4. Chạy lại để kiểm tra profile mới.

Nếu chạy được sau bước này, nguyên nhân gần như chắc chắn là profile bị khóa hoặc hỏng. Không nên xóa profile gốc ngay; cần giữ bản `.bak` để bảo toàn cookies và điều tra thêm.

## Kết luận

Lỗi profile dùng chung là rủi ro kiến trúc, không chỉ là lỗi riêng của Undetected ChromeDriver. Cần quản lý vòng đời profile tập trung và giới hạn mỗi UID chỉ có một Selenium task hoạt động tại một thời điểm trước khi bàn giao cho nhiều máy khách.
