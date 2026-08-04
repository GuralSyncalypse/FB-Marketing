import tkinter as tk
from tkinter import ttk, messagebox
import threading
import bot  # Import module bot chứa FacebookBot

class UidScanScreen(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.parent = parent
        self.controller = controller

        self.scan_results = []
        self.stop_event = threading.Event()  # Cờ tín hiệu dừng thread
        self._build_ui()

    def _build_ui(self):
        left_frame = ttk.LabelFrame(self.parent, text=" Cấu hình quét UID ", padding=10)
        left_frame.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        ttk.Label(
            left_frame,
            text="Màn hình này dùng để quét UID các thành viên từ danh sách nhóm đã chọn.",
            wraplength=320,
            foreground="#444444",
        ).pack(anchor="w", pady=(0, 10))

        group_box = ttk.LabelFrame(left_frame, text=" Nguồn groups ", padding=8)
        group_box.pack(fill="x", pady=(0, 10))

        self.lbl_group_status = ttk.Label(group_box, text="Chưa nạp groups")
        self.lbl_group_status.pack(anchor="w")

        btn_row = ttk.Frame(group_box)
        btn_row.pack(fill="x", pady=(8, 0))

        ttk.Button(
            btn_row,
            text="Tải lại groups",
            command=self.refresh_groups_preview,
        ).pack(side="left", fill="x", expand=True, padx=(0, 2))

        # Nút Bắt đầu quét UID
        self.btn_start = ttk.Button(
            btn_row,
            text="Bắt đầu quét",
            command=self.start_uid_scan,
        )
        self.btn_start.pack(side="left", fill="x", expand=True, padx=2)

        # Nút Dừng quét UID (Thêm mới)
        self.btn_stop = ttk.Button(
            btn_row,
            text="Dừng quét",
            command=self.stop_uid_scan,
            state=tk.DISABLED
        )
        self.btn_stop.pack(side="left", fill="x", expand=True, padx=(2, 0))

        option_box = ttk.LabelFrame(left_frame, text=" Tùy chọn quét ", padding=8)
        option_box.pack(fill="x", pady=(0, 10))

        # --- Checkbutton nhóm 1: Phạm vi quét ---
        self.chk_only_selected_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            option_box,
            text="Chỉ quét các group đang được chọn",
            variable=self.chk_only_selected_var,
        ).pack(anchor="w", pady=2)

        # --- Checkbutton nhóm 2: Trình duyệt & An toàn ---
        self.chk_headless_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            option_box,
            text="Chạy ẩn trình duyệt (Headless mode)",
            variable=self.chk_headless_var,
        ).pack(anchor="w", pady=2)

        self.chk_merge_files_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            option_box,
            text="Gộp chung tất cả UID cào được vào 1 file",
            variable=self.chk_merge_files_var,
        ).pack(anchor="w", pady=2)

        self.chk_skip_no_avatar_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            option_box,
            text="Bỏ qua tài khoản không có ảnh đại diện",
            variable=self.chk_skip_no_avatar_var,
        ).pack(anchor="w", pady=2)

        # --- Spinbox: Giới hạn số UID mỗi group ---
        limit_frame = ttk.Frame(option_box)
        limit_frame.pack(fill="x", pady=(6, 2))

        ttk.Label(limit_frame, text="UID tối đa / Group:").pack(
            side="left"
        )

        self.spn_limit_uid_var = tk.IntVar(value=0)  # 0 nghĩa là không giới hạn
        spn_limit = ttk.Spinbox(
            limit_frame,
            from_=0,
            to=100000,
            increment=500,
            textvariable=self.spn_limit_uid_var,
            width=8,
        )
        spn_limit.pack(side="left", padx=5)
        ttk.Label(limit_frame, text="(0 = Không giới hạn)").pack(side="left")

        # --- Combobox: Tốc độ cuộn ---
        speed_frame = ttk.Frame(option_box)
        speed_frame.pack(fill="x", pady=(4, 2))

        ttk.Label(speed_frame, text="Tốc độ cuộn:").pack(side="left")
        self.cbo_speed_var = tk.StringVar(value="Vừa phải (2.5s)")
        cbo_speed = ttk.Combobox(
            speed_frame,
            textvariable=self.cbo_speed_var,
            values=[
                "Nhanh (1.5s)",
                "Vừa phải (2.5s)",
                "An toàn (4.0s)",
            ],
            state="readonly",
            width=15,
        )
        cbo_speed.pack(side="left", padx=5)

        self.lbl_status = ttk.Label(left_frame, text="Trạng thái: Sẵn sàng", foreground="blue")
        self.lbl_status.pack(anchor="w", pady=(4, 0))

        # BẢNG THỐNG KÊ KẾT QUẢ QUÉT (CHỈ HIỂN THỊ TỔNG QUAN GROUP)
        right_frame = ttk.LabelFrame(self.parent, text=" Tiến trình quét theo Group ", padding=10)
        right_frame.pack(side="right", fill="both", expand=True, padx=10, pady=10)

        tree_frame = ttk.Frame(right_frame)
        tree_frame.pack(fill="both", expand=True)

        self.tree_results = ttk.Treeview(
            tree_frame,
            columns=("group_name", "group_id", "count", "status"),
            show="headings",
            height=14,
        )
        self.tree_results.heading("group_name", text="Tên Group")
        self.tree_results.heading("group_id", text="ID Group")
        self.tree_results.heading("count", text="Số UID thu thập")
        self.tree_results.heading("status", text="Trạng thái")

        self.tree_results.column("group_name", width=200, anchor="w")
        self.tree_results.column("group_id", width=130, anchor="w")
        self.tree_results.column("count", width=110, anchor="e")
        self.tree_results.column("status", width=90, anchor="center")

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree_results.yview)
        self.tree_results.configure(yscrollcommand=scrollbar.set)

        self.tree_results.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        footer_row = ttk.Frame(right_frame)
        footer_row.pack(fill="x", pady=(10, 0))

        ttk.Button(
            footer_row,
            text="Clear kết quả",
            command=self.clear_results,
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.refresh_groups_preview()

    def get_source_groups(self):
        groups = getattr(self.controller, "groups_data", []) or []
        if self.chk_only_selected_var.get():
            return [g for g in groups if g.get("checked", False)]
        return list(groups)

    def refresh_groups_preview(self):
        groups = getattr(self.controller, "groups_data", []) or []
        selected = [g for g in groups if g.get("checked", False)]

        if not groups:
            self.lbl_group_status.config(text="Chưa có groups nào được nạp!")
        else:
            self.lbl_group_status.config(
                text=f"Tổng groups: {len(groups)} | Đang chọn: {len(selected)}"
            )

    def set_status(self, text, color="blue"):
        self.lbl_status.config(text=f"Trạng thái: {text}", foreground=color)

    def add_group_result(self, group_name, group_id, count, status="OK"):
        """Thêm 1 dòng tổng kết của Group vào bảng (Không lặp từng UID)"""
        count_display = f"{count:,}" if isinstance(count, int) else "0"
        self.scan_results.append({
            "group_name": group_name, 
            "group_id": group_id, 
            "count": count, 
            "status": status
        })
        self.tree_results.insert("", "end", values=(group_name, group_id, count_display, status))

    def clear_results(self):
        self.scan_results.clear()
        for item in self.tree_results.get_children():
            self.tree_results.delete(item)
        self.set_status("Đã xóa danh sách kết quả", color="gray")

    def stop_uid_scan(self):
        """Hàm xử lý khi người dùng ấn nút Dừng"""
        self.stop_event.set()
        self.set_status("Đang dọn dẹp và dừng tiến trình...", color="red")
        self.btn_stop.config(state=tk.DISABLED)

    # =========================================================================
    # LOGIC CHẠY TỰ ĐỘNG VỚI SELENIUM THREADING
    # =========================================================================

    def start_uid_scan(self):
        # 1. Lấy và kiểm tra tài khoản đăng nhập
        user_id = getattr(self.controller, "ent_uid_shared", None)
        user = user_id.get() if user_id else ""
        empty_uid = getattr(self.controller, "empty_uid", "")

        if not user or user == empty_uid:
            messagebox.showerror("Lỗi", "Vui lòng nhập/chọn tài khoản trước khi quét!")
            return

        # 2. Lấy danh sách nhóm cần quét
        source_groups = self.get_source_groups()
        if not source_groups:
            messagebox.showwarning(
                "Thiếu dữ liệu",
                "Chưa có group nào được chọn để quét!"
            )
            return

        # Reset cờ dừng
        self.stop_event.clear()

        # 3. Vô hiệu hóa nút Bắt đầu & Kích hoạt nút Dừng
        self.btn_start.config(state=tk.DISABLED, text="Đang quét...")
        self.btn_stop.config(state=tk.NORMAL)
        self.set_status(f"Đang khởi tạo trình duyệt cho {len(source_groups)} groups...", color="orange")

        # 4. Tạo thread chạy Selenium ngầm (daemon=True)
        scan_thread = threading.Thread(
            target=self.run_selenium_scan_process,
            args=(user, source_groups),
            daemon=True
        )
        scan_thread.start()

    def run_selenium_scan_process(self, user, target_groups):
        """Hàm thực thi logic Selenium chạy ngầm trong Thread"""
        print(f"\n[Selenium Quét UID] Bắt đầu tiến trình cho UID: {user}...")
        self.bot_obj = None  # ⚡ BỔ SUNG 1: Khởi tạo biến instance để hàm Stop có thể truy cập
        total_found = 0

        try:
            # Khởi tạo FacebookBot từ bot.py
            obj = bot.FacebookBot(self.controller.is_demo_mode)
            obj.user_agent = getattr(self.controller, "user_agent", None)
            
            # ⚡ BỔ SUNG 2: Gán cờ stop_event vào bot để hàm perform_search dùng được
            obj.stop_event = self.stop_event 
            self.bot_obj = obj 

            if self.stop_event.is_set():
                return

            # Đăng nhập bằng Cookies
            is_login = obj.login_with_cookies(user, getattr(self.controller, "cookies", []))
            if not is_login:
                self.after(0, lambda: messagebox.showerror("Lỗi", "Đăng nhập Cookies thất bại!"))
                return

            # Lặp qua từng Group
            for idx, group in enumerate(target_groups, start=1):
                # Kiểm tra nếu bấm Dừng giữa các lượt quét
                if self.stop_event.is_set():
                    print("🛑 Tiến trình đã bị người dùng dừng.")
                    break

                group_id = group.get("id")
                group_name = group.get("name", group_id)

                # Cập nhật trạng thái hiển thị
                self.after(0, lambda g_name=group_name, i=idx, total=len(target_groups): 
                    self.set_status(f"[{i}/{total}] Đang quét nhóm: {g_name}...", color="orange")
                )

                try:
                    obj.output_path = f"output_{group_id}.json"

                    members = obj.perform_search(
                        group_id=group_id,
                        base_scroll_pause=1.5
                    )

                    group_count = len(members) if members else 0
                    total_found += group_count

                    # Đưa kết quả lên Treeview
                    self.after(0, self.add_group_result, group_name, group_id, group_count, "OK")

                except Exception as group_err:
                    print(f"❌ Lỗi khi quét group {group_id}: {group_err}")
                    self.after(0, self.add_group_result, group_name, group_id, 0, "Lỗi Quét")

            # Thông báo hoàn tất / dừng
            if self.stop_event.is_set():
                self.after(0, lambda: messagebox.showwarning(
                    "Đã dừng", 
                    f"Đã dừng tiến trình quét!\nTổng cộng đã thu thập được {total_found:,} UIDs."
                ))
            else:
                self.after(0, lambda: messagebox.showinfo(
                    "Hoàn tất", 
                    f"Đã quét xong {len(target_groups)} groups!\nTổng cộng thu thập được {total_found:,} UIDs."
                ))

        except Exception as e:
            print(f"❌ Lỗi tiến trình quét UID: {e}")
            self.after(0, lambda err=str(e): messagebox.showerror("Lỗi Tiến Trình", f"Có lỗi xảy ra: {err}"))

        finally:
            # ⚡ BỔ SUNG 4: Dọn dẹp an toàn và xóa tham chiếu self.bot_obj
            if self.bot_obj:
                try:
                    self.bot_obj.close()
                except Exception:
                    pass
                self.bot_obj = None

            # Bật lại các nút bấm giao diện
            self.after(0, lambda: self.btn_start.config(state=tk.NORMAL, text="Bắt đầu quét"))
            self.after(0, lambda: self.btn_stop.config(state=tk.DISABLED))
            
            status_text = "Đã dừng quét" if self.stop_event.is_set() else "Hoàn tất quét"
            status_color = "red" if self.stop_event.is_set() else "green"
            self.after(0, lambda: self.set_status(status_text, color=status_color))