import csv
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import bot
import os
from services.gemini_writer import GeminiRewriter


class SmsScreen(tk.Frame):

	def __init__(self, parent, controller):
		super().__init__(parent)
		self.parent = parent
		self.controller = controller
		self.user_list = []
		self._build_ui()

	def _build_ui(self):
		# Cấu hình grid tổng cho self.parent để phân chia 2 cột Left - Right
		self.parent.columnconfigure(0, weight=3)  # Cột cấu hình chiếm nhiều không gian hơn
		self.parent.columnconfigure(1, weight=2)  # Cột danh sách UID
		self.parent.rowconfigure(0, weight=1)

		# ================= CỘT BÊN TRÁI: CẤU HÌNH =================
		left_frame = ttk.LabelFrame(self.parent, text=" Cấu hình ", padding=12)
		left_frame.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)

		# --- 1. CẤU HÌNH AI REWRITER ---
		ai_frame = ttk.LabelFrame(left_frame, text=" Cấu hình AI ", padding=10)
		ai_frame.pack(fill="x", pady=(0, 8))
		ai_frame.columnconfigure(1, weight=1)

		# Checkbox bật/tắt AI
		self.var_use_ai = tk.BooleanVar(value=True)
		chk_ai = ttk.Checkbutton(
			ai_frame,
			text="Bật AI Rewriter (Chống Spam FB)",
			variable=self.var_use_ai,
		)
		chk_ai.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

		# API Key
		ttk.Label(ai_frame, text="API Key:").grid(
			row=1, column=0, sticky="w", padx=(0, 5), pady=3
		)
		self.ent_api_key = ttk.Entry(ai_frame, show="*")
		self.ent_api_key.grid(row=1, column=1, sticky="ew", padx=(0, 5), pady=3)

		self.btn_check_key = ttk.Button(
			ai_frame, text="Kiểm tra", width=10, command=self.check_api_key
		)
		self.btn_check_key.grid(row=1, column=2, sticky="e", pady=3)

		# Model AI
		ttk.Label(ai_frame, text="Model AI:").grid(
			row=2, column=0, sticky="w", padx=(0, 5), pady=3
		)
		self.cbo_model = ttk.Combobox(
			ai_frame,
			values=[
				"gemini-3.5-flash-lite",
				"gemini-1.5-flash",
				"gemini-3.5-flash",
			],
			state="readonly",
		)
		self.cbo_model.set("gemini-3.5-flash-lite")
		self.cbo_model.grid(
			row=2, column=1, columnspan=2, sticky="ew", pady=3
		)

		# Custom Prompt
		ttk.Label(ai_frame, text="Custom Prompt:").grid(
			row=3, column=0, sticky="w", padx=(0, 5), pady=3
		)
		self.ent_custom_prompt = ttk.Entry(ai_frame)
		self.ent_custom_prompt.grid(
			row=3, column=1, columnspan=2, sticky="ew", pady=3
		)

		# Ghi chú AI
		ttk.Label(ai_frame, text="Ghi chú AI:").grid(
			row=4, column=0, sticky="w", padx=(0, 5), pady=3
		)
		self.ent_ai_note = ttk.Entry(ai_frame)
		self.ent_ai_note.grid(
			row=4, column=1, columnspan=2, sticky="ew", pady=3
		)

		# --- 2. NỘI DUNG MẪU ---
		content_frame = ttk.LabelFrame(
			left_frame, text=" Nội dung mẫu ", padding=10
		)
		content_frame.pack(fill="x", pady=(0, 8))

		self.txt_content = tk.Text(content_frame, height=4, wrap="word", font=("Segoe UI", 9))
		self.txt_content.pack(fill="x", pady=(0, 4))

		ttk.Label(
			content_frame,
			text="💡 Nội dung trong ngoặc nhọn { } sẽ được giữ nguyên khi AI viết lại.",
			font=("Segoe UI", 8, "italic"),
			foreground="#0056b3",
		).pack(anchor="w")

		# --- 3. ĐÍNH KÈM HÌNH ẢNH ---
		img_frame = ttk.LabelFrame(
			left_frame, text=" Đính kèm hình ảnh ", padding=10
		)
		img_frame.pack(fill="x", pady=(0, 8))
		img_frame.columnconfigure(0, weight=1)

		self.ent_image_path = ttk.Entry(img_frame)
		self.ent_image_path.grid(row=0, column=0, sticky="ew", padx=(0, 5))

		btn_browse_img = ttk.Button(
			img_frame, text="Chọn ảnh", width=9, command=self.browse_image
		)
		btn_browse_img.grid(row=0, column=1, padx=(0, 3))

		btn_clear_img = ttk.Button(
			img_frame, text="Xóa", width=6, command=self.clear_image
		)
		btn_clear_img.grid(row=0, column=2)

		# --- 4. CẤU HÌNH DELAY (CHỐNG SPAM) ---
		delay_frame = ttk.LabelFrame(
			left_frame, text=" Cấu hình Delay (Giãn cách) ", padding=10
		)
		delay_frame.pack(fill="x", pady=(0, 8))

		# Chờ giữa 2 tin
		ttk.Label(delay_frame, text="Chờ giữa 2 tin:").grid(
			row=0, column=0, sticky="w", pady=2
		)
		self.ent_delay_min = ttk.Entry(delay_frame, width=6, justify="center")
		self.ent_delay_min.insert(0, "30")
		self.ent_delay_min.grid(row=0, column=1, padx=4, pady=2)

		ttk.Label(delay_frame, text="đến").grid(row=0, column=2, pady=2)
		self.ent_delay_max = ttk.Entry(delay_frame, width=6, justify="center")
		self.ent_delay_max.insert(0, "60")
		self.ent_delay_max.grid(row=0, column=3, padx=4, pady=2)

		ttk.Label(delay_frame, text="giây").grid(
			row=0, column=4, sticky="w", pady=2
		)

		# Giả lập gõ phím
		ttk.Label(delay_frame, text="Giả lập gõ phím:").grid(
			row=1, column=0, sticky="w", pady=2
		)
		self.ent_typing_min = ttk.Entry(delay_frame, width=6, justify="center")
		self.ent_typing_min.insert(0, "3")
		self.ent_typing_min.grid(row=1, column=1, padx=4, pady=2)

		ttk.Label(delay_frame, text="đến").grid(row=1, column=2, pady=2)
		self.ent_typing_max = ttk.Entry(delay_frame, width=6, justify="center")
		self.ent_typing_max.insert(0, "5")
		self.ent_typing_max.grid(row=1, column=3, padx=4, pady=2)

		ttk.Label(delay_frame, text="giây").grid(
			row=1, column=4, sticky="w", pady=2
		)

		# --- 5. TIẾN TRÌNH & NÚT CHẠY ---
		self.progress = ttk.Progressbar(left_frame, mode="determinate")
		self.progress.pack(fill="x", pady=(4, 8))

		self.btn_start = ttk.Button(
			left_frame, text="Chạy tiến trình", command=self.start_screen_2
		)
		self.btn_start.pack(fill="x", ipady=4)

		# ================= CỘT BÊN PHẢI: DANH SÁCH UIDS =================
		right_frame = ttk.LabelFrame(
			self.parent, text=" Danh sách UIDs ", padding=12
		)
		right_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 10), pady=10)

		ttk.Label(
			right_frame,
			text="(Phím Delete hoặc Double Click để xóa dòng)",
			font=("Segoe UI", 8, "italic"),
			foreground="gray",
		).pack(anchor="w", pady=(0, 4))

		# Bọc Listbox + Scrollbar vào Frame để cuộn mượt mà
		list_container = ttk.Frame(right_frame)
		list_container.pack(fill="both", expand=True, pady=(0, 8))

		scrollbar = ttk.Scrollbar(list_container, orient="vertical")
		scrollbar.pack(side="right", fill="y")

		self.listbox_uids = tk.Listbox(
			list_container,
			yscrollcommand=scrollbar.set,
			selectmode="extended",
			font=("Consolas", 9),
			bd=1,
			relief="solid",
		)
		self.listbox_uids.pack(side="left", fill="both", expand=True)
		scrollbar.config(command=self.listbox_uids.yview)

		self.listbox_uids.bind("<Delete>", self.delete_selected_uid)
		self.listbox_uids.bind("<Double-1>", self.delete_selected_uid)

		# ---- NÚT ĐIỀU KHIỂN DANH SÁCH ----
		btn_frame = ttk.Frame(right_frame)
		btn_frame.pack(fill="x")

		btn_import_txt = ttk.Button(
			btn_frame,
			text="Thêm vào list (.csv/.txt)",
			command=self.import_uids,
		)
		btn_import_txt.pack(side="left", fill="x", expand=True, padx=(0, 3))

		btn_clear_all = ttk.Button(
			btn_frame, text="Clear All", command=self.clear_all_uids
		)
		btn_clear_all.pack(side="right", fill="x", expand=True, padx=(3, 0))

	# ================= LOGIC HÀM PHỤ TRỢ =================
	def browse_image(self):
		"""Mở hộp thoại chọn NHIỀU hình ảnh cùng lúc."""
		file_paths = filedialog.askopenfilenames(
			title="Chọn một hoặc nhiều hình ảnh đính kèm",
			filetypes=[
				("Image Files", "*.png *.jpg *.jpeg *.gif *.bmp"),
				("All Files", "*.*"),
			],
		)
		if file_paths:
			# Nối các đường dẫn lại với nhau bằng dấu semicolon ";"
			joined_paths = ";".join(file_paths)
			self.ent_image_path.delete(0, tk.END)
			self.ent_image_path.insert(0, joined_paths)

	def clear_image(self):
		"""Xóa toàn bộ đường dẫn ảnh đã chọn."""
		self.ent_image_path.delete(0, tk.END)


	def check_api_key(self):
		key = self.ent_api_key.get().strip()
		if not key:
			messagebox.showwarning("Cảnh báo", "Vui lòng nhập API Key!")
			return

		if not GeminiRewriter:
			messagebox.showerror(
				"Lỗi", "Không tìm thấy module gemini_rewriter.py!"
			)
			return

		try:
			test_rewriter = GeminiRewriter(
				api_key=key, model_name=self.cbo_model.get()
			)
			res = test_rewriter.generate_variant("Test kết nối")
			if res:
				messagebox.showinfo(
					"Thành công", "API Key hợp lệ và hoạt động tốt!"
				)
			else:
				messagebox.showerror("Lỗi", "API Key không trả về kết quả.")
		except Exception as e:
			messagebox.showerror("Lỗi API Key", f"Chi tiết lỗi: {e}")

	def import_uids(self):
		file_path = filedialog.askopenfilename(
			title="Chọn file UIDs",
			filetypes=[("CSV Files", "*.csv"), ("Text Files", "*.txt")],
		)
		if not file_path:
			return

		try:
			with open(file_path, mode="r", encoding="utf-8-sig") as f:
				if file_path.endswith(".csv"):
					reader = csv.DictReader(f)
					for row in reader:
						u_id = row.get("user_id", "").strip()
						u_name = row.get("name", "").strip()
						u_url = row.get("url", "").strip()

						if u_id:
							# 1. Lưu dict đầy đủ thông tin
							user_data = {
								"user_id": u_id,
								"name": u_name if u_name else "bạn",
								"url": (
									u_url
									if u_url
									else f"https://facebook.com/profile.php?id={u_id}"
								),
							}
							self.user_list.append(user_data)

							# 2. Hiển thị dạng "UID - Tên" lên Listbox giao diện
							display_str = (
								f"{u_id} - {u_name}" if u_name else u_id
							)
							self.listbox_uids.insert("end", display_str)

				else:  # Đọc file .txt chỉ có UID
					for line in f:
						u_id = line.strip()
						if u_id:
							self.user_list.append({
								"user_id": u_id,
								"name": "bạn",
								"url": (
									f"https://facebook.com/profile.php?id={u_id}"
								),
							})
							self.listbox_uids.insert("end", u_id)

			messagebox.showinfo(
				"Thành công", f"Đã nạp {len(self.user_list)} người dùng!"
			)
		except Exception as e:
			messagebox.showerror("Lỗi", f"Không đọc được file: {e}")

	def delete_selected_uid(self, event=None):
		selected_indices = self.listbox_uids.curselection()
		if not selected_indices:
			return
		for idx in reversed(selected_indices):
			self.listbox_uids.delete(idx)
			if idx < len(self.user_list):
				del self.user_list[idx]

	def clear_all_uids(self):
		self.listbox_uids.delete(0, "end")
		self.user_list.clear()

	def start_screen_2(self):
		# Lấy dữ liệu từ giao diện tại luồng chính trước khi truyền vào Thread
		content = self.txt_content.get("1.0", tk.END).strip()
		uid = self.controller.ent_uid_shared.get()

		if uid == self.controller.empty_uid:
			messagebox.showerror("Lỗi", "Không có tài khoản để chạy!")
			return

		if not self.user_list:
			messagebox.showerror("Lỗi", "Không danh sách uids!")
			return

		if not content:
			messagebox.showerror("Lỗi", "Không có nội dung!")
			return

		self.btn_start.config(state=tk.DISABLED, text="Đang chạy...")
		# daemon=True để khi tắt app tkinter thì tiến trình Selenium này cũng tự tắt theo
		selenium_thread = threading.Thread(
			target=self.run_selenium_process_s2,
			args=(uid, content),
			daemon=True,
		)
		selenium_thread.start()

	def run_selenium_process_s2(self, user, content):
		print(
			f"\n[Selenium Màn 2] Đang khởi chạy tiến trình ngầm cho UID:"
			f" {user}..."
		)

		try:
			obj = bot.FacebookBot(self.controller.is_demo_mode)
			obj.user_agent = self.controller.user_agent
			success = obj.start_browser(
				user, user_agent=self.controller.get_user_agent()
			)
			if not success:
				self.after(
					0, lambda: messagebox.showerror("Lỗi", "Đăng nhập thất bại!")
				)
				return

			# 1. Lấy thông số cấu hình AI từ giao diện
			use_ai = self.var_use_ai.get()
			ai_note = self.ent_ai_note.get().strip()
			api_key = self.ent_api_key.get().strip()
			custom_prompt = self.ent_custom_prompt.get().strip() or None

			# Khởi tạo AI Rewriter nếu bật AI
			rewriter = None
			if use_ai and api_key and GeminiRewriter:
				rewriter = GeminiRewriter(
					api_key=api_key, model_name=self.cbo_model.get(),custom_instruction=custom_prompt
				)

			success_count = 0
			total_users = len(self.user_list)

			raw_image_str = self.ent_image_path.get().strip()
			image_paths = (
				[p.strip() for p in raw_image_str.split(";") if p.strip()]
				if raw_image_str
				else []
			)

			# Lọc chỉ lấy các file thực sự tồn tại trên ổ đĩa
			valid_image_paths = [p for p in image_paths if os.path.exists(p)]

			# 2. Vòng lặp gửi tin nhắn
			for idx, user_data in enumerate(self.user_list):
				# Trích xuất UID (xử lý cả trường hợp user_data là dict hoặc string)
				target_uid = (
					user_data.get("user_id", "")
					if isinstance(user_data, dict)
					else str(user_data)
				)

				if not target_uid:
					continue

				# Mặc định sử dụng nội dung gốc
				msg_to_send = content

				# Nếu bật AI -> Viết lại biến thể mới
				if use_ai and rewriter:
					ai_variant = rewriter.generate_variant(content, extra_note=ai_note)
					if ai_variant:
						msg_to_send = ai_variant  # Gán kết quả AI trả về

				# Gửi tin nhắn qua Selenium
				success = obj.send_message_via_uid(target_uid, msg_to_send, image_paths=valid_image_paths)
				if success:
					success_count += 1

				# Cập nhật thanh Progressbar trên giao diện
				progress_val = int(((idx + 1) / total_users) * 100)
				self.after(0, lambda v=progress_val: self.progress.config(value=v))

			# 3. Thông báo kết quả sau khi hoàn thành
			self.after(
				0,
				lambda: messagebox.showinfo(
					"Thông báo",
					f"Hoàn thành tiến trình!\nThành công: [{success_count}/{total_users}]",
				),
			)

		except Exception as e:
			self.after(
				0,
				lambda: messagebox.showerror(
					"Lỗi Tiến Trình", f"Có lỗi xảy ra: {str(e)}"
				),
			)
		finally:
			obj.close()
			self.after(
				0,
				lambda: self.btn_start.config(
					state=tk.NORMAL, text="Chạy Tiến Trình"
				),
			)