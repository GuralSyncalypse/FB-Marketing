import asyncio
import json
import logging
from typing import List, Dict, Any
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

# --- CẤU HÌNH LOGGING ---
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# --- CẤU HÌNH HỆ THỐNG CÀO ---
TARGET_URL = "https://cbonds.hnx.vn/to-chuc-phat-hanh/danh-sach-trai-phieu"
SESSION_ID = "bond_pagination_session"
OUTPUT_FILENAME = "trang_68.json"
TOTAL_PAGES = 68  # Thay đổi số lượng trang cần cào tại đây

# --- SCHEMA TRÍCH XUẤT ĐẦY ĐỦ CÁC CỘT (ĐÃ BỎ QUA TÀI LIỆU ĐÍNH KÈM) ---
BOND_EXTRACTION_SCHEMA = {
    "name": "bond_data_table",
    "baseSelector": "table#tbBond tbody tr",
    "fields": [
        {"name": "stt", "selector": "td:nth-child(1)", "type": "text"},
        {"name": "ma_trai_phieu", "selector": "td:nth-child(2) a", "type": "text"},
        {"name": "tien_te", "selector": "td:nth-child(3)", "type": "text"},
        {"name": "doanh_nghiep", "selector": "td:nth-child(4)", "type": "text"},
        {"name": "menh_gia", "selector": "td:nth-child(5)", "type": "text"},
        {"name": "ky_han", "selector": "td:nth-child(6)", "type": "text"},
        {"name": "ky_han_con_lai_ngay", "selector": "td:nth-child(7)", "type": "text"},
        {"name": "ngay_phat_hanh", "selector": "td:nth-child(8)", "type": "text"},
        {"name": "ngay_dao_hanh", "selector": "td:nth-child(9)", "type": "text"},
        {"name": "phuong_thuc_tra_lai", "selector": "td:nth-child(10)", "type": "text"},
        {"name": "ky_han_tra_lai", "selector": "td:nth-child(11)", "type": "text"},
        {"name": "kl_phat_hanh", "selector": "td:nth-child(12)", "type": "text"},
        {"name": "kl_con_luu_hanh", "selector": "td:nth-child(13)", "type": "text"},
        {"name": "to_chuc_luu_ky", "selector": "td:nth-child(14)", "type": "text"},
        {"name": "lai_suat_phat_hanh", "selector": "td:nth-child(15)", "type": "text"},
        {"name": "doi_tuong_chao_ban", "selector": "td:nth-child(16)", "type": "text"},
        {"name": "don_vi_xhtn_gan_nhat", "selector": "td:nth-child(17)", "type": "text"},
        {"name": "ket_qua_xhtn_gan_nhat", "selector": "td:nth-child(18)", "type": "text"},
        {"name": "ngay_hieu_luc", "selector": "td:nth-child(19)", "type": "text"},
        # td:nth-child(20) là Tài liệu đính kèm -> Chủ động bỏ qua không khai báo
        {"name": "tieu_chuan_ben_vung", "selector": "td:nth-child(21)", "type": "text"},
        {"name": "don_vi_danh_gia_doc_lap", "selector": "td:nth-child(22)", "type": "text"},
        {"name": "tinh_trang", "selector": "td:nth-child(23)", "type": "text"}
    ]
}


def build_pagination_javascript(page_number: int) -> str:
    """Khởi tạo đoạn mã JavaScript vừa giữ chế độ hiển thị 100 dòng vừa chuyển trang chính xác."""
    return f"""
        (function() {{
            var selectBox = document.getElementById('slChangeNumberRecord');
            if (selectBox) {{
                selectBox.value = '100';
            }}
            if (typeof ChangePage === 'function') {{
                ChangePage({page_number});
            }}
        }})();
    """


async def crawl_dynamic_bond_data():
    """Hàm điều phối chính thực hiện tuần tự việc cào dữ liệu qua các trang."""
    extraction_strategy = JsonCssExtractionStrategy(BOND_EXTRACTION_SCHEMA)
    
    # Cấu hình Trình duyệt (Tối ưu hóa tài nguyên phần cứng)
    browser_config = BrowserConfig(
        headless=True,
        light_mode=True,
        extra_args=["--disable-gpu", "--disable-dev-shm-usage"]
    )
    
    all_bonds_data: List[Dict[str, Any]] = []
    seen_bond_ids = set()  # Lưu vết Mã trái phiếu để lọc dữ liệu trùng

    async with AsyncWebCrawler(config=browser_config) as crawler:
        
        # --- XỬ LÝ TRANG 1 + THAY ĐỔI HIỂN THỊ 100 BẢN GHI ---
        logging.info("Đang khởi tạo Trang 1 và cấu hình hiển thị 100 bản ghi...")
        
        js_select_100 = """
            (function() {
                var selectBox = document.getElementById('slChangeNumberRecord');
                if (selectBox) {
                    selectBox.value = '100';
                    if (typeof ChangePage === 'function') {
                        ChangePage(68);
                    }
                }
            })();
        """
        
        run_config_p1 = CrawlerRunConfig(
            session_id=SESSION_ID,
            js_code=js_select_100,
            wait_until="domcontentloaded",
            delay_before_return_html=4.0,
            extraction_strategy=extraction_strategy,
            cache_mode="bypass"
        )
        
        result = await crawler.arun(url=TARGET_URL, config=run_config_p1)
        if result.success:
            try:
                page_data = json.loads(result.extracted_content)
                for item in page_data:
                    bond_id = item.get("ma_trai_phieu")
                    if bond_id:
                        seen_bond_ids.add(bond_id)
                        all_bonds_data.append(item)
                logging.info(f"Thành công! Đã lấy {len(page_data)} dòng dữ liệu từ Trang 1.")
            except json.JSONDecodeError as e:
                logging.error(f"Lỗi phân tích cú pháp JSON ở Trang 1: {e}")
        else:
            logging.error(f"Thất bại khi tải Trang 1: {result.error_message}")

        # --- VÒNG LẶP CHUYỂN TRANG ĐỘNG (Từ Trang 2 trở đi) ---
        for page in range(68, 69):
            logging.info(f"Đang kích hoạt lệnh JavaScript để chuyển sang: Trang {page}")
            
            run_config_next = CrawlerRunConfig(
                session_id=SESSION_ID,
                js_code=build_pagination_javascript(page),
                js_only=True,          
                wait_until="domcontentloaded",
                extraction_strategy=extraction_strategy,
                delay_before_return_html=4.0,
                cache_mode="bypass"
            )

            result_next = await crawler.arun(url=TARGET_URL, config=run_config_next)
            
            if result_next.success:
                try:
                    page_data = json.loads(result_next.extracted_content)
                    new_records = []
                    
                    # Tiến hành lọc dữ liệu trùng lặp
                    for item in page_data:
                        bond_id = item.get("ma_trai_phieu")
                        if bond_id and bond_id not in seen_bond_ids:
                            seen_bond_ids.add(bond_id)
                            new_records.append(item)
                    
                    if new_records:
                        all_bonds_data.extend(new_records)
                        logging.info(f"Thành công! Đã lấy {len(new_records)} dòng dữ liệu mới từ Trang {page} (Bỏ qua {len(page_data) - len(new_records)} dòng trùng).")
                    else:
                        logging.warning(f"Trang {page}: Không có dữ liệu mới do trang chưa kịp tải AJAX.")
                        
                except json.JSONDecodeError as e:
                    logging.error(f"Lỗi phân tích cú pháp JSON ở Trang {page}: {e}")
            else:
                logging.error(f"Thất bại tại Trang {page}: {result_next.error_message}")
                
    # --- XUẤT KẾT QUẢ RA FILE JSON ---
    if all_bonds_data:
        with open(OUTPUT_FILENAME, "w", encoding="utf-8") as f:
            json.dump(all_bonds_data, f, ensure_ascii=False, indent=4)
        logging.info(f"HOÀN THÀNH! Đã lưu tổng cộng {len(all_bonds_data)} bản ghi độc nhất vào file '{OUTPUT_FILENAME}'")
    else:
        logging.warning("Không có dữ liệu nào được thu thập để lưu.")


if __name__ == "__main__":
    asyncio.run(crawl_dynamic_bond_data())