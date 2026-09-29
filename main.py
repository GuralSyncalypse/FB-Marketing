import json
import os
import threading
from queue import Empty, Queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import urllib.parse

import bot
from services.local_server import start_local_server
from views.dev_screen import DevelopScreen
from views.post_screen import PostScreen
from views.post_scan_screen import PostScanScreen
from views.sms_screen import SmsScreen
from views.uid_scan_screen import UidScanScreen


# ================= CLASS GIAO DIỆN CHÍNH (APP) =================
class App(tk.Tk):

  def __init__(self):
    super().__init__()
    self.title("H2 Tool - Công cụ Marketing Facebook")
    self.geometry("950x700")

    self.protocol("WM_DELETE_WINDOW", self.__on_close)

    # --- Biến cấu hình chung ---
    self.is_demo_mode = False
    self.empty_uid = "Chờ tín hiệu từ Extension..."


    # --- Khởi tạo dữ liệu ---
    self.has_uid = False
    self._server_events = Queue()
    self.selected_files_s1 = []
    self.selected_files_s2 = []

    # Biến lưu trữ dữ liệu từ server
    self.uid = ""
    self.cookies = []

    # Biến dùng chung
    self.groups_data = []

    # --- Xây dựng các thành phần Giao diện ---
    self.__build_menu()  # 🌟 Thêm thanh Taskbar / Menu Bar ở trên cùng
    self.__build_shared_panel()  # 1. Khu vực thông tin phía trên (Cố định chiều cao)
    self.__build_navigation_tabs()  # 2. Khu vực Notebook (Tab) chính

    # --- Khởi chạy dịch vụ ngầm ---
    self.after(100, self._process_server_events)
    start_local_server(
        port=8000,
        on_uid_received_callback=self.on_server_received
    )


  # Hàm dùng chung
  def get_uid(self) -> str:
    """Lấy UID hiện tại từ Entry"""
    return self.ent_uid_shared.get().strip()

  def get_user_agent(self) -> str:
    """Lấy User Agent hiện tại từ Entry"""
    return self.ent_ua.get().strip()

  # ---

  @staticmethod
  def _normalize_saved_groups_data(raw_data: object) -> dict:
    """Chuẩn hóa dữ liệu groups_saved.json về dạng {uid: {"groups": [...]}}."""
    if isinstance(raw_data, dict):
      entries = [raw_data]
    elif isinstance(raw_data, list):
      entries = raw_data
    else:
      return {}

    normalized_data = {}
    for entry in entries:
      if not isinstance(entry, dict):
        continue

      for uid, payload in entry.items():
        if not isinstance(payload, dict):
          continue

        groups = payload.get("groups", [])
        normalized_data[str(uid)] = {
          "groups": groups if isinstance(groups, list) else []
        }

    return normalized_data

  def load_data(self) -> list:
    """Đọc dữ liệu của User chỉ trong 1 dòng"""
    try:
        self.screens["Quét UID"].refresh_groups_preview()
        with open("groups_saved.json", "r", encoding="utf-8") as f:
            raw_data = json.load(f)
            data = self._normalize_saved_groups_data(raw_data)
            # Lấy trực tiếp groups của uid, nếu không có trả về []
            return data.get(str(self.uid), {}).get("groups", [])
    except Exception:
        return []

  def save_data(self) -> bool:
      """Lưu dữ liệu của User không cần vòng lặp"""
      if not self.uid:
          return False

      file_path = "groups_saved.json"
      data = {}

      # 1. Đọc file cũ
      if os.path.exists(file_path):
           try:
               with open(file_path, "r", encoding="utf-8") as f:
                   data = self._normalize_saved_groups_data(json.load(f))
           except Exception:
               data = {}

      data = self._normalize_saved_groups_data(data)

       # 2. Cập nhật hoặc thêm mới User trực tiếp
      data[str(self.uid)] = {"groups": self.groups_data}

      # 3. Ghi lại file
      with open(file_path, "w", encoding="utf-8") as f:
          json.dump(data, f, ensure_ascii=False, indent=4)
      return True
  
  def __on_close(self):
    print("Đang lưu trạng thái ứng dụng...")

    # Pipeline 1: Lưu dữ liệu nhóm hiện tại của User
    try:
      self.save_data()
    except Exception as e:
      print(f"Không thể lưu trạng thái ứng dụng: {e}")
    finally:
      self.destroy()  # Giải phóng giao diện và thoát hẳn

  # ================= THÊM THANH MENU BAR (TASKBAR) =================
  def __build_menu(self):
    """Xây dựng thanh Menu Bar trên cùng của ứng dụng"""
    menubar = tk.Menu(self)

    # Tạo Menu thả xuống cho "Cài đặt"
    settings_menu = tk.Menu(menubar, tearoff=0)
    settings_menu.add_command(
        label="Cấu hình hệ thống", command=self.open_settings_window
    )
    settings_menu.add_separator()
    settings_menu.add_command(label="Thoát", command=self.quit)

    # Đưa "Cài đặt" lên thanh Menu chính
    menubar.add_cascade(label="Cài đặt", menu=settings_menu)

    # Gán menubar cho cửa sổ chính
    self.config(menu=menubar)

  def open_settings_window(self):
        """Mở cửa sổ Popup Cài đặt hệ thống"""
        settings_win = tk.Toplevel(self)
        settings_win.title("Cài đặt hệ thống")
        settings_win.geometry("380x200")
        settings_win.resizable(False, False)
        settings_win.grab_set()  # Khóa tương tác với màn hình chính khi popup đang mở

        # Tiêu đề Popup
        ttk.Label(
            settings_win, text="CẤU HÌNH CÀI ĐẶT", font=("Arial", 11, "bold")
        ).pack(pady=(20, 10))

        # Khung chứa nội dung cài đặt
        form_frame = ttk.Frame(settings_win, padding=10)
        form_frame.pack(fill="both", expand=True)

        # Biến quản lý trạng thái Checkbox
        chk_demo_var = tk.BooleanVar(value=getattr(self, "is_demo_mode", False))

        # --- TÙY CHỌN DEMO MODE (CHECKBOX) ---
        chk_demo = ttk.Checkbutton(
            form_frame,
            text=" Demo Mode",
            variable=chk_demo_var,
        )
        chk_demo.pack(anchor="center", pady=15)

        # Hàm xử lý khi bấm nút Lưu
        def save_settings():
            self.is_demo_mode = chk_demo_var.get()
            
            # Lưu trạng thái vào file config.json (nếu có)
            if hasattr(self, "save_config_to_file"):
                self.save_config_to_file()
                
            status_text = "BẬT" if self.is_demo_mode else "TẮT"
            messagebox.showinfo("Thông báo", f"Đã lưu cài đặt thành công!\nTrạng thái Demo Mode: {status_text}")
            settings_win.destroy()

        # Nút Lưu cấu hình
        btn_save = ttk.Button(settings_win, text="Lưu cấu hình", command=save_settings)
        btn_save.pack(pady=(0, 20))

  # =========================================================================

  def __build_shared_panel(self):
    """Xây dựng khu vực cấu hình thông tin tài khoản dùng chung phía trên (Đã thu gọn)"""
    top_shared_frame = ttk.LabelFrame(
        self, text=" Thông tin tài khoản hiện tại ", padding=10
    )
    top_shared_frame.pack(side="top", fill="x", padx=10, pady=5)

    # Định hình layout sử dụng grid để kiểm soát khoảng cách tốt hơn thay vì pack hỗn hợp
    top_shared_frame.columnconfigure(1, weight=1)
    top_shared_frame.columnconfigure(
        3, weight=2
    )  # Cho ô User Agent rộng hơn vì UA thường rất dài

    # HÀNG 1: UID & USER AGENT
    # --- Cụm UID ---
    ttk.Label(top_shared_frame, text="UID:", width=8).grid(
        row=0, column=0, sticky="w", pady=5
    )
    self.ent_uid_shared = ttk.Entry(
        top_shared_frame, font=("Arial", 10, "bold"), width=25
    )
    self.ent_uid_shared.grid(row=0, column=1, sticky="w", pady=5, padx=(0, 20))
    self.ent_uid_shared.insert(0, self.empty_uid)
    self.ent_uid_shared.config(state="readonly")

    # --- Cụm User Agent ---
    ttk.Label(top_shared_frame, text="User Agent:").grid(
        row=0, column=2, sticky="w", pady=5
    )
    self.ent_ua = ttk.Entry(top_shared_frame)
    self.ent_ua.grid(row=0, column=3, sticky="ew", pady=5)

    # HÀNG 2: QUẢN LÝ GROUPS (Rút gọn thành hiển thị số lượng)
    group_status_frame = ttk.Frame(top_shared_frame)
    group_status_frame.grid(
        row=1, column=0, columnspan=4, sticky="ew", pady=(8, 0)
    )

    # Biến lưu trữ số lượng group để cập nhật động lên giao diện
    self.lbl_group_count_var = tk.StringVar(value="Đã quét: 0 groups")
    lbl_count = ttk.Label(
        group_status_frame,
        textvariable=self.lbl_group_count_var,
        font=("Arial", 10, "italic"),
    )
    lbl_count.pack(side="left", padx=(0, 15))

    btn_show_groups = ttk.Button(
        group_status_frame,
        text="Danh sách nhóm",
        command=self.open_groups_window,
    )
    btn_show_groups.pack(side="left")

  def get_selected_groups(self):
    """Trả về danh sách các object group đang được tích chọn"""
    # Sử dụng getattr để lấy dữ liệu an toàn, mặc định là [] nếu chưa có attribute
    groups = getattr(self, "groups_data", []) or []
    return [g for g in groups if g.get("checked", False)]

  def update_group_selection(self):
    """Cập nhật UI số lượng nhóm đã chọn"""
    groups = getattr(self, "groups_data", []) or []
    selected_count = len(self.get_selected_groups())  # Tái sử dụng hàm trên
    total_count = len(groups)
    
    self.lbl_group_count_var.set(f"Đã chọn: {selected_count}/{total_count} nhóm")

  def open_groups_window(self):
    """Mở cửa sổ Popup quản lý và tích chọn danh sách nhóm"""
    # ================= KHỞI TẠO CỬA SỔ POPUP =================
    groups_win = tk.Toplevel(self)
    groups_win.title("Danh sách nhóm")
    groups_win.geometry("580x520")
    groups_win.grab_set()
    groups_win.resizable(False, False)

    # 1. TOOLBAR TẠO THAO TÁC CHÍNH (Top Bar)
    toolbar = ttk.Frame(groups_win, padding=(10, 10, 10, 5))
    toolbar.pack(fill="x")

    # 2. THANH TÌM KIẾM (Search Bar)
    search_frame = ttk.Frame(groups_win, padding=(10, 5, 10, 5))
    search_frame.pack(fill="x")

    # 3. NỘI DUNG BẢNG (Treeview Main)
    main_content = ttk.Frame(groups_win, padding=(10, 5, 10, 10))
    main_content.pack(fill="both", expand=True)

    # ================= XÂY DỰNG CONTROL =================
    # --- Toolbar controls ---
    btn_scan = ttk.Button(toolbar, text="Quét", command=lambda: handle_scan())
    btn_scan.pack(side="left", padx=(0, 10))

    rad_var = tk.IntVar(value=-1)

    rad_all = ttk.Radiobutton(
        toolbar,
        text="Chọn tất cả",
        variable=rad_var,
        value=1,
        command=lambda: on_radio_changed(),
    )
    rad_all.pack(side="left", padx=5)

    rad_none = ttk.Radiobutton(
        toolbar,
        text="Bỏ chọn tất cả",
        variable=rad_var,
        value=0,
        command=lambda: on_radio_changed(),
    )
    rad_none.pack(side="left", padx=5)

    btn_save = ttk.Button(
        toolbar, text="Xác nhận", command=lambda: save_and_close()
    )
    btn_save.pack(side="right")

    # --- Search Bar controls ---
    ttk.Label(search_frame, text="🔍 Tìm kiếm:").pack(
        side="left", padx=(0, 5)
    )
    search_var = tk.StringVar()
    ent_search = ttk.Entry(search_frame, textvariable=search_var)
    ent_search.pack(side="left", fill="x", expand=True, padx=(0, 5))

    btn_clear_search = ttk.Button(
        search_frame,
        text="✕",
        width=3,
        command=lambda: search_var.set(""),
    )
    btn_clear_search.pack(side="right")

    # --- Treeview controls ---
    tree_groups = ttk.Treeview(
      main_content,
      columns=("Select", "Name"),
      show="headings",
      selectmode="browse",  # Chuyển thành "browse" để bật Highlight dòng khi click
    )

    scrollbar = ttk.Scrollbar(
        main_content, orient="vertical", command=tree_groups.yview
    )
    tree_groups.configure(yscrollcommand=scrollbar.set)

    tree_groups.heading("Select", text="Chọn")
    tree_groups.heading("Name", text="Tên nhóm")

    tree_groups.column("Select", width=60, anchor="center")
    tree_groups.column("Name", width=440, anchor="w")

    tree_groups.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    # ================= LOGIC VÀ XỬ LÝ SỰ KIỆN =================
    def refresh_tree(*args):
        """Làm mới dữ liệu hiển thị trên Treeview theo từ khóa tìm kiếm"""
        tree_groups.delete(*tree_groups.get_children())
        query = search_var.get().strip().lower()

        for idx, g in enumerate(self.groups_data):
            name = g.get("name", "")
            # Lọc theo từ khóa tìm kiếm
            if query and query not in name.lower():
                continue

            # Chuẩn hóa biểu tượng Checkbox gọn gàng
            status = "☑" if g.get("checked", False) else "☐"
            # Lưu chỉ số thật (idx) vào iid để không bị lệch dữ liệu khi filter
            tree_groups.insert(
                "", "end", iid=str(idx), values=(status, name)
            )

        update_radio_selection_state()

    def toggle_item(item_id):
      if item_id:
          idx = int(item_id)
          # 1. Đảo trạng thái trong dữ liệu gốc
          self.groups_data[idx]["checked"] = not self.groups_data[idx]["checked"]

          # 2. Cập nhật trực tiếp giao diện dòng này (giữ nguyên trạng thái Highlight)
          status = "☑" if self.groups_data[idx]["checked"] else "☐"
          name = self.groups_data[idx].get("name", "")
          tree_groups.item(item_id, values=(status, name))

          # 3. Kích hoạt Highlight dòng vừa click
          tree_groups.selection_set(item_id)

          # 4. Cập nhật lại nút 'Chọn tất cả / Bỏ chọn'
          update_radio_selection_state()

    def on_tree_click(event):
        """Click vào cột 'Chọn' để bật/tắt checkbox"""
        item_id = tree_groups.identify_row(event.y)
        column = tree_groups.identify_column(event.x)
        if item_id and column == "#1":
            toggle_item(item_id)

    def on_tree_double_click(event):
        """Double click vào bất kỳ dòng nào để bật/tắt checkbox"""
        item_id = tree_groups.identify_row(event.y)
        if item_id:
            toggle_item(item_id)

    def on_radio_changed():
        """Chọn/Bỏ chọn tất cả các nhóm đang được lọc hiển thị"""
        val = rad_var.get()
        query = search_var.get().strip().lower()

        for g in self.groups_data:
            # Nếu đang search, chỉ tác động lên các nhóm khớp tìm kiếm
            if not query or query in g.get("name", "").lower():
                g["checked"] = val == 1

        refresh_tree()

    def update_radio_selection_state():
        """Cập nhật trạng thái hiển thị của nút Chọn tất cả / Bỏ chọn"""
        if not self.groups_data:
            rad_var.set(-1)
            return

        all_checked = all(g.get("checked", False) for g in self.groups_data)
        all_unchecked = all(
            not g.get("checked", False) for g in self.groups_data
        )

        if all_checked:
            rad_var.set(1)
        elif all_unchecked:
            rad_var.set(0)
        else:
            rad_var.set(-1)

    def handle_scan():
        if not self.has_uid:
            messagebox.showwarning(
                "Cảnh báo", "Vui lòng kết nối Extension để nhận UID trước khi quét!"
            )
            return

        btn_scan.config(state="disabled", text="Đang quét...")

        def local_refresh():
            if not groups_win.winfo_exists():
                return
            refresh_tree()
            self.lbl_group_count_var.set(
                f"Đã quét: {len(self.groups_data)} groups"
            )
            btn_scan.config(state="normal", text="Quét")
            messagebox.showinfo(
                "Thành công",
                f"Đã cập nhật {len(self.groups_data)} nhóm thành công!",
            )

        def reset_scan_button():
            if groups_win.winfo_exists():
                btn_scan.config(state="normal", text="Quét")

        self._trigger_ui_refresh = local_refresh
        self._reset_group_scan_button = reset_scan_button
        self.scan_groups()

    def save_and_close():
        self.screens["Quét UID"].refresh_groups_preview()
        self.update_group_selection()
        groups_win.destroy()

    # Bắt sự kiện thay đổi trên ô tìm kiếm
    search_var.trace_add("write", refresh_tree)

    # Gán sự kiện tương tác chuột cho Treeview
    tree_groups.bind("<ButtonRelease-1>", on_tree_click)
    tree_groups.bind("<Double-1>", on_tree_double_click)

    # Khởi chạy ban đầu
    refresh_tree()

  def __build_navigation_tabs(self):
    """Xây dựng khu vực Notebook và nhúng các màn hình tính năng vào"""
    def on_tab_changed(event):
      # Lấy Notebook phát ra sự kiện
      notebook = event.widget

      # Lấy ID/Widget của tab đang được chọn
      selected_tab = notebook.select()

      # Lấy index của tab (0, 1, 2,...)
      current_index = notebook.index(selected_tab)

      # Lấy tiêu đề (text) của tab
      tab_title = notebook.tab(selected_tab, "text")
      # Xử lý logic tương ứng từng tab
      if current_index == 0:
          # Code khi ở Tab 1
          pass
      elif tab_title in ("Quét UID", "Quét bài"):
          self.screens[tab_title].refresh_groups_preview()


    self.notebook = ttk.Notebook(self)
    self.notebook.pack(fill="both", expand=True, padx=5, pady=5)

    tab_configs = [
        ("Share bài", DevelopScreen),
        ("Đăng bài", PostScreen),
        ("Bắn SMS", SmsScreen),
        ("Quét UID", UidScanScreen),
        ("Quét bài", PostScanScreen),
    ]

    self.tabs = []
    self.screens = {}

    for label, screen_cls in tab_configs:
      tab = ttk.Frame(self.notebook)
      self.notebook.add(tab, text=label)

      screen = screen_cls(tab, self)

      self.tabs.append(tab)
      self.screens[label] = screen

    self.notebook.bind("<<NotebookTabChanged>>", on_tab_changed)

  # ================= CÁC HÀM XỬ LÝ LOGIC =================
  def save_to_profile_folder(self, uid: str, cookies: list):
    """Lưu file cookies.json vào thư mục profiles/{uid}"""
    profile_dir = os.path.join("profiles", uid)
    os.makedirs(profile_dir, exist_ok=True)  # Tự động tạo thư mục nếu chưa có

    cookie_file_path = os.path.join(profile_dir, "cookies.json")
    with open(cookie_file_path, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=4, ensure_ascii=False)

  def _update_ui_after_scan(self):
    self.lbl_group_count_var.set(f"Đã quét: {len(self.groups_data)} groups")
    if hasattr(self, "popup_refresh_func") and self.popup_refresh_func:
      self.popup_refresh_func()

  def on_server_received(self, data: dict):
    """Nhận dữ liệu từ HTTP server mà không thao tác Tkinter ở server thread."""
    self._server_events.put(data)

  def _process_server_events(self):
    """Xử lý dữ liệu server trên main thread của Tkinter."""
    try:
      while True:
        self._apply_server_received(self._server_events.get_nowait())
    except Empty:
      pass

    if self.winfo_exists():
      self.after(100, self._process_server_events)

  def _apply_server_received(self, data: dict):
    self.uid = data.get("uid", "")
    self.cookies = data.get("cookies", [])
    self.user_agent = data.get("user_agent", "")

    self.ent_uid_shared.config(state="normal")
    self.ent_uid_shared.delete(0, tk.END)
    self.ent_uid_shared.insert(0, self.uid)
    self.ent_uid_shared.config(state="readonly")

    self.ent_ua.delete(0, tk.END)
    self.ent_ua.insert(0, self.user_agent)

    # Cập nhật lại danh sách nhóm từ file JSON nếu có
    self.groups_data = self.load_data()
    self.update_group_selection()

    if self.uid:
        self.has_uid = True
        self.save_to_profile_folder(self.uid, self.cookies)

    self.screens["Quét UID"].refresh_groups_preview()

  def scan_groups(self):
    uid = self.ent_uid_shared.get()

    selenium_thread = threading.Thread(
        target=self.run_scan_groups, args=(uid,), daemon=True
    )
    selenium_thread.start()

  def run_scan_groups(self, user) -> None:
    worker = None
    try:
        worker = bot.FacebookBot(visualize=self.is_demo_mode)

        success = worker.start_browser(
            uid=user, user_agent=self.user_agent
        )
        if not success:
          error_message = worker.get_start_error_message()
          self.after(0, lambda msg=error_message: messagebox.showerror("Lỗi", msg))
          return
        
        results = worker.scrape_joined_groups()

        # 1. Chuyển đổi dữ liệu bằng List Comprehension
        self.groups_data = [
            {
                "id": g.get("group_id", ""),
                "name": g.get("group_name", ""),
                "checked": False,
            }
            for g in (results or [])
        ]

        # 2. Tái sử dụng hàm lưu file JSON đã viết trước đó
        self.save_data()
        print("Hoàn thành cào dữ liệu ngầm và lưu JSON thành công!")

        # 3. Cập nhật lại giao diện ở main thread
        if callable(getattr(self, "_trigger_ui_refresh", None)):
            self.after(0, self._trigger_ui_refresh)

    except Exception as e:
        msg = f"Có lỗi xảy ra: {e}"
        self.after(0, lambda: messagebox.showerror("Lỗi Tiến Trình", msg))

    finally:
        if worker:
            worker.close()
        reset_scan_button = getattr(self, "_reset_group_scan_button", None)
        if callable(reset_scan_button):
            self.after(0, reset_scan_button)


if __name__ == "__main__":
  app = App()
  app.mainloop()
