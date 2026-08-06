import json
import os
import pandas as pd

def convert_json_file_to_spreadsheet(json_filepath, output_file="facebook_users.xlsx", join_details=True):
    """
    Đọc file .json hoặc .jsonl từ ổ đĩa và chuyển đổi sang file Excel (.xlsx) hoặc CSV (.csv).
    """
    if not os.path.exists(json_filepath):
        print(f"Lỗi: Không tìm thấy file '{json_filepath}'")
        return

    processed_rows = []

    # 2. Đọc file theo đúng định dạng (.jsonl đọc từng dòng, .json đọc toàn bộ)
    with open(json_filepath, 'r', encoding='utf-8') as f:
        if json_filepath.endswith('.jsonl'):
            data = (json.loads(line) for line in f if line.strip())
        else:
            data = json.load(f)

        # 3. Xử lý từng đối tượng
        for item in data:
            row = {
                "user_id": f"'{str(item.get('user_id', ''))}",
                "name": item.get("name", ""),
                "link": item.get("link", ""),
                "avatar": item.get("avatar", "")
            }
            
            details = item.get("details", [])
            
            if join_details:
                row["details"] = " | ".join(details)
            else:
                for idx, detail in enumerate(details, start=1):
                    row[f"detail_{idx}"] = detail

            processed_rows.append(row)

    # 4. Xuất ra DataFrame và lưu file
    df = pd.DataFrame(processed_rows)

    if output_file.endswith(".csv"):
        df.to_csv(output_file, index=False, encoding="utf-8-sig")
    elif output_file.endswith(".xlsx"):
        df.to_excel(output_file, index=False)
    else:
        raise ValueError("Định dạng file không hỗ trợ. Vui lòng chọn .xlsx hoặc .csv")

    print(f"Đã chuyển đổi thành công từ '{json_filepath}' sang '{output_file}'!")

    

def filter_members(input_file="users.json"):
    """
    Đọc file JSON dữ liệu thô và lọc dựa trên KHỚP CHUỖI CHÍNH XÁC (Case-sensitive exact match)
    """
    if not os.path.exists(input_file):
        print(f"❌ File '{input_file}' không tồn tại. Vui lòng kiểm tra lại đường dẫn!")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        try:
            raw_data = json.load(f)
        except json.JSONDecodeError:
            print(f"❌ File '{input_file}' bị lỗi định dạng JSON!")
            return

    valid_members = []
    admins_mods = []
    junk_accounts = []

    # 🎯 Tập hợp các chuỗi ĐÍCH DANH (Phân biệt chính xác chữ hoa / chữ thường)
    # Chỉ nhận đúng các kiểu viết này, không nhận kiểu khác
    exact_admin_keywords = {
        "Admin", 
        "admin",
        "Quản trị viên", 
        "quản trị viên",
        "Người kiểm duyệt", 
        "người kiểm duyệt",
        "Chuyên gia nhóm", 
        "chuyên gia nhóm",
        "Moderator", 
        "moderator"
    }

    for item in raw_data:
        name = item.get("name", "").strip()
        user_id = item.get("user_id", "").strip()
        avatar = item.get("avatar", "").strip()

        # 1. Tiêu chí Lọc Nick Rác / Clone / Lỗi data
        if not avatar or not name or not user_id:
            item["filter_reason"] = "Thiếu Avatar hoặc Thông tin cá nhân"
            junk_accounts.append(item)
            continue

        # 2. Tiêu chí Lọc Ban Quản Trị: Khớp chính xác 100% chuỗi từng dòng trong details
        details_lines = [line.strip() for line in item.get("details", [])]
        
        # Kiểm tra xem có bất kỳ dòng nào khớp đúng 1 trong các từ khóa trong exact_admin_keywords hay không
        is_admin = any(line in exact_admin_keywords for line in details_lines)

        if is_admin:
            admins_mods.append(item)
            continue

        # 3. Thành viên bình thường đạt chuẩn
        valid_members.append(item)

    # Export các danh sách ra file riêng biệt
    files_to_save = {
        "valid_members.json": valid_members,
        "admins_mods.json": admins_mods,
        "junk_accounts.json": junk_accounts
    }

    for filename, data in files_to_save.items():
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    # In báo cáo thống kê
    total = len(raw_data)
    print("=" * 50)
    print("📊 BÁO CÁO KẾT QUẢ LỌC DỮ LIỆU")
    print("=" * 50)
    print(f"📥 Tổng số record ban đầu:  {total}")
    print(f"✅ Thành viên chuẩn (Valid): {len(valid_members)} ({len(valid_members)/total*100:.1f}%)")
    print(f"🛡️ Quản trị viên/Admin:     {len(admins_mods)} ({len(admins_mods)/total*100:.1f}%)")
    print(f"🗑️ Nick rác/Clone lọc bỏ:  {len(junk_accounts)} ({len(junk_accounts)/total*100:.1f}%)")
    print("=" * 50)

# ==========================================
# CÁCH SỬ DỤNG HÀM
# ==========================================
if __name__ == "__main__":
    #filter_members("users_group_KillingFloorClanESP.json")


    # Thay 'du_lieu.json' bằng đường dẫn file .json thực tế trên máy của bạn
    file_json_dau_vao = "output_KillingFloorClanESP.json" 

    # 1. Đọc file JSON và xuất ra file Excel
    convert_json_file_to_spreadsheet(
        json_filepath=file_json_dau_vao, 
        output_file="ket_qua.xlsx", 
        join_details=True
    )

    # 2. Đọc file JSON và xuất ra file CSV (Tách details thành các cột riêng)
    # convert_json_file_to_spreadsheet(
    #     json_filepath=file_json_dau_vao, 
    #     output_file="ket_qua.csv", 
    #     join_details=False
    # )