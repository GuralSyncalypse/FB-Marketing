import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import threading
import urllib.parse
import bot

# Biến toàn cục để lưu trữ tạm thời Cookies nhận từ Extension
TEMPORARY_COOKIES = None
USER_AGENT = ""

# ================= CLASS XỬ LÝ REQUEST TỪ EXTENSION =================
class ExtensionHandler(BaseHTTPRequestHandler):
    def __init__(self, request, client_address, server):
        # Lưu lại tham chiếu tới app tkinter được truyền từ server
        self.app = server.app_reference
        super().__init__(request, client_address, server)

    def do_POST(self):
        global TEMPORARY_COOKIES
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length).decode('utf-8')
        
        try:
            # 1. Parse dữ liệu JSON từ Extension
            data = json.loads(post_data)
            uid = data.get("uid", "Không tìm thấy UID")
            user_agent = data.get("user_agent", "")
            
            # 2. Xử lý gom mảng cookies thành chuỗi string
            cookie_list = data.get("cookie_json", [])
            cookie_pairs = []
            for ck in cookie_list:
                name = ck.get("name")
                value = ck.get("value")
                if name and value:
                    cookie_pairs.append(f"{name}={value}")
            
            cookie_string = "; ".join(cookie_pairs)
            TEMPORARY_COOKIES = data.get("cookie_json", [])
            USER_AGENT = user_agent
            
            # 3. Log debug ra console
            print("\n" + "="*50)
            print("[SERVER] NHẬN DATA THÀNH CÔNG TỪ EXTENSION")
            print(f"-> UID nhận được: {uid}")
            print(f"-> Chuỗi Cookie tạo ra: {TEMPORARY_COOKIES[:80]}...")
            print("="*50)

            # 4. Cập nhật UID lên ô hiển thị dùng chung của giao diện chính
            self.app.server_update_uid_interface(uid)

        except Exception as e:
            print(f"[Server Lỗi] Không thể xử lý JSON: {str(e)}")

        # Phản hồi lại cho Extension
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        return

# ================= CLASS GIAO DIỆN CHÍNH (APP) =================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Phần mềm Quản lý Tính năng - Nhận Data từ Extension")
        self.geometry("950x700")
        
        self.selected_files_s1 = []
        self.selected_files_s2 = []
        
        # --- KHU VỰC CỐ ĐỊNH PHÍA TRÊN: Ô Cấu hình UID dùng chung ---
        top_shared_frame = ttk.LabelFrame(self, text=" Thông tin tài khoản hiện tại (Dùng chung) ", padding=10)
        top_shared_frame.pack(side="top", fill="x", padx=10, pady=5)
        
        self.empty_uid = "Chờ tín hiệu từ Extension..."

        ttk.Label(top_shared_frame, text="UID Hiện tại (Nhận tự động từ Extension):").pack(side="left", padx=(0, 10))
        self.ent_uid_shared = ttk.Entry(top_shared_frame, font=("Arial", 11, "bold"), foreground="blue")
        self.ent_uid_shared.pack(side="left", fill="x", expand=True)
        self.ent_uid_shared.insert(0, self.empty_uid)
        
        # --- KHU VỰC DI CHUYỂN: Giao diện chính chứa các Tab Navigation ---
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=5, pady=5)
        
        self.tab1 = ttk.Frame(self.notebook)
        self.tab2 = ttk.Frame(self.notebook)
        self.notebook.add(self.tab1, text="Dev")
        self.notebook.add(self.tab2, text="Bắn SMS")
        
        # Cài đặt giao diện chi tiết các màn hình
        self.dev_screen()
        self.setup_screen_2()
        
        # KHỞI CHẠY SERVER NGẦM (Mặc định chạy ở port 8000 theo cấu hình của bạn)
        self.start_local_server(port=8000)

    def start_local_server(self, port):
        def run_server():
            server_address = ('', port)
            httpd = HTTPServer(server_address, ExtensionHandler)
            httpd.app_reference = self # Đính kèm tham chiếu App vào server
            print(f"[Server] Đang chạy ngầm tại http://localhost:{port}...")
            httpd.serve_forever()

        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()

    def server_update_uid_interface(self, uid):
        # Cập nhật trực tiếp vào ô dữ liệu dùng chung phía trên
        self.ent_uid_shared.delete(0, tk.END)
        self.ent_uid_shared.insert(0, uid)

    # ================= MÀN HÌNH 1 =================
    def dev_screen(self):
        left_frame = ttk.LabelFrame(self.tab1, text=" Cấu hình & Điều khiển ", padding=10)
        left_frame.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        
        ttk.Label(left_frame, text="Nội dung (Hỗ trợ Icon/Ký tự đặc biệt):").pack(anchor="w", pady=2)
        self.txt_content_s1 = tk.Text(left_frame, height=8, wrap="word")
        self.txt_content_s1.pack(fill="x", pady=5)
        self.txt_content_s1.insert("1.0", "Nhập nội dung tại đây... ✨🚀🔥")

        ttk.Label(left_frame, text="Tập tin đính kèm (Có thể chọn nhiều hình ảnh/video):").pack(anchor="w", pady=5)
        file_frame = ttk.Frame(left_frame)
        file_frame.pack(fill="x", pady=2)
        
        self.txt_files_s1 = tk.Text(file_frame, height=3, wrap="none")
        self.txt_files_s1.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        scrollbar_x = ttk.Scrollbar(left_frame, orient="horizontal", command=self.txt_files_s1.xview)
        self.txt_files_s1.configure(xscrollcommand=scrollbar_x.set)
        
        btn_browse_s1 = ttk.Button(file_frame, text="Chọn files", command=self.browse_multiple_files_s1)
        btn_browse_s1.pack(side="right", anchor="n")
        scrollbar_x.pack(fill="x", pady=(0, 5))

        # Nút Start Màn hình 1
        btn_start_s1 = ttk.Button(left_frame, text="START (Màn hình 1)", command=self.dev_start)
        btn_start_s1.pack(fill="x", pady=20, ipady=5)

        # Cột bên phải: Danh sách lựa chọn kèm checkbox
        right_frame = ttk.LabelFrame(self.tab1, text=" Danh sách nhóm ", padding=10)
        right_frame.pack(side="right", fill="both", padx=10, pady=10)

        self.tree_s1 = ttk.Treeview(right_frame, columns=("Name"), show="tree headings", selectmode="none")
        self.tree_s1.heading("#0", text="Chọn", anchor="w")
        self.tree_s1.heading("Name", text="Tên nhóm", anchor="w")
        self.tree_s1.column("#0", width=60, anchor="center")
        self.tree_s1.column("Name", width=200, anchor="w")
        self.tree_s1.pack(fill="both", expand=True)
            
        self.tree_s1.bind("<Button-1>", self.toggle_checkbox)

    def browse_multiple_files_s1(self):
        file_paths = filedialog.askopenfilenames(filetypes=[("Media Files", "*.png *.jpg *.jpeg *.mp4 *.avi *.mkv"), ("All Files", "*.*")])
        if file_paths:
            self.selected_files_s1 = list(file_paths)
            self.txt_files_s1.delete("1.0", tk.END)
            self.txt_files_s1.insert("1.0", ", ".join(self.selected_files_s1))

    def toggle_checkbox(self, event):
        item = self.tree_s1.identify_row(event.y)
        column = self.tree_s1.identify_column(event.x)
        if item and column == "#0":
            current_status = self.tree_s1.item(item, "text")
            new_status = "☑" if current_status == "☐" else "☐"
            self.tree_s1.item(item, text=new_status)

   # ================= THỜI ĐIỂM NHẤN START MÀN HÌNH 1 =================
    def dev_start(self):
        # Lấy dữ liệu từ giao diện tại luồng chính trước khi truyền vào Thread
        content = self.txt_content_s1.get("1.0", tk.END).strip()
        uid = self.ent_uid_shared.get()
        files = list(self.selected_files_s1)
        
        # Khởi tạo một tiến trình (Thread) riêng cho Selenium của Màn 1
        # daemon=True để khi tắt app tkinter thì tiến trình Selenium này cũng tự tắt theo
        selenium_thread = threading.Thread(
            target=self.run_selenium_process_s1, 
            args=(uid,), 
            daemon=True
        )
        selenium_thread.start()

    def run_selenium_process_s1(self, uid):
        global TEMPORARY_COOKIES
        print(f"\n[Dev Mode] Đang khởi chạy tiến trình ngầm cho UID: {uid}...")
        post = 'https://www.facebook.com/share/p/17soorDCmE/?mibextid=wwXIfr'
        
        try:
            obj = bot.FacebookBot()
            obj.login_with_cookies(uid, TEMPORARY_COOKIES)

            # Cấu trúc groups
            # group_info = {
            #                 "group_name": title,
            #                 "group_id": group_id,
            #                 "group_url": f"https://www.facebook.com/groups/{group_id}/"
            #             }

            obj.share_post_to_group(post, '1309302016338203')
            print("Hoàn thành!")
            
            # Hiển thị thông báo khi xong (Cần gọi messagebox thông qua luồng an toàn)
            self.after(0, lambda: messagebox.showinfo("Thành công", f"UID {uid} đã hoàn thành tiến trình!"))
            
        except Exception as e:
            print(f"[Selenium Màn 1 Lỗi] {str(e)}")
            self.after(0, lambda: messagebox.showerror("Lỗi Tiến Trình", f"Có lỗi xảy ra: {str(e)}"))
        finally:
            print("Tiến hành đóng tiến trình...")
            obj.close()
            print("Đóng trình duyệt hoàn tất!")

    # ================= MÀN HÌNH 2 (SMS) =================
    def setup_screen_2(self):
        left_frame = ttk.LabelFrame(self.tab2, text=" Cấu hình ", padding=10)
        left_frame.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        ttk.Label(left_frame, text="Nội dung (Hỗ trợ Icon/Ký tự đặc biệt):").pack(anchor="w", pady=2)
        self.txt_content_s2 = tk.Text(left_frame, height=8, wrap="word")
        self.txt_content_s2.pack(fill="x", pady=5)
        self.txt_content_s2.insert("1.0", "")

        # Nút Start Màn hình 2
        self.btn_start_s2 = ttk.Button(left_frame, text="Chạy", command=self.start_screen_2)
        self.btn_start_s2.pack(fill="x", pady=20, ipady=5)

        # Cột bên phải: Danh sách UIDs
        right_frame = ttk.LabelFrame(self.tab2, text=" Danh sách UIDs ", padding=10)
        right_frame.pack(side="right", fill="both", padx=10, pady=10)

        # Hướng dẫn nhỏ
        ttk.Label(right_frame, text="(Bấm phím Delete hoặc Click đúp để xóa dòng)", font=("Arial", 8, "italic"), foreground="gray").pack(anchor="w", pady=(0,2))

        self.listbox_uids = tk.Listbox(right_frame, width=35)
        self.listbox_uids.pack(fill="both", expand=True, pady=(0, 5))

        # Đăng ký sự kiện xóa bằng tay từng dòng
        self.listbox_uids.bind("<Delete>", self.delete_selected_uid)
        self.listbox_uids.bind("<Double-1>", self.delete_selected_uid)

        # ---- KHU VỰC CÁC NÚT ĐIỀU KHIỂN DANH SÁCH ----
        btn_frame = ttk.Frame(right_frame)
        btn_frame.pack(fill="x")

        # Nút thêm file .txt (Nằm bên trái)
        btn_import_txt = ttk.Button(btn_frame, text="Thêm vào list (.txt)", command=self.import_uids_from_txt)
        btn_import_txt.pack(side="left", fill="x", expand=True, padx=(0, 2), ipady=2)

        # Nút Clear sạch danh sách (Nằm bên phải, dùng chung dòng)
        btn_clear_all = ttk.Button(btn_frame, text="Clear All", command=self.clear_all_uids)
        btn_clear_all.pack(side="right", fill="x", expand=True, padx=(2, 0), ipady=2)

   
    def get_uids(self):
        # Lấy tất cả các dòng từ vị trí đầu tiên (0) đến cuối cùng (tk.END)
        raw_uids = self.listbox_uids.get(0, tk.END)

        # Chuyển thành list và loại bỏ các UID trùng lặp
        uid_list = list(dict.fromkeys(raw_uids))



        return uid_list

    def clear_all_uids(self):
        # Kiểm tra xem danh sách có dữ liệu không trước khi xóa
        if self.listbox_uids.size() == 0:
            return
            
        # Hiển thị hộp thoại xác nhận để tránh người dùng bấm nhầm
        confirm = messagebox.askyesno("Xác nhận", "Bạn có chắc chắn muốn xóa toàn bộ danh sách UID không?")
        if confirm:
            self.listbox_uids.delete(0, tk.END)

    def delete_selected_uid(self, event):
        try:
            # Lấy vị trí dòng đang được chọn (Trả về tuple các chỉ mục)
            selected_index = self.listbox_uids.curselection()
            
            if selected_index:
                # Tiến hành xóa dòng tại vị trí đó
                self.listbox_uids.delete(selected_index[0])
        except Exception as e:
            pass

    def import_uids_from_txt(self):
        file_path = filedialog.askopenfilename(filetypes=[("Text Files", "*.txt")])
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as file:
                    uids = file.readlines()
                
                # ---- XÓA TOÀN BỘ DỮ LIỆU CŨ TRONG LISTBOX ----
                self.listbox_uids.delete(0, tk.END)
                # ---------------------------------------------
                
                count = 0
                for uid in uids:
                    clean_uid = uid.strip()
                    if clean_uid:
                        self.listbox_uids.insert(tk.END, clean_uid)
                        count += 1
                messagebox.showinfo("Thành công", f"Đã làm mới và nhập thành công {count} UIDs từ file.")
            except Exception as e:
                messagebox.showerror("Lỗi", f"Không thể đọc file: {str(e)}")

    def start_screen_2(self):
        # Lấy dữ liệu từ giao diện tại luồng chính trước khi truyền vào Thread
        content = self.txt_content_s2.get("1.0", tk.END).strip()
        uid = self.ent_uid_shared.get()
        uids = self.get_uids()

        if uid == self.empty_uid:
            messagebox.showerror("Lỗi", f"Không có tài khoản để chạy!")
            return

        if not uids:
            messagebox.showerror("Lỗi", f"Không danh sách uids!")
            return

        if not content:
            messagebox.showerror("Lỗi", f"Không có nội dung!")
            return
        
        self.btn_start_s2.config(state=tk.DISABLED, text="Đang chạy...")
        # daemon=True để khi tắt app tkinter thì tiến trình Selenium này cũng tự tắt theo
        selenium_thread = threading.Thread(
            target=self.run_selenium_process_s2, 
            args=(uid, content, uids), 
            daemon=True
        )
        selenium_thread.start()

    def run_selenium_process_s2(self, user, content, uids):
        global TEMPORARY_COOKIES
        print(f"\n[Selenium Màn 2] Đang khởi chạy tiến trình ngầm cho UID: {user}...")

        try:
            obj = bot.FacebookBot()
            obj.user_agent = USER_AGENT
            obj.login_with_cookies(user, TEMPORARY_COOKIES)

            success_count = 0
            for uid in uids:
                success = obj.send_message_via_uid(uid, content)
                if success:
                    success_count += 1

            messagebox.showinfo("Thông báo", f'Thành công [{success_count}/{len(uids)}]')
            
            # Hiển thị thông báo khi xong (Cần gọi messagebox thông qua luồng an toàn)
            self.after(0, lambda: messagebox.showinfo("Thành công", f"UID {user} đã hoàn thành tiến trình!"))
            
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Lỗi Tiến Trình", f"Có lỗi xảy ra: {str(e)}"))
        finally:
            obj.close()
            self.after(0, lambda: self.btn_start_s2.config(state=tk.NORMAL, text="Chạy Tiến Trình"))



if __name__ == "__main__":
    app = App()
    app.mainloop()