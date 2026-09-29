import tkinter as tk
from tkinter import messagebox, ttk
import threading

import bot


class PostScanScreen(tk.Frame):
    """Giao diện cấu hình quét bài viết; chưa gọi crawler/Selenium."""

    def __init__(self, parent, controller):
        super().__init__(parent)
        self.parent = parent
        self.controller = controller
        self.scan_results = []
        self.scope_var = tk.StringVar(value="search")
        self.max_posts_var = tk.IntVar(value=100)
        self.stop_event = threading.Event()
        self.current_bot = None
        self._build_ui()

    def _build_ui(self):
        left_container = ttk.Frame(self.parent)
        left_container.pack(side="left", fill="both", expand=False, padx=(10, 5), pady=10)
        left_container.rowconfigure(0, weight=1)
        left_container.columnconfigure(0, weight=1)

        config_canvas = tk.Canvas(left_container, highlightthickness=0, borderwidth=0)
        config_scrollbar = ttk.Scrollbar(
            left_container, orient="vertical", command=config_canvas.yview
        )
        config_canvas.configure(yscrollcommand=config_scrollbar.set)
        config_canvas.grid(row=0, column=0, sticky="nsew")
        config_scrollbar.grid(row=0, column=1, sticky="ns")

        left_frame = ttk.LabelFrame(
            config_canvas, text=" Cấu hình quét bài ", padding=12
        )
        config_window = config_canvas.create_window(
            (0, 0), window=left_frame, anchor="nw"
        )

        def update_config_scroll_region(event=None):
            config_canvas.configure(scrollregion=config_canvas.bbox("all"))

        def fit_config_width(event):
            config_canvas.itemconfigure(config_window, width=event.width)

        def scroll_config(event):
            config_canvas.yview_scroll(-int(event.delta / 120), "units")

        left_frame.bind("<Configure>", update_config_scroll_region)
        config_canvas.bind("<Configure>", fit_config_width)
        config_canvas.bind("<MouseWheel>", scroll_config)

        right_frame = ttk.LabelFrame(
            self.parent, text=" Kết quả quét bài ", padding=12
        )
        right_frame.pack(side="right", fill="both", expand=True, padx=(5, 10), pady=10)

        scope_box = ttk.LabelFrame(left_frame, text=" Phạm vi quét ", padding=10)
        scope_box.pack(fill="x", pady=(0, 10))

        ttk.Radiobutton(
            scope_box,
            text="Search tổng quát trên Facebook",
            variable=self.scope_var,
            value="search",
            command=self._update_scope_ui,
        ).pack(anchor="w")
        ttk.Radiobutton(
            scope_box,
            text="Chỉ trong group đã chọn",
            variable=self.scope_var,
            value="groups",
            command=self._update_scope_ui,
        ).pack(anchor="w", pady=(5, 0))

        self.lbl_scope_help = ttk.Label(
            scope_box,
            foreground="#0056b3",
            font=("Segoe UI", 8, "italic"),
            wraplength=290,
        )
        self.lbl_scope_help.pack(anchor="w", pady=(8, 0))

        search_box = ttk.LabelFrame(left_frame, text=" Thanh Search ", padding=10)
        search_box.pack(fill="x", pady=(0, 10))
        search_box.columnconfigure(0, weight=1)

        ttk.Label(search_box, text="Từ khóa tìm bài:").grid(row=0, column=0, sticky="w")
        self.ent_keyword = ttk.Entry(search_box)
        self.ent_keyword.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        ttk.Label(
            search_box,
            text="Dùng cho phạm vi Search tổng quát.",
            foreground="#666666",
            font=("Segoe UI", 8, "italic"),
        ).grid(row=2, column=0, sticky="w", pady=(4, 0))

        self.group_box = ttk.LabelFrame(left_frame, text=" Phạm vi Group ", padding=10)
        self.group_box.pack(fill="x", pady=(0, 10))
        self.lbl_group_source = ttk.Label(self.group_box, wraplength=290)
        self.lbl_group_source.pack(anchor="w")
        ttk.Label(
            self.group_box,
            text="Quản lý lựa chọn trong Danh sách nhóm.",
            foreground="#666666",
            font=("Segoe UI", 8, "italic"),
        ).pack(anchor="w", pady=(4, 0))

        filter_box = ttk.LabelFrame(left_frame, text=" Bộ lọc cơ bản ", padding=10)
        filter_box.pack(fill="x", pady=(0, 10))
        filter_box.columnconfigure(1, weight=1)

        ttk.Label(filter_box, text="Số bài tối đa:").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Spinbox(
            filter_box,
            from_=1,
            to=10000,
            increment=50,
            textvariable=self.max_posts_var,
            width=10,
        ).grid(row=0, column=1, sticky="w", padx=(8, 0), pady=3)

        ttk.Label(filter_box, text="Khoảng thời gian:").grid(row=1, column=0, sticky="w", pady=3)
        self.cbo_time_range = ttk.Combobox(
            filter_box,
            values=("24 giờ gần đây", "7 ngày gần đây", "30 ngày gần đây", "Không giới hạn"),
            state="readonly",
        )
        self.cbo_time_range.set("7 ngày gần đây")
        self.cbo_time_range.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=3)

        ttk.Label(filter_box, text="Loại bài:").grid(row=2, column=0, sticky="w", pady=3)
        self.cbo_post_type = ttk.Combobox(
            filter_box,
            values=("Tất cả", "Bài có ảnh/video", "Bài có link", "Bài văn bản"),
            state="readonly",
        )
        self.cbo_post_type.set("Tất cả")
        self.cbo_post_type.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=3)

        output_box = ttk.LabelFrame(left_frame, text=" Dữ liệu dự kiến lưu ", padding=10)
        output_box.pack(fill="x", pady=(0, 10))
        self.var_content = tk.BooleanVar(value=True)
        self.var_author = tk.BooleanVar(value=True)
        self.var_metrics = tk.BooleanVar(value=False)
        ttk.Checkbutton(output_box, text="Nội dung và link bài", variable=self.var_content).pack(anchor="w")
        ttk.Checkbutton(output_box, text="Tác giả và thời gian đăng", variable=self.var_author).pack(anchor="w")
        ttk.Checkbutton(output_box, text="Reaction và bình luận", variable=self.var_metrics).pack(anchor="w")

        footer_frame = ttk.Frame(left_container, padding=(12, 8, 12, 0))
        footer_frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        action_box = ttk.Frame(footer_frame)
        action_box.pack(fill="x")
        self.btn_start = ttk.Button(
            action_box, text="Bắt đầu phân tích", command=self.start_post_scan
        )
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.btn_stop = ttk.Button(
            action_box, text="Dừng", command=self.stop_post_scan, state=tk.DISABLED
        )
        self.btn_stop.pack(side="right", padx=(4, 0))

        utility_box = ttk.Frame(footer_frame)
        utility_box.pack(fill="x", pady=(6, 0))
        ttk.Button(
            utility_box, text="Kiểm tra cấu hình", command=self.validate_configuration
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(
            utility_box, text="Xóa kết quả", command=self.clear_results
        ).pack(side="right", fill="x", expand=True, padx=(4, 0))

        self.lbl_status = ttk.Label(
            footer_frame,
            text="Trạng thái: Sẵn sàng cấu hình quét bài.",
            foreground="#0066cc",
            wraplength=310,
        )
        self.lbl_status.pack(anchor="w", pady=(10, 0))

        table_frame = ttk.Frame(right_frame)
        table_frame.pack(fill="both", expand=True)
        self.tree_results = ttk.Treeview(
            table_frame,
            columns=("scope", "source", "content", "published_at", "link"),
            show="headings",
        )
        self.tree_results.heading("scope", text="Phạm vi")
        self.tree_results.heading("source", text="Nguồn")
        self.tree_results.heading("content", text="Nội dung")
        self.tree_results.heading("published_at", text="Thời gian")
        self.tree_results.heading("link", text="Link bài")
        self.tree_results.column("scope", width=100, anchor="center")
        self.tree_results.column("source", width=170, anchor="w")
        self.tree_results.column("content", width=280, anchor="w")
        self.tree_results.column("published_at", width=130, anchor="center")
        self.tree_results.column("link", width=220, anchor="w")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree_results.yview)
        self.tree_results.configure(yscrollcommand=scrollbar.set)
        self.tree_results.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        ttk.Label(
            right_frame,
            text="Kết quả thực tế sẽ được hiển thị tại đây khi crawler được tích hợp.",
            foreground="#666666",
            font=("Segoe UI", 8, "italic"),
        ).pack(anchor="w", pady=(8, 0))

        self._update_scope_ui()

    def refresh_groups_preview(self):
        groups = getattr(self.controller, "groups_data", []) or []
        selected_count = sum(1 for group in groups if group.get("checked", False))
        self.lbl_group_source.config(
            text=f"Đã lưu: {len(groups)} group | Đã chọn: {selected_count} group"
        )

    def _update_scope_ui(self):
        is_search_scope = self.scope_var.get() == "search"
        self.ent_keyword.config(state="normal" if is_search_scope else "disabled")
        self.lbl_scope_help.config(
            text=(
                "Search là phạm vi rộng nhất; quét bài theo từ khóa trên Facebook."
                if is_search_scope
                else "Group là phạm vi hẹp hơn; chỉ quét các group đã được chọn."
            )
        )
        self.refresh_groups_preview()

    def validate_configuration(self):
        return self._get_scan_configuration() is not None

    def _get_scan_configuration(self):
        if not self.controller.has_uid:
            messagebox.showwarning(
                "Thiếu tài khoản",
                "Vui lòng kết nối Extension để nhận tài khoản trước khi quét.",
            )
            return None

        scope = self.scope_var.get()
        keyword = self.ent_keyword.get().strip()
        selected_groups = []
        if scope == "search" and not keyword:
            messagebox.showwarning("Thiếu từ khóa", "Vui lòng nhập từ khóa để quét Search tổng quát.")
            return None

        if scope == "groups":
            selected_groups = [
                group for group in getattr(self.controller, "groups_data", [])
                if group.get("checked", False)
            ]
            if not selected_groups:
                messagebox.showwarning("Thiếu group", "Vui lòng chọn ít nhất một group.")
                return None

        try:
            max_posts = self.max_posts_var.get()
        except tk.TclError:
            max_posts = 0

        if max_posts < 1:
            messagebox.showwarning("Dữ liệu không hợp lệ", "Số bài tối đa phải lớn hơn 0.")
            return None

        self.lbl_status.config(
            text="Trạng thái: Cấu hình hợp lệ. Sẵn sàng mở Facebook để phân tích.",
            foreground="#008000",
        )
        return {
            "scope": scope,
            "keyword": keyword,
            "group_ids": [group.get("id", "") for group in selected_groups],
            "max_posts": max_posts,
        }

    def start_post_scan(self):
        config = self._get_scan_configuration()
        if not config:
            return

        self.stop_event.clear()
        self.btn_start.config(state=tk.DISABLED, text="Đang mở Facebook...")
        self.btn_stop.config(state=tk.NORMAL)
        self.lbl_status.config(
            text="Trạng thái: Đang khởi tạo browser để phân tích bài viết...",
            foreground="#cc7a00",
        )
        threading.Thread(
            target=self._run_post_scan_analysis,
            args=(self.controller.get_uid(), config),
            daemon=True,
        ).start()

    def stop_post_scan(self):
        self.stop_event.set()
        self.btn_stop.config(state=tk.DISABLED)
        self.lbl_status.config(
            text="Trạng thái: Đang dừng và đóng browser...", foreground="#cc0000"
        )

    def _run_post_scan_analysis(self, user_id, config):
        worker = None
        try:
            # Phân tích thủ công luôn cần browser hiển thị, độc lập với Demo Mode.
            worker = bot.FacebookBot(
                visualize=True,
                stop_event=self.stop_event,
                browser_mode="analysis",
            )
            self.current_bot = worker
            if not worker.start_browser(
                user_id,
                user_agent=self.controller.get_user_agent(),
                driver_type="undetected",
            ):
                error_message = worker.get_start_error_message()
                self.after(0, lambda msg=error_message: messagebox.showerror("Lỗi", msg))
                return

            self.after(
                0,
                lambda: self.lbl_status.config(
                    text="Trạng thái: Facebook đã mở. Có 30 phút để phân tích thủ công.",
                    foreground="#008000",
                ),
            )
            result = worker.prepare_post_scan_analysis(
                scope=config["scope"],
                keyword=config["keyword"],
                group_ids=config["group_ids"],
                pause_seconds=1800,
            )
            status = result.get("status", "completed")
            source = result.get("source", "")
            self.after(0, self.tree_results.insert, "", "end", values=(
                config["scope"], source, "Chưa trích xuất", "", result.get("url", "")
            ))
            self.after(
                0,
                lambda: self.lbl_status.config(
                    text=(
                        "Trạng thái: Đã dừng phiên phân tích."
                        if status == "stopped"
                        else "Trạng thái: Browser đã được đóng thủ công."
                        if status == "browser_closed"
                        else "Trạng thái: Hết thời gian phân tích; chưa trích xuất bài viết."
                    ),
                    foreground="#cc0000" if status in ("stopped", "browser_closed") else "#008000",
                ),
            )
        except Exception as error:
            self.after(
                0,
                lambda err=str(error): messagebox.showerror(
                    "Lỗi Quét bài", f"Không thể chuẩn bị phiên phân tích: {err}"
                ),
            )
        finally:
            if worker:
                try:
                    worker.close()
                except Exception:
                    pass
            self.current_bot = None
            self.after(0, lambda: self.btn_start.config(state=tk.NORMAL, text="Bắt đầu phân tích"))
            self.after(0, lambda: self.btn_stop.config(state=tk.DISABLED))

    def clear_results(self):
        self.scan_results.clear()
        self.tree_results.delete(*self.tree_results.get_children())
        self.lbl_status.config(
            text="Trạng thái: Đã xóa kết quả hiển thị.", foreground="#0066cc"
        )
