import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import random
import time
import json
import threading
import urllib.parse
import bot

class DevelopScreen(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.parent = parent
        self.controller = controller
        self.posts = []

        self._build_ui()

    def _build_ui(self):
        # ==================== KHUNG BÊN TRÁI ====================
        left_frame = ttk.LabelFrame(self.parent, text=" Cấu hình & Điều khiển ", padding=10)
        left_frame.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        
        ttk.Label(left_frame, text="Nội dung (Hỗ trợ Icon/Ký tự đặc biệt):").pack(anchor="w", pady=2)
        self.txt_content = tk.Text(left_frame, height=6, wrap="word") # Giảm bớt height để nhường chỗ cho cấu hình khác
        self.txt_content.pack(fill="x", pady=5)
        self.txt_content.insert("1.0", "Nhập nội dung tại đây... ✨🚀🔥")

        # --- BỔ SUNG: Khung cấu hình Delay và Giới hạn ---
        config_frame = ttk.Frame(left_frame)
        config_frame.pack(fill="x", pady=5)

        # Cấu hình Delay
        ttk.Label(config_frame, text="Delay (giây):").grid(row=0, column=0, sticky="w", pady=5)
        self.ent_delay_min = ttk.Entry(config_frame, width=5)
        self.ent_delay_min.insert(0, "30")
        self.ent_delay_min.grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(config_frame, text="đến").grid(row=0, column=2, pady=5)
        self.ent_delay_max = ttk.Entry(config_frame, width=5)
        self.ent_delay_max.insert(0, "60")
        self.ent_delay_max.grid(row=0, column=3, padx=5, pady=5)

        # Cấu hình Số lượng bài tối đa
        ttk.Label(config_frame, text="Số bài muốn share:").grid(row=1, column=0, sticky="w", pady=5)
        self.ent_max_posts = ttk.Entry(config_frame, width=12)
        self.ent_max_posts.insert(0, "10")  # Mặc định điền sẵn 10 bài
        self.ent_max_posts.grid(row=1, column=1, columnspan=3, sticky="w", padx=5, pady=5)

        # Nút Start Màn hình 1
        button_frame = ttk.Frame(left_frame)
        button_frame.pack(fill="x", pady=15)

        self.btn_start = ttk.Button(
            button_frame,
            text="Chạy",
            command=self.dev_start
        )
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 5), ipady=5)

        self.btn_stop = tk.Button(
            button_frame,
            text="Dừng",
            command=self.dev_stop,
            state=tk.DISABLED,
            fg="red"
        )
        self.btn_stop.pack(side="left", fill="x", expand=True, padx=(5, 0), ipady=5)

        # --- BỔ SUNG: Thanh Trạng Thái (Status Bar) ---
        self.lbl_status = ttk.Label(left_frame, text="Trạng thái: Sẵn sàng", foreground="blue")
        self.lbl_status.pack(side="bottom", anchor="w", pady=(10, 0))

        # Biến lưu trữ đối tượng bot hiện tại để có thể điều khiển từ luồng chính
        self.current_bot = None 
        self.is_stopping = False # Cờ đánh dấu người dùng chủ động bấm dừng

        # ==================== KHUNG BÊN PHẢI ====================
        right_frame = ttk.LabelFrame(
            self.parent,
            text=" Danh sách bài đăng ",
            padding=10
        )
        right_frame.pack(side="right", fill="both", expand=True, padx=10, pady=10)

        tree_frame = ttk.Frame(right_frame)
        tree_frame.pack(fill="both", expand=True)

        # --- CẢI TIẾN: Thêm cột "status" vào columns ---
        self.tree = ttk.Treeview(
            tree_frame,
            columns=("checked", "post", "status"),
            show="headings",
            height=10
        )
        self.tree.bind("<Button-1>", self.toggle_checkbox)

        scrollbar = ttk.Scrollbar(
            tree_frame,
            orient="vertical",
            command=self.tree.yview
        )

        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.heading("checked", text="Chọn")
        self.tree.heading("post", text="Link bài đăng")
        self.tree.heading("status", text="Trạng thái") # Đầu mục cột mới

        self.tree.column("checked", width=50, anchor="center")
        self.tree.column("post", width=320)
        self.tree.column("status", width=100, anchor="center") # Kích thước cột mới

        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        btn_frame_right = ttk.Frame(right_frame)
        btn_frame_right.pack(fill="x", pady=(8, 0))

        btn_load = ttk.Button(
            btn_frame_right,
            text="Load file TXT",
            command=self.load_posts_from_txt
        )
        btn_load.pack(side="left", fill="x", expand=True, padx=(0, 5))

        btn_clear = ttk.Button(
            btn_frame_right,
            text="Clear",
            command=self.clear_posts
        )
        btn_clear.pack(side="left", fill="x", expand=True)
        
    def clear_posts(self):
        self.posts.clear()
        self.refresh_tree()

    def refresh_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        for post in self.posts:
            checkbox = "☑" if post["checked"] else "☐"

            self.tree.insert(
                "",
                "end",
                values=(checkbox, post["url"])
            )

    def load_posts_from_txt(self):
        filepath = filedialog.askopenfilename(
            filetypes=[("Text files", "*.txt")]
        )

        if not filepath:
            return

        self.posts.clear()

        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                post = line.strip()
                if post:
                    self.posts.append({
                        "checked": False,
                        "url": post,
                        "status": "Chờ xử lý"
                    })

        self.refresh_tree()

    def toggle_checkbox(self, event):
        region = self.tree.identify("region", event.x, event.y)
        column = self.tree.identify_column(event.x)
        item = self.tree.identify_row(event.y)

        if region != "cell" or column != "#1":
            return

        items = self.tree.get_children()

        if item not in items:
            return

        index = items.index(item)

        self.posts[index]["checked"] = not self.posts[index]["checked"]

        self.refresh_tree()

    def get_checked_posts(self):
        checked_items = []
        for item in self.tree.get_children():
            values = self.tree.item(item, "values")
            # Kiểm tra xem dòng đó có đang được tick chọn hay không
            if values and "☑" in values[0]: 
                checked_items.append({
                    "id": item,          # Lưu lại ID này để lát nữa cập nhật đúng dòng
                    "link": values[1]    # Link bài viết
                })
        return checked_items
    
    def dev_start(self):
        # Lấy dữ liệu từ giao diện tại luồng chính trước khi truyền vào Thread
        content = self.txt_content.get("1.0", tk.END).strip()
        uid = self.controller.ent_uid_shared.get()
        #files = list(self.selected_files)
        
        self.btn_start.config(state=tk.DISABLED, text="Đang chạy...")
        self.btn_stop.config(state=tk.NORMAL)
        self.is_stopping = False  # Reset lại cờ dừng

        # Khởi tạo một tiến trình (Thread) riêng cho Selenium của Màn 1
        # daemon=True để khi tắt app tkinter thì tiến trình Selenium này cũng tự tắt theo
        selenium_thread = threading.Thread(
            target=self.run_selenium_process, 
            args=(uid,content), 
            daemon=True
        )
        selenium_thread.start()

    def dev_stop(self):
        """Hàm xử lý khi người dùng nhấn nút Dừng"""
        if self.current_bot:
            self.is_stopping = True
            self.btn_stop.config(state=tk.DISABLED, text="Đang dừng...")
            print("[Dev Mode] Đang yêu cầu dừng tiến trình Selenium...")
            
            # Đóng trình duyệt từ luồng chính, việc này sẽ kích hoạt Exception ở luồng ngầm và dừng lại
            try:
                self.current_bot.close() 
            except Exception as e:
                print(f"[Dev Mode] Lỗi khi đóng bot: {e}")
            self.lbl_status.config(text="Trạng thái: Sẵn sàng", foreground="blue")
        else:
            messagebox.showwarning("Thông báo", "Không có tiến trình nào đang chạy!")


    def run_selenium_process(self, user, content):
        print(f"\n[Dev Mode] Đang khởi chạy tiến trình cho UID: {user}...")
        
        # Khởi tạo bộ đếm thống kê tổng quan chiến dịch
        stats = {"total_targets": 0, "success": 0, "pending": 0, "failed": 0}
        
        try:
            # 1. Lấy cấu hình delay từ giao diện
            try:
                delay_min = int(self.ent_delay_min.get())
                delay_max = int(self.ent_delay_max.get())
            except ValueError:
                delay_min, delay_max = 30, 60


            # 2. Khởi tạo Bot và Đăng nhập
            self.current_bot = bot.FacebookBot(self.controller.is_demo_mode)
            self.after(0, lambda: self.lbl_status.config(text="Trạng thái: Đang đăng nhập...", foreground="orange"))
            success = self.current_bot.start_browser(user, user_agent=self.controller.get_user_agent())
            if not success:
                self.after(0, lambda: messagebox.showerror("Lỗi", "Đăng nhập thất bại!"))
                return

            # 3. Lấy danh sách Bài đăng (đã chọn) và Nhóm (đã chọn)
            posts = self.get_checked_posts()
            
            # Lấy danh sách nhóm dựa theo cấu trúc dữ liệu của bạn
            groups_to_run = [
                {"id": g["id"], "name": g["name"], "status": "Chờ xử lý", "msg": ""}
                for g in self.controller.groups_data if g.get("checked")
            ]
            
            # Tổng số lượt share dự kiến = (Số bài) x (Số nhóm)
            stats["total_targets"] = len(posts) * len(groups_to_run)
            
            if stats["total_targets"] == 0:
                self.after(0, lambda: messagebox.showwarning("Chú ý", "Vui lòng chọn ít nhất 1 bài viết và 1 nhóm!"))
                return

            # VÒNG LẶP CHÍNH: Duyệt qua từng bài đăng
            for post_item in posts:
                if self.is_stopping: break
                
                item_id = post_item["id"]
                post_url = post_item["link"]
                
                # Cập nhật bảng danh sách bài đăng: Báo hiệu bài này đang được xử lý
                self.after(0, lambda idx=item_id, url=post_url: 
                        self.tree.item(idx, values=("☑", url, "⏳ Đang rải nhóm...")))
                
                # VÒNG LẶP CON: Duyệt qua từng nhóm để share bài hiện tại
                for group in groups_to_run:
                    if self.is_stopping: break
                    
                    # Cập nhật thanh trạng thái tổng số lượng ở góc dưới UI
                    current_index = stats["success"] + stats["pending"] + stats["failed"] + 1
                    self.after(0, lambda c=current_index, t=stats["total_targets"]: 
                            self.lbl_status.config(text=f"Trạng thái: Đang share ({c}/{t}) - Nhóm: {group['name']}...", foreground="green"))
                    
                    try:
                        # Gọi hàm share của Selenium Bot
                        # Thường hàm này của bạn sẽ trả về chuỗi kết quả: "success", "pending" (chờ duyệt), hoặc "failed"
                        result = self.current_bot.share_post_to_group(post_url, content, group['id'])
                        
                        # Cập nhật kết quả vào biến tạm của nhóm đó
                        if result == True:
                            group["status"] = "Thành công"
                            stats["success"] += 1
                        elif result == "pending":
                            group["status"] = "Chờ duyệt"
                            stats["pending"] += 1
                        else:
                            group["status"] = "Thất bại"
                            group["msg"] = "Không thể click nút đăng hoặc lỗi giao diện"
                            stats["failed"] += 1
                            
                    except Exception as group_err:
                        group["status"] = "Lỗi"
                        group["msg"] = str(group_err)
                        stats["failed"] += 1

                    # Cơ chế Delay chống quét Spam (Nghỉ sau mỗi nhóm, trừ lượt cuối cùng)
                    if not (post_item == posts[-1] and group == groups_to_run[-1]) and not self.is_stopping:
                        sleep_time = random.randint(delay_min, delay_max)
                        for s in range(sleep_time, 0, -1):
                            if self.is_stopping: break
                            self.after(0, lambda sec=s: self.lbl_status.config(
                                text=f"Trạng thái: Nghỉ giãn cách... còn {sec}s", foreground="blue"
                            ))
                            time.sleep(1)

                # Sau khi chạy hết các nhóm cho bài viết này -> Cập nhật kết quả tổng hợp lên Treeview của bài viết đó
                if not self.is_stopping:
                    post_summary = f"Thành công: {stats['success']} | Lỗi: {stats['failed']}"
                    self.after(0, lambda idx=item_id, url=post_url, txt=post_summary: 
                            self.tree.item(idx, values=("☑", url, txt)))

            # 4. Xuất báo cáo thống kê chi tiết (Chiến dịch hoàn thành)
            if not self.is_stopping:
                self.after(0, lambda: self.lbl_status.config(text="Trạng thái: Hoàn thành!", foreground="navy"))
                
                # Tạo chuỗi chi tiết từng nhóm thành công/thất bại để log hoặc hiển thị
                group_details = ""
                for g in groups_to_run:
                    icon = "✅" if g["status"] in ["Thành công", "Chờ duyệt"] else "❌"
                    err_msg = f" ({g['msg']})" if g["msg"] else ""
                    group_details += f"  + {icon} {g['name']}: {g['status']}{err_msg}\n"

                msg_box = (
                    f"🎉 UID {user} đã hoàn thành tiến trình rải bài!\n\n"
                    f"📊 BẢNG THỐNG KÊ CHIẾN DỊCH:\n"
                    f"━ Tổng số lượt share: {stats['total_targets']}\n"
                    f"❌ Thất bại / Gặp lỗi: {stats['failed']}\n\n"
                    f"📝 CHI TIẾT TỪNG NHÓM:\n{group_details}"
                )
                self.after(0, lambda: messagebox.showinfo("Kết quả chiến dịch", msg_box))
                
        except Exception as e:
            if self.is_stopping:
                self.after(0, lambda: self.lbl_status.config(text="Trạng thái: Đã dừng", foreground="red"))
                self.after(0, lambda: messagebox.showinfo("Đã dừng", "Tiến trình đã được dừng theo yêu cầu."))
            else:
                self.after(0, lambda: self.lbl_status.config(text="Trạng thái: Lỗi hệ thống", foreground="red"))
                self.after(0, lambda: messagebox.showerror("Lỗi", f"Lỗi tiến trình chính: {str(e)}"))
        finally:
            self.current_bot.close()
            self.current_bot = None
            self.after(0, self.reset_ui_buttons)

    def reset_ui_buttons(self):
        """Khôi phục lại trạng thái ban đầu của các nút bấm"""
        self.btn_start.config(state=tk.NORMAL, text="Chạy")
        self.btn_stop.config(state=tk.DISABLED, text="Dừng")
