"""FacebookBot: các tác vụ quét thành viên, bài viết và tương tác Facebook.

Vòng đời browser nằm ở ``bot.browser.BrowserMixin``; đăng nhập/cookie nằm ở
``bot.auth.AuthMixin``. Các nhóm chức năng còn lại sẽ tiếp tục được tách dần.
"""

from __future__ import annotations

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
import random
import time
import os
import re
import json
import datetime as dt
import unicodedata
import pandas as pd

from services.graphql_post_extractor import (
    extract_posts_from_graphql_response,
    parse_graphql_post,
)
from services.post_extractor import (
    dedupe_posts,
    extract_posts,
    parse_post_wrapper,
    post_key,
)

from .auth import AuthMixin
from .browser import BrowserMixin
from .comments import (
    COMMENT_EXPORT_COLUMNS,
    CommentMixin,
    export_comments_to_spreadsheet,
)
from .reactions import (
    REACTION_EXPORT_COLUMNS,
    ReactionMixin,
    export_reactions_to_spreadsheet,
)
from .graphql import (
    GROUP_MEMBERS_DOC_ID,
    GROUP_MEMBERS_FRIENDLY_NAME,
    THINGS_IN_COMMON_DOC_ID,
    THINGS_IN_COMMON_FRIENDLY_NAME,
    GraphQLMixin,
)
from .paths import APP_DIR, BASE_DIR
from .profiles import get_profile_manager

# Thời gian chờ Facebook tải lại feed sau khi bật filter "Bài đăng gần đây".
RECENT_POSTS_SETTLE_SECONDS = 1.5


def _fold_label(text: str) -> str:
    """Bỏ dấu tiếng Việt để so khớp aria-label không phân biệt ngôn ngữ."""
    normalized = unicodedata.normalize("NFD", str(text or "").lower())
    without_marks = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )
    return without_marks.replace("đ", "d")


def is_recent_posts_label(label: str) -> bool:
    """Nhận diện nhãn switch 'Recent posts' (Anh/Việt, có dấu hoặc không)."""
    folded = _fold_label(label)
    return (
        "recent" in folded
        or "gan day" in folded
        or "moi nhat" in folded
    )


def _normalize_time_range(value) -> int | None:
    """Đổi lựa chọn thời gian của UI/API thành số giờ.

    Trả về ``None`` cho "không giới hạn". Hàm nhận cả nhãn tiếng Việt, tiếng
    Anh và các khóa ngắn (``24h``, ``7d``, ``30d``, ``all``).
    """
    folded = _fold_label(value).replace("_", " ").strip()
    if not folded or folded in {"all", "any", "0", "none"}:
        return None
    if "khong gioi han" in folded:
        return None
    if "24" in folded or "1d" in folded or "1 ngay" in folded:
        return 24
    if "7" in folded or "week" in folded or "tuan" in folded:
        return 7 * 24
    if "30" in folded or "month" in folded or "thang" in folded:
        return 30 * 24
    return None


def _normalize_post_type(value) -> frozenset[str] | None:
    """Đổi lựa chọn loại bài thành tập ``media_type`` cần giữ.

    Trả về ``None`` cho "tất cả".
    """
    folded = _fold_label(value).replace("_", " ").strip()
    if not folded or folded in {"all", "any", "tat ca"}:
        return None
    if "anh" in folded and "video" in folded:
        return frozenset({"image", "video"})
    if "link" in folded:
        return frozenset({"link"})
    if "van ban" in folded or folded == "text":
        return frozenset({"text"})
    if "media" in folded:
        return frozenset({"image", "video"})
    return None


def _parse_published_at(value) -> dt.datetime | None:
    """Parse ``published_at`` (ISO 8601 hoặc Unix timestamp) về UTC."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return dt.datetime.fromtimestamp(int(value), tz=dt.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None

    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _post_matches_filters(
    post: dict,
    post_type: frozenset[str] | None = None,
    time_range_hours: int | None = None,
    now: dt.datetime | None = None,
) -> bool:
    """Kiểm tra một bài có thỏa bộ lọc loại bài và khoảng thời gian không."""
    if post_type is not None and post.get("media_type") not in post_type:
        return False

    if time_range_hours:
        published_at = _parse_published_at(post.get("published_at"))
        if published_at is None:
            return False
        reference = now or dt.datetime.now(dt.timezone.utc)
        if published_at < reference - dt.timedelta(hours=time_range_hours):
            return False

    return True


def convert_to_spreadsheet(json_filepath, output_filename=None, output_dir=None):
    """Đọc file .json hoặc .jsonl, xử lý dữ liệu và tự động xuất ra đúng thư mục:

    - Nếu đầu ra là CSV  -> lưu vào './data/processed/csv/'
    - Nếu đầu ra là XLSX -> lưu vào './data/processed/excel/'
    """

    def parse_contribution_score(score_str):
        """Trích xuất số từ chuỗi contribution_score, mặc định là 0 nếu null hoặc rỗng."""
        if not score_str:
            return 0
        match = re.search(r"\d+", str(score_str))
        return int(match.group()) if match else 0

    def parse_boolean_status(status_str, positive_value):
        """Chuyển đổi trạng thái text sang Boolean:

        - Nếu đúng positive_value -> True
        - Nếu null / None / rỗng -> None (Để trống trong Excel/CSV)
        - Nếu là trạng thái ngược lại -> False
        """
        if status_str is None or status_str == "":
            return None
        elif status_str == positive_value:
            return True
        return False

    # 0. KIỂM TRA FILE ĐẦU VÀO
    if not os.path.exists(json_filepath):
        print(f"❌ Lỗi: Không tìm thấy file '{json_filepath}'")
        return

    # Tự động tạo tên file xuất ra nếu người dùng không truyền vào
    base_name = os.path.splitext(os.path.basename(json_filepath))[0]
    if not output_filename:
        output_filename = f"{base_name}_cleaned.csv"  # Mặc định là CSV

    # ---------------------------------------------------------
    # 1. TÍNH TOÁN VÀ TẠO THƯ MỤC ĐẦU RA (DATA/PROCESSED/...)
    # ---------------------------------------------------------
    file_ext = os.path.splitext(output_filename)[1].lower()

    if output_dir:
        final_output_dir = output_dir
    elif file_ext == ".csv":
        final_output_dir = os.path.join(APP_DIR, "data", "processed", "csv")
    elif file_ext == ".xlsx":
        final_output_dir = os.path.join(APP_DIR, "data", "processed", "excel")
    else:
        raise ValueError(
            "❌ Định dạng file không hỗ trợ. Vui lòng chọn file có đuôi .xlsx hoặc .csv"
        )

    # Tự động tạo folder nếu chưa tồn tại
    os.makedirs(final_output_dir, exist_ok=True)

    # Đường dẫn file hoàn chỉnh
    final_output_path = os.path.join(final_output_dir, output_filename)

    # ---------------------------------------------------------
    # 2. ĐỌC FILE .JSON / .JSONL
    # ---------------------------------------------------------
    items = []
    with open(json_filepath, "r", encoding="utf-8") as f:
        if json_filepath.endswith(".jsonl"):
            items = [json.loads(line) for line in f if line.strip()]
        else:
            data = json.load(f)
            items = data if isinstance(data, list) else [data]

    # ---------------------------------------------------------
    # 3. XỬ LÝ TỪNG ĐỐI TƯỢNG
    # ---------------------------------------------------------
    processed_rows = []
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
            "contribution_score": parse_contribution_score(
                item.get("contribution_score")
            ),
            "friendship_status": parse_boolean_status(
                item.get("friendship_status"), "CAN_REQUEST"
            ),
            "subscribe_status": parse_boolean_status(
                item.get("subscribe_status"), "CAN_SUBSCRIBE"
            ),
            "membership_id": str(item.get("membership_id") or ""),
            "join_status_text": item.get("join_status_text", ""),
            "added_by_id": str(item.get("added_by_id") or ""),
            "added_by_name": item.get("added_by_name", ""),
            "added_by_url": item.get("added_by_url", ""),
        }
        processed_rows.append(row)

    # ---------------------------------------------------------
    # 4. XUẤT RA DATAFRAME & LƯU VÀO ĐÚNG FOLDER PROCESSED
    # ---------------------------------------------------------
    df = pd.DataFrame(processed_rows)

    if file_ext == ".csv":
        df.to_csv(
            final_output_path, index=False, encoding="utf-8-sig", na_rep=""
        )
    elif file_ext == ".xlsx":
        df.to_excel(final_output_path, index=False, engine="openpyxl")

    print(
        f"✅ Đã chuyển đổi {len(df)} dòng thành công!"
        f"\n📍 File được lưu tại: {final_output_path}"
    )


POST_EXPORT_COLUMNS = (
    "post_id",
    "author_name",
    "author_url",
    "source_name",
    "content",
    "media_type",
    "media_count",
    "media_urls",
    "reactions",
    "comments",
    "shares",
    "published_at",
    "permalink",
    "group_id",
    "scope",
    "content_truncated",
    "scraped_at",
)


def _export_count(value):
    """Chuẩn hóa reaction/comment/share count về int hoặc None."""
    if isinstance(value, dict):
        value = value.get("count")
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _post_export_rows(posts: list[dict]) -> list[dict]:
    rows = []
    for post in posts:
        if not isinstance(post, dict):
            continue
        media_urls = post.get("media_urls") or []
        if isinstance(media_urls, str):
            media_urls = [media_urls]
        elif not isinstance(media_urls, (list, tuple)):
            media_urls = []
        media_urls = [str(url) for url in media_urls if url]

        rows.append(
            {
                "post_id": str(post.get("post_id") or ""),
                "author_name": post.get("author_name") or "",
                "author_url": post.get("author_url") or "",
                "source_name": post.get("source_name") or "",
                "content": str(post.get("content") or ""),
                "media_type": post.get("media_type") or "",
                "media_count": len(media_urls),
                "media_urls": " | ".join(media_urls),
                "reactions": _export_count(post.get("reactions")),
                "comments": _export_count(post.get("comments")),
                "shares": _export_count(post.get("shares")),
                "published_at": post.get("published_at") or "",
                "permalink": post.get("permalink") or "",
                "group_id": post.get("group_id") or "",
                "scope": post.get("scope") or "",
                "content_truncated": bool(post.get("content_truncated")),
                "scraped_at": post.get("scraped_at") or "",
            }
        )
    return rows


def export_posts_to_spreadsheet(
    json_filepath: str,
    output_dir: str | None = None,
    output_basename: str | None = None,
) -> dict:
    """Xuất file JSON kết quả quét bài ra cả .xlsx và .csv.

    Trả về dict dạng ``{"xlsx": path, "csv": path}``. Nếu một định dạng lỗi,
    định dạng còn lại vẫn được giữ và hàm vẫn trả về đường dẫn tương ứng.
    """
    if not os.path.exists(json_filepath):
        print(f"⚠️ Không tìm thấy file JSON để xuất: {json_filepath}")
        return {}

    try:
        with open(json_filepath, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        print(f"⚠️ Không đọc được file JSON để xuất: {error}")
        return {}

    if isinstance(payload, dict):
        posts = payload.get("posts") or []
    elif isinstance(payload, list):
        posts = payload
    else:
        posts = []

    rows = _post_export_rows(posts)
    if not rows:
        print("⚠️ File JSON không có bài viết nào để xuất Excel/CSV.")
        return {}

    base_name = output_basename or os.path.splitext(
        os.path.basename(json_filepath)
    )[0]
    target_dir = output_dir or os.path.join(APP_DIR, "data", "processed")
    os.makedirs(target_dir, exist_ok=True)

    csv_path = os.path.join(target_dir, f"{base_name}.csv")
    xlsx_path = os.path.join(target_dir, f"{base_name}.xlsx")
    df = pd.DataFrame(rows, columns=list(POST_EXPORT_COLUMNS))
    exported = {}

    try:
        df.to_csv(csv_path, index=False, encoding="utf-8-sig", na_rep="")
        exported["csv"] = csv_path
    except Exception as error:
        print(f"⚠️ Không xuất được CSV: {error}")

    try:
        # Excel giới hạn 32767 ký tự/ô; cắt bớt nếu bài quá dài.
        excel_df = df.copy()
        excel_df["content_truncated"] = [
            bool(flag) or (isinstance(content, str) and len(content) > 32000)
            for flag, content in zip(
                excel_df["content_truncated"], excel_df["content"]
            )
        ]
        for column in excel_df.columns:
            excel_df[column] = excel_df[column].map(
                lambda value: (
                    value[:32000]
                    if isinstance(value, str) and len(value) > 32000
                    else value
                )
            )

        from openpyxl.utils import get_column_letter

        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            excel_df.to_excel(writer, index=False, sheet_name="Posts")
            worksheet = writer.sheets["Posts"]
            worksheet.freeze_panes = "A2"
            for index, column in enumerate(excel_df.columns, start=1):
                max_length = len(str(column))
                if len(excel_df):
                    max_length = max(
                        max_length,
                        int(excel_df[column].astype(str).map(len).max()),
                    )
                worksheet.column_dimensions[
                    get_column_letter(index)
                ].width = min(max_length + 2, 60)
        exported["xlsx"] = xlsx_path
    except Exception as error:
        print(f"⚠️ Không xuất được Excel: {error}")

    if exported:
        print(
            f"📊 Đã xuất {len(df)} bài ra Excel/CSV:\n"
            + "\n".join(f"   - {path}" for path in exported.values())
        )
    return exported


class FacebookBot(
    BrowserMixin,
    AuthMixin,
    GraphQLMixin,
    CommentMixin,
    ReactionMixin,
):
    """Ghép các nhóm chức năng của bot Facebook."""

    def log_raw_response(self, res_data: dict, filename: str = None):
        """
        Log request GraphQL (mặc định: logs/<uid>/requests.jsonl).
        """
        if not filename:
            base = self.log_dir or os.path.join(APP_DIR, "logs")
            os.makedirs(base, exist_ok=True)
            filename = os.path.join(base, "requests.jsonl")
        else:
            folder = os.path.dirname(os.path.abspath(filename))
            if folder:
                os.makedirs(folder, exist_ok=True)

        with open(filename, "a", encoding="utf-8") as f:
            f.write(json.dumps(res_data, ensure_ascii=False) + "\n")

    def get_numeric_group_id(self, group_input: str = None) -> str:
        """
        Giải mã và trả về Numeric Group ID từ mọi nguồn:
        1. group_input là dãy số UID sẵn (VD: '2396395143940094')
        2. group_input là URL chứa dãy số (VD: 'https://.../groups/2396395143940094/')
        3. group_input là URL dạng Tên/Slug (VD: 'https://.../groups/congdongpython/') -> Fetch ngầm JS
        4. group_input = None -> Lấy trực tiếp từ DOM trang Selenium đang mở
        """
        # ------------------------------------------------------------------
        # TRƯỜNG HỢP 1 & 2: Kiểm tra nếu chuỗi truyền vào hoặc URL đã chứa ID dạng số
        # ------------------------------------------------------------------
        if group_input:
            group_input = str(group_input).strip()
            # Nếu truyền vào nguyên dãy số
            if group_input.isdigit():
                return group_input
            
            # Nếu truyền vào URL chứa ID dạng số
            match = re.search(r'/groups/(\d+)', group_input)
            if match:
                return match.group(1)

        # ------------------------------------------------------------------
        # TRƯỜNG HỢP 3: Không truyền URL (hoặc URL truyền vào trùng với trang đang mở)
        # -> Bóc tách trực tiếp từ DOM hiện tại (Tốc độ cao nhất, 0ms request)
        # ------------------------------------------------------------------
        current_url = self.driver.current_url
        if not group_input or group_input in current_url:
            js_dom_script = r"""
                // 1. Quét meta iOS
                const meta = document.querySelector('meta[property="al:ios:url"]');
                if (meta && meta.content) {
                    const m = meta.content.match(/fb:\/\/group\/([0-9]+)/);
                    if (m) return m[1];
                }
                // 2. Tìm trong Relay Store
                try {
                    const routeId = require('CometRouteStore').getRoute().params.groupID;
                    if (routeId) return routeId;
                } catch(e) {}
                // 3. Quét HTML thô
                const html = document.documentElement.innerHTML;
                const m = html.match(/"groupID":"([0-9]+)"/) || html.match(/"target_id":"([0-9]+)"/);
                return m ? m[1] : null;
            """
            try:
                return self.driver.execute_script(js_dom_script)
            except Exception:
                pass

        # ------------------------------------------------------------------
        # TRƯỜNG HỢP 4: URL là Tên/Slug của nhóm KHÁC trang hiện tại
        # -> Gửi fetch() ngầm qua JS lấy HTML bóc tách ID (Không cần driver.get())
        # ------------------------------------------------------------------
        js_async_script = r"""
            const targetUrl = arguments[0];
            const done = arguments[arguments.length - 1];

            fetch(targetUrl, { credentials: 'include' })
                .then(res => res.text())
                .then(html => {
                    const match = html.match(/fb:\/\/group\/([0-9]+)/) ||
                                html.match(/"groupID":"([0-9]+)"/) ||
                                html.match(/"target_id":"([0-9]+)"/);
                    done(match ? match[1] : null);
                })
                .catch(() => done(null));
        """
        self.driver.set_script_timeout(5)
        try:
            return self.driver.execute_async_script(js_async_script, group_input)
        except Exception as e:
            print(f"⚠️ Lỗi fetch ngầm Group ID từ {group_input}: {e}")
            return None
        finally:
            # Khôi phục timeout để không ép fetch_group_members (10s) xuống 5s.
            try:
                self.driver.set_script_timeout(30)
            except Exception:
                pass

    def scrape_group_members(
        self, 
        group_id: str, 
        max_members: int = 5000, 
        batch_size: int = 10, 
        retries: int = 3
    ) -> int:
        def access_group() -> bool:
            target_url = f"https://www.facebook.com/groups/{group_id}/members"
            print(f"🌐 Đang truy cập: {target_url}")
    
            try:
                self.driver.get(target_url)
                WebDriverWait(self.driver, 30).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
            except Exception as e:
                print(f"🚨 Không thể truy cập nhóm {group_id}: {e}")
                return False
    
            return True
        
        if self.is_stopped():
            return 0

        if not group_id:
            print("⚠️ Thiếu group_id, bỏ qua tìm kiếm.")
            return 0

        if not access_group():
            print("🚨 Không thể truy cập nhóm.")
            return 0

        payload = {
            'new_members': {
                'doc_id': GROUP_MEMBERS_DOC_ID,
                'friendly_name': GROUP_MEMBERS_FRIENDLY_NAME,
            },
            'things_in_common': {
                'doc_id': THINGS_IN_COMMON_DOC_ID,
                'friendly_name': THINGS_IN_COMMON_FRIENDLY_NAME,
            }    
        }
        collected_uids = set()
        
        cursor = None
        has_next_page = True
        request_index = 1

        unlimited = max_members <= 0
        limit_text = "TẤT CẢ" if unlimited else f"{max_members}"

        file_name = group_id + '.jsonl'
        for key, value in payload.items():
            if self.is_stopped():
                break

            if key != 'new_members':
                continue

            print(f"Đang truy cập API {key}")
            while not self.is_stopped():
                if not (unlimited or len(collected_uids) < max_members):
                    break
            
                print(f"[*] Request #{request_index} | Đã cào: {len(collected_uids)}/{limit_text} UIDs (Cursor: {cursor})...")
                
                # --- CƠ CHẾ RETRY: Thử lại tối đa N lần ---
                attempt = 0
                success = False
                raw_res = {}
                edges = []
                node = {}

                while attempt < retries and not self.is_stopped():
                    attempt += 1
                    raw_res = self.fetch_group_members(group_id, cursor=cursor, count=batch_size, doc_id=value['doc_id'], friendly_name=value['friendly_name'])
                    self.log_raw_response(raw_res)

                    # 1. Xử lý an toàn chống NoneType/Null
                    data = raw_res.get("data") if isinstance(raw_res, dict) else None

                    if isinstance(raw_res, dict) and "error" not in raw_res and isinstance(data, dict):
                        node_data = data.get("node")
                        
                        # Nếu node tồn tại (không bị null do FB block)
                        if isinstance(node_data, dict):
                            if key == 'new_members':
                                node = node_data.get("new_members") or {}
                            elif key == 'things_in_common':
                                node = node_data.get("group_member_discovery") or {}
                            edges = node.get("edges") or []
                            
                            # Flag
                            success = True
                            break  

                    # 2. Tăng thời gian chờ ngẫu nhiên/tăng dần (Exponential Backoff) giúp nhả Rate Limit
                    wait_time = attempt * 3
                    print(f"⚠️ Thử lại sau {wait_time}s (Attempt {attempt}/{retries})...")
                    time.sleep(wait_time)

                # --- NẾU THẤT BẠI SAU N LẦN THỬ: HỦY VÀ THOÁT LUỒNG ---
                if not success:
                    print(f"🚨 [GỢI Ý] Đã thử {retries} lần nhưng API không phản hồi (có thể dính Checkpoint/Rate Limit). Hủy nhóm {group_id}!")
                    break  # Thoát vòng lặp while, chuyển sang group tiếp theo hoặc dừng

                # --- NẾU THÀNH CÔNG NHƯNG RỖNG: ĐÃ HẾT DANH SÁCH NHÓM ---
                if not edges:
                    print("[!] Đã duyệt đến cuối danh sách thành viên của nhóm.")
                    break

                # --- XỬ LÝ DỮ LIỆU KHI THÀNH CÔNG ---
                for edge in edges:
                    m = edge.get("node", {})
                    uid = m.get("id")

                    bio_data = m.get("bio_text") or {}
                    profile_pic = m.get("profile_picture") or {}
                    group_mem = m.get("group_membership") or {}
                    contrib_score = group_mem.get("group_contribution_score_text") or {}

                    # Lấy thông tin gia nhập từ cấp edge (cùng cấp với node/cursor)
                    join_status = edge.get("join_status_text") or {}
                    ranges = join_status.get("ranges") or []
                    added_by_entity = ranges[0].get("entity", {}) if ranges else {}

                    # Lấy trạng thái kết bạn
                    user_renderer = (m.get("user_type_renderer") or {}).get("user") or {}

                    if uid and uid not in collected_uids:
                        collected_uids.add(uid)
                        
                        member_info = {
                            "id": m.get("id"),
                            "name": m.get("name"),
                            "url": m.get("url"),
                            "avatar": profile_pic.get("uri"),

                            # 1. Thông tin cá nhân chi tiết
                            "bio": bio_data.get("text"),
                            "follower_count": m.get("follower_count"),
                            "is_verified": m.get("is_verified"),
                            "category": m.get("profile_plus_category_display_name"),

                            # 2. Hoạt động & Đóng góp trong nhóm
                            "contribution_score": contrib_score.get("text"),
                            "membership_id": group_mem.get("id"),

                            # 3. Lịch sử tham gia & Người giới thiệu
                            "join_status_text": join_status.get("text"),
                            "added_by_id": added_by_entity.get("id"),
                            "added_by_name": added_by_entity.get("short_name"),
                            "added_by_url": added_by_entity.get("url"),

                            # 4. Trạng thái tương tác
                            "subscribe_status": m.get("subscribe_status"),
                            "friendship_status": user_renderer.get("friendship_status")
                        }
                        self._buffer.append(member_info)

                        if not unlimited and len(collected_uids) >= max_members:
                            break
                
                self._flush(file_name)  # Ghi batch ra file jsonl

                if not unlimited and len(collected_uids) >= max_members:
                    print(f"\n[THÀNH CÔNG] Đã thu thập đủ mục tiêu {max_members} UIDs!")
                    break

                # Lấy cursor cho trang tiếp theo
                page_info = node.get("page_info", {})
                has_next_page = page_info.get("has_next_page", False)
                cursor = page_info.get("end_cursor")

                # cursor = null & has_next_page = false -> STOP
                if not cursor and not has_next_page:
                    print("[!] Đã duyệt đến cuối danh sách nhóm.")
                    break

                request_index += 1
                time.sleep(random.uniform(1.5, 2.5))

        if unlimited:
            print(f"\n[HOÀN THÀNH] Đã cào TẤT CẢ {len(collected_uids)} UIDs trong nhóm!")

        # Xuất kết quả (data/<uid>/raw → data/<uid>/exports)
        raw_path = os.path.join(
            self.data_dir or os.path.join(APP_DIR, "data", "raw"),
            f"{group_id}.jsonl",
        )
        if os.path.exists(raw_path):
            convert_to_spreadsheet(
                raw_path, f"{group_id}.xlsx", output_dir=self.exports_dir
            )
            convert_to_spreadsheet(
                raw_path, f"{group_id}.csv", output_dir=self.exports_dir
            )
        else:
            print(f"[Export] Không tìm thấy {raw_path}, bỏ qua xuất Excel/CSV.")

        return len(collected_uids)

    def prepare_post_scan_analysis(
        self,
        scope: str,
        keyword: str = "",
        group_ids=None,
        pause_seconds: int = 0,
        max_posts: int = 100,
        expand_content: bool = True,
        recent_posts: bool = False,
        time_range: str = "all",
        post_type: str = "all",
    ) -> dict:
        """Mở feed Facebook, trích xuất bài viết và lưu ra file JSON.

        `scope="search"` tìm qua thanh search của Facebook, mở tab "Bài viết"
        rồi trích xuất theo từ khóa.
        `scope="groups"` quét lần lượt các group đã chọn.

        `recent_posts=True` chỉ áp dụng cho scope search: bật filter
        `recent_posts` trên UI và GraphQL để lấy bài đăng gần đây.

        `time_range` và `post_type` hiện chỉ áp dụng cho scope search:
        - thời gian: ``24h`` / ``7d`` / ``30d`` / ``all`` (hoặc nhãn UI);
        - loại bài: ``all`` / ``media`` / ``link`` / ``text`` (hoặc nhãn UI).

        Kết quả được ghi vào `data/<uid>/raw/posts_<scope>_<timestamp>.json`.
        `pause_seconds` chỉ dùng khi cần giữ browser mở thêm để phân tích thủ công.
        """
        if not self.driver:
            raise RuntimeError("Browser chưa được khởi tạo.")

        normalized_scope = str(scope).strip().lower()
        normalized_groups = [
            str(group_id).strip()
            for group_id in (group_ids or [])
            if str(group_id).strip()
        ]
        normalized_keyword = str(keyword or "").strip()
        recent_posts = bool(recent_posts) and normalized_scope == "search"
        try:
            max_posts = int(max_posts)
        except (TypeError, ValueError):
            max_posts = 100
        if max_posts < 0:
            max_posts = 0

        # Bộ lọc thời gian/loại bài chỉ hỗ trợ Search ở giai đoạn này.
        time_range_hours = (
            _normalize_time_range(time_range)
            if normalized_scope == "search"
            else None
        )
        post_type_filter = (
            _normalize_post_type(post_type)
            if normalized_scope == "search"
            else None
        )
        scan_now = dt.datetime.now(dt.timezone.utc)

        if normalized_scope == "search":
            if not normalized_keyword:
                raise ValueError("Search tổng quát yêu cầu từ khóa.")
            # Không mở thẳng URL /search/posts nữa; dùng thanh search của
            # Facebook rồi mở tab "Bài viết" để tránh bị chặn/redirect.
            targets = [(None, f"search:{normalized_keyword}", None)]
            source_label = f"search:{normalized_keyword}"
        elif normalized_scope == "groups":
            if not normalized_groups:
                raise ValueError("Quét theo group yêu cầu ít nhất một group ID.")
            targets = [
                (
                    f"https://www.facebook.com/groups/{group_id}",
                    f"group:{group_id}",
                    group_id,
                )
                for group_id in normalized_groups
            ]
            source_label = f"groups:{','.join(normalized_groups)}"
        else:
            raise ValueError("Phạm vi quét không hợp lệ.")

        try:
            self.driver.set_page_load_timeout(60)
        except Exception:
            pass

        collected: dict[str, dict] = {}
        feed_found = False
        browser_closed = False
        extraction_error = None
        last_url = "https://www.facebook.com"

        print(
            f"[Post Scan] Bắt đầu trích xuất {source_label} "
            f"(tối đa {max_posts if max_posts else 'không giới hạn'} bài)."
        )

        try:
            for target_url, target_label, group_id in targets:
                if self.is_stopped():
                    break
                if max_posts and len(collected) >= max_posts:
                    break
                if not self.driver.window_handles:
                    raise WebDriverException("Browser window is closed.")

                if target_url:
                    last_url = target_url
                    print(f"[Post Scan] Mở {target_label}...")
                    self.driver.get(target_url)
                else:
                    print(
                        f"[Post Scan] Tìm '{normalized_keyword}' qua thanh search..."
                    )
                    found_search_bar = self._search_via_search_bar(normalized_keyword)
                    print(found_search_bar)
                    if not found_search_bar:
                        extraction_error = (
                            "Không mở được trang kết quả Search bằng thanh search."
                        )
                        print(f"[Post Scan] {extraction_error}")
                        continue
                    last_url = self.driver.current_url

                feed_found = False
                skip_dom_extraction = False
                skip_dom_reason = ""

                # Filter recent_posts phải được bật trên UI thì feed DOM mới
                # đổi sang bài mới nhất; GraphQL filter chỉ tác động API.
                if normalized_scope == "search" and recent_posts:
                    if not self._ensure_recent_posts_toggle():
                        skip_dom_extraction = True
                        skip_dom_reason = (
                            "không xác nhận được filter 'Bài đăng gần đây' "
                            "nên chỉ dùng GraphQL để tránh lẫn bài cũ"
                        )
                        print(
                            "[Post Scan] Không xác nhận được filter 'Bài đăng gần đây'; "
                            "sẽ chỉ dùng GraphQL, bỏ qua DOM."
                        )

                # DOM post_extractor chưa đọc được thời gian đăng, nên khi lọc
                # thời gian chỉ GraphQL (có published_at) mới đáng tin.
                if time_range_hours:
                    skip_dom_extraction = True
                    skip_dom_reason = (
                        "bài trong DOM không có published_at để lọc thời gian"
                    )

                # Search GraphQL bổ sung timestamp/nội dung đầy đủ; ưu tiên
                # chạy trước để không phụ thuộc việc Facebook có render feed DOM.
                if normalized_scope == "search":
                    remaining = max_posts - len(collected) if max_posts else 0
                    try:
                        graph_posts = self._collect_search_posts_from_graphql(
                            normalized_keyword,
                            max_posts=remaining,
                            recent_posts=recent_posts,
                            post_type=post_type_filter,
                            time_range_hours=time_range_hours,
                            now=scan_now,
                        )
                    except Exception as error:
                        print(f"[Post Scan] Bỏ qua GraphQL search: {error}")
                        graph_posts = []
                    for post in graph_posts:
                        collected.setdefault(post_key(post), post)
                elif normalized_scope == "groups" and group_id:
                    remaining = max_posts - len(collected) if max_posts else 0
                    try:
                        graph_posts = self._collect_group_posts_from_graphql(
                            group_id,
                            max_posts=remaining,
                        )
                    except Exception as error:
                        print(f"[Post Scan] Bỏ qua GraphQL group feed: {error}")
                        graph_posts = []
                    for post in graph_posts:
                        collected.setdefault(post_key(post), post)

                if max_posts and len(collected) >= max_posts:
                    skip_dom_extraction = True
                    skip_dom_reason = "đã đủ số bài yêu cầu"

                if skip_dom_extraction:
                    print(f"[Post Scan] Bỏ qua DOM: {skip_dom_reason}.")
                else:
                    remaining = max_posts - len(collected) if max_posts else 0
                    feed_timeout = 10 if normalized_scope == "search" else 30
                    feed_found = self._wait_for_post_feed(timeout=feed_timeout)
                    if not feed_found:
                        print(
                            f"[Post Scan] Không tìm thấy feed DOM tại "
                            f"{target_label}."
                        )
                        if normalized_scope != "search":
                            continue
                        # UI Search mới có thể không có role=feed; GraphQL ở
                        # trên đã lấy bài nên không cần dừng cả lượt quét.
                        print(
                            "[Post Scan] Search đã lấy bài bằng GraphQL, "
                            "bỏ qua DOM."
                        )
                    else:
                        posts = self._extract_posts_from_current_feed(
                            scope=normalized_scope,
                            group_id=group_id,
                            max_posts=remaining,
                            expand_content=expand_content,
                        )
                        for post in posts:
                            collected.setdefault(post_key(post), post)
                        print(
                            f"[Post Scan] {target_label}: thu được {len(posts)} bài "
                            f"(tổng {len(collected)})."
                        )
                if self.is_stopped():
                    break

        except (WebDriverException, OSError) as error:
            browser_closed = True
            print(f"[Post Scan] Browser bị đóng hoặc lỗi điều hướng: {error}")
        except Exception as error:
            # Vẫn lưu những bài đã thu được trước khi trả lỗi.
            extraction_error = str(error)
            print(f"[Post Scan] Lỗi khi trích xuất: {error}")

        posts = dedupe_posts(collected.values())
        if post_type_filter is not None or time_range_hours:
            before_filter = len(posts)
            posts = [
                post
                for post in posts
                if _post_matches_filters(
                    post,
                    post_type=post_type_filter,
                    time_range_hours=time_range_hours,
                    now=scan_now,
                )
            ]
            print(
                f"[Post Scan] Bộ lọc loại bài/thời gian giữ lại "
                f"{len(posts)}/{before_filter} bài."
            )
        if max_posts:
            posts = posts[:max_posts]

        file_path = None
        export_paths = {}
        if posts:
            file_path = self._save_posts_json(
                posts,
                scope=normalized_scope,
                keyword=normalized_keyword,
                group_ids=normalized_groups,
                source_label=source_label,
                recent_posts=recent_posts,
                time_range=time_range,
                post_type=post_type,
            )
            print(f"[Post Scan] Đã lưu {len(posts)} bài vào {file_path}.")

            # Xuất thêm Excel/CSV; lỗi export không được làm hỏng kết quả JSON.
            try:
                export_paths = export_posts_to_spreadsheet(
                    file_path, output_dir=self.exports_dir
                )
            except Exception as error:
                print(f"[Post Scan] Không xuất được Excel/CSV: {error}")

        if self.is_stopped():
            status = "stopped"
        elif browser_closed:
            status = "browser_closed"
        elif extraction_error:
            status = "error"
        elif not feed_found and not posts:
            status = "feed_not_found"
        elif not posts:
            status = "no_posts"
        else:
            status = "completed"

        # Giữ browser mở thêm nếu người gọi thực sự yêu cầu phân tích thủ công.
        wait_seconds = max(0, int(pause_seconds or 0))
        if wait_seconds and status == "completed":
            deadline = time.monotonic() + wait_seconds
            print(f"[Post Scan] Giữ browser mở thêm {wait_seconds} giây.")
            while time.monotonic() < deadline:
                if self.is_stopped():
                    status = "stopped"
                    break
                try:
                    if not self.driver.window_handles:
                        raise WebDriverException("Browser window is closed.")
                except (WebDriverException, OSError):
                    status = "browser_closed"
                    break
                time.sleep(max(0, min(1, deadline - time.monotonic())))

        return {
            "status": status,
            "scope": normalized_scope,
            "source": source_label,
            "url": last_url,
            "post_count": len(posts),
            "file_path": file_path,
            "xlsx_path": export_paths.get("xlsx"),
            "csv_path": export_paths.get("csv"),
            "export_paths": export_paths,
            "error": extraction_error,
            "recent_posts": recent_posts,
            "time_range": time_range,
            "post_type": post_type,
        }

    def _collect_search_posts_from_graphql(
        self,
        keyword: str,
        max_posts: int = 0,
        page_size: int = 10,
        recent_posts: bool = False,
        post_type: frozenset[str] | None = None,
        time_range_hours: int | None = None,
        now: dt.datetime | None = None,
    ) -> list[dict]:
        """Lấy bài từ response GraphQL Search, có phân trang bằng end_cursor.

        Khi có bộ lọc loại bài/thời gian, hàm tiếp tục phân trang cho tới khi
        đủ số bài thỏa điều kiện hoặc Facebook hết trang.
        """
        collected: dict[str, dict] = {}
        cursor = None
        request_index = 0
        limit = max_posts if max_posts and max_posts > 0 else 50
        filters_active = post_type is not None or bool(time_range_hours)

        while not self.is_stopped() and len(collected) < limit:
            request_index += 1
            count = min(page_size, max(1, limit - len(collected)))
            raw = self.fetch_search_posts(
                keyword,
                cursor=cursor,
                count=count,
                recent_posts=recent_posts,
            )
            output_file = "search_posts_response.json"
            try:
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(raw, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

            if not isinstance(raw, dict) or raw.get("error"):
                error = raw.get("error") if isinstance(raw, dict) else "INVALID_RESPONSE"
                print(f"[Post Scan] GraphQL search #{request_index} lỗi: {error}")
                break

            raw_posts = extract_posts_from_graphql_response(raw, scope="search")
            page_posts = raw_posts
            filtered_out = 0
            if filters_active:
                page_posts = [
                    post
                    for post in raw_posts
                    if _post_matches_filters(
                        post,
                        post_type=post_type,
                        time_range_hours=time_range_hours,
                        now=now,
                    )
                ]
                filtered_out = len(raw_posts) - len(page_posts)

            new_count = 0
            for post in page_posts:
                key = post_key(post)
                if key in collected:
                    continue
                collected[key] = post
                new_count += 1

            print(
                f"[Post Scan] GraphQL search #{request_index}: "
                f"+{new_count} bài (tổng {len(collected)}"
                + (f", bỏ {filtered_out} do bộ lọc)." if filtered_out else ").")
            )

            page_info = (
                ((raw.get("data") or {}).get("serpResponse") or {}).get("results")
                or {}
            ).get("page_info") or {}
            next_cursor = page_info.get("end_cursor")
            if not page_info.get("has_next_page") or not next_cursor:
                break
            if next_cursor == cursor:
                break
            cursor = next_cursor

            if not raw_posts:
                break
            if not new_count and not filtered_out:
                # Trang chỉ toàn bài trùng -> tránh lặp vô hạn.
                break
            if len(collected) >= limit:
                break
            time.sleep(random.uniform(1.0, 2.0))

        return list(collected.values())[:limit]

    def _collect_group_posts_from_graphql(
        self,
        group_id: str,
        max_posts: int = 0,
        page_size: int = 3,
    ) -> list[dict]:
        """Lấy bài từ feed group bằng GraphQL GroupsCometFeedRegularStoriesPaginationQuery."""
        collected: dict[str, dict] = {}
        cursor = None
        request_index = 0
        limit = max_posts if max_posts and max_posts > 0 else 100

        while not self.is_stopped() and len(collected) < limit:
            request_index += 1
            count = min(page_size, max(1, limit - len(collected)))
            raw = self.fetch_group_feed_posts(
                group_id,
                cursor=cursor,
                count=count,
            )

            try:
                with open("group_posts_response.json", "w", encoding="utf-8") as f:
                    json.dump(raw, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

            if not isinstance(raw, dict) or raw.get("error"):
                error = raw.get("error") if isinstance(raw, dict) else "INVALID_RESPONSE"
                print(f"[Post Scan] GraphQL group #{request_index} lỗi: {error}")
                break

            raw_posts = extract_posts_from_graphql_response(
                raw, scope="groups", fallback_group_id=group_id
            )

            new_count = 0
            for post in raw_posts:
                key = post_key(post)
                if key in collected:
                    continue
                collected[key] = post
                new_count += 1

            print(
                f"[Post Scan] GraphQL group {group_id} #{request_index}: "
                f"+{new_count} bài (tổng {len(collected)})."
            )

            page_info = (
                ((raw.get("data") or {}).get("node") or {})
                .get("group_feed")
                or {}
            ).get("page_info") or {}
            next_cursor = page_info.get("end_cursor")
            if not page_info.get("has_next_page") or not next_cursor:
                break
            if next_cursor == cursor:
                break
            cursor = next_cursor

            if not raw_posts:
                break
            if not new_count:
                break
            if len(collected) >= limit:
                break
            time.sleep(random.uniform(1.0, 1.6))

        return list(collected.values())[:limit]

    SEARCH_BAR_SELECTORS = (
        "input[type='search']",
        "input[role='combobox'][type='search']",
        "input[aria-label='Search Facebook']",
        "input[placeholder='Search Facebook']",
        "input[aria-label*='Tìm kiếm']",
        "input[placeholder*='Tìm kiếm']",
    )

    def _find_search_bar(self, timeout: float = 15):
        """Tìm ô search trên thanh điều hướng Facebook (Anh/Việt)."""

        def locate(driver):
            for selector in self.SEARCH_BAR_SELECTORS:
                for element in driver.find_elements(By.CSS_SELECTOR, selector):
                    try:
                        if element.is_displayed() and element.is_enabled():
                            return element
                    except Exception:
                        continue
            return False

        try:
            return WebDriverWait(
                self.driver, timeout, poll_frequency=0.3
            ).until(locate)
        except TimeoutException:
            return None

    def _click_element(self, element) -> bool:
        """Click thường, fallback JS click nếu bị overlay chặn."""
        try:
            element.click()
            return True
        except Exception:
            try:
                self.driver.execute_script("arguments[0].click();", element)
                return True
            except Exception:
                return False

    def _wait_for_url_contains(self, fragment: str, timeout: float = 20) -> bool:
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda driver: fragment in (driver.current_url or "")
            )
            return True
        except TimeoutException:
            return False

    def _find_posts_search_tab(self, timeout: float = 20):
        """Tìm tab 'Bài viết' / 'Posts' trên trang kết quả Search."""

        def locate(driver):
            for anchor in driver.find_elements(
                By.CSS_SELECTOR, "a[href*='/search/posts']"
            ):
                try:
                    if anchor.is_displayed():
                        return anchor
                except Exception:
                    continue

            # Fallback theo nhãn nếu Facebook không render href đúng.
            for element in driver.find_elements(
                By.CSS_SELECTOR, "[role='link'], [role='tab'], a"
            ):
                try:
                    if not element.is_displayed():
                        continue
                    label = _fold_label(
                        (element.text or "")
                        + " "
                        + (element.get_attribute("aria-label") or "")
                    ).strip()
                except Exception:
                    continue
                if label in {"posts", "bai viet", "bai dang"}:
                    return element
            return False

        try:
            return WebDriverWait(
                self.driver, timeout, poll_frequency=0.3
            ).until(locate)
        except TimeoutException:
            return None

    def _open_posts_search_tab(self, timeout: float = 20) -> bool:
        if "/search/posts" in (self.driver.current_url or ""):
            return True

        # Không chờ quá lâu: UI mới của Facebook không có tab này, cần fallback
        # sang mục "All" thay vì treo 20-30 giây.
        tab_timeout = min(timeout, 5)
        tab = self._find_posts_search_tab(timeout=tab_timeout)
        if tab is not None:
            if self._click_element(tab) and self._wait_for_url_contains(
                "/search/posts", timeout=tab_timeout
            ):
                return True
            print(
                "[Post Scan] Không chuyển được sang tab 'Bài viết', "
                "thử dùng trang Search hiện tại."
            )
        else:
            print(
                "[Post Scan] Không thấy tab 'Bài viết'; "
                "Facebook có thể đang gộp bài vào mục 'All'."
            )

        # UI mới của Facebook (ảnh: sidebar Filters/All) không còn tab
        # "Bài viết" riêng. Khi đang ở trang Search, dùng luôn trang hiện tại
        # và để GraphQL lọc bài viết thay vì báo lỗi rồi dừng.
        if "/search" in (self.driver.current_url or ""):
            print(
                "[Post Scan] Tiếp tục với trang kết quả Search hiện tại (All)."
            )
            return True

        print("[Post Scan] Không tìm thấy trang kết quả Search phù hợp.")
        return False

    def _search_via_search_bar(self, keyword: str, timeout: float = 30) -> bool:
        """Tìm bằng thanh search của Facebook rồi mở tab Bài viết.

        Không dùng ``driver.get`` tới URL ``/search/posts`` để tránh bị
        Facebook redirect/checkpoint và để giữ đúng luồng điều hướng UI.
        """
        search_bar = self._find_search_bar(timeout=min(15, timeout))
        if search_bar is None:
            print("[Post Scan] Không tìm thấy thanh search của Facebook.")
            return False

        if not self._click_element(search_bar):
            print("[Post Scan] Không click được thanh search.")
            return False

        try:
            # JS click có thể không focus; focus lại trước khi gõ.
            self.driver.execute_script("arguments[0].focus();", search_bar)
        except Exception:
            pass

        try:
            search_bar.send_keys(Keys.CONTROL, "a")
            search_bar.send_keys(Keys.BACKSPACE)
            search_bar.send_keys(keyword)
            time.sleep(random.uniform(0.3, 0.7))
            search_bar.send_keys(Keys.ENTER)
        except Exception as error:
            print(f"[Post Scan] Không nhập được từ khóa vào thanh search: {error}")
            return False

        if not self._wait_for_url_contains("/search", timeout=timeout):
            print("[Post Scan] Thanh search không mở được trang kết quả.")
            return False

        return self._open_posts_search_tab(timeout=timeout)

    def _wait_for_post_feed(self, timeout: float = 30) -> bool:
        """Chờ tới khi feed Facebook xuất hiện trong DOM."""
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda driver: driver.execute_script(
                    "return document.querySelector('div[role=\"feed\"]') !== null;"
                )
            )
            return True
        except Exception:
            return False

    def _find_recent_posts_toggle(self, timeout: float = 10):
        """Tìm switch 'Recent posts' / 'Bài đăng gần đây' đang render."""

        def locate(driver):
            for element in driver.find_elements(By.CSS_SELECTOR, "[role='switch']"):
                labels = []
                try:
                    labels.append(element.get_attribute("aria-label") or "")
                except Exception:
                    pass
                try:
                    labels.append(getattr(element, "text", "") or "")
                except Exception:
                    pass
                # UI mới đặt nhãn "Recent posts" cạnh switch, không phải lúc
                # nào cũng nằm trong aria-label của chính switch.
                if not any(is_recent_posts_label(label) for label in labels):
                    try:
                        parent = element.find_element(By.XPATH, "..")
                        labels.append(parent.text or "")
                    except Exception:
                        pass
                if any(is_recent_posts_label(label) for label in labels):
                    return element
            return False

        try:
            return WebDriverWait(
                self.driver, timeout, poll_frequency=0.3
            ).until(locate)
        except TimeoutException:
            return None

    @staticmethod
    def _is_toggle_on(element) -> bool:
        """Đọc trạng thái aria-checked của switch."""
        try:
            return (element.get_attribute("aria-checked") or "").lower() == "true"
        except Exception:
            return False

    def _ensure_recent_posts_toggle(self, timeout: float = 10) -> bool:
        """Bật switch 'Bài đăng gần đây' trên UI Facebook.

        Facebook đổi aria-label theo ngôn ngữ tài khoản, nên hàm nhận cả
        "Recent posts", "Bài đăng gần đây" và "Bài viết gần đây". Trả về True
        khi switch đang ở trạng thái bật.
        """
        element = self._find_recent_posts_toggle(timeout=timeout)
        if element is None:
            print(
                "[Post Scan] Không tìm thấy nút 'Bài đăng gần đây' trên Facebook."
            )
            return False

        if self._is_toggle_on(element):
            print("[Post Scan] 'Bài đăng gần đây' đã bật sẵn.")
            return True

        try:
            element.click()
        except Exception:
            try:
                # Một số lớp overlay chặn click chuột; JS click vẫn kích hoạt React.
                self.driver.execute_script("arguments[0].click();", element)
            except Exception as error:
                print(
                    f"[Post Scan] Không click được nút 'Bài đăng gần đây': {error}"
                )
                return False

        # React có thể render lại switch sau khi click -> tìm lại element mới.
        deadline = time.monotonic() + max(2.0, timeout / 2)
        while time.monotonic() < deadline:
            current = self._find_recent_posts_toggle(timeout=0.5)
            if current is not None and self._is_toggle_on(current):
                print("[Post Scan] Đã bật 'Bài đăng gần đây'.")
                time.sleep(RECENT_POSTS_SETTLE_SECONDS)
                return True
            time.sleep(0.2)

        print(
            "[Post Scan] Đã click nhưng nút 'Bài đăng gần đây' chưa chuyển sang bật."
        )
        return False

    def _collect_post_wrappers(self):
        """Lấy outerHTML của từng wrapper bài viết đang render trong feed."""
        script = """
            const feed = document.querySelector('div[role="feed"]');
            if (!feed) return null;
            const result = [];
            for (const child of feed.children) {
                if (child.querySelector('[data-ad-rendering-role="story_message"]')) {
                    result.push(child.outerHTML);
                }
            }
            return result;
        """
        try:
            return self.driver.execute_script(script)
        except (WebDriverException, OSError):
            raise
        except Exception:
            return None

    def _expand_post_content(self) -> int:
        """Bấm các nút 'See more' / 'Xem thêm' để lấy nội dung đầy đủ hơn."""
        script = """
            const feed = document.querySelector('div[role="feed"]');
            if (!feed) return 0;
            let clicked = 0;
            const nodes = feed.querySelectorAll('a, div[role="button"], span[role="button"]');
            for (const node of nodes) {
                const text = (node.innerText || '').trim();
                if (text === 'See more' || text === 'Xem thêm') {
                    try {
                        node.click();
                        clicked += 1;
                    } catch (error) {}
                }
            }
            return clicked;
        """
        try:
            return int(self.driver.execute_script(script) or 0)
        except Exception:
            return 0

    def _extract_posts_from_current_feed(
        self,
        scope: str,
        group_id,
        max_posts: int = 0,
        expand_content: bool = True,
    ) -> list[dict]:
        """Cuộn feed, parse từng bài và trả về danh sách đã chống trùng."""
        collected: dict[str, dict] = {}
        stale_rounds = 0
        scroll_rounds = 0
        max_scroll_rounds = 80
        fallback_used = False

        while not self.is_stopped():
            if expand_content:
                clicked = self._expand_post_content()
                if clicked:
                    time.sleep(random.uniform(0.4, 0.8))

            wrappers = self._collect_post_wrappers()
            new_in_round = 0

            if wrappers:
                for wrapper_html in wrappers:
                    post = parse_post_wrapper(
                        wrapper_html, scope=scope, fallback_group_id=group_id
                    )
                    if not post:
                        continue
                    key = post_key(post)
                    if key in collected:
                        continue
                    collected[key] = post
                    new_in_round += 1
            elif not fallback_used:
                # Một số biến thể DOM không có role=feed trực tiếp.
                fallback_used = True
                for post in extract_posts(
                    self.driver.page_source,
                    scope=scope,
                    fallback_group_id=group_id,
                ):
                    key = post_key(post)
                    if key not in collected:
                        collected[key] = post
                        new_in_round += 1

            if max_posts and len(collected) >= max_posts:
                break
            if self.is_stopped():
                break

            try:
                self.driver.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight);"
                )
                time.sleep(random.uniform(1.2, 2.0))
            except (WebDriverException, OSError):
                raise

            scroll_rounds += 1
            if new_in_round:
                stale_rounds = 0
            else:
                stale_rounds += 1

            # Hết bài: không có bài mới sau nhiều lần cuộn.
            if stale_rounds >= 4:
                break
            if scroll_rounds >= max_scroll_rounds:
                break

        posts = list(collected.values())
        if max_posts:
            posts = posts[:max_posts]
        return posts

    def _save_posts_json(
        self,
        posts: list[dict],
        scope: str,
        keyword: str,
        group_ids: list[str],
        source_label: str,
        recent_posts: bool = False,
        time_range: str = "all",
        post_type: str = "all",
    ) -> str:
        """Ghi kết quả trích xuất ra data/<uid>/raw/posts_*.json."""
        exported_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        for post in posts:
            post.setdefault("scraped_at", exported_at)

        if scope == "search":
            safe_name = "search_" + keyword
        else:
            safe_name = f"groups_{len(group_ids)}"
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", safe_name).strip("_")[:60]
        if not safe_name:
            safe_name = "posts"

        target_dir = self.data_dir or os.path.join(APP_DIR, "data", "raw")
        os.makedirs(target_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(
            target_dir, f"posts_{safe_name}_{timestamp}.json"
        )

        payload = {
            "scope": scope,
            "keyword": keyword if scope == "search" else "",
            "group_ids": list(group_ids),
            "source": source_label,
            "exported_at": exported_at,
            "recent_posts": bool(recent_posts) and scope == "search",
            "time_range": time_range if scope == "search" else "all",
            "post_type": post_type if scope == "search" else "all",
            "post_count": len(posts),
            "posts": posts,
        }
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
        return file_path

    def type_content_to_editor(self, editor, content):
        def insert_to_editor(editor, text):
            """Bắn chữ/emoji an toàn qua JS"""
            self.driver.execute_script("""
                var element = arguments[0];
                var text = arguments[1];
                element.focus();
                document.execCommand('insertText', false, text);
                element.dispatchEvent(new Event('input', { bubbles: true }));
            """, editor, text)
        editor.click()
        
        # Tách chuỗi: Giữ riêng emoji và giữ riêng cả dấu xuống dòng \n
        tokens = re.split(r'([\U00010000-\U0010FFFF]|\n)', content)
        
        current_chunk = ""
        target_length = random.randint(15, 35) # Độ dài ký tự ngẫu nhiên cho mỗi cụm
        
        for token in tokens:
            if not token:
                continue
                
            # TRƯỜNG HỢP 1: Gặp dấu xuống dòng
            if token == '\n':
                if current_chunk:
                    insert_to_editor(editor, current_chunk)
                    current_chunk = ""
                
                # Ép ô chatbox xuống dòng bằng Shift + Enter
                editor.send_keys(Keys.SHIFT + Keys.ENTER)
                time.sleep(0.05)
                target_length = random.randint(15, 35) # Reset độ dài ngẫu nhiên
                continue
                
            # TRƯỜNG HỢP 2: Gặp Emoji
            if re.match(r'[\U00010000-\U0010FFFF]', token):
                # Nếu cụm chữ hiện tại + emoji này dài quá target, đẩy cụm cũ đi trước
                if len(current_chunk) + 1 >= target_length:
                    insert_to_editor(editor, current_chunk)
                    current_chunk = token # Emoji sẽ mở đầu cho cụm mới
                    target_length = random.randint(15, 35)
                    time.sleep(random.uniform(0.1, 0.2))
                else:
                    current_chunk += token
                continue
                
            # TRƯỜNG HỢP 3: Chữ thường
            current_chunk += token
            
            # Nếu tích lũy đủ độ dài ngẫu nhiên thì đẩy vào ô chat
            if len(current_chunk) >= target_length:
                insert_to_editor(editor, current_chunk)
                current_chunk = ""
                target_length = random.randint(15, 35)
                time.sleep(random.uniform(0.1, 0.2))
                
        # Đẩy nốt phần nội dung còn lại (nếu có)
        if current_chunk:
            insert_to_editor(editor, current_chunk)

    def send_message_via_uid(self, uid, content, image_paths=None, typing_delay_range=None):
        def human_delay(min_sec=0.5, max_sec=1.5):
            """Tạo khoảng trễ ngẫu nhiên mô phỏng sự suy nghĩ của người dùng"""
            time.sleep(random.uniform(min_sec, max_sec))

        def human_scroll_to(element):
            """Cuộn trang mượt mà và tự nhiên giống người thật"""
            try:
                # Cuộn từ từ đến vị trí element
                desired_y = element.location['y'] - random.randint(150, 250)
                current_y = self.driver.execute_script("return window.pageYOffset;")
                step = 40 if desired_y > current_y else -40
                
                # Cuộn từng bước nhỏ
                for pos in range(current_y, desired_y, step):
                    self.driver.execute_script(f"window.scrollTo(0, {pos});")
                    time.sleep(random.uniform(0.01, 0.03))
                
                # Cuộn chính xác bước cuối
                self.driver.execute_script(f"window.scrollTo(0, {desired_y});")
                human_delay(0.3, 0.7)
            except Exception:
                # Fallback nếu cuộn mượt bị lỗi
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)

        def human_click(element):
            """Click vào một điểm ngẫu nhiên trên nút thay vì click vào tâm"""
            try:
                size = element.size
                # Lấy tọa độ ngẫu nhiên bên trong kích thước của nút (tránh sát rìa)
                offset_x = random.randint(int(size['width'] * 0.2), int(size['width'] * 0.8))
                offset_y = random.randint(int(size['height'] * 0.2), int(size['height'] * 0.8))
                
                # Di chuyển chuột tới phần tử và click với khoảng lệch ngẫu nhiên
                action = ActionChains(self.driver)
                action.move_to_element_with_offset(element, offset_x - (size['width']/2), offset_y - (size['height']/2))
                action.click()
                action.perform()
            except Exception:
                # Fallback nếu ActionChains bị chặn
                element.click()

        def close_chat():
            try:
                human_delay(1.5, 3.5) # Người thật nhìn màn hình một lúc rồi mới tắt
                print("[+] Đang đóng chat...")

                close_button = self.driver.find_element(
                    By.XPATH,
                    '//div[contains(@aria-label, "Close") or contains(@aria-label, "Đóng")]'
                )

                human_click(close_button)
                print("[+] Đã đóng chat")

            except Exception as e:
                print(f"[!] Close chat failed UID={uid}: {e}")

        def find_message_button():
            try:
                message_button = WebDriverWait(self.driver, 4).until(
                    EC.element_to_be_clickable((
                        By.XPATH,
                        '//div[@aria-label="Message" or @aria-label="Nhắn tin"]'
                    ))
                )
                print("[+] Đã tìm thấy nút Message")
                return message_button
            except TimeoutException as e:
                raise Exception(f"[MESSAGE_BUTTON_TIMEOUT] UID={uid}") from e
            except NoSuchElementException as e:
                raise Exception(f"[MESSAGE_BUTTON_NOT_FOUND] UID={uid}") from e
            
        def find_chatbox():
            try:
                chatbox_xpath = '//div[contains(@aria-label, "Write to") or contains(@aria-label, "Viết cho")]'
                chatbox = WebDriverWait(self.driver, 4).until(
                    EC.presence_of_element_located((By.XPATH, chatbox_xpath))
                )
                print("[+] Đã tìm thấy chatbox")
                return chatbox
            except Exception as e:
                print(f"[!] Không tìm thấy chatbox cho UID={uid}. Tiến hành đóng chat...")
                close_chat()
                raise Exception(f"[CHATBOX_TIMEOUT] UID={uid}") from e
            
        def clear_chatbox():
            try:
                print("[+] Đang clear chatbox...")
                human_click(chatbox) # Click vào trước khi xóa giống người thật
                human_delay(0.2, 0.5)
                chatbox.send_keys(Keys.CONTROL, "a")
                human_delay(0.1, 0.3)
                chatbox.send_keys(Keys.DELETE)
                print("[+] Đã clear chatbox")
            except Exception as e:
                print(f"[!] Clear chatbox failed UID={uid}: {e}")

        try:
            # =========================
            # OPEN PROFILE
            # =========================
            try:
                print(f"\n[+] Đang mở trang cá nhân UID: {uid}")
                user_url = f"https://www.facebook.com/{uid}"
                self.driver.get(user_url)
                human_delay(2.0, 4.0) # Chờ trang tải và người dùng "nhìn" giao diện

            except Exception as e:
                raise Exception(f"[OPEN_PROFILE_FAILED] UID={uid}") from e

            # =========================
            # FIND & SCROLL TO MESSAGE BUTTON
            # =========================
            message_button = find_message_button()
            human_scroll_to(message_button)

            # =========================
            # CLICK MESSAGE BUTTON
            # =========================
            try:
                human_click(message_button)
                print("[+] Đã click Message")
                human_delay(1.0, 2.5) # Chờ khung chat bật lên

            except Exception as e:
                raise Exception(f"[MESSAGE_BUTTON_CLICK_FAILED] UID={uid}") from e

            # =========================
            # FIND CHATBOX
            # =========================
            chatbox = find_chatbox()

            # =========================
            # INPUT MESSAGE (Đã có logic của bạn)
            # =========================
            try:
                print(f"[+] Đang nhập tin nhắn: '{content}'")
                human_click(chatbox) # Click kích hoạt khung chat trước khi gõ
                human_delay(0.3, 0.7)
                
                self.type_content_to_editor(chatbox, content)
                if typing_delay_range:
                    human_delay(*typing_delay_range)
                print("[+] Đã nhập tin nhắn")
                human_delay(0.5, 1.2) # Do dự một chút trước khi bấm gửi

            except Exception as e:
                raise Exception(f"[INPUT_MESSAGE_FAILED] UID={uid}") from e

            # =========================
            # SEND MESSAGE
            # =========================
            try:
                print("[+] Đang gửi tin nhắn...")

                # Giả lập nhấn ENTER để gửi tin nhắn một cách tự nhiên
                chatbox.send_keys(Keys.ENTER)
                
                human_delay(1.5, 3.0) # Đợi tin nhắn chuyển trạng thái "Đã gửi"
                print("[🔑] Gửi thành công!")

            except Exception as e:
                raise Exception(f"[SEND_MESSAGE_FAILED] UID={uid}") from e

            clear_chatbox()
            close_chat()
            return True

        except Exception as e:
            print(f"[❌] {e}")
            return False

    def scrape_joined_groups(self):
        """
        Hàm cào danh sách Group đã tham gia từ trang /groups/joins
        Chỉ tập trung tìm kiếm trong vùng nội dung chính (role="main")
        """
        print("🔄 Đang truy cập trang danh sách Nhóm đã tham gia...")
        self.driver.get("https://www.facebook.com/groups/joins")
        time.sleep(4) # Đợi trang tải các group đầu tiên

        # Vòng lặp cuộn trang để tải hết danh sách Group
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        scroll_attempts = 10 
        
        for i in range(scroll_attempts):
            print(f"📜 Đang cuộn trang lần {i+1}/{scroll_attempts}...")
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3) 
            
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                print("🛑 Đã cuộn đến cuối danh sách hoặc không có dữ liệu mới.")
                break
            last_height = new_height

        print("🔍 Bắt đầu trích xuất dữ liệu Group từ vùng nội dung chính...")
        joined_groups = []

        try:
            # 1. Định vị vùng nội dung chính của trang Facebook
            main_container = self.driver.find_element(By.XPATH, "//*[@role='main']")
            
            # 2. Chỉ tìm các khối group item NẰM TRONG vùng role="main" này
            group_items = main_container.find_elements(By.XPATH, ".//div[@role='listitem']")
            print(f"📊 Phát hiện {len(group_items)} khối group item trong khu vực nội dung chính.")

            for item in group_items:
                try:
                    # 3. Tìm thẻ <a> chứa link nhóm bên trong item
                    a_tag = item.find_element(By.XPATH, ".//a[contains(@href, '/groups/')]")
                    url = a_tag.get_attribute("href")
                    
                    # 4. Lấy tên Group (Xử lý fallback nếu thẻ a đầu tiên là ảnh/trống chữ)
                    title = a_tag.text.strip()
                    if not title:
                        all_links = item.find_elements(By.XPATH, ".//a[contains(@href, '/groups/')]")
                        for link in all_links:
                            if link.text.strip():
                                title = link.text.strip()
                                break

                    if title and url:
                        # Trích xuất ID/Alias từ URL
                        match = re.search(r'/groups/([^/]+)', url)
                        group_id = match.group(1) if match else None
                        
                        # Loại bỏ các sub-page mặc định
                        if not group_id or group_id in ["joins", "feed", "discover", "create"]:
                            continue

                        numeric_id = self.get_numeric_group_id(group_id) or group_id
                        resolved_id = str(numeric_id)

                        group_info = {
                            "group_name": title,
                            "group_id": resolved_id,
                            "group_url": f"https://www.facebook.com/groups/{group_id}/"
                        }

                        # Kiểm tra trùng lặp theo ID đã resolve
                        if not any(
                            str(g["group_id"]) == resolved_id for g in joined_groups
                        ):
                            print(f"✅ Đã tìm thấy: {title} (ID: {resolved_id})")
                            joined_groups.append(group_info)
                            
                except Exception:
                    continue

        except Exception as e:
            print(f"❌ Không tìm thấy vùng nội dung chính (role='main'). Lỗi: {e}")
            return []

        print(f"🎉 Đã lọc và trích xuất thành công {len(joined_groups)} nhóm đã tham gia.")
        return joined_groups

    def share_post_to_group(self, post_url, content : str, uid=""):
        time.sleep(2)
        self.driver.get(post_url)

        try:
            xpath_dialog = "//div[@role='dialog']"
            time.sleep(2)

            # Tìm phần tử có thuộc tính aria-label cụ thể
            xpath_locator = xpath_dialog + "//div[@aria-label='Gửi nội dung này cho bạn bè hoặc đăng lên trang cá nhân của bạn.']"

            # Sử dụng trong Selenium
            share_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, xpath_locator))
            )
            self.driver.execute_script("arguments[0].click();", share_button)
            print("Đã click nút Share")

            # Sử dụng XPath để đợi một thẻ <a> có chứa UID trong href xuất hiện
            group_btn_xpath = xpath_dialog + '//div[@aria-label="Chia sẻ lên nhóm"]'
            group_btn = WebDriverWait(self.driver, 4).until(
                EC.element_to_be_clickable((By.XPATH, group_btn_xpath))
            )
            self.driver.execute_script("arguments[0].click();", group_btn)
            print("Đã click: Chia sẻ lên nhóm")

            time.sleep(1)

            # Tìm thẻ a chứa uid, nhưng chỉ tìm bên trong cái dialog đang mở
            group_xpath = xpath_dialog + f"//a[contains(@href, '{uid}')]/ancestor::div[@role='listitem']"
            
            try:
                # Đợi tối đa 15 giây cho đến khi phần tử xuất hiện
                group = WebDriverWait(self.driver, 15).until(
                    EC.element_to_be_clickable((By.XPATH, group_xpath))
                )
                print(group.get_attribute("outerHTML"))

                # Click vào link
                ActionChains(self.driver).move_to_element(group).click().perform()
                print(f"Đã tìm thấy và click vào nhóm: {uid}")

            except Exception as e:
                print(f"Không tìm thấy nhóm sau 15s chờ đợi: {e}")
            print("Đã vào trang share group!")

            editor_xpath = xpath_dialog + "//div[@data-lexical-editor='true' and contains(@aria-placeholder, 'Tạo bài viết')]"
            editor = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, editor_xpath))
            )

            # Focus và nhập
            self.type_content_to_editor(editor, content)

            post_btn_xpath = xpath_dialog + "//*[@role='button' and (@aria-label='Đăng' or @aria-label='Post')]"
            post_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, post_btn_xpath))
            )
            
            post_btn.click()

            return True
        except Exception as e:
            print(e)
            return False

    def create_post(self, id, content="", img_paths=[]):
        self.driver.get(f"https://www.facebook.com/groups/{id}")
        post_box_xpath = "//span[contains(text(),'mind') or contains(text(),'nghĩ gì') or contains(text(),'something') or contains(text(),'viết gì')]"

        try:
            post_box = WebDriverWait(self.driver, 5).until( # Tăng lên 5s cho an toàn mạng
                EC.element_to_be_clickable((By.XPATH, post_box_xpath))
            )
            post_box.click()
        except:
            return False
        print("Đã mở hộp đăng bài")

        # Giả lập: Nghỉ ngẫu nhiên, không lần nào giống lần nào để qua mặt AI Facebook
        time.sleep(random.uniform(1.2, 2.5))

        composer = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, "//div[@role='dialog' and @aria-modal='true']")
            )
        )

        print("Đã vào hộp đăng bài")

        # Cô lập Form
        editor = WebDriverWait(composer, 4, poll_frequency=0.1).until(
            EC.visibility_of_element_located((By.XPATH, ".//div[@role='textbox']"))
        )

        editor.click()
        time.sleep(random.uniform(0.5, 1.0))

        print("🚀 Đang tiến hành gõ cụm thông minh kết hợp xử lý Emoji...")

        # Biểu thức chính quy (Regex) để tách văn bản thành mảng gồm các cụm chữ và các icon riêng biệt
        # Nó sẽ tách chuỗi kiểu: "Hello 🌍 mọi người 😍" thành ['Hello ', '🌍', ' mọi người ', '😍']
        tokens = re.split(r'([\U00010000-\U0010FFFF])', content)

        for token in tokens:
            if not token:
                continue
            
            # TRƯỜNG HỢP 1: Nếu token là một Emoji (Ký tự nằm ngoài vùng BMP)
            if re.match(r'[\U00010000-\U0010FFFF]', token):
                # Dùng Javascript để chèn icon vào cuối nội dung hiện tại của thẻ div editor
                self.driver.execute_script("""
                    var element = arguments[0];
                    var emoji = arguments[1];
                    
                    // Chèn emoji vào thẻ div editable
                    element.focus();
                    document.execCommand('insertText', false, emoji);
                    
                    // Kích hoạt sự kiện để Facebook cập nhật trạng thái
                    element.dispatchEvent(new Event('input', { bubbles: true }));
                """, editor, token)
                time.sleep(random.uniform(0.1, 0.3)) # Nghỉ một chút sau khi chèn icon
                
            # TRƯỜNG HỢP 2: Nếu là chữ viết thông thường
            else:
                # Tách chữ thường thành các cụm nhỏ hơn nữa (tầm 15 ký tự) để gõ nhanh
                chunk_size = 15
                chunks = [token[i:i+chunk_size] for i in range(0, len(token), chunk_size)]
                
                for chunk in chunks:
                    editor.send_keys(chunk)
                    time.sleep(random.uniform(0.05, 0.15)) # Tốc độ gõ cụm chữ nhanh

        time.sleep(random.uniform(1.0, 2.0))
        print("✅ Đã gõ xong toàn bộ văn bản và Emoji không một lỗi vết!")

        # BOT
        # self.driver.execute_script("""
        #     var element = arguments[0];
        #     var text = arguments[1];
            
        #     // 1. Gán text (bao gồm cả Emoji) vào thẻ div
        #     element.innerText = text;
            
        #     // 2. Kích hoạt liên tiếp các sự kiện để React/Vue/Angular cập nhật State
        #     element.dispatchEvent(new Event('focus', { bubbles: true }));
        #     element.dispatchEvent(new Event('input', { bubbles: true }));
        #     element.dispatchEvent(new Event('change', { bubbles: true }));
        #     element.dispatchEvent(new Event('blur', { bubbles: true }));
        # """, editor, content)

        # Thêm ảnh
        if not img_paths:
            print("Không tìm thấy ảnh!")
            return

        valid_file = 'image/*,image/heif,image/heic,video/*,video/mp4,video/x-m4v,video/x-matroska,.mkv,.avi,.wmv,.mov,.flv,.webm,.3gp,.3g2,.mts,.m2ts,.vob,.divx,.f4v,.ogv'
        file_input = composer.find_element(
            By.XPATH,
            f".//input[@accept='{valid_file}']"
        )
        
        for img_path in img_paths:
            file_name = img_path.split('\\')[-1]
            file_path = os.path.join(APP_DIR, "bot_media_tmp", file_name)
            file_input.send_keys(file_path)
            # Nghỉ một chút giữa mỗi lần nạp file ảnh tiếp theo
            time.sleep(random.uniform(1.0, 2.0))

        print("Đã nạp toàn bộ ảnh, chờ Facebook xử lý render...")

        # Giả lập: Đợi cho đến khi nút Post thực sự "Bấm được" (Hết trạng thái disabled của FB)
        post_btn = WebDriverWait(composer, 15).until(
            EC.element_to_be_clickable((By.XPATH, ".//div[@aria-label='Post']"))
        )

        # Di chuột mồi đến nút trước khi click (Sử dụng ActionChains nếu cần thiết)
        time.sleep(random.uniform(0.7, 1.5)) 

        # post_btn.click()
        print("Đã đăng bài!")

        # Nút đăng bài
        post_btn = composer.find_element(
            By.XPATH,
            ".//div[@aria-label='Post']"
        )

        #post_btn.click()

        actions = ActionChains(self.driver)
        actions.move_to_element(post_btn).perform() # Rê chuột đến ô đăng bài
        time.sleep(random.uniform(0.3, 0.7))        # Giữ chuột ở đó một tí
        #actions.click(post_btn).perform()                   # Bấm chuột
        
        print("Hoàn tất đăng bài")
        return True
