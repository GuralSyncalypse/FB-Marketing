import os
import shutil
import threading

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox

import bot
from services.ui_theme import (
    BG_PANEL,
    SELECT_COLOR,
    TEXT,
    TEXT_MUTED,
    TitledFrame,
    apply_theme,
    status_color,
)


class PostScreen(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.parent = parent
        self.controller = controller
        self.image_paths = []
        self.worker = None
        self.current_bot = None

        apply_theme()
        self._build_ui()

    def _build_ui(self):
        left_frame = TitledFrame(self.parent, title=" Nội dung bài đăng ")
        left_frame.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(left_frame.body, text="Nội dung bài viết:").pack(
            anchor="w", pady=(0, 4)
        )
        self.txt_content = ctk.CTkTextbox(left_frame.body, height=220, wrap="word")
        self.txt_content.pack(fill="both", expand=True, pady=(0, 10))
        self.txt_content.insert(
            "1.0",
            "Nhập nội dung bài viết tại đây..."
        )

        control_frame = TitledFrame(left_frame.body, title=" Điều khiển ")
        control_frame.pack(fill="x", pady=(0, 10))

        btn_row = ctk.CTkFrame(control_frame.body, fg_color="transparent")
        btn_row.grid(row=0, column=0, sticky="ew")
        btn_row.columnconfigure(0, weight=1)
        btn_row.columnconfigure(1, weight=1)

        self.btn_select_images = ctk.CTkButton(
            btn_row,
            text="Chọn ảnh/video",
            command=self.select_images
        )
        self.btn_select_images.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.btn_start = ctk.CTkButton(
            btn_row,
            text="Đăng bài",
            command=self.start_posting
        )
        self.btn_start.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.lbl_status = ctk.CTkLabel(
            left_frame.body,
            text="Trạng thái: Sẵn sàng",
            text_color=status_color("blue"),
            anchor="w"
        )
        self.lbl_status.pack(anchor="w")

        right_frame = TitledFrame(self.parent, title=" Tệp đính kèm ")
        right_frame.pack(side="right", fill="both", padx=10, pady=10)

        ctk.CTkLabel(
            right_frame.body,
            text="Danh sách file sẽ được gửi lên bài viết:",
            font=ctk.CTkFont(size=11, slant="italic"),
            text_color=TEXT_MUTED,
            anchor="w"
        ).pack(anchor="w", pady=(0, 6))

        self.listbox_files = tk.Listbox(
            right_frame.body,
            width=42,
            height=18,
            bg=BG_PANEL,
            fg=TEXT,
            selectbackground=SELECT_COLOR,
            selectforeground="#ffffff",
            highlightthickness=0,
            borderwidth=0,
            relief="flat",
        )
        self.listbox_files.pack(fill="both", expand=True, pady=(0, 8))

        file_btn_row = ctk.CTkFrame(right_frame.body, fg_color="transparent")
        file_btn_row.pack(fill="x")

        ctk.CTkButton(
            file_btn_row,
            text="Xóa file chọn",
            command=self.remove_selected_file
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))

        ctk.CTkButton(
            file_btn_row,
            text="Xóa tất cả",
            command=self.clear_files
        ).pack(side="left", fill="x", expand=True, padx=(4, 0))

    def select_images(self):
        file_paths = filedialog.askopenfilenames(
            title="Chọn ảnh/video để đăng",
            filetypes=[
                ("Media files", "*.png *.jpg *.jpeg *.gif *.bmp *.webp *.mp4 *.mov *.avi *.mkv *.flv *.wmv"),
                ("All files", "*.*"),
            ],
        )

        if not file_paths:
            return

        for path in file_paths:
            if path not in self.image_paths:
                self.image_paths.append(path)

        self.refresh_file_list()

    def refresh_file_list(self):
        self.listbox_files.delete(0, tk.END)
        for path in self.image_paths:
            self.listbox_files.insert(tk.END, os.path.basename(path))

    def remove_selected_file(self):
        selection = list(self.listbox_files.curselection())
        if not selection:
            return

        for index in reversed(selection):
            if 0 <= index < len(self.image_paths):
                del self.image_paths[index]

        self.refresh_file_list()

    def clear_files(self):
        self.image_paths.clear()
        self.refresh_file_list()

    def start_posting(self):
        uid = self.controller.ent_uid_shared.get().strip()
        content = self.txt_content.get("1.0", tk.END).strip()
        selected_groups = [
            g for g in getattr(self.controller, "groups_data", [])
            if g.get("checked") and g.get("id")
        ]

        if not uid or uid == self.controller.empty_uid:
            messagebox.showerror("Lỗi", "Vui lòng nhập hoặc chờ UID từ Extension trước khi đăng bài.")
            return

        if not content:
            messagebox.showerror("Lỗi", "Vui lòng nhập nội dung bài viết.")
            return

        if not selected_groups:
            messagebox.showerror("Lỗi", "Vui lòng chọn ít nhất 1 group trong danh sách Groups trước khi đăng bài.")
            return

        self.btn_start.configure(state="disabled", text="Đang đăng...")
        self.btn_select_images.configure(state="disabled")
        self.lbl_status.configure(text="Trạng thái: Đang khởi chạy...", text_color=status_color("orange"))

        thread = threading.Thread(
            target=self.run_posting,
            args=(uid, content, list(self.image_paths), selected_groups),
            daemon=True,
        )
        thread.start()

    def run_posting(self, uid, content, image_paths, selected_groups):
        driver = None
        try:
            self.after(0, lambda: self.lbl_status.configure(
                text="Trạng thái: Đang đăng nhập...",
                text_color=status_color("orange")
            ))

            driver = bot.FacebookBot(self.controller.is_demo_mode)
            self.current_bot = driver
            driver.user_agent = self.controller.user_agent

            success = driver.start_browser(uid, user_agent=self.controller.get_user_agent())
            if not success:
                error_message = driver.get_start_error_message()
                self.after(0, lambda msg=error_message: messagebox.showerror("Lỗi", msg))
                return

            total_groups = len(selected_groups)
            success_count = 0
            fail_count = 0

            media_dir = os.path.join(bot.APP_DIR, "bot_media_tmp")
            os.makedirs(media_dir, exist_ok=True)

            prepared_paths = []
            for src_path in image_paths:
                if not src_path or not os.path.exists(src_path):
                    continue
                dst_path = os.path.join(media_dir, os.path.basename(src_path))
                shutil.copy2(src_path, dst_path)
                prepared_paths.append(dst_path)

            for index, group in enumerate(selected_groups, start=1):
                group_id = group.get("id", "").strip()
                if not group_id:
                    fail_count += 1
                    continue
                group_name = group.get("name", "").strip() or group_id or f"Group {index}"

                self.after(0, lambda i=index, t=total_groups, name=group_name: self.lbl_status.configure(
                    text=f"Trạng thái: Đang đăng {i}/{t} - {name}",
                    text_color=status_color("green")
                ))

                try:
                    driver.create_post(group_id, content, prepared_paths)
                    success_count += 1
                except Exception as group_error:
                    fail_count += 1
                    print(f"[PostScreen] Failed posting to {group_name}: {group_error}")

            summary = f"Hoàn thành. Thành công: {success_count}, Thất bại: {fail_count}"
            self.after(0, lambda: messagebox.showinfo("Kết quả", summary))
            self.after(0, lambda: self.lbl_status.configure(
                text="Trạng thái: Hoàn thành",
                text_color=status_color("navy")
            ))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Lỗi", f"Không thể đăng bài: {e}"))
            self.after(0, lambda: self.lbl_status.configure(
                text="Trạng thái: Có lỗi xảy ra",
                text_color=status_color("red")
            ))
        finally:
            if driver:
                try:
                    driver.close()
                except Exception:
                    pass
            self.current_bot = None
            self.after(0, lambda: self.btn_start.configure(state="normal", text="Đăng bài"))
            self.after(0, lambda: self.btn_select_images.configure(state="normal"))
