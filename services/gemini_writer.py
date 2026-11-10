from typing import Optional
from google import genai
from google.genai import types


class GeminiRewriter:
	"""Class xử lý việc kết nối Gemini API và biến đổi văn bản theo template.

	Tự động giữ nguyên 100% mọi nội dung nằm trong cặp ngoặc nhọn {...}.
	"""

	def __init__(
		self,
		api_key: str,
		model_name: str = "gemini-3.5-flash-lite",
		temperature: float = 0.85,
		custom_instruction: Optional[str] = None,
	):
		self.api_key = api_key
		self.model_name = model_name
		self.temperature = temperature
		self.client = genai.Client(api_key=self.api_key)

		# Prompt được tối ưu để giữ nguyên BẤT KỲ thứ gì trong ngoặc nhọn {...}
		default_instruction = (
			"Bạn là công cụ viết lại tin nhắn tự động.\n"
			"Nhiệm vụ: Viết lại văn bản gốc thành 1 biến thể mới nhưng giữ nguyên ý nghĩa.\n"
			"QUY TẮC BẮT BUỘC THỐNG NHẤT:\n"
			"1. BẤT KỲ NỘI DUNG NÀO nằm trong ngoặc nhọn dạng {...} (bao gồm biến, từ ngữ, tên riêng, URL link như {Anh}, {Tuấn}, {ABC}, {https://...}) PHẢI GIỮ NGUYÊN 100% cả dấu ngoặc nhọn lẫn nội dung bên trong.\n"
			"2. Chỉ được thay đổi, diễn đạt lại các từ ngữ NGOÀI dấu ngoặc nhọn để tránh trùng lặp tin nhắn.\n"
			"3. CHỈ TRẢ VỀ VĂN BẢN ĐÃ VIẾT LẠI, không thêm lời chào, không giải thích, không bọc dấu ngoặc kép."
		)

		self.system_instruction = custom_instruction or default_instruction

	def generate_variant(
		self, original_text: str, extra_note: str = ""
	) -> Optional[str]:
		try:
			current_instruction = self.system_instruction
			if extra_note:
				current_instruction += f"\nLƯU Ý THÊM: {extra_note}"

			response = self.client.models.generate_content(
				model=self.model_name,
				contents=original_text,
				config=types.GenerateContentConfig(
					system_instruction=current_instruction,
					temperature=self.temperature,
				),
			)

			if response.text:
				return response.text.strip()
			return None

		except Exception as e:
			print(f"⚠️ [Lỗi Gemini Rewriter Module]: {e}")
			return None