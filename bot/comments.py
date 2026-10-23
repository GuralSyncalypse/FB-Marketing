"""Quét bình luận/reply của một bài viết Facebook.

Transport GraphQL nằm ở ``bot.graphql``; parse ở
``services.comment_extractor``. Module này chỉ điều phối phân trang, lưu JSON
và xuất Excel/CSV.
"""

from __future__ import annotations

import json
import os
import re
import time

import pandas as pd

from services.comment_extractor import (
    CommentParseError,
    dedupe_comments,
    parse_comments_page,
    parse_replies_page,
)

from .paths import APP_DIR


COMMENT_EXPORT_COLUMNS = (
    "post_id",
    "comment_id",
    "parent_comment_id",
    "depth",
    "is_reply",
    "author_id",
    "author_name",
    "author_url",
    "content",
    "reaction_count",
    "reply_count",
    "created_at",
    "permalink",
    "attachment_count",
    "attachment_urls",
    "is_hidden_by_viewer",
    "is_disabled",
    "scraped_at",
)


def _short(value, limit: int = 24) -> str:
    """Rút gọn cursor/token để log không làm rối console."""
    text = str(value or "")
    if not text:
        return "-"
    return text[:limit] + ("..." if len(text) > limit else "")

# URL dạng bài thường có sẵn ID feedback. Reel/permalink đặc biệt cần đọc
# ``"post_id"`` trong page source vì ID trên URL là video/story ID.
POST_URL_ID_PATTERNS = (
    re.compile(r"/posts/(\d+)"),
    re.compile(r"/permalink/(\d+)"),
    re.compile(r"[?&]story_fbid=(\d+)"),
    re.compile(r"[?&]multi_permalinks=(\d+)"),
)
PAGE_POST_ID_PATTERNS = (
    re.compile(r'"post_id"\s*:\s*"(\d+)"'),
    re.compile(r'"feedback_id"\s*:\s*"(\d+)"'),
    re.compile(r"feedback%3A(\d+)"),
)


def _comment_rows(comments: list[dict]) -> list[dict]:
    rows = []
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        urls = comment.get("attachment_urls") or []
        if isinstance(urls, str):
            urls = [urls]
        elif not isinstance(urls, (list, tuple)):
            urls = []
        urls = [str(url) for url in urls if url]
        rows.append(
            {
                "post_id": str(comment.get("post_id") or ""),
                "comment_id": str(comment.get("comment_id") or ""),
                "parent_comment_id": str(
                    comment.get("parent_comment_id") or ""
                ),
                "depth": comment.get("depth") or 0,
                "is_reply": bool(comment.get("is_reply")),
                "author_id": str(comment.get("author_id") or ""),
                "author_name": comment.get("author_name") or "",
                "author_url": comment.get("author_url") or "",
                "content": str(comment.get("content") or ""),
                "reaction_count": comment.get("reaction_count"),
                "reply_count": comment.get("reply_count"),
                "created_at": comment.get("created_at") or "",
                "permalink": comment.get("permalink") or "",
                "attachment_count": len(urls),
                "attachment_urls": " | ".join(urls),
                "is_hidden_by_viewer": bool(
                    comment.get("is_hidden_by_viewer")
                ),
                "is_disabled": bool(comment.get("is_disabled")),
                "scraped_at": comment.get("scraped_at") or "",
            }
        )
    return rows


def _truncate_excel_cells(dataframe: pd.DataFrame) -> pd.DataFrame:
    result = dataframe.copy()
    for column in result.columns:
        result[column] = result[column].map(
            lambda value: (
                value[:32000]
                if isinstance(value, str) and len(value) > 32000
                else value
            )
        )
    return result


def export_comments_to_spreadsheet(
    json_filepath: str,
    output_dir: str | None = None,
    output_basename: str | None = None,
) -> dict:
    """Xuất JSON bình luận ra cả .xlsx và .csv.

    Trả về ``{"csv": path, "xlsx": path}``; định dạng lỗi sẽ bị bỏ qua để
    định dạng còn lại vẫn được tạo.
    """
    if not os.path.exists(json_filepath):
        print(f"⚠️ Không tìm thấy file JSON bình luận: {json_filepath}")
        return {}

    try:
        with open(json_filepath, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        print(f"⚠️ Không đọc được file JSON bình luận: {error}")
        return {}

    if isinstance(payload, dict):
        comments = payload.get("comments") or []
    elif isinstance(payload, list):
        comments = payload
    else:
        comments = []

    rows = _comment_rows(comments)
    if not rows:
        print("⚠️ File JSON không có bình luận nào để xuất Excel/CSV.")
        return {}

    base_name = output_basename or os.path.splitext(
        os.path.basename(json_filepath)
    )[0]
    target_dir = output_dir or os.path.join(APP_DIR, "data", "processed")
    os.makedirs(target_dir, exist_ok=True)

    csv_path = os.path.join(target_dir, f"{base_name}.csv")
    xlsx_path = os.path.join(target_dir, f"{base_name}.xlsx")
    df = pd.DataFrame(rows, columns=list(COMMENT_EXPORT_COLUMNS))
    exported = {}

    try:
        df.to_csv(csv_path, index=False, encoding="utf-8-sig", na_rep="")
        exported["csv"] = csv_path
    except Exception as error:
        print(f"⚠️ Không xuất được CSV bình luận: {error}")

    try:
        from openpyxl.utils import get_column_letter

        excel_df = _truncate_excel_cells(df)
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            excel_df.to_excel(writer, index=False, sheet_name="Comments")
            worksheet = writer.sheets["Comments"]
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
        print(f"⚠️ Không xuất được Excel bình luận: {error}")

    if exported:
        print(
            f"📊 Đã xuất {len(df)} bình luận ra Excel/CSV:\n"
            + "\n".join(f"   - {path}" for path in exported.values())
        )
    return exported


class CommentMixin:
    """Điều phối quét bình luận/reply cho ``FacebookBot``."""

    def resolve_post_feedback_id(
        self,
        post_url_or_id: str,
        wait_seconds: float = 4.0,
        log_prefix: str = "Comments",
    ) -> str:
        """Đổi URL/ID bài viết thành ID feedback dùng cho GraphQL.

        - ID số: trả về nguyên giá trị.
        - URL bài thường (``/posts/``, ``story_fbid=``...): lấy ID ngay từ URL.
        - Reel/permalink không chứa feedback ID: mở URL rồi đọc
          ``"post_id"`` trong page source.
        """
        prefix = log_prefix or "Comments"
        text = str(post_url_or_id or "").strip()
        print(f"[{prefix}] Phân giải bài viết: {text[:160] or '(rỗng)'}")
        if not text:
            raise ValueError("Vui lòng nhập URL hoặc ID bài viết.")
        if text.isdigit():
            print(f"[{prefix}] Dùng ID feedback trực tiếp: {text}")
            return text

        url = text
        if not re.match(r"^https?://", url, flags=re.IGNORECASE):
            url = "https://www.facebook.com/" + url.lstrip("/")
            print(f"[{prefix}] Chuẩn hóa URL: {url}")

        # URL bài thường có ID feedback trực tiếp, không cần mở browser.
        if "/reel/" not in url.lower():
            for pattern in POST_URL_ID_PATTERNS:
                match = pattern.search(url)
                if match:
                    post_id = match.group(1)
                    print(f"[{prefix}] Lấy post_id từ URL: {post_id}")
                    return post_id

        if self.driver is None:
            raise ValueError(
                "Chưa mở browser để đọc ID bài viết từ URL này."
            )

        print(f"[{prefix}] Mở URL để tìm post_id: {url}")
        try:
            self.driver.get(url)
        except Exception as error:
            raise ValueError(
                f"Không mở được URL bài viết: {error}"
            ) from error

        time.sleep(max(0.0, float(wait_seconds)))
        try:
            page_source = self.driver.page_source or ""
        except Exception as error:
            raise ValueError(
                f"Không đọc được nội dung trang bài viết: {error}"
            ) from error
        print(
            f"[{prefix}] Đã đọc page source ({len(page_source)} ký tự), "
            "đang tìm post_id..."
        )

        for pattern in PAGE_POST_ID_PATTERNS:
            match = pattern.search(page_source)
            if match:
                post_id = match.group(1)
                print(f"[{prefix}] Tìm thấy post_id: {post_id}")
                return post_id

        print(f"[{prefix}] Không tìm thấy post_id trong page source.")
        raise ValueError(
            "Không tìm thấy ID feedback của bài viết. "
            "Hãy mở permalink bài viết rồi thử lại."
        )

    def collect_comment_replies(
        self,
        post_id: str,
        parent_comment_id: str,
        expansion_token: str,
        max_replies: int | None = None,
    ) -> list[dict]:
        """Lấy toàn bộ reply của một comment cha."""
        if not expansion_token:
            print(
                f"[Comments] Bỏ qua reply của {parent_comment_id}: "
                "không có expansionToken."
            )
            return []

        print(
            f"[Comments] Bắt đầu lấy reply cho comment {parent_comment_id} "
            f"(token={_short(expansion_token)}, max={max_replies or 'không giới hạn'})"
        )
        replies = []
        seen = set()
        cursor = None
        page_number = 0
        while True:
            if self.is_stopped():
                print("[Comments] Đã yêu cầu dừng khi đang lấy reply.")
                break
            page_number += 1
            print(
                f"[Comments] Reply page #{page_number} cho {parent_comment_id}: "
                f"cursor={_short(cursor)}"
            )
            response = self.fetch_replies_page(
                post_id,
                parent_comment_id,
                expansion_token,
                cursor=cursor,
            )
            page = parse_replies_page(
                response,
                post_id=post_id,
                parent_comment_id=parent_comment_id,
            )
            added = 0
            for reply in page["replies"]:
                key = reply.get("comment_id") or reply.get("global_id")
                if not key or key in seen:
                    print(f"[Comments] Bỏ qua reply trùng/rỗng: {key or '-'}")
                    continue
                seen.add(key)
                replies.append(reply)
                added += 1
                if max_replies and len(replies) >= max_replies:
                    print(
                        f"[Comments] Đạt giới hạn {max_replies} reply "
                        f"cho {parent_comment_id}."
                    )
                    return replies

            page_info = page["page_info"]
            cursor = page_info.get("end_cursor")
            print(
                f"[Comments] Reply page #{page_number} cho {parent_comment_id}: "
                f"+{added} (tổng {len(replies)}), "
                f"has_next={page_info.get('has_next_page')}, "
                f"next_cursor={_short(cursor)}"
            )
            if not page_info.get("has_next_page") or not cursor:
                break
        print(
            f"[Comments] Hoàn tất reply cho {parent_comment_id}: "
            f"{len(replies)} reply."
        )
        return replies

    def collect_post_comments(
        self,
        post_id: str,
        include_replies: bool = True,
        max_comments: int | None = None,
        max_replies_per_comment: int | None = None,
    ) -> list[dict]:
        """Lấy bình luận top-level và (tùy chọn) reply của một bài/reel.

        ``post_id`` là ID feedback của bài, ví dụ ``1473471161654707``. Hàm
        giữ thứ tự comment cha do Facebook trả về; reply của mỗi cha được gắn
        ngay sau cha đó.
        """
        top_level = []
        seen = set()
        cursor = None
        page_number = 0

        print(
            f"[Comments] Bắt đầu quét comment cho post {post_id} "
            f"(replies={include_replies}, max={max_comments or 'không giới hạn'})"
        )
        while True:
            if self.is_stopped():
                print("[Comments] Đã yêu cầu dừng khi đang lấy comment.")
                break
            page_number += 1
            print(
                f"[Comments] Comment page #{page_number}: cursor={_short(cursor)}"
            )
            response = self.fetch_comments_page(post_id, cursor=cursor)
            page = parse_comments_page(response)
            added = 0

            for comment in page["comments"]:
                key = comment.get("comment_id") or comment.get("global_id")
                if not key or key in seen:
                    print(f"[Comments] Bỏ qua comment trùng/rỗng: {key or '-'}")
                    continue
                seen.add(key)
                top_level.append(comment)
                added += 1
                if max_comments and len(top_level) >= max_comments:
                    print(
                        f"[Comments] Đạt giới hạn {max_comments} mục top-level."
                    )
                    break

            page_info = page["page_info"]
            cursor = page_info.get("end_cursor")
            print(
                f"[Comments] Comment page #{page_number}: +{added} "
                f"(tổng top-level {len(top_level)}), "
                f"prev={page_info.get('has_previous_page')}, "
                f"next={page_info.get('has_next_page')}, "
                f"next_cursor={_short(cursor)}"
            )

            if max_comments and len(top_level) >= max_comments:
                break
            if not page_info.get("has_next_page") or not cursor:
                break

        ordered = []
        for parent in top_level:
            if max_comments and len(ordered) >= max_comments:
                break
            ordered.append(parent)
            if max_comments and len(ordered) >= max_comments:
                break

            if not include_replies:
                continue

            reply_count = parent.get("reply_count")
            token = parent.get("expansion_token")
            if not reply_count or not token:
                if reply_count:
                    print(
                        f"[Comments] Comment {parent.get('comment_id')} "
                        f"có {reply_count} reply nhưng thiếu expansionToken."
                    )
                continue

            parent_id = parent.get("comment_id")
            if not parent_id:
                continue

            remaining = None
            if max_comments:
                remaining = max_comments - len(ordered)
                if remaining <= 0:
                    print(
                        f"[Comments] Đã đủ {max_comments} mục, "
                        f"bỏ qua reply của {parent_id}."
                    )
                    break
            reply_limit = max_replies_per_comment
            if remaining is not None:
                reply_limit = (
                    min(reply_limit, remaining)
                    if reply_limit
                    else remaining
                )

            print(
                f"[Comments] Comment {parent_id} có {reply_count} reply "
                f"-> bắt đầu lấy reply (tối đa {reply_limit or 'không giới hạn'})."
            )
            ordered.extend(
                self.collect_comment_replies(
                    post_id,
                    parent_id,
                    token,
                    max_replies=reply_limit,
                )
            )

        cleaned = []
        for item in dedupe_comments(ordered):
            row = dict(item)
            row.pop("raw_node", None)
            cleaned.append(row)
        reply_total = sum(1 for item in cleaned if item.get("is_reply"))
        print(
            f"[Comments] Hoàn tất quét post {post_id}: "
            f"{len(cleaned)} mục "
            f"({len(cleaned) - reply_total} comment, {reply_total} reply)."
        )
        return cleaned

    def _save_comments_json(
        self,
        post_id: str,
        comments: list[dict],
        source_url: str = "",
    ) -> str:
        """Lưu JSON bình luận vào ``data/<uid>/raw/comments_*.json``."""
        scraped_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        cleaned = []
        for comment in comments:
            row = dict(comment)
            row.pop("raw_node", None)
            row.setdefault("scraped_at", scraped_at)
            cleaned.append(row)

        safe_post_id = re.sub(r"[^A-Za-z0-9_-]+", "_", str(post_id)).strip("_")
        if not safe_post_id:
            safe_post_id = "post"
        target_dir = self.data_dir or os.path.join(APP_DIR, "data", "raw")
        os.makedirs(target_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(
            target_dir, f"comments_{safe_post_id}_{timestamp}.json"
        )

        payload = {
            "post_id": str(post_id),
            "source_url": source_url,
            "exported_at": scraped_at,
            "comment_count": len(cleaned),
            "top_level_count": sum(
                1 for item in cleaned if not item.get("is_reply")
            ),
            "reply_count": sum(
                1 for item in cleaned if item.get("is_reply")
            ),
            "comments": cleaned,
        }
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
        print(
            f"[Comments] Đã lưu JSON: {file_path} "
            f"({payload['comment_count']} mục, "
            f"{payload['top_level_count']} comment, "
            f"{payload['reply_count']} reply)."
        )
        return file_path

    def scan_post_comments(
        self,
        post_id: str,
        include_replies: bool = True,
        max_comments: int | None = None,
        max_replies_per_comment: int | None = None,
        source_url: str = "",
        save: bool = True,
        export: bool = True,
    ) -> dict:
        """Quét bình luận và (mặc định) lưu JSON + Excel/CSV.

        Trả về dict gồm ``post_id``, ``comments``, ``json_path`` và
        ``export_paths``.
        """
        comments = self.collect_post_comments(
            post_id,
            include_replies=include_replies,
            max_comments=max_comments,
            max_replies_per_comment=max_replies_per_comment,
        )
        print(
            f"[Comments] Chuẩn bị lưu kết quả post {post_id}: "
            f"{len(comments)} mục."
        )
        result = {
            "post_id": str(post_id),
            "source_url": source_url,
            "comments": comments,
            "json_path": None,
            "export_paths": {},
        }
        if not save:
            print("[Comments] Bỏ qua lưu file (save=False).")
            return result

        json_path = self._save_comments_json(
            post_id, comments, source_url=source_url
        )
        result["json_path"] = json_path

        if export:
            print("[Comments] Bắt đầu xuất CSV/XLSX...")
            output_dir = self.exports_dir or os.path.join(
                APP_DIR, "data", "processed"
            )
            result["export_paths"] = export_comments_to_spreadsheet(
                json_path, output_dir=output_dir
            )
            print(
                f"[Comments] Xuất xong: {result['export_paths'] or 'không có file'}"
            )
        return result

    def scan_post_comments_from_url(
        self,
        post_url_or_id: str,
        include_replies: bool = True,
        max_comments: int | None = None,
        max_replies_per_comment: int | None = None,
        save: bool = True,
        export: bool = True,
    ) -> dict:
        """Quét bình luận từ URL/ID bài viết (hỗ trợ cả Reel)."""
        print(f"[Comments] Nhận yêu cầu quét từ: {post_url_or_id}")
        post_id = self.resolve_post_feedback_id(post_url_or_id)
        print(f"[Comments] Dùng post_id={post_id} để gọi GraphQL comments.")
        result = self.scan_post_comments(
            post_id,
            include_replies=include_replies,
            max_comments=max_comments,
            max_replies_per_comment=max_replies_per_comment,
            source_url=str(post_url_or_id or ""),
            save=save,
            export=export,
        )
        result["input"] = str(post_url_or_id or "")
        print(
            f"[Comments] Xong yêu cầu: {len(result.get('comments') or [])} mục, "
            f"JSON={result.get('json_path') or '-'}"
        )
        return result
