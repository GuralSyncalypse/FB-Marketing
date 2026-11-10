"""Quét danh sách người thả reaction/like của một bài viết Facebook.

Transport GraphQL nằm ở ``bot.graphql``; parse ở
``services.reaction_extractor``. Module này điều phối phân trang, lưu JSON và
xuất Excel/CSV.
"""

from __future__ import annotations

import json
import os
import random
import re
import time

import pandas as pd

from services.reaction_extractor import (
    dedupe_reactions,
    normalize_reaction_type,
    parse_reactions_page,
)

from .paths import APP_DIR


# Nghỉ giữa các trang để tránh bắn GraphQL quá nhanh (giây).
REACTION_PAGE_DELAY_SECONDS = 1.8


REACTION_EXPORT_COLUMNS = (
    "post_id",
    "user_id",
    "user_name",
    "reaction_type",
    "reaction_type_id",
    "profile_url",
    "profile_picture",
    "reaction_icon_url",
    "mutual_friends_count",
    "friendship_status",
    "subscribe_status",
    "scraped_at",
)


def _short(value, limit: int = 24) -> str:
    """Rút gọn cursor để log không làm rối console."""
    text = str(value or "")
    if not text:
        return "-"
    return text[:limit] + ("..." if len(text) > limit else "")


def _reaction_rows(reactions: list[dict]) -> list[dict]:
    rows = []
    for reaction in reactions:
        if not isinstance(reaction, dict):
            continue
        rows.append(
            {
                "post_id": str(reaction.get("post_id") or ""),
                "user_id": str(reaction.get("user_id") or ""),
                "user_name": reaction.get("user_name") or "",
                "reaction_type": reaction.get("reaction_type") or "",
                "reaction_type_id": str(
                    reaction.get("reaction_type_id") or ""
                ),
                "profile_url": reaction.get("profile_url") or "",
                "profile_picture": reaction.get("profile_picture") or "",
                "reaction_icon_url": reaction.get("reaction_icon_url") or "",
                "mutual_friends_count": reaction.get(
                    "mutual_friends_count"
                ),
                "friendship_status": reaction.get("friendship_status") or "",
                "subscribe_status": reaction.get("subscribe_status") or "",
                "scraped_at": reaction.get("scraped_at") or "",
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


def export_reactions_to_spreadsheet(
    json_filepath: str,
    output_dir: str | None = None,
    output_basename: str | None = None,
) -> dict:
    """Xuất JSON reaction ra cả .xlsx và .csv."""
    if not os.path.exists(json_filepath):
        print(f"⚠️ Không tìm thấy file JSON reaction: {json_filepath}")
        return {}

    try:
        with open(json_filepath, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        print(f"⚠️ Không đọc được file JSON reaction: {error}")
        return {}

    if isinstance(payload, dict):
        reactions = payload.get("reactions") or []
    elif isinstance(payload, list):
        reactions = payload
    else:
        reactions = []

    rows = _reaction_rows(reactions)
    if not rows:
        print("⚠️ File JSON không có reaction nào để xuất Excel/CSV.")
        return {}

    base_name = output_basename or os.path.splitext(
        os.path.basename(json_filepath)
    )[0]
    target_dir = output_dir or os.path.join(APP_DIR, "data", "processed")
    os.makedirs(target_dir, exist_ok=True)

    csv_path = os.path.join(target_dir, f"{base_name}.csv")
    xlsx_path = os.path.join(target_dir, f"{base_name}.xlsx")
    df = pd.DataFrame(rows, columns=list(REACTION_EXPORT_COLUMNS))
    exported = {}

    try:
        df.to_csv(csv_path, index=False, encoding="utf-8-sig", na_rep="")
        exported["csv"] = csv_path
    except Exception as error:
        print(f"⚠️ Không xuất được CSV reaction: {error}")

    try:
        from openpyxl.utils import get_column_letter

        excel_df = _truncate_excel_cells(df)
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            excel_df.to_excel(writer, index=False, sheet_name="Reactions")
            worksheet = writer.sheets["Reactions"]
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
        print(f"⚠️ Không xuất được Excel reaction: {error}")

    if exported:
        print(
            f"📊 Đã xuất {len(df)} reaction ra Excel/CSV:\n"
            + "\n".join(f"   - {path}" for path in exported.values())
        )
    return exported


class ReactionMixin:
    """Điều phối quét người thả reaction/like cho ``FacebookBot``."""

    def _wait_between_reaction_pages(self, seconds: float) -> None:
        """Nghỉ có thể ngắt giữa 2 trang reaction."""
        remaining = max(0.0, float(seconds or 0))
        while remaining > 0:
            if self.is_stopped():
                return
            time.sleep(min(0.2, remaining))
            remaining -= 0.2

    def collect_post_reactions(
        self,
        post_id: str,
        max_reactions: int | None = None,
        reaction_type: str = None,
        reaction_id: str = None,
        name_query: str = None,
        page_size: int = 10,
        page_delay_seconds: float = REACTION_PAGE_DELAY_SECONDS,
    ) -> list[dict]:
        """Lấy toàn bộ (hoặc tới giới hạn) người thả reaction của bài."""
        try:
            page_size = max(1, int(page_size))
        except (TypeError, ValueError):
            page_size = 10
        if max_reactions is not None:
            max_reactions = max(0, int(max_reactions))

        collected = []
        seen = set()
        cursor = None
        page_number = 0
        expected_type = normalize_reaction_type(reaction_type)
        if expected_type in {"", "ALL", "TAT CA", "TẤT CẢ"}:
            expected_type = None
        expected_id = str(reaction_id) if reaction_id else None

        print(
            f"[Reactions] Bắt đầu quét reaction cho post {post_id} "
            f"(reaction={reaction_type or reaction_id or 'all'}, "
            f"max={max_reactions or 'không giới hạn'}, "
            f"delay={page_delay_seconds}s/trang)"
        )
        while True:
            if self.is_stopped():
                print("[Reactions] Đã yêu cầu dừng khi đang lấy reaction.")
                break
            page_number += 1
            print(
                f"[Reactions] Reaction page #{page_number}: "
                f"cursor={_short(cursor)}"
            )
            response = self.fetch_reactions_page(
                post_id,
                cursor=cursor,
                count=page_size,
                reaction_type=reaction_type,
                reaction_id=reaction_id,
                name_query=name_query,
            )
            page = parse_reactions_page(response, post_id=str(post_id))
            added = 0

            for reaction in page["reactions"]:
                if expected_type and (
                    normalize_reaction_type(
                        reaction.get("reaction_type")
                    )
                    != expected_type
                ):
                    continue
                if expected_id and (
                    str(reaction.get("reaction_type_id") or "")
                    != expected_id
                ):
                    continue
                key = reaction.get("user_id") or reaction.get("cursor")
                if not key or key in seen:
                    print(
                        f"[Reactions] Bỏ qua người dùng trùng/rỗng: "
                        f"{key or '-'}"
                    )
                    continue
                seen.add(key)
                collected.append(reaction)
                added += 1
                if max_reactions and len(collected) >= max_reactions:
                    print(
                        f"[Reactions] Đạt giới hạn {max_reactions} người."
                    )
                    break

            page_info = page["page_info"]
            cursor = page_info.get("end_cursor")
            print(
                f"[Reactions] Reaction page #{page_number}: +{added} "
                f"(tổng {len(collected)}), "
                f"next={page_info.get('has_next_page')}, "
                f"next_cursor={_short(cursor)}"
            )

            if max_reactions and len(collected) >= max_reactions:
                break
            if not page_info.get("has_next_page") or not cursor:
                break
            if not added:
                print(
                    "[Reactions] Trang không có người mới, dừng để tránh lặp."
                )
                break

            delay = max(0.0, float(page_delay_seconds or 0))
            if delay:
                actual_delay = delay * random.uniform(0.85, 1.35)
                print(
                    f"[Reactions] Nghỉ {actual_delay:.1f}s "
                    "trước request trang tiếp theo..."
                )
                self._wait_between_reaction_pages(actual_delay)
                if self.is_stopped():
                    print(
                        "[Reactions] Đã yêu cầu dừng trong lúc chờ trang sau."
                    )
                    break

        cleaned = []
        for item in dedupe_reactions(collected):
            row = dict(item)
            row.pop("raw_node", None)
            cleaned.append(row)

        counts = {}
        for item in cleaned:
            key = item.get("reaction_type") or "UNKNOWN"
            counts[key] = counts.get(key, 0) + 1
        print(
            f"[Reactions] Hoàn tất quét post {post_id}: "
            f"{len(cleaned)} người, phân loại={counts or '{}'}."
        )
        return cleaned

    def _save_reactions_json(
        self,
        post_id: str,
        reactions: list[dict],
        source_url: str = "",
        reaction_type: str = None,
    ) -> str:
        """Lưu JSON reaction vào ``data/<uid>/raw/reactions_*.json``."""
        scraped_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        cleaned = []
        for reaction in reactions:
            row = dict(reaction)
            row.pop("raw_node", None)
            row.setdefault("scraped_at", scraped_at)
            cleaned.append(row)

        safe_post_id = re.sub(
            r"[^A-Za-z0-9_-]+", "_", str(post_id)
        ).strip("_")
        if not safe_post_id:
            safe_post_id = "post"
        target_dir = self.data_dir or os.path.join(APP_DIR, "data", "raw")
        os.makedirs(target_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(
            target_dir, f"reactions_{safe_post_id}_{timestamp}.json"
        )

        payload = {
            "post_id": str(post_id),
            "source_url": source_url,
            "reaction_type_filter": reaction_type or "ALL",
            "exported_at": scraped_at,
            "reaction_count": len(cleaned),
            "reactions": cleaned,
        }
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
        print(
            f"[Reactions] Đã lưu JSON: {file_path} "
            f"({payload['reaction_count']} người)."
        )
        return file_path

    def scan_post_reactions(
        self,
        post_id: str,
        max_reactions: int | None = None,
        reaction_type: str = None,
        reaction_id: str = None,
        name_query: str = None,
        source_url: str = "",
        save: bool = True,
        export: bool = True,
        page_delay_seconds: float = REACTION_PAGE_DELAY_SECONDS,
    ) -> dict:
        """Quét reaction và (mặc định) lưu JSON + Excel/CSV."""
        reactions = self.collect_post_reactions(
            post_id,
            max_reactions=max_reactions,
            reaction_type=reaction_type,
            reaction_id=reaction_id,
            name_query=name_query,
            page_delay_seconds=page_delay_seconds,
        )
        print(
            f"[Reactions] Chuẩn bị lưu kết quả post {post_id}: "
            f"{len(reactions)} người."
        )
        result = {
            "post_id": str(post_id),
            "source_url": source_url,
            "reaction_type": reaction_type or "ALL",
            "reactions": reactions,
            "json_path": None,
            "export_paths": {},
        }
        if not save:
            print("[Reactions] Bỏ qua lưu file (save=False).")
            return result

        json_path = self._save_reactions_json(
            post_id,
            reactions,
            source_url=source_url,
            reaction_type=reaction_type,
        )
        result["json_path"] = json_path

        if export:
            print("[Reactions] Bắt đầu xuất CSV/XLSX...")
            output_dir = self.exports_dir or os.path.join(
                APP_DIR, "data", "processed"
            )
            result["export_paths"] = export_reactions_to_spreadsheet(
                json_path, output_dir=output_dir
            )
            print(
                f"[Reactions] Xuất xong: "
                f"{result['export_paths'] or 'không có file'}"
            )
        return result

    def scan_post_reactions_from_url(
        self,
        post_url_or_id: str,
        max_reactions: int | None = None,
        reaction_type: str = None,
        reaction_id: str = None,
        name_query: str = None,
        save: bool = True,
        export: bool = True,
        page_delay_seconds: float = REACTION_PAGE_DELAY_SECONDS,
    ) -> dict:
        """Quét reaction từ URL/ID bài viết (hỗ trợ cả Reel)."""
        print(f"[Reactions] Nhận yêu cầu quét từ: {post_url_or_id}")
        post_id = self.resolve_post_feedback_id(
            post_url_or_id, log_prefix="Reactions"
        )
        print(
            f"[Reactions] Dùng post_id={post_id} để gọi GraphQL reactions."
        )
        result = self.scan_post_reactions(
            post_id,
            max_reactions=max_reactions,
            reaction_type=reaction_type,
            reaction_id=reaction_id,
            name_query=name_query,
            source_url=str(post_url_or_id or ""),
            page_delay_seconds=page_delay_seconds,
            save=save,
            export=export,
        )
        result["input"] = str(post_url_or_id or "")
        print(
            f"[Reactions] Xong yêu cầu: "
            f"{len(result.get('reactions') or [])} người, "
            f"JSON={result.get('json_path') or '-'}"
        )
        return result
