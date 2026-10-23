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


REACTION_OPTIONS = {
    "Tất cả": None,
    "Like": "LIKE",
    "Yêu thích": "LOVE",
    "Thương thương": "CARE",
    "Haha": "HAHA",
    "Wow": "WOW",
    "Buồn": "SAD",
    "Phẫn nộ": "ANGRY",
}

REACTION_LABELS = {
    "LIKE": "Like",
    "LOVE": "Yêu thích",
    "CARE": "Thương thương",
    "SUPPORT": "Thương thương",
    "HAHA": "Haha",
    "WOW": "Wow",
    "SAD": "Buồn",
    "ANGRY": "Phẫn nộ",
}


class ReactionScanScreen(ctk.CTkFrame):
    """Giao diện quét người thả reaction/like của một bài viết."""

    def __init__(self, parent, controller):
        super().__init__(parent)
        self.parent = parent
        self.controller = controller
        self.stop_event = threading.Event()
        self.current_bot = None
        self.reactions = []

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
            label_text=" Cấu hình quét reaction ",
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
            placeholder_text="https://www.facebook.com/reel/... hoặc 164...",
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

        ctk.CTkLabel(
            options_box.body, text="Loại cảm xúc:"
        ).grid(row=0, column=0, sticky="w", pady=3)
        self.opt_reaction = ctk.CTkOptionMenu(
            options_box.body,
            values=list(REACTION_OPTIONS.keys()),
            width=150,
        )
        self.opt_reaction.set("Tất cả")
        self.opt_reaction.grid(
            row=0, column=1, sticky="w", padx=(8, 0), pady=3
        )

        ctk.CTkLabel(
            options_box.body, text="Số người tối đa:"
        ).grid(row=1, column=0, sticky="w", pady=3)
        self.max_reactions_var = tk.IntVar(value=0)
        ttk.Spinbox(
            options_box.body,
            from_=0,
            to=1000000,
            increment=50,
            textvariable=self.max_reactions_var,
            width=10,
        ).grid(row=1, column=1, sticky="w", padx=(8, 0), pady=3)

        ctk.CTkLabel(
            options_box.body, text="Nghỉ giữa các trang (giây):"
        ).grid(row=2, column=0, sticky="w", pady=3)
        self.page_delay_var = tk.DoubleVar(value=1.8)
        ttk.Spinbox(
            options_box.body,
            from_=0,
            to=30,
            increment=0.5,
            textvariable=self.page_delay_var,
            width=10,
        ).grid(row=2, column=1, sticky="w", padx=(8, 0), pady=3)

        ctk.CTkLabel(
            options_box.body,
            text=(
                "0 = không giới hạn. Facebook thường trả tối đa 10 người "
                "mỗi trang; tool sẽ tự phân trang và nghỉ giữa các trang "
                "để tránh bắn request quá nhanh."
            ),
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
            text="Bắt đầu quét reaction",
            command=self.start_reaction_scan,
        )
        self.btn_start.pack(fill="x")
        self.btn_stop = DangerButton(
            footer_frame,
            text="Dừng",
            command=self.stop_reaction_scan,
            state="disabled",
        )
        self.btn_stop.pack(fill="x", pady=(6, 0))

        self.lbl_status = ctk.CTkLabel(
            footer_frame,
            text="Trạng thái: Sẵn sàng quét reaction.",
            text_color=INFO_COLOR,
            wraplength=310,
            justify="left",
            anchor="w",
        )
        self.lbl_status.pack(anchor="w", pady=(10, 0))

        right_frame = TitledFrame(
            self.parent, title=" Kết quả reaction "
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
                "reaction",
                "user",
                "user_id",
                "friends",
                "status",
                "link",
            ),
            show="headings",
        )
        self.tree_results.heading("reaction", text="Cảm xúc")
        self.tree_results.heading("user", text="Người dùng")
        self.tree_results.heading("user_id", text="User ID")
        self.tree_results.heading("friends", text="Bạn chung")
        self.tree_results.heading("status", text="Trạng thái")
        self.tree_results.heading("link", text="Profile")
        self.tree_results.column("reaction", width=100, anchor="center")
        self.tree_results.column("user", width=190, anchor="w")
        self.tree_results.column("user_id", width=150, anchor="w")
        self.tree_results.column("friends", width=80, anchor="center")
        self.tree_results.column("status", width=120, anchor="w")
        self.tree_results.column("link", width=280, anchor="w")
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
                "Vui lòng nhập URL hoặc ID bài viết cần quét reaction.",
            )
            return None

        try:
            max_reactions = int(self.max_reactions_var.get())
            page_delay = float(self.page_delay_var.get())
        except (tk.TclError, ValueError):
            messagebox.showwarning(
                "Dữ liệu không hợp lệ",
                "Số người tối đa và thời gian nghỉ phải là số.",
            )
            return None

        if max_reactions < 0 or page_delay < 0:
            messagebox.showwarning(
                "Dữ liệu không hợp lệ",
                "Số người tối đa và thời gian nghỉ không được âm.",
            )
            return None

        reaction_type = REACTION_OPTIONS.get(self.opt_reaction.get())

        return {
            "target": target,
            "max_reactions": max_reactions or None,
            "reaction_type": reaction_type,
            "page_delay_seconds": page_delay,
        }

    def start_reaction_scan(self):
        config = self._get_configuration()
        if not config:
            return

        print(
            "[ReactionScan] Bắt đầu: "
            f"target={config['target']}, "
            f"reaction={config['reaction_type'] or 'ALL'}, "
            f"max_reactions={config['max_reactions']}, "
            f"page_delay={config['page_delay_seconds']}s"
        )
        self.stop_event.clear()
        self.reactions = []
        self.tree_results.delete(*self.tree_results.get_children())
        self.btn_start.configure(state="disabled", text="Đang mở Facebook...")
        self.btn_stop.configure(state="normal")
        self.lbl_status.configure(
            text="Trạng thái: Đang khởi tạo browser để quét reaction...",
            text_color=WARNING_COLOR,
        )
        threading.Thread(
            target=self._run_reaction_scan,
            args=(self.controller.get_uid(), config),
            daemon=True,
        ).start()

    def stop_reaction_scan(self):
        self.stop_event.set()
        self.btn_stop.configure(state="disabled")
        self.lbl_status.configure(
            text="Trạng thái: Đang dừng và đóng browser...",
            text_color=ERROR_COLOR,
        )

    def _run_reaction_scan(self, user_id, config):
        worker = None
        try:
            print(f"[ReactionScan] Mở browser cho UID {user_id}...")
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
                print(
                    f"[ReactionScan] Không mở được browser: {error_message}"
                )
                self.after(
                    0,
                    lambda msg=error_message: messagebox.showerror(
                        "Lỗi", msg
                    ),
                )
                return

            print("[ReactionScan] Browser đã mở, bắt đầu quét reaction.")
            self.after(
                0,
                lambda: self.lbl_status.configure(
                    text=(
                        "Trạng thái: Facebook đã mở. Đang đọc ID bài viết "
                        "và quét reaction..."
                    ),
                    text_color=SUCCESS_COLOR,
                ),
            )
            result = worker.scan_post_reactions_from_url(
                config["target"],
                max_reactions=config["max_reactions"],
                reaction_type=config["reaction_type"],
                page_delay_seconds=config["page_delay_seconds"],
                save=True,
                export=True,
            )
            reactions = result.get("reactions") or []
            self.reactions = reactions
            print(
                f"[ReactionScan] Đã nhận {len(reactions)} người từ backend. "
                "Đang cập nhật bảng..."
            )
            self.after(
                0, lambda items=reactions: self._render_results(items)
            )

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
                    f"Trạng thái: Đã dừng. Đã lấy {len(reactions)} người."
                    f"{output_text}"
                )
                color = ERROR_COLOR
            else:
                message = (
                    f"Trạng thái: Đã lấy {len(reactions)} người thả reaction."
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
            print(f"[ReactionScan] Lỗi: {message}")
            self.after(
                0,
                lambda err=message: messagebox.showerror(
                    "Lỗi quét reaction", err
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
            print("[ReactionScan] Đã đóng browser và kết thúc tác vụ.")
            self.current_bot = None
            self.after(
                0,
                lambda: self.btn_start.configure(
                    state="normal", text="Bắt đầu quét reaction"
                ),
            )
            self.after(0, lambda: self.btn_stop.configure(state="disabled"))

    def _render_results(self, reactions):
        self.tree_results.delete(*self.tree_results.get_children())
        for index, reaction in enumerate(reactions):
            reaction_type = str(reaction.get("reaction_type") or "")
            self.tree_results.insert(
                "",
                "end",
                iid=f"reaction-{index}",
                values=(
                    REACTION_LABELS.get(reaction_type, reaction_type),
                    reaction.get("user_name") or "",
                    reaction.get("user_id") or "",
                    reaction.get("mutual_friends_count")
                    if reaction.get("mutual_friends_count") is not None
                    else "",
                    reaction.get("friendship_status") or "",
                    reaction.get("profile_url") or "",
                ),
            )

    def _open_selected_link(self, _event=None):
        selection = self.tree_results.selection()
        if not selection:
            return
        values = self.tree_results.item(selection[0], "values")
        if not values or len(values) < 6 or not values[5]:
            return
        try:
            import webbrowser

            webbrowser.open(values[5])
        except Exception as error:
            messagebox.showerror("Lỗi", f"Không mở được link: {error}")
