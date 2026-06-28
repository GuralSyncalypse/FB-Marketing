import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import os
import threading
import urllib.parse
import bot

from views.dev_screen import DevelopScreen
from views.sms_screen import SmsScreen
from services.local_server import start_local_server

# ================= CLASS GIAO DIỆN CHÍNH (APP) =================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Phần mềm Quản lý Tính năng - Nhận Data từ Extension")
        self.geometry("950x700")
        
        # --- Khởi tạo dữ liệu ---
        self.selected_files_s1 = []
        self.selected_files_s2 = []
        self.empty_uid = "Chờ tín hiệu từ Extension..."
        
        # Biến lưu trữ dữ liệu từ server
        self.uid = ""
        self.cookies = []
        self.user_agent = ""

        # --- Xây dựng các thành phần Giao diện (Tách hàm) ---
        # Quy tắc pack: Thành phần nào cố định kích thước/muốn giữ chỗ thì build trước hoặc pack trước.
        self._build_shared_panel()      # 1. Khu vực thông tin phía trên (Cố định chiều cao)
        #self._build_log_panel()         # 2. Khu vực Log phía dưới (Cố định chiều cao, không cho expand)
        self._build_navigation_tabs(2)   # 3. Khu vực Notebook ở giữa (Sẽ tự giãn nở chiếm phần còn lại)

        # --- Khởi chạy dịch vụ ngầm ---
        start_local_server(
            port=8000, 
            on_uid_received_callback=self.on_server_received, 
            on_log_callback=None
        )

    def _build_shared_panel(self):
        """Xây dựng khu vực cấu hình thông tin tài khoản dùng chung phía trên (Đã thu gọn)"""
        top_shared_frame = ttk.LabelFrame(
            self,
            text=" Thông tin tài khoản hiện tại ",
            padding=10
        )
        top_shared_frame.pack(side="top", fill="x", padx=10, pady=5)

        # Định hình layout sử dụng grid để kiểm soát khoảng cách tốt hơn thay vì pack hỗn hợp
        top_shared_frame.columnconfigure(1, weight=1)
        top_shared_frame.columnconfigure(3, weight=2) # Cho ô User Agent rộng hơn vì UA thường rất dài

        # HÀNG 1: UID & USER AGENT
        # --- Cụm UID ---
        ttk.Label(top_shared_frame, text="UID:", width=8).grid(row=0, column=0, sticky="w", pady=5)
        self.ent_uid_shared = ttk.Entry(top_shared_frame, font=("Arial", 10, "bold"), width=25)
        self.ent_uid_shared.grid(row=0, column=1, sticky="w", pady=5, padx=(0, 20))
        self.ent_uid_shared.insert(0, self.empty_uid)

        # --- Cụm User Agent ---
        ttk.Label(top_shared_frame, text="User Agent:").grid(row=0, column=2, sticky="w", pady=5)
        self.ent_ua = ttk.Entry(top_shared_frame)
        self.ent_ua.grid(row=0, column=3, sticky="ew", pady=5)

        # HÀNG 2: QUẢN LÝ GROUPS (Rút gọn thành hiển thị số lượng)
        group_status_frame = ttk.Frame(top_shared_frame)
        group_status_frame.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(8, 0))

        # Biến lưu trữ số lượng group để cập nhật động lên giao diện
        self.lbl_group_count_var = tk.StringVar(value="Đã quét: 0 groups")
        lbl_count = ttk.Label(group_status_frame, textvariable=self.lbl_group_count_var, font=("Arial", 10, "italic"))
        lbl_count.pack(side="left", padx=(0, 15))

        btn_show_groups = ttk.Button(
            group_status_frame,
            text="Danh sách nhóm",
            command=self.open_groups_window
        )
        btn_show_groups.pack(side="left")
        
        # Biến cục bộ để lưu danh sách group phục vụ cho cửa sổ popup (Cấu trúc ví dụ: [{"id": "1", "name": "Group A", "checked": True}, ...])
        self.groups_data = []
    
    def get_selected_groups(self):
        """Trả về danh sách các object group đang được tích chọn"""
        if not hasattr(self, 'groups_data') or not self.groups_data:
            return []
        
        # Lọc ra những nhóm có 'checked' là True
        return [g for g in self.groups_data if g.get("checked", False)]

    def open_groups_window(self):
        """Mở cửa sổ mới (Popup) hiển thị chi tiết danh sách nhóm và tích chọn"""

        # --- 0. LẤY UID HIỆN TẠI ĐỂ KIỂM TRA TRONG FILE JSON ---
        # Giả sử UID được lưu ở self.current_uid hoặc lấy từ UI chính, bạn chỉnh lại cho đúng tên biến nhé
        current_uid = self.ent_uid_shared.get()
        if not current_uid:
            # Ví dụ nếu bạn lấy từ một ô Entry ở giao diện chính:
            # current_uid = self.txt_user_id.get().strip()
            pass

        # --- TỰ ĐỘNG KIỂM TRA VÀ LOAD DỮ LIỆU TỪ FILE JSON KHI VỪA MỞ CỬA SỔ ---
        file_path = "groups_saved.json"
        if current_uid and os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    full_json_data = json.load(f)

                    # Tìm xem trong list JSON có Object nào chứa key là UID hiện tại không
                    found_data = False
                    for item in full_json_data:
                        if current_uid in item:
                            # Đổ dữ liệu từ file vào biến của App
                            self.groups_data = item[current_uid].get("groups", [])
                            found_data = True
                            print(
                                f"Đã tự động nạp {len(self.groups_data)} nhóm của UID {current_uid} từ file JSON."
                            )
                            break

                    if not found_data:
                        # Nếu file tồn tại nhưng không có UID này, thiết lập list rỗng
                        self.groups_data = []
            except Exception as e:
                print(f"Lỗi đọc file JSON khi mở cửa sổ: {e}")
                self.groups_data = []
        else:
            # Nếu chưa chọn UID hoặc file chưa từng được tạo, giữ nguyên hoặc reset rỗng
            if not hasattr(self, "groups_data"):
                self.groups_data = []

        # ================= KHỞI TẠO GIAO DIỆN POPUP =================
        groups_win = tk.Toplevel(self)
        groups_win.title("Quản lý danh sách Groups")
        groups_win.geometry(
            "550x450"
        )  # Tăng nhẹ chiều rộng để vừa khít cụm Radiobutton
        groups_win.grab_set()  # Khóa màn hình chính cho đến khi đóng cửa sổ này
        groups_win.resizable(False, False)

        # Khung trên: Thanh công cụ/Nút hành động
        toolbar = ttk.Frame(groups_win, padding=10)
        toolbar.pack(fill="x")

        # Khung dưới: Chứa danh sách Treeview
        main_content = ttk.Frame(groups_win, padding=10)
        main_content.pack(fill="both", expand=True)

        # --- Cấu hình Treeview tích chọn ---
        tree_groups = ttk.Treeview(
            main_content, columns=("Select", "Name"), show="headings", selectmode="none"
        )

        scrollbar = ttk.Scrollbar(
            main_content, orient="vertical", command=tree_groups.yview
        )
        tree_groups.configure(yscrollcommand=scrollbar.set)

        tree_groups.heading("Select", text="Chọn")
        tree_groups.heading("Name", text="Tên nhóm")

        tree_groups.column("Select", width=60, anchor="center")
        tree_groups.column("Name", width=430, anchor="w")

        tree_groups.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # --- Hàm cập nhật hiển thị Treeview từ dữ liệu `self.groups_data` ---
        def refresh_tree():
            tree_groups.delete(*tree_groups.get_children())
            for idx, g in enumerate(self.groups_data):
                status = "🟢 [X]" if g.get("checked", False) else "⚪ [ ]"
                tree_groups.insert(
                    "", "end", iid=str(idx), values=(status, g.get("name", ""))
                )

            # Đồng bộ lại trạng thái của cụm Radiobutton dựa trên dữ liệu thực tế
            update_radio_selection_state()

        # --- Sự kiện click để đảo trạng thái Checkbox từng dòng ---
        def on_tree_click(event):
            item_id = tree_groups.identify_row(event.y)
            column = tree_groups.identify_column(event.x)
            if item_id and column == "#1":
                idx = int(item_id)
                self.groups_data[idx]["checked"] = not self.groups_data[idx][
                    "checked"
                ]
                refresh_tree()

        tree_groups.bind("<ButtonRelease-1>", on_tree_click)

        # --- Xử lý sự kiện khi bấm chọn Radiobutton (Chọn tất cả / Bỏ chọn tất cả) ---
        def on_radio_changed():
            val = rad_var.get()
            if val == 1:  # Chọn tất cả
                for g in self.groups_data:
                    g["checked"] = True
            elif val == 0:  # Bỏ chọn tất cả
                for g in self.groups_data:
                    g["checked"] = False
            refresh_tree()

        # Hàm bổ trợ: Kiểm tra dữ liệu để trả trạng thái hiển thị đúng cho Radiobutton
        def update_radio_selection_state():
            if not self.groups_data:
                rad_var.set(-1)  # Không chọn cái nào nếu danh sách trống
                return

            all_checked = all(g.get("checked", False) for g in self.groups_data)
            all_unchecked = all(not g.get("checked", False) for g in self.groups_data)

            if all_checked:
                rad_var.set(1)  # Tự bật Radio "Chọn tất cả"
            elif all_unchecked:
                rad_var.set(0)  # Tự bật Radio "Bỏ chọn"
            else:
                rad_var.set(-1)  # Trạng thái lấp lửng (không chọn radio nào)

        # --- Xử lý nút quét dữ liệu mới ---
        def handle_scan():
            if not current_uid:
                messagebox.showwarning(
                    "Cảnh báo", "Vui lòng nhập/chọn UID trước khi quét!"
                )
                return

            btn_scan.config(state="disabled", text="Đang quét...")

            def local_refresh():
                refresh_tree()
                self.lbl_group_count_var.set(f"Đã quét: {len(self.groups_data)} groups")
                btn_scan.config(state="normal", text="Quét")
                messagebox.showinfo(
                    "Thành công",
                    f"Đã cập nhật {len(self.groups_data)} nhóm thành công!",
                )

            self._trigger_ui_refresh = local_refresh
            # Hàm scan_groups này sẽ chạy hàm run_scan_groups(current_uid) ngầm ở luồng phụ mà bạn viết từ trước
            self.scan_groups()

        # === KHỞI TẠO CÁC NÚT VÀ RADIOBUTTON TRÊN TOOLBAR ===
        # Nút Quét
        btn_scan = ttk.Button(toolbar, text="Quét", command=handle_scan)
        btn_scan.pack(side="left", padx=5)

        # Cụm Radiobutton Điều khiển Trạng Thái Chọn
        rad_var = tk.IntVar(value=-1)

        rad_all = ttk.Radiobutton(
            toolbar,
            text="Chọn tất cả",
            variable=rad_var,
            value=1,
            command=on_radio_changed,
        )
        rad_all.pack(side="left", padx=10)

        rad_none = ttk.Radiobutton(
            toolbar,
            text="Bỏ chọn tất cả",
            variable=rad_var,
            value=0,
            command=on_radio_changed,
        )
        rad_none.pack(side="left", padx=5)

        # Nút Xác nhận & Đóng
        def save_and_close():
            selected_count = sum(1 for g in self.groups_data if g.get("checked", False))
            self.lbl_group_count_var.set(
                f"Đã quét: {len(self.groups_data)} groups (Đang chọn: {selected_count})"
            )
            groups_win.destroy()

        btn_save = ttk.Button(toolbar, text="Xác nhận & Đóng", command=save_and_close)
        btn_save.pack(side="right", padx=5)

        # Nạp dữ liệu vừa đọc từ JSON lên Treeview hiển thị
        refresh_tree()

    def _build_navigation_tabs(self, num_tabs):
        """Xây dựng khu vực Notebook và nhúng các màn hình tính năng vào"""
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=5, pady=5)

        tab_configs = [
            ("Share bài", DevelopScreen),
            ("Bắn SMS", SmsScreen),
        ]

        self.tabs = []
        self.screens = {}

        for label, screen_cls in tab_configs:
            tab = ttk.Frame(self.notebook)
            self.notebook.add(tab, text=label)

            screen = screen_cls(tab, self)

            self.tabs.append(tab)
            self.screens[label] = screen

    def _build_log_panel(self):
        """Xây dựng ô hiển thị log hệ thống ở dưới cùng"""
        log_frame = ttk.LabelFrame(self, text=" Nhật ký hoạt động ", padding=5)
        # Đặt side="bottom", fill="x" và tắt expand để cố định form log ở đáy app
        log_frame.pack(side="bottom", fill="x", expand=False, padx=10, pady=5)

        # Giới hạn chiều cao cố định (height=8 dòng)
        self.txt_log = tk.Text(log_frame, height=8, width=50, bg="#f8f9fa")
        self.txt_log.pack(expand=True, fill=tk.BOTH)

    # ================= CÁC HÀM XỬ LÝ LOGIC =================
    def _update_ui_after_scan(self):
        """Hàm này chạy trên Luồng chính (Main Thread) nên an toàn 100%"""
        # 1. Cập nhật số lượng hiển thị ở trang chủ
        self.lbl_group_count_var.set(f"Đã quét: {len(self.groups_data)} groups")
        
        # 2. Nếu cửa sổ popup đang mở, gọi hàm refresh_tree() của popup đó
        # (Bạn có thể lưu biến reference của popup hoặc dùng callback để reload bảng)
        if hasattr(self, 'popup_refresh_func') and self.popup_refresh_func:
            self.popup_refresh_func()
        
    def log_to_interface(self, message):
        """Hàm nhận log từ server và chèn vào giao diện an toàn"""
        self.after(0, self._safe_append_log, message)

    def _safe_append_log(self, message):
        self.txt_log.insert(tk.END, f"{message}\n")
        self.txt_log.see(tk.END)  # Tự động cuộn xuống dòng mới nhất

    def on_server_received(self, data: dict):
        """Callback xử lý khi nhận được dữ liệu từ Extension qua Local Server"""
        self.uid = data.get('uid', '')
        self.cookies = data.get('cookies', [])
        self.user_agent = data.get('user_agent', '')

        # Cập nhật thông tin lên UI
        self.ent_uid_shared.delete(0, tk.END)
        self.ent_uid_shared.insert(0, self.uid)

        self.ent_ua.delete(0, tk.END)
        self.ent_ua.insert(0, self.user_agent)

    def scan_groups(self):
        uid = self.ent_uid_shared.get()
        
        # Tiến trình con sẽ tắt khi tiến trình cha bị hủy (daemon = True)
        selenium_thread = threading.Thread(
            target=self.run_scan_groups, 
            args=(uid,), 
            daemon=True
        )
        selenium_thread.start()

    def run_scan_groups(self, user) -> None:       
        try:
            worker = bot.FacebookBot()
            worker.login_with_cookies(user, self.cookies)
            results = worker.scrape_joined_groups() # Giả sử trả về list dict

            # 1. CẬP NHẬT TRỰC TIẾP VÀO BIẾN CỦA APP
            self.groups_data = []
            for group in results:
                self.groups_data.append({
                    "id": group.get("group_id", ""),
                    "name": group.get("group_name", ""),
                    "checked": False
                })

            # 2. LƯU DỮ LIỆU THÀNH FILE JSON THEO ĐỊNH DẠNG YÊU CẦU
            file_path = "groups_saved.json"
            
            # Tạo cấu trúc data mới dựa trên format: [{ user: { "groups": [...] } }]
            new_data_entry = {
                user: {
                    "groups": self.groups_data
                }
            }

            # Đọc dữ liệu cũ nếu file đã tồn tại để tránh ghi đè mất dữ liệu của UID khác
            full_json_data = []
            if os.path.exists(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        full_json_data = json.load(f)
                        if not isinstance(full_json_data, list):
                            full_json_data = []
                except Exception:
                    full_json_data = [] # Nếu file lỗi/trống thì reset thành list rỗng

            # Cập nhật hoặc thêm mới: Nếu UID này đã tồn tại trong file thì ghi đè, chưa có thì append
            updated = False
            for item in full_json_data:
                if user in item:
                    item[user]["groups"] = self.groups_data
                    updated = True
                    break
            
            if not updated:
                full_json_data.append(new_data_entry)

            # Tiến hành ghi vào file JSON
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(full_json_data, f, ensure_ascii=False, indent=4)

            print("Hoàn thành cào dữ liệu ngầm và lưu JSON thành công!")

            # 3. GỌI LỆNH CẬP NHẬT GIAO DIỆN (Đẩy về Main Thread an toàn)
            if hasattr(self, '_trigger_ui_refresh') and self._trigger_ui_refresh:
                self.after(0, self._trigger_ui_refresh)      
                
        except Exception as e:
            msg = f"Có lỗi xảy ra: {e}"
            self.after(0, lambda: messagebox.showerror("Lỗi Tiến Trình", msg))
        finally:
            # Bọc try-except cho worker.close() đề phòng worker khởi tạo lỗi (None)
            if 'worker' in locals():
                worker.close()

if __name__ == "__main__":
    app = App()
    app.mainloop()