import tkinter as tk
from tkinter import ttk, messagebox
import requests
import threading
import json

class AccountManagerTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.accounts = {} # Lưu trữ dữ liệu: {uid: {"name": ..., "cookie": ..., "status": ...}}
        self.init_ui()

    def init_ui(self):
        # --- Khung cấu trúc chức năng (Top Bar) ---
        top_frame = ttk.LabelFrame(self, text=" Chức năng nâng cao ", padding=10)
        top_frame.pack(fill=tk.X, padx=10, pady=5)

        btn_check_all = ttk.Button(top_frame, text="Check Live/Die Toàn bộ", command=self.start_check_all_threads)
        btn_check_all.pack(side=tk.LEFT, padx=5)

        btn_delete = ttk.Button(top_frame, text="Xóa tài khoản chọn", command=self.delete_selected)
        btn_delete.pack(side=tk.LEFT, padx=5)
        
        lbl_info = ttk.Label(top_frame, text="* Dữ liệu tự động cập nhật khi Extension gửi về", font=("Arial", 9, "italic"))
        lbl_info.pack(side=tk.RIGHT, padx=5)

        # --- Bảng hiển thị danh sách tài khoản (Treeview) ---
        table_frame = ttk.Frame(self, padding=10)
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("uid", "name", "cookie", "status")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        
        # Định nghĩa tiêu đề cột
        self.tree.heading("uid", text="Facebook UID")
        self.tree.heading("name", text="Tên tài khoản")
        self.tree.heading("cookie", text="Cookie (Rút gọn)")
        self.tree.heading("status", text="Trạng thái")

        # Định nghĩa độ rộng cột
        self.tree.column("uid", width=120, anchor=tk.CENTER)
        self.tree.column("name", width=150, anchor=tk.W)
        self.tree.column("cookie", width=350, anchor=tk.W)
        self.tree.column("status", width=100, anchor=tk.CENTER)

        # Thanh cuộn (Scrollbar)
        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Thiết lập màu sắc trực quan cho trạng thái Live/Die
        self.tree.tag_configure("Live", foreground="green", font=("Arial", 10, "bold"))
        self.tree.tag_configure("Die", foreground="red")
        self.tree.tag_configure("Checking", foreground="orange")

    def add_or_update_account(self, uid, name, cookie):
        """Hàm này sẽ được gọi khi nhận được dữ liệu từ Extension Chrome gửi về"""
        short_cookie = cookie[:50] + "..." if len(cookie) > 50 else cookie
        
        if uid in self.accounts:
            # Cập nhật tài khoản cũ
            self.accounts[uid].update({"name": name, "cookie": cookie})
            # Tìm item trong Treeview để sửa giao diện
            for item in self.tree.get_children():
                if self.tree.item(item)['values'][0] == uid:
                    self.tree.item(item, values=(uid, name, short_cookie, self.accounts[uid]["status"]))
                    break
        else:
            # Thêm mới tài khoản
            self.accounts[uid] = {"name": name, "cookie": cookie, "status": "Chưa check"}
            self.tree.insert("", tk.END, values=(uid, name, short_cookie, "Chưa check"))

    def delete_selected(self):
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("Chú ý", "Vui lòng chọn tài khoản muốn xóa!")
            return
        for item in selected_items:
            uid = self.tree.item(item)['values'][0]
            if uid in self.accounts:
                del self.accounts[uid]
            self.tree.delete(item)

    def start_check_all_threads(self):
        """Khởi chạy Thread riêng để tránh treo UI Tkinter"""
        threading.Thread(target=self.check_live_die_process, daemon=True).start()

    def check_live_die_process(self):
        items = self.tree.get_children()
        print(self.accounts)
        for item in items:
            uid = self.tree.item(item)['values'][0]
            uid = str(uid)
            cookie = self.accounts[uid]["cookie"]
            
            # Cập nhật trạng thái hiển thị tạm thời "Đang check..."
            self.tree.set(item, column="status", value="Đang check...")
            self.tree.item(item, tags=("Checking",))
            
            # Gọi hàm kiểm tra thực tế
            is_live = self.verify_facebook_cookie(cookie)
            
            status_text = "Live" if is_live else "Die"
            self.accounts[uid]["status"] = status_text
            
            # Cập nhật kết quả lên giao diện
            self.tree.set(item, column="status", value=status_text)
            self.tree.item(item, tags=(status_text,))

    def verify_facebook_cookie(self, cookie_string):
        """Hàm ẩn kiểm tra gói tin HTTP bằng cách gọi thử API lấy thông tin cá nhân của FB"""
        url = "https://mbasic.facebook.com/profile.php"
        headers = {
            "cookie": cookie_string,
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        try:
            # Chỉ cần gọi mbasic để nhẹ và nhanh
            response = requests.get(url, headers=headers, timeout=10)
            # Nếu trong source trả về có chữ "Đăng nhập" hoặc chuyển hướng về trang login thì cookie die
            if "c_user=" in cookie_string and ("privacyx" in response.text or "xc_message" in response.text or "logout" in response.text):
                return True
            return False
        except Exception:
            return False

# --- Khởi chạy giao diện chính ---
if __name__ == "__main__":
    root = tk.Tk()
    root.title("Facebook Post Processor - Admin Panel")
    root.geometry("800x500")
    
    # Giả lập add dữ liệu ban đầu
    mgr_tab = AccountManagerTab(root)
    mgr_tab.pack(fill=tk.BOTH, expand=True)
    
    mgr_tab.add_or_update_account("1000123456789", "Nguyễn Văn A", "c_user=1000123456789; xs=abc123xyz;")
    mgr_tab.add_or_update_account("1000987654321", "Clone Giá Rẻ", "c_user=1000987654321; xs=expired_token;")

    root.mainloop()