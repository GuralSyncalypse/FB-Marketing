import json
from bs4 import BeautifulSoup


def find_member_data_script(html_source: str) -> dict | None:
    """Quét HTML page_source để lọc ra đúng JSON chứa danh sách thành viên

    nhóm.
    """
    soup = BeautifulSoup(html_source, "html.parser")

    # 1. Lọc tất cả các thẻ script có type="application/json"
    json_scripts = soup.find_all("script", {"type": "application/json"})

    for script in json_scripts:
        content = script.string
        if not content:
            continue

        # 2. Kiểm tra các từ khóa đặc trưng của Relay GraphQL Member Data
        if (
            "RelayPrefetchedStreamCache" in content
            and "group_member_profiles" in content
        ):
            try:
                # Parse nội dung thẻ script thành Python Dictionary
                data = json.loads(content)
                return data
            except json.JSONDecodeError:
                continue

    return None


# --- CÁCH SỬ DỤNG TRONG CLASS CỦA BẠN ---
# raw_html = self.driver.page_source
# group_data_json = find_member_data_script(raw_html)
#
# if group_data_json:
#     print("[+] Đã tìm thấy đúng script chứa dữ liệu thành viên!")