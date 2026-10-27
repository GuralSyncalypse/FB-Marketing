"""Cấu hình CustomTkinter dùng chung cho quá trình chuyển đổi tkinter -> CustomTkinter.

Module này giữ một nguồn màu sắc duy nhất và áp theme cho các widget ttk còn
được giữ lại trong chế độ hybrid (Treeview, Spinbox, Listbox...).
"""

import tkinter.ttk as ttk

import customtkinter as ctk

# ================= BẢNG MÀU DÙNG CHUNG =================
BG_BASE = "#1a1a1a"
BG_PANEL = "#242424"
BG_ELEVATED = "#2f2f2f"
TEXT = "#e6e6e6"
TEXT_MUTED = "#9aa0a6"

ACCENT = "#1f6aa5"
ACCENT_HOVER = "#144870"
SELECT_COLOR = "#1f6aa5"

INFO_COLOR = "#4da3ff"
SUCCESS_COLOR = "#5ddc7f"
WARNING_COLOR = "#ffb454"
ERROR_COLOR = "#ff6b6b"

# Nền nút "nguy hiểm" (Dừng/Đang quét...). Đỏ đậm hơn ERROR_COLOR để chữ trắng
# đạt tương phản >= 4.5 (ERROR_COLOR chỉ hợp làm MÀU CHỮ trên nền tối).
DANGER_BG = "#c0392b"
DANGER_BG_HOVER = "#a93226"
DANGER_BG_DISABLED = "#6b2b26"
TEXT_ON_DANGER = "#ffffff"

# Chữ trên nút khi bị vô hiệu hóa. Mặc định của CTk là gray60 (#999999) -> gần như
# tàng hình trên nền nút sáng (tương phản ~1.0). Dùng xám sáng để vẫn đọc được.
BUTTON_TEXT_DISABLED = "#d8d8d8"

APPEARANCE_MODE = "dark"
COLOR_THEME = "blue"

_STATUS_MAP = {
    "blue": INFO_COLOR,
    "info": INFO_COLOR,
    "navy": INFO_COLOR,
    "orange": WARNING_COLOR,
    "warning": WARNING_COLOR,
    "red": ERROR_COLOR,
    "error": ERROR_COLOR,
    "green": SUCCESS_COLOR,
    "success": SUCCESS_COLOR,
    "gray": TEXT_MUTED,
    "grey": TEXT_MUTED,
}

_ttk_styled = False


def status_color(color):
    """Chuẩn hóa tên màu trạng thái cũ ('blue', 'red'...) sang màu theme."""
    if not color:
        return TEXT
    return _STATUS_MAP.get(str(color).lower(), color)


class TitledFrame(ctk.CTkFrame):
    """CTkFrame có tiêu đề, thay thế cho ttk.LabelFrame.

    Nội dung của khung nên được thêm vào ``self.body`` để có padding hợp lý.
    """

    def __init__(self, master, title="", **kwargs):
        kwargs.setdefault("fg_color", BG_PANEL)
        kwargs.setdefault("border_width", 0)
        kwargs.setdefault("corner_radius", 10)
        super().__init__(master, **kwargs)

        self.header = ctk.CTkLabel(
            self,
            text=title,
            anchor="w",
            text_color=TEXT,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.header.pack(anchor="w", padx=14, pady=(10, 0))

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=14, pady=(6, 12))

    def set_title(self, title):
        self.header.configure(text=title)


class DangerButton(ctk.CTkButton):
    """Nút hành động nguy hiểm (Dừng / Đang quét...).

    - Bật: nền đỏ đậm + chữ trắng (tương phản ~5.4).
    - Tắt: nền đỏ mờ hẳn đi nhưng chữ vẫn đọc được (tương phản > 7).

    Chỉ cần gọi ``configure(state=...)`` như bình thường, việc đổi màu nền
    sẽ được xử lý tự động.
    """

    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", DANGER_BG)
        kwargs.setdefault("hover_color", DANGER_BG_HOVER)
        kwargs.setdefault("text_color", TEXT_ON_DANGER)
        kwargs.setdefault("text_color_disabled", BUTTON_TEXT_DISABLED)
        self._danger_state = kwargs.get("state", "normal")
        self._danger_ready = False
        super().__init__(master, **kwargs)
        self._danger_ready = True
        self._sync_danger_bg()

    def configure(self, require_redraw=False, **kwargs):
        if "state" in kwargs:
            self._danger_state = kwargs["state"]
        super().configure(require_redraw=require_redraw, **kwargs)
        if "state" in kwargs:
            self._sync_danger_bg()

    config = configure

    def _sync_danger_bg(self):
        if not getattr(self, "_danger_ready", False):
            return
        try:
            disabled = self._danger_state == "disabled"
            super().configure(
                fg_color=DANGER_BG_DISABLED if disabled else DANGER_BG
            )
        except Exception:
            pass


class ScanActionBar(ctk.CTkFrame):
    """Cụm nút Bắt đầu/Dừng dùng chung cho các màn hình quét.

    Hai nút luôn chia đôi chiều ngang, cùng nhãn và cùng trạng thái để người
    dùng không phải học lại giao diện khi chuyển tab.
    """

    START_TEXT = "▶ Bắt đầu quét"
    RUNNING_TEXT = "⏳ Đang quét..."
    STOP_TEXT = "⏹ Dừng quét"
    STOPPING_TEXT = "⏳ Đang dừng..."

    def __init__(
        self,
        master,
        *,
        start_command,
        stop_command,
        start_text=None,
        stop_text=None,
        **kwargs,
    ):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(master, **kwargs)

        self._start_text = start_text or self.START_TEXT
        self._stop_text = stop_text or self.STOP_TEXT

        self.columnconfigure(0, weight=1, uniform="scan_action")
        self.columnconfigure(1, weight=1, uniform="scan_action")

        self.btn_start = ctk.CTkButton(
            self, text=self._start_text, command=start_command
        )
        self.btn_start.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.btn_stop = DangerButton(
            self,
            text=self._stop_text,
            command=stop_command,
            state="disabled",
        )
        self.btn_stop.grid(row=0, column=1, sticky="ew", padx=(4, 0))

    def mark_running(self, text=None):
        """Khóa nút Bắt đầu và mở nút Dừng khi tiến trình bắt đầu."""
        self.btn_start.configure(
            state="disabled", text=text or self.RUNNING_TEXT
        )
        self.btn_stop.configure(state="normal", text=self._stop_text)

    def mark_stopping(self):
        """Vô hiệu hóa nút Dừng trong lúc dọn dẹp."""
        self.btn_stop.configure(state="disabled", text=self.STOPPING_TEXT)

    def mark_idle(self):
        """Trả hai nút về trạng thái sẵn sàng."""
        self.btn_start.configure(state="normal", text=self._start_text)
        self.btn_stop.configure(state="disabled", text=self._stop_text)


def apply_theme():
    """Áp appearance mode của CTk và style các widget ttk còn giữ lại.

    Hàm này an toàn để gọi nhiều lần. Cần một Tk root đã tồn tại để style ttk.
    """
    ctk.set_appearance_mode(APPEARANCE_MODE)
    ctk.set_default_color_theme(COLOR_THEME)

    # Tinh chỉnh màu chữ của nút cho đủ tương phản. Phải đặt SAU
    # set_default_color_theme() vì hàm đó nạp lại theme mặc định.
    ctk.ThemeManager.theme["CTkButton"]["text_color"] = ["#ffffff", "#ffffff"]
    ctk.ThemeManager.theme["CTkButton"]["text_color_disabled"] = [
        BUTTON_TEXT_DISABLED,
        BUTTON_TEXT_DISABLED,
    ]

    global _ttk_styled
    if _ttk_styled:
        return

    try:
        style = ttk.Style()
    except Exception:
        # Chưa có Tk root; lần gọi sau (sau khi root tồn tại) sẽ style tiếp.
        return

    # 'clam' cho phép ghi đè màu trên Windows (theme 'vista' bỏ qua màu tùy chỉnh).
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure(
        "Treeview",
        background=BG_PANEL,
        fieldbackground=BG_PANEL,
        foreground=TEXT,
        rowheight=28,
        borderwidth=0,
        relief="flat",
    )
    style.map(
        "Treeview",
        background=[("selected", SELECT_COLOR)],
        foreground=[("selected", "#ffffff")],
    )
    style.configure(
        "Treeview.Heading",
        background=BG_ELEVATED,
        foreground=TEXT,
        borderwidth=0,
        relief="flat",
        padding=(6, 4),
    )
    style.map("Treeview.Heading", background=[("active", SELECT_COLOR)])

    style.configure("TScrollbar", background=BG_ELEVATED, troughcolor=BG_BASE)
    style.configure("TSpinbox", fieldbackground=BG_ELEVATED, background=BG_ELEVATED,
                    foreground=TEXT, arrowcolor=TEXT, borderwidth=0)
    style.configure("TCombobox", fieldbackground=BG_ELEVATED, foreground=TEXT)
    style.configure("TListbox", background=BG_PANEL, foreground=TEXT,
                    borderwidth=0, highlightthickness=0)

    _ttk_styled = True
