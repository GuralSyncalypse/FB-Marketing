import json
import os
import pandas as pd
import re

def convert_to_spreadsheet(json_filepath, output_file="facebook_users.xlsx"):
    """
    Đọc file .json hoặc .jsonl và chuyển đổi sang file Excel (.xlsx) hoặc CSV (.csv).
    """

    def parse_contribution_score(score_str):
        """Trích xuất số từ chuỗi contribution_score, mặc định là 0 nếu null hoặc rỗng."""
        if not score_str:
            return 0
        match = re.search(r'\d+', str(score_str))
        return int(match.group()) if match else 0

    def parse_boolean_status(status_str, positive_value):
        """
        Chuyển đổi trạng thái text sang Boolean:
        - Nếu đúng positive_value -> True
        - Nếu null / None / rỗng -> None (Để trống trong Excel/CSV)
        - Nếu là trạng thái ngược lại -> False
        """
        if status_str is None or status_str == "":
            return None
        elif status_str == positive_value:
            return True
        return False

    if not os.path.exists(json_filepath):
        print(f"Lỗi: Không tìm thấy file '{json_filepath}'")
        return

    items = []

    # 1. Đọc file .json / .jsonl
    with open(json_filepath, 'r', encoding='utf-8') as f:
        if json_filepath.endswith('.jsonl'):
            items = [json.loads(line) for line in f if line.strip()]
        else:
            data = json.load(f)
            items = data if isinstance(data, list) else [data]

    processed_rows = []

    # 2. Xử lý từng đối tượng
    for item in items:
        row = {
            "user_id": str(item.get("id") or item.get("user_id") or ""),
            "name": item.get("name", ""),
            "url": item.get("url") or item.get("link") or "",
            "avatar": item.get("avatar", ""),
            "bio": item.get("bio", ""),
            "follower_count": item.get("follower_count", 0),
            "is_verified": item.get("is_verified", False),
            "category": item.get("category", ""),
            
            # Các trường xử lý đặc biệt
            "contribution_score": parse_contribution_score(item.get("contribution_score")),
            "friendship_status": parse_boolean_status(item.get("friendship_status"), "CAN_REQUEST"),
            "subscribe_status": parse_boolean_status(item.get("subscribe_status"), "CAN_SUBSCRIBE"),
            
            "membership_id": str(item.get("membership_id") or ""),
            "join_status_text": item.get("join_status_text", ""),
            "added_by_id": str(item.get("added_by_id") or ""),
            "added_by_name": item.get("added_by_name", ""),
            "added_by_url": item.get("added_by_url", "")
        }

        processed_rows.append(row)

    # 3. Xuất ra DataFrame & Lưu file
    df = pd.DataFrame(processed_rows)

    if output_file.endswith(".csv"):
        # na_rep="" đảm bảo các giá trị None/null ghi ra CSV dạng ô trống
        df.to_csv(output_file, index=False, encoding="utf-8-sig", na_rep="")
    elif output_file.endswith(".xlsx"):
        df.to_excel(output_file, index=False, engine="openpyxl")
    else:
        raise ValueError("Định dạng file không hỗ trợ. Vui lòng chọn .xlsx hoặc .csv")

    print(f"Đã chuyển đổi thành công {len(df)} dòng từ '{json_filepath}' sang '{output_file}'!")

# ==========================================
# CÁCH SỬ DỤNG HÀM
# ==========================================
if __name__ == "__main__":
    # Thay 'du_lieu.json' bằng đường dẫn file .json thực tế trên máy của bạn
    file_json_dau_vao = "data/679011295472431.jsonl" 

    # 1. Đọc file JSON và xuất ra file Excel
    convert_to_spreadsheet(
        json_filepath=file_json_dau_vao, 
        output_file="ket_qua.xlsx"
    )