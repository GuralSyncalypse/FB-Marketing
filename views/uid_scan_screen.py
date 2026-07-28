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
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))

        # Nút Bắt đầu quét UID
        self.btn_start = ttk.Button(
            btn_row,
            text="Bắt đầu quét",
            command=self.start_uid_scan,
        )
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(4, 0))

        option_box = ttk.LabelFrame(left_frame, text=" Tùy chọn ", padding=8)
        option_box.pack(fill="x", pady=(0, 10))

        self.chk_only_selected_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            option_box,
            text="Chỉ quét các group đang được chọn",
            variable=self.chk_only_selected_var,
        ).pack(anchor="w", pady=(6, 0))

        self.lbl_status = ttk.Label(left_frame, text="Trạng thái: Sẵn sàng", foreground="blue")
        self.lbl_status.pack(anchor="w", pady=(4, 0))

        right_frame = ttk.LabelFrame(self.parent, text=" Danh sách UID quét được ", padding=10)
        right_frame.pack(side="right", fill="both", expand=True, padx=10, pady=10)

        tree_frame = ttk.Frame(right_frame)
        tree_frame.pack(fill="both", expand=True)

        self.tree_results = ttk.Treeview(
            tree_frame,
            columns=("uid", "group_name", "status"),
            show="headings",
            height=14,
        )
        self.tree_results.heading("uid", text="UID")
        self.tree_results.heading("group_name", text="Group")
        self.tree_results.heading("status", text="Trạng thái")

        self.tree_results.column("uid", width=180, anchor="w")
        self.tree_results.column("group_name", width=220, anchor="w")
        self.tree_results.column("status", width=110, anchor="center")

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

    def add_result(self, uid, group_name="", status="OK"):
        self.scan_results.append({"uid": uid, "group_name": group_name, "status": status})
        self.tree_results.insert("", "end", values=(uid, group_name, status))

    def clear_results(self):
        self.scan_results.clear()
        for item in self.tree_results.get_children():
            self.tree_results.delete(item)
        self.set_status("Đã xóa danh sách kết quả", color="gray")

    # =========================================================================
    # LOGIC CHẠY TỰ ĐỘNG VỚI SELENIUM THREADING (THAM KHẢO TỪ SMS_SCREEN)
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

        # 3. Vô hiệu hóa nút bấm & đổi trạng thái
        self.btn_start.config(state=tk.DISABLED, text="Đang quét...")
        self.set_status(f"Đang khởi tạo trình duyệt cho {len(source_groups)} groups...", color="orange")

        print(source_groups)
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
        obj = None
        total_found = 0

        try:
            # Khởi tạo FacebookBot từ bot.py
            obj = bot.FacebookBot()
            obj.user_agent = getattr(self.controller, "user_agent", None)

            # Đăng nhập bằng Cookies
            is_login = obj.login_with_cookies(user, getattr(self.controller, "cookies", []))
            if not is_login:
                self.after(0, lambda: messagebox.showerror("Lỗi", "Đăng nhập Cookies thất bại!"))
                return

            # Lặp qua từng Group để perform_scan / perform_search
            for idx, group in enumerate(target_groups, start=1):
                group_id = group.get("id")
                group_name = group.get("name", group_id)

                # Cập nhật trạng thái hiển thị
                self.after(0, lambda g_name=group_name, i=idx, total=len(target_groups): 
                    self.set_status(f"[{i}/{total}] Đang quét nhóm: {g_name}...", color="orange")
                )

                try:
                    # Gọi trực tiếp hàm perform_search từ bot.py
                    members = obj.perform_search(
                        group_id=group_id,
                        output_path=f"users_group_{group_id}.json",
                        scroll_pause=1.5
                    )

                    # Đưa danh sách UID thu thập được lên Treeview giao diện
                    for member in members:
                        u_id = member.get("user_id")
                        if u_id:
                            total_found += 1
                            # Gọi add_result trên thread chính
                            self.after(0, self.add_result, u_id, group_name, "OK")

                except Exception as group_err:
                    print(f"❌ Lỗi khi quét group {group_id}: {group_err}")
                    self.after(0, self.add_result, "N/A", group_name, "Lỗi Quét")

            # Thông báo hoàn tất thành công
            self.after(0, lambda: messagebox.showinfo(
                "Hoàn tất", 
                f"Đã quét xong {len(target_groups)} groups!\nTổng cộng thu thập được {total_found} UIDs."
            ))

        except Exception as e:
            print(f"❌ Lỗi tiến trình quét UID: {e}")
            self.after(0, lambda err=str(e): messagebox.showerror("Lỗi Tiến Trình", f"Có lỗi xảy ra: {err}"))

        finally:
            # Luôn đóng trình duyệt và bật lại nút Start trên giao diện
            if obj:
                obj.close()
            self.after(0, lambda: self.btn_start.config(state=tk.NORMAL, text="Bắt đầu quét"))
            self.after(0, lambda: self.set_status("Hoàn tất quét", color="green"))