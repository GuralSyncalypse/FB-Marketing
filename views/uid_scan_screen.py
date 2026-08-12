import json
import time
import tkinter as tk
import os
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

        # --- Frame chứa giới hạn UID & Số lần thử lại ---
        limit_frame = ttk.Frame(option_box)
        limit_frame.pack(fill="x", pady=(6, 2))

        # Spinbox 1: Giới hạn UID
        ttk.Label(limit_frame, text="Giới hạn UID/Group:").grid(row=0, column=0, sticky="w", padx=(0, 5))
        self.spin_max_members_var = tk.IntVar(value=5000)
        ttk.Spinbox(
            limit_frame,
            from_=0,
            to=500000,
            increment=500,
            textvariable=self.spin_max_members_var,
            width=10
        ).grid(row=0, column=1, sticky="w", pady=2)
        ttk.Label(limit_frame, text="(0 = Tất cả)").grid(row=0, column=2, sticky="w", padx=(5, 0))

        # Spinbox 2: Số lần thử lại (Retries)
        ttk.Label(limit_frame, text="Số lần thử lại (Retries):").grid(row=1, column=0, sticky="w", padx=(0, 5), pady=(4, 0))
        self.spin_retries_var = tk.IntVar(value=3)
        ttk.Spinbox(
            limit_frame,
            from_=1,
            to=10,
            increment=1,
            textvariable=self.spin_retries_var,
            width=10
        ).grid(row=1, column=1, sticky="w", pady=(4, 0))

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

    def handle_save_batch(self, batch_data, file_name="output.jsonl", folder_path="data"):
        """
        Hàm lưu dữ liệu vào thư mục chỉ định.
        Tự động tạo thư mục nếu chưa có.
        """
        if not batch_data:
            return

        # 1. Ghép đường dẫn file với thư mục
        if folder_path:
            full_path = os.path.join(folder_path, file_name)
        else:
            full_path = file_name

        # 2. Tạo thư mục cha (nếu chưa tồn tại)
        dir_name = os.path.dirname(full_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        print(f"--> [MAIN] Đang ghi batch {len(batch_data)} bản ghi vào {full_path}...")

        # 3. Ghi dữ liệu vào file
        with open(full_path, "a", encoding="utf-8") as f:
            for item in batch_data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    def start_uid_scan(self):
        # 1. Lấy và kiểm tra tài khoản đăng nhập
        user_id = self.controller.get_uid()

        if not self.controller.has_uid:
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
            args=(user_id, source_groups),
            daemon=True
        )
        scan_thread.start()

    def run_selenium_scan_process(self, user, target_groups):
        """Hàm thực thi logic Selenium chạy ngầm trong Thread."""
        print(f"\n[Selenium Quét UID] Bắt đầu tiến trình cho UID: {user}...")
        total_found = 0
        total_groups = len(target_groups)

        try:
            # Khởi tạo FacebookBot
            bot_obj = bot.FacebookBot(
                self.controller.is_demo_mode, 
                on_save_batch=self.handle_save_batch
            )
            bot_obj.stop_event = self.stop_event

            if self.stop_event.is_set():
                return

            # Đăng nhập bằng Cookies
            if not bot_obj.start_browser(user, user_agent=self.controller.get_user_agent()):
                self.after(0, lambda: messagebox.showerror("Lỗi", "Đăng nhập thất bại!"))
                return

            # Lặp qua từng Group
            for idx, group in enumerate(target_groups, start=1):
                if self.stop_event.is_set():
                    print("🛑 Tiến trình đã bị người dùng dừng.")
                    break

                group_id = group.get("id")
                group_name = group.get("name", group_id)

                self.after(0, lambda name=group_name, i=idx: 
                    self.set_status(f"[{i}/{total_groups}] Đang quét nhóm: {name}...", color="orange")
                )

                try:
                    output_path = f"output_{group_id}.jsonl"
                    bot_obj.output_path = output_path

                    members = bot_obj.scrape_group_members(
                        group_id=group_id, 
                        max_members=self.spin_max_members_var.get(), 
                        retries=self.spin_retries_var.get()
                    )

                    group_count = members
                    total_found += group_count
                    self.after(0, self.add_group_result, group_name, group_id, group_count, "OK")

                except Exception as group_err:
                    print(f"❌ Lỗi khi quét group {group_id}: {group_err}")
                    self.after(0, self.add_group_result, group_name, group_id, 0, "Lỗi Quét")

            # Thông báo kết quả cuối cùng
            is_stopped = self.stop_event.is_set()
            title = "Đã dừng" if is_stopped else "Hoàn tất"
            msg = f"{'Đã dừng tiến trình quét' if is_stopped else f'Đã quét xong {total_groups} groups'}!\nTổng cộng thu thập được {total_found:,} UIDs."
            show_box = messagebox.showwarning if is_stopped else messagebox.showinfo
            
            self.after(0, lambda: show_box(title, msg))

        except Exception as e:
            print(f"❌ Lỗi tiến trình quét UID: {e}")
            self.after(0, lambda err=str(e): messagebox.showerror("Lỗi Tiến Trình", f"Có lỗi xảy ra: {err}"))

        finally:
            # Dọn dẹp tài nguyên
            if bot_obj:
                try:
                    bot_obj.close()
                except Exception:
                    pass
                bot_obj = None

            # Cập nhật UI kết thúc
            is_stopped = self.stop_event.is_set()
            self.after(0, lambda: self.btn_start.config(state=tk.NORMAL, text="Bắt đầu quét"))
            self.after(0, lambda: self.btn_stop.config(state=tk.DISABLED))
            self.after(0, lambda: self.set_status(
                "Đã dừng quét" if is_stopped else "Hoàn tất quét", 
                color="red" if is_stopped else "green"
            ))