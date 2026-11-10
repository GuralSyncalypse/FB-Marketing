import tkinter as tk
from tkinter import messagebox, ttk

import customtkinter as ctk
import threading

import bot
from services.ui_theme import (
    BG_PANEL,
    ERROR_COLOR,
    INFO_COLOR,
    SUCCESS_COLOR,
    TEXT_MUTED,
    TitledFrame,
    WARNING_COLOR,
    ScanActionBar,
    apply_theme,
)


class PostScanScreen(ctk.CTkFrame):
    """Giao diện cấu hình quét bài viết và lưu kết quả ra file JSON."""

    def __init__(self, parent, controller):
        super().__init__(parent)
        self.parent = parent
        self.controller = controller
        self.scan_results = []
        self.scope_var = tk.StringVar(value="search")
        self.max_posts_var = tk.IntVar(value=100)
        self.var_recent_posts = tk.BooleanVar(value=False)
        self.stop_event = threading.Event()
        self.current_bot = None
        apply_theme()
        self._build_ui()

    def _build_ui(self):
        left_container = ctk.CTkFrame(self.parent, fg_color="transparent")
        left_container.pack(side="left", fill="both", expand=False, padx=(10, 5), pady=10)
        left_container.rowconfigure(0, weight=1)
        left_container.columnconfigure(0, weight=1)

        # CTkScrollableFrame thay cho Canvas + Scrollbar thủ công
        config_scroll = ctk.CTkScrollableFrame(
            left_container,
            label_text=" Cấu hình quét bài ",
            label_fg_color=BG_PANEL,
            label_anchor="w",
            fg_color=BG_PANEL,
            corner_radius=10,
            width=340,
        )
        config_scroll.grid(row=0, column=0, sticky="nsew")

        right_frame = TitledFrame(
            self.parent, title=" Kết quả quét bài "
        )
        right_frame.pack(side="right", fill="both", expand=True, padx=(5, 10), pady=10)

        scope_box = TitledFrame(config_scroll, title=" Phạm vi quét ")
        scope_box.pack(fill="x", pady=(0, 10))

        ctk.CTkRadioButton(
            scope_box.body,
            text="Search tổng quát trên Facebook",
            variable=self.scope_var,
            value="search",
            command=self._update_scope_ui,
        ).pack(anchor="w")
        ctk.CTkRadioButton(
            scope_box.body,
            text="Chỉ trong group đã chọn",
            variable=self.scope_var,
            value="groups",
            command=self._update_scope_ui,
        ).pack(anchor="w", pady=(5, 0))

        self.lbl_scope_help = ctk.CTkLabel(
            scope_box.body,
            text_color=INFO_COLOR,
            font=ctk.CTkFont(size=11, slant="italic"),
            wraplength=290,
            justify="left",
            anchor="w",
        )
        self.lbl_scope_help.pack(anchor="w", pady=(8, 0))

        self.search_box = TitledFrame(config_scroll, title=" Từ khóa Search ")
        self.search_box.pack(fill="x", pady=(0, 10))
        self.search_box.body.columnconfigure(0, weight=1)

        ctk.CTkLabel(self.search_box.body, text="Từ khóa tìm bài:").grid(
            row=0, column=0, sticky="w"
        )
        self.ent_keyword = ctk.CTkEntry(self.search_box.body)
        self.ent_keyword.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        self.chk_recent_posts = ctk.CTkCheckBox(
            self.search_box.body,
            text="Ưu tiên bài đăng gần đây",
            variable=self.var_recent_posts,
        )
        self.chk_recent_posts.grid(row=2, column=0, sticky="w", pady=(8, 0))

        self.group_box = TitledFrame(config_scroll, title=" Phạm vi Group ")
        self.group_box.pack(fill="x", pady=(0, 10))
        self.lbl_group_source = ctk.CTkLabel(
            self.group_box.body, wraplength=290, justify="left", anchor="w"
        )
        self.lbl_group_source.pack(anchor="w")
        ctk.CTkLabel(
            self.group_box.body,
            text="Quản lý lựa chọn trong Danh sách nhóm.",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=11, slant="italic"),
        ).pack(anchor="w", pady=(4, 0))

        self.filter_box = TitledFrame(config_scroll, title=" Bộ lọc ")
        self.filter_box.pack(fill="x", pady=(0, 10))
        self.filter_box.body.columnconfigure(1, weight=1)
        filter_box = self.filter_box

        ctk.CTkLabel(filter_box.body, text="Số bài tối đa:").grid(
            row=0, column=0, sticky="w", pady=3
        )
        ttk.Spinbox(
            filter_box.body,
            from_=1,
            to=10000,
            increment=50,
            textvariable=self.max_posts_var,
            width=10,
        ).grid(row=0, column=1, sticky="w", padx=(8, 0), pady=3)

        self.lbl_time_range = ctk.CTkLabel(
            filter_box.body, text="Khoảng thời gian:"
        )
        self.lbl_time_range.grid(row=1, column=0, sticky="w", pady=3)
        self.cbo_time_range = ctk.CTkComboBox(
            filter_box.body,
            values=("24 giờ gần đây", "7 ngày gần đây", "30 ngày gần đây", "Không giới hạn"),
            state="readonly",
        )
        self.cbo_time_range.set("7 ngày gần đây")
        self.cbo_time_range.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=3)

        self.lbl_post_type = ctk.CTkLabel(filter_box.body, text="Loại bài:")
        self.lbl_post_type.grid(row=2, column=0, sticky="w", pady=3)
        self.cbo_post_type = ctk.CTkComboBox(
            filter_box.body,
            values=("Tất cả", "Bài có ảnh/video", "Bài có link", "Bài văn bản"),
            state="readonly",
        )
        self.cbo_post_type.set("Tất cả")
        self.cbo_post_type.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=3)

        self.lbl_filter_help = ctk.CTkLabel(
            filter_box.body,
            text="Thời gian/loại bài chỉ áp dụng cho Search.",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=11, slant="italic"),
            wraplength=290,
            justify="left",
            anchor="w",
        )
        self.lbl_filter_help.grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )

        footer_frame = ctk.CTkFrame(left_container, fg_color="transparent")
        footer_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(8, 0))

        # Cụm nút dùng chung với tab Quét UID để đồng bộ thao tác.
        self.action_bar = ScanActionBar(
            footer_frame,
            start_command=self.start_post_scan,
            stop_command=self.stop_post_scan,
        )
        self.action_bar.pack(fill="x")
        self.btn_start = self.action_bar.btn_start
        self.btn_stop = self.action_bar.btn_stop

        self.lbl_status = ctk.CTkLabel(
            footer_frame,
            text="Trạng thái: Sẵn sàng quét bài.",
            text_color=INFO_COLOR,
            wraplength=310,
            justify="left",
            anchor="w",
        )
        self.lbl_status.pack(anchor="w", pady=(10, 0))

        table_frame = ctk.CTkFrame(right_frame.body, fg_color="transparent")
        table_frame.pack(fill="both", expand=True)
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
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

        scrollbar = ctk.CTkScrollbar(
            table_frame, orientation="vertical", command=self.tree_results.yview
        )
        hscrollbar = ctk.CTkScrollbar(
            table_frame, orientation="horizontal", command=self.tree_results.xview
        )
        self.tree_results.configure(
            yscrollcommand=scrollbar.set, xscrollcommand=hscrollbar.set
        )
        self.tree_results.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        hscrollbar.grid(row=1, column=0, sticky="ew")

        result_footer = ctk.CTkFrame(right_frame.body, fg_color="transparent")
        result_footer.pack(fill="x", pady=(8, 0))

        ctk.CTkLabel(
            result_footer,
            text=(
                "Kết quả lưu JSON trong data/<uid>/raw; "
                "Excel/CSV trong data/<uid>/exports."
            ),
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=11, slant="italic"),
            justify="left",
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        ctk.CTkButton(
            result_footer,
            text="Xóa kết quả",
            command=self.clear_results,
            width=100,
            height=26,
            fg_color="transparent",
            border_width=1,
            text_color=TEXT_MUTED,
        ).pack(side="right", padx=(10, 0))

        self._update_scope_ui()

    def refresh_groups_preview(self):
        groups = getattr(self.controller, "groups_data", []) or []
        selected_count = sum(1 for group in groups if group.get("checked", False))
        self.lbl_group_source.configure(
            text=f"Tổng groups: {len(groups)} | Đang chọn: {selected_count}"
        )

    def _update_scope_ui(self):
        """Chỉ hiển thị đúng phần cấu hình liên quan tới phạm vi đang chọn."""
        is_search_scope = self.scope_var.get() == "search"

        if is_search_scope:
            self.group_box.pack_forget()
            self.search_box.pack(
                fill="x", pady=(0, 10), before=self.filter_box
            )
        else:
            self.search_box.pack_forget()
            self.group_box.pack(
                fill="x", pady=(0, 10), before=self.filter_box
            )

        # Bộ lọc thời gian/loại bài chỉ hỗ trợ Search: ẩn hẳn khi quét Group
        # thay vì để các ô bị vô hiệu hóa gây rối mắt.
        self.lbl_time_range.grid_remove()
        self.cbo_time_range.grid_remove()
        self.lbl_post_type.grid_remove()
        self.cbo_post_type.grid_remove()
        self.lbl_filter_help.grid_remove()
        if is_search_scope:
            self.lbl_time_range.grid()
            self.cbo_time_range.grid()
            self.lbl_post_type.grid()
            self.cbo_post_type.grid()
            self.lbl_filter_help.grid()

        self.lbl_scope_help.configure(
            text=(
                "Quét bài theo từ khóa trên toàn Facebook."
                if is_search_scope
                else "Chỉ quét bài trong các group đã chọn."
            )
        )
        self.refresh_groups_preview()

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

        self.lbl_status.configure(
            text="Trạng thái: Cấu hình hợp lệ. Sẵn sàng mở Facebook để phân tích.",
            text_color=SUCCESS_COLOR,
        )
        # Khoảng thời gian, loại bài chỉ hỗ trợ Search. Tùy chọn dữ liệu lưu
        # vẫn chưa được hỗ trợ và nằm trong khung "Chưa có".
        time_range = (
            self.cbo_time_range.get() if scope == "search" else "all"
        )
        post_type = (
            self.cbo_post_type.get() if scope == "search" else "all"
        )
        return {
            "scope": scope,
            "keyword": keyword,
            "group_ids": [group.get("id", "") for group in selected_groups],
            "max_posts": max_posts,
            "recent_posts": bool(self.var_recent_posts.get()) if scope == "search" else False,
            "time_range": time_range,
            "post_type": post_type,
        }

    def start_post_scan(self):
        config = self._get_scan_configuration()
        if not config:
            return

        self.stop_event.clear()
        self.action_bar.mark_running()
        self.lbl_status.configure(
            text="Trạng thái: Đang khởi tạo browser để phân tích bài viết...",
            text_color=WARNING_COLOR,
        )
        threading.Thread(
            target=self._run_post_scan_analysis,
            args=(self.controller.get_uid(), config),
            daemon=True,
        ).start()

    def stop_post_scan(self):
        self.stop_event.set()
        self.action_bar.mark_stopping()
        self.lbl_status.configure(
            text="Trạng thái: Đang dừng và đóng browser...", text_color=ERROR_COLOR
        )

    def _run_post_scan_analysis(self, user_id, config):
        worker = None
        try:
            # Trích xuất DOM cần browser hiển thị, độc lập với Demo Mode.
            worker = bot.FacebookBot(
                visualize=True,
                stop_event=self.stop_event,
                browser_mode="analysis",
            )
            self.current_bot = worker
            if not worker.start_browser(
                user_id,
                user_agent=self.controller.get_user_agent(),
            ):
                error_message = worker.get_start_error_message()
                self.after(0, lambda msg=error_message: messagebox.showerror("Lỗi", msg))
                return

            self.after(
                0,
                lambda: self.lbl_status.configure(
                    text="Trạng thái: Facebook đã mở. Đang trích xuất bài viết...",
                    text_color=SUCCESS_COLOR,
                ),
            )
            result = worker.prepare_post_scan_analysis(
                scope=config["scope"],
                keyword=config["keyword"],
                group_ids=config["group_ids"],
                pause_seconds=0,
                max_posts=config["max_posts"],
                recent_posts=config.get("recent_posts", False),
                time_range=config.get("time_range", "all"),
                post_type=config.get("post_type", "all"),
            )
            status = result.get("status", "completed")
            post_count = result.get("post_count", 0)

            output_parts = []
            xlsx_path = result.get("xlsx_path")
            csv_path = result.get("csv_path")
            file_path = result.get("file_path")
            if xlsx_path:
                output_parts.append(f"Excel: {xlsx_path}")
            if csv_path:
                output_parts.append(f"CSV: {csv_path}")
            if file_path:
                output_parts.append(f"JSON: {file_path}")
            output_text = (
                "\n" + "\n".join(output_parts) if output_parts else ""
            )

            if status == "completed":
                message = (
                    f"Trạng thái: Đã trích xuất {post_count} bài."
                    f"{output_text}"
                )
                text_color = SUCCESS_COLOR
            elif status == "stopped":
                message = (
                    f"Trạng thái: Đã dừng. Đã lưu {post_count} bài."
                    f"{output_text}"
                )
                text_color = ERROR_COLOR
            elif status == "browser_closed":
                message = (
                    f"Trạng thái: Browser đã được đóng thủ công. "
                    f"Đã lưu {post_count} bài.{output_text}"
                )
                text_color = ERROR_COLOR
            elif status == "feed_not_found":
                message = "Trạng thái: Không tìm thấy feed bài viết để trích xuất."
                text_color = ERROR_COLOR
            elif status == "error":
                message = (
                    "Trạng thái: Lỗi khi trích xuất"
                    + (f" ({result.get('error')})" if result.get("error") else ".")
                    + (f" Đã lưu {post_count} bài." if post_count else "")
                    + output_text
                )
                text_color = ERROR_COLOR
            else:
                message = "Trạng thái: Không trích xuất được bài viết nào."
                text_color = WARNING_COLOR
            self.after(
                0,
                lambda text=message, color=text_color: self.lbl_status.configure(
                    text=text, text_color=color
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
            self.after(0, self.action_bar.mark_idle)

    def clear_results(self):
        self.scan_results.clear()
        self.tree_results.delete(*self.tree_results.get_children())
        self.lbl_status.configure(
            text="Trạng thái: Đã xóa kết quả hiển thị.", text_color=INFO_COLOR
        )
