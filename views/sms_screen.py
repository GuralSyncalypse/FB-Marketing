import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import threading
import urllib.parse
import bot

class SmsScreen(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.parent = parent
        self.controller = controller
        self._build_ui()

    def _build_ui(self):
        left_frame = ttk.LabelFrame(self.parent, text=" Cấu hình ", padding=10)
        left_frame.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        ttk.Label(left_frame, text="Nội dung (Hỗ trợ Icon/Ký tự đặc biệt):").pack(anchor="w", pady=2)
        self.txt_content = tk.Text(left_frame, height=8, wrap="word")
        self.txt_content.pack(fill="x", pady=5)
        self.txt_content.insert("1.0", "")

        # Nút Start Màn hình 2
        self.btn_start = ttk.Button(left_frame, text="Chạy", command=self.start_screen_2)
        self.btn_start.pack(fill="x", pady=20, ipady=5)

        # Cột bên phải: Danh sách UIDs
        right_frame = ttk.LabelFrame(self.parent, text=" Danh sách UIDs ", padding=10)
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
        content = self.txt_content.get("1.0", tk.END).strip()
        uid = self.controller.ent_uid_shared.get()
        uids = self.get_uids()

        if uid == self.controller.empty_uid:
            messagebox.showerror("Lỗi", f"Không có tài khoản để chạy!")
            return

        if not uids:
            messagebox.showerror("Lỗi", f"Không danh sách uids!")
            return

        if not content:
            messagebox.showerror("Lỗi", f"Không có nội dung!")
            return
        
        self.btn_start.config(state=tk.DISABLED, text="Đang chạy...")
        # daemon=True để khi tắt app tkinter thì tiến trình Selenium này cũng tự tắt theo
        selenium_thread = threading.Thread(
            target=self.run_selenium_process_s2, 
            args=(uid, content, uids), 
            daemon=True
        )
        selenium_thread.start()

    def run_selenium_process_s2(self, user, content, uids):
        print(f"\n[Selenium Màn 2] Đang khởi chạy tiến trình ngầm cho UID: {user}...")

        try:
            obj = bot.FacebookBot(self.controller.is_demo_mode)
            obj.user_agent = self.controller.user_agent
            success = obj.start_browser(user, user_agent=self.controller.get_user_agent())
            if not success:
                self.after(0, lambda: messagebox.showerror("Lỗi", "Đăng nhập thất bại!"))
                return

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
            self.after(0, lambda: self.btn_start.config(state=tk.NORMAL, text="Chạy Tiến Trình"))