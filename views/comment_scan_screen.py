import threading
import tkinter as tk
from tkinter import messagebox, ttk

import customtkinter as ctk

import bot
from services.ui_theme import (
    BG_PANEL,
    DangerButton,
    ERROR_COLOR,
    INFO_COLOR,
    SUCCESS_COLOR,
    TEXT_MUTED,
    TitledFrame,
    WARNING_COLOR,
    apply_theme,
)


class CommentScanScreen(ctk.CTkFrame):
    """Giao diện quét bình luận/reply từ URL hoặc ID một bài viết."""

    def __init__(self, parent, controller):
        super().__init__(parent)
        self.parent = parent
        self.controller = controller
        self.stop_event = threading.Event()
        self.current_bot = None
        self.comments = []

        apply_theme()
        self._build_ui()

    def _build_ui(self):
        left_container = ctk.CTkFrame(self.parent, fg_color="transparent")
        left_container.pack(
            side="left", fill="both", expand=False, padx=(10, 5), pady=10
        )
        left_container.rowconfigure(0, weight=1)
        left_container.columnconfigure(0, weight=1)

        config_scroll = ctk.CTkScrollableFrame(
            left_container,
            label_text=" Cấu hình quét bình luận ",
            label_fg_color=BG_PANEL,
            label_anchor="w",
            fg_color=BG_PANEL,
            corner_radius=10,
            width=340,
        )
        config_scroll.grid(row=0, column=0, sticky="nsew")

        source_box = TitledFrame(config_scroll, title=" Bài viết cần quét ")
        source_box.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            source_box.body, text="URL hoặc ID bài viết:"
        ).pack(anchor="w")
        self.ent_target = ctk.CTkEntry(
            source_box.body,
            placeholder_text="https://www.facebook.com/reel/... hoặc 147...",
        )
        self.ent_target.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(
            source_box.body,
            text=(
                "Hỗ trợ bài thường, permalink và Reel. Có thể dán trực tiếp "
                "ID feedback nếu đã biết."
            ),
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=11, slant="italic"),
            wraplength=290,
            justify="left",
            anchor="w",
        ).pack(anchor="w", pady=(4, 0))

        options_box = TitledFrame(config_scroll, title=" Tùy chọn ")
        options_box.pack(fill="x", pady=(0, 10))
        options_box.body.columnconfigure(1, weight=1)

        self.var_replies = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            options_box.body,
            text="Lấy cả reply",
            variable=self.var_replies,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        ctk.CTkLabel(
            options_box.body, text="Tổng mục tối đa (gồm reply):"
        ).grid(row=1, column=0, sticky="w", pady=3)
        self.max_comments_var = tk.IntVar(value=0)
        ttk.Spinbox(
            options_box.body,
            from_=0,
            to=100000,
            increment=50,
            textvariable=self.max_comments_var,
            width=10,
        ).grid(row=1, column=1, sticky="w", padx=(8, 0), pady=3)

        ctk.CTkLabel(
            options_box.body, text="Reply tối đa/comment:"
        ).grid(row=2, column=0, sticky="w", pady=3)
        self.max_replies_var = tk.IntVar(value=0)
        ttk.Spinbox(
            options_box.body,
            from_=0,
            to=10000,
            increment=10,
            textvariable=self.max_replies_var,
            width=10,
        ).grid(row=2, column=1, sticky="w", padx=(8, 0), pady=3)

        ctk.CTkLabel(
            options_box.body,
            text="0 = không giới hạn. Nên đặt giới hạn khi bài có nhiều bình luận.",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=11, slant="italic"),
            wraplength=290,
            justify="left",
            anchor="w",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))

        output_box = TitledFrame(config_scroll, title=" Kết quả ")
        output_box.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            output_box.body,
            text=(
                "Kết quả được lưu JSON trong data/<uid>/raw; Excel và CSV "
                "trong data/<uid>/exports."
            ),
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=11, slant="italic"),
            wraplength=290,
            justify="left",
            anchor="w",
        ).pack(anchor="w")

        footer_frame = ctk.CTkFrame(left_container, fg_color="transparent")
        footer_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(8, 0))
        self.btn_start = ctk.CTkButton(
            footer_frame,
            text="Bắt đầu quét bình luận",
            command=self.start_comment_scan,
        )
        self.btn_start.pack(fill="x")
        self.btn_stop = DangerButton(
            footer_frame,
            text="Dừng",
            command=self.stop_comment_scan,
            state="disabled",
        )
        self.btn_stop.pack(fill="x", pady=(6, 0))

        self.lbl_status = ctk.CTkLabel(
            footer_frame,
            text="Trạng thái: Sẵn sàng quét bình luận.",
            text_color=INFO_COLOR,
            wraplength=310,
            justify="left",
            anchor="w",
        )
        self.lbl_status.pack(anchor="w", pady=(10, 0))

        right_frame = TitledFrame(
            self.parent, title=" Kết quả bình luận "
        )
        right_frame.pack(
            side="right", fill="both", expand=True, padx=(5, 10), pady=10
        )

        table_frame = ctk.CTkFrame(right_frame.body, fg_color="transparent")
        table_frame.pack(fill="both", expand=True)
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        self.tree_results = ttk.Treeview(
            table_frame,
            columns=(
                "type",
                "author",
                "content",
                "reactions",
                "replies",
                "created_at",
                "link",
            ),
            show="headings",
        )
        self.tree_results.heading("type", text="Loại")
        self.tree_results.heading("author", text="Tác giả")
        self.tree_results.heading("content", text="Nội dung")
        self.tree_results.heading("reactions", text="Reaction")
        self.tree_results.heading("replies", text="Reply")
        self.tree_results.heading("created_at", text="Thời gian")
        self.tree_results.heading("link", text="Link")
        self.tree_results.column("type", width=80, anchor="center")
        self.tree_results.column("author", width=160, anchor="w")
        self.tree_results.column("content", width=360, anchor="w")
        self.tree_results.column("reactions", width=75, anchor="center")
        self.tree_results.column("replies", width=60, anchor="center")
        self.tree_results.column("created_at", width=145, anchor="center")
        self.tree_results.column("link", width=240, anchor="w")
        self.tree_results.tag_configure("reply", foreground=TEXT_MUTED)
        self.tree_results.bind("<Double-1>", self._open_selected_link)

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

    def _get_configuration(self):
        if not getattr(self.controller, "has_uid", False):
            messagebox.showwarning(
                "Thiếu tài khoản",
                "Vui lòng kết nối Extension để nhận tài khoản trước khi quét.",
            )
            return None

        target = self.ent_target.get().strip()
        if not target:
            messagebox.showwarning(
                "Thiếu bài viết",
                "Vui lòng nhập URL hoặc ID bài viết cần quét bình luận.",
            )
            return None

        try:
            max_comments = int(self.max_comments_var.get())
            max_replies = int(self.max_replies_var.get())
        except (tk.TclError, ValueError):
            messagebox.showwarning(
                "Dữ liệu không hợp lệ",
                "Số bình luận/reply tối đa phải là số nguyên không âm.",
            )
            return None

        if max_comments < 0 or max_replies < 0:
            messagebox.showwarning(
                "Dữ liệu không hợp lệ",
                "Số bình luận/reply tối đa không được âm.",
            )
            return None

        return {
            "target": target,
            "include_replies": bool(self.var_replies.get()),
            "max_comments": max_comments or None,
            "max_replies_per_comment": max_replies or None,
        }

    def start_comment_scan(self):
        config = self._get_configuration()
        if not config:
            return

        print(
            "[CommentScan] Bắt đầu: "
            f"target={config['target']}, replies={config['include_replies']}, "
            f"max_comments={config['max_comments']}, "
            f"max_replies={config['max_replies_per_comment']}"
        )
        self.stop_event.clear()
        self.comments = []
        self.tree_results.delete(*self.tree_results.get_children())
        self.btn_start.configure(state="disabled", text="Đang mở Facebook...")
        self.btn_stop.configure(state="normal")
        self.lbl_status.configure(
            text="Trạng thái: Đang khởi tạo browser để quét bình luận...",
            text_color=WARNING_COLOR,
        )
        threading.Thread(
            target=self._run_comment_scan,
            args=(self.controller.get_uid(), config),
            daemon=True,
        ).start()

    def stop_comment_scan(self):
        self.stop_event.set()
        self.btn_stop.configure(state="disabled")
        self.lbl_status.configure(
            text="Trạng thái: Đang dừng và đóng browser...",
            text_color=ERROR_COLOR,
        )

    def _run_comment_scan(self, user_id, config):
        worker = None
        try:
            print(f"[CommentScan] Mở browser cho UID {user_id}...")
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
                print(f"[CommentScan] Không mở được browser: {error_message}")
                self.after(
                    0,
                    lambda msg=error_message: messagebox.showerror(
                        "Lỗi", msg
                    ),
                )
                return

            print("[CommentScan] Browser đã mở, bắt đầu quét bình luận.")
            self.after(
                0,
                lambda: self.lbl_status.configure(
                    text=(
                        "Trạng thái: Facebook đã mở. Đang đọc ID bài viết "
                        "và quét bình luận..."
                    ),
                    text_color=SUCCESS_COLOR,
                ),
            )
            result = worker.scan_post_comments_from_url(
                config["target"],
                include_replies=config["include_replies"],
                max_comments=config["max_comments"],
                max_replies_per_comment=config[
                    "max_replies_per_comment"
                ],
                save=True,
                export=True,
            )
            comments = result.get("comments") or []
            self.comments = comments
            print(
                f"[CommentScan] Đã nhận {len(comments)} mục từ backend. "
                "Đang cập nhật bảng..."
            )
            self.after(0, lambda items=comments: self._render_results(items))

            output_parts = []
            json_path = result.get("json_path")
            export_paths = result.get("export_paths") or {}
            if json_path:
                output_parts.append(f"JSON: {json_path}")
            if export_paths.get("csv"):
                output_parts.append(f"CSV: {export_paths['csv']}")
            if export_paths.get("xlsx"):
                output_parts.append(f"Excel: {export_paths['xlsx']}")
            output_text = (
                "\n" + "\n".join(output_parts) if output_parts else ""
            )

            if self.stop_event.is_set():
                message = (
                    f"Trạng thái: Đã dừng. Đã lấy {len(comments)} bình luận."
                    f"{output_text}"
                )
                color = ERROR_COLOR
            else:
                message = (
                    f"Trạng thái: Đã lấy {len(comments)} bình luận/reply."
                    f"{output_text}"
                )
                color = SUCCESS_COLOR
            self.after(
                0,
                lambda text=message, text_color=color: self.lbl_status.configure(
                    text=text, text_color=text_color
                ),
            )
        except Exception as error:
            message = str(error)
            print(f"[CommentScan] Lỗi: {message}")
            self.after(
                0,
                lambda err=message: messagebox.showerror(
                    "Lỗi quét bình luận", err
                ),
            )
            self.after(
                0,
                lambda err=message: self.lbl_status.configure(
                    text=f"Trạng thái: Lỗi - {err}",
                    text_color=ERROR_COLOR,
                ),
            )
        finally:
            if worker:
                try:
                    worker.close()
                except Exception:
                    pass
            print("[CommentScan] Đã đóng browser và kết thúc tác vụ.")
            self.current_bot = None
            self.after(
                0,
                lambda: self.btn_start.configure(
                    state="normal", text="Bắt đầu quét bình luận"
                ),
            )
            self.after(0, lambda: self.btn_stop.configure(state="disabled"))

    def _render_results(self, comments):
        self.tree_results.delete(*self.tree_results.get_children())
        for index, comment in enumerate(comments):
            is_reply = bool(comment.get("is_reply"))
            depth = int(comment.get("depth") or 0)
            content = str(comment.get("content") or "").replace("\n", " ")
            if len(content) > 240:
                content = content[:240] + "…"
            self.tree_results.insert(
                "",
                "end",
                iid=f"comment-{index}",
                values=(
                    ("Reply" if is_reply else "Bình luận")
                    if not depth
                    else f"Reply cấp {depth}",
                    comment.get("author_name") or "",
                    content,
                    comment.get("reaction_count")
                    if comment.get("reaction_count") is not None
                    else "",
                    comment.get("reply_count")
                    if comment.get("reply_count") is not None
                    else "",
                    comment.get("created_at") or "",
                    comment.get("permalink") or "",
                ),
                tags=("reply",) if is_reply else (),
            )

    def _open_selected_link(self, _event=None):
        selection = self.tree_results.selection()
        if not selection:
            return
        values = self.tree_results.item(selection[0], "values")
        if not values or len(values) < 7 or not values[6]:
            return
        try:
            import webbrowser

            webbrowser.open(values[6])
        except Exception as error:
            messagebox.showerror("Lỗi", f"Không mở được link: {error}")
