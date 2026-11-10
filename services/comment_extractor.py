"""Chuẩn hóa dữ liệu bình luận/reply từ GraphQL Facebook.

Response mẫu nằm trong ``samples/comments.json``, ``samples/comments_2.json``
và ``samples/replies.json``. Module này chỉ parse response thô, không gọi
mạng và không phụ thuộc Selenium.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import re


class CommentParseError(ValueError):
    """Response GraphQL không đúng cấu trúc bình luận/reply."""


def decode_global_id(value) -> str:
    """Giải mã Global ID dạng base64 của Facebook, trả chuỗi rỗng nếu lỗi."""
    if not isinstance(value, str) or not value.strip():
        return ""
    text = value.strip()
    try:
        padded = text + "=" * (-len(text) % 4)
        return base64.urlsafe_b64decode(padded).decode("utf-8", "replace")
    except Exception:
        return ""


def feedback_global_id(post_id: str) -> str:
    """Tạo Global ID ``feedback:<post_id>`` để gửi GraphQL."""
    return base64.b64encode(f"feedback:{post_id}".encode("utf-8")).decode("ascii")


def reply_feedback_global_id(post_id: str, parent_comment_id: str) -> str:
    """Tạo Global ID ``feedback:<post_id>_<parent_comment_id>``."""
    return base64.b64encode(
        f"feedback:{post_id}_{parent_comment_id}".encode("utf-8")
    ).decode("ascii")


def _split_feedback_key(global_id) -> tuple[str, str]:
    """Tách Global ID ``feedback:<post>_<comment>`` thành (post, comment)."""
    decoded = decode_global_id(global_id)
    if not decoded.startswith("feedback:"):
        return "", ""
    body = decoded.split(":", 1)[1]
    if "_" not in body:
        return body, ""
    post_id, comment_id = body.split("_", 1)
    return post_id, comment_id


def _split_comment_key(global_id) -> tuple[str, str]:
    """Tách Global ID ``comment:<post>_<comment>`` thành (post, comment)."""
    decoded = decode_global_id(global_id)
    if not decoded.startswith("comment:"):
        return "", ""
    body = decoded.split(":", 1)[1]
    if "_" not in body:
        return body, ""
    post_id, comment_id = body.split("_", 1)
    return post_id, comment_id


def _to_int(value):
    """Đổi count GraphQL (int/chuỗi, có thể rút gọn 1.2K) về int."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, dict):
        return _to_int(value.get("count"))
    if not isinstance(value, str):
        return None

    text = value.strip().replace(",", "").replace(".", "")
    if text.isdigit():
        return int(text)

    match = re.match(r"^([0-9]+(?:[.,][0-9]+)?)\s*([KkMmBbNn]?)$", value.strip())
    if not match:
        return None
    number = float(match.group(1).replace(",", "."))
    multiplier = {
        "k": 1_000,
        "m": 1_000_000,
        "b": 1_000_000_000,
        "n": 1_000,
    }.get(match.group(2).lower(), 1)
    return int(number * multiplier)


def _timestamp_to_iso(value):
    if isinstance(value, bool) or value is None:
        return ""
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return ""
    try:
        return dt.datetime.fromtimestamp(
            timestamp, tz=dt.timezone.utc
        ).isoformat()
    except (OverflowError, OSError, ValueError):
        return ""


def _reaction_count(node: dict) -> int | None:
    feedback = node.get("feedback") or {}
    reactors = feedback.get("reactors") or {}
    for key in ("count_reduced", "count", "total_count"):
        count = _to_int(reactors.get(key))
        if count is not None:
            return count

    # Fallback: một số response không trả reactors ở feedback chính mà chỉ
    # trả trong comment_action_links[].comment.feedback.reactors.
    for action in node.get("comment_action_links") or []:
        if not isinstance(action, dict):
            continue
        linked_comment = action.get("comment") or {}
        linked_feedback = linked_comment.get("feedback") or {}
        count = _to_int((linked_feedback.get("reactors") or {}).get("count_reduced"))
        if count is not None:
            return count
    return None


def _attachment_urls(attachments) -> list[str]:
    """Lấy URL media từ danh sách attachment (schema có thể thay đổi)."""
    urls = []

    def visit(value):
        if isinstance(value, dict):
            uri = value.get("uri")
            url = value.get("url")
            if isinstance(uri, str) and uri.startswith("http"):
                urls.append(uri)
            elif isinstance(url, str) and url.startswith("http"):
                urls.append(url)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(attachments)
    # Giữ thứ tự xuất hiện nhưng bỏ URL trùng.
    return list(dict.fromkeys(urls))


def parse_comment_node(
    node: dict,
    post_id: str = "",
    parent_comment_id: str | None = None,
) -> dict:
    """Chuẩn hóa một node comment/reply GraphQL."""
    if not isinstance(node, dict):
        raise CommentParseError("Comment node không phải object.")

    node_post_id, node_comment_id = _split_comment_key(node.get("id"))
    feedback = node.get("feedback") or {}
    feedback_post_id, feedback_comment_id = _split_feedback_key(feedback.get("id"))

    resolved_post_id = str(post_id or node_post_id or feedback_post_id or "")
    comment_id = str(
        node.get("legacy_fbid")
        or node_comment_id
        or feedback_comment_id
        or ""
    )

    author = node.get("author") or {}
    body = node.get("body") or {}
    preferred_body = node.get("preferred_body") or {}
    direct_parent = node.get("comment_direct_parent") or {}
    parent_decoded_id = decode_global_id(direct_parent.get("id"))
    parent_id = str(parent_comment_id or "")
    if not parent_id and parent_decoded_id:
        parent_id = parent_decoded_id.rsplit("_", 1)[-1].split(":", 1)[-1]

    replies_fields = feedback.get("replies_fields") or {}
    expansion_info = feedback.get("expansion_info") or {}
    attachments = node.get("attachments") or []
    attachment_urls = _attachment_urls(attachments)
    depth = node.get("depth")
    try:
        depth = int(depth) if depth is not None else (1 if parent_id else 0)
    except (TypeError, ValueError):
        depth = 1 if parent_id else 0

    return {
        "post_id": resolved_post_id,
        "comment_id": comment_id,
        "parent_comment_id": parent_id,
        "depth": depth,
        "is_reply": depth > 0 or bool(parent_id),
        "author_id": str(author.get("id") or ""),
        "author_name": author.get("name") or "",
        "author_url": author.get("url") or "",
        "author_profile_picture": (
            (author.get("profile_picture_depth_1") or {}).get("uri")
            or (author.get("profile_picture_depth_0") or {}).get("uri")
            or ""
        ),
        "content": body.get("text")
        if body.get("text") is not None
        else (preferred_body.get("text") or ""),
        "source_dialect": (
            (node.get("translatability_for_viewer") or {}).get("source_dialect")
            or ""
        ),
        "reaction_count": _reaction_count(node),
        "reply_count": _to_int(replies_fields.get("total_count"))
        if replies_fields.get("total_count") is not None
        else _to_int(replies_fields.get("count")),
        "created_time": node.get("created_time"),
        "created_at": _timestamp_to_iso(node.get("created_time")),
        "permalink": feedback.get("url") or "",
        "attachments": attachments,
        "attachment_urls": attachment_urls,
        "attachment_count": len(attachment_urls),
        "expansion_token": expansion_info.get("expansion_token") or "",
        "is_hidden_by_viewer": bool(node.get("is_hidden_by_viewer")),
        "is_disabled": bool(node.get("is_disabled")),
        "global_id": node.get("id") or "",
        "feedback_id": feedback.get("id") or "",
        "raw_node": node,
    }


def _response_data(response: dict) -> dict:
    if not isinstance(response, dict):
        raise CommentParseError("Response GraphQL không phải object.")
    if response.get("error"):
        raise CommentParseError(
            f"GraphQL trả lỗi: {response.get('error')}"
        )
    data = response.get("data")
    if not isinstance(data, dict) or not data.get("node"):
        raise CommentParseError("Response GraphQL thiếu data.node.")
    return data["node"]


def _page_info(value: dict) -> dict:
    page_info = (value or {}).get("page_info") or {}
    return {
        "start_cursor": page_info.get("start_cursor"),
        "end_cursor": page_info.get("end_cursor"),
        "has_previous_page": bool(page_info.get("has_previous_page")),
        "has_next_page": bool(page_info.get("has_next_page")),
    }


def parse_comments_page(response: dict) -> dict:
    """Parse response ``CommentsListComponentsPaginationQuery``."""
    node = _response_data(response)
    comments = (
        (node.get("comment_rendering_instance_for_feed_location") or {}).get(
            "comments"
        )
        or {}
    )
    edges = comments.get("edges") or []
    post_id, _ = _split_feedback_key(node.get("id"))

    parsed = []
    for edge in edges:
        comment_node = (edge or {}).get("node") if isinstance(edge, dict) else None
        if comment_node:
            parsed.append(parse_comment_node(comment_node, post_id=post_id))

    return {
        "post_id": post_id,
        "post_feedback_id": node.get("id") or "",
        "comments": parsed,
        "page_info": _page_info(comments),
        "comment_count": _to_int(comments.get("total_count")),
        "raw_edge_count": len(edges),
        "behind_the_fold_subtext": comments.get("behind_the_fold_subtext") or "",
    }


def parse_replies_page(
    response: dict,
    post_id: str = "",
    parent_comment_id: str = "",
) -> dict:
    """Parse response ``Depth1CommentsListPaginationQuery``."""
    node = _response_data(response)
    replies_connection = node.get("replies_connection") or {}
    edges = replies_connection.get("edges") or []
    resolved_post_id = str(post_id or "")
    resolved_parent_id = str(parent_comment_id or "")

    parsed = []
    for edge in edges:
        reply_node = (edge or {}).get("node") if isinstance(edge, dict) else None
        if not reply_node:
            continue
        item = parse_comment_node(
            reply_node,
            post_id=resolved_post_id,
            parent_comment_id=resolved_parent_id or None,
        )
        if not resolved_post_id:
            resolved_post_id = item.get("post_id") or ""
        parsed.append(item)

    return {
        "post_id": resolved_post_id,
        "parent_comment_id": resolved_parent_id,
        "replies": parsed,
        "page_info": _page_info(replies_connection),
        "raw_edge_count": len(edges),
        "behind_the_fold_subtext": (
            replies_connection.get("behind_the_fold_subtext") or ""
        ),
    }


def dedupe_comments(items: list[dict]) -> list[dict]:
    """Bỏ comment/reply trùng ID, giữ lần xuất hiện đầu tiên."""
    seen = set()
    result = []
    for item in items:
        key = item.get("comment_id") or item.get("global_id")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def comments_to_json(items: list[dict]) -> str:
    """Serialize list comment đã chuẩn hóa, bỏ ``raw_node`` để nhẹ file."""
    cleaned = []
    for item in items:
        row = dict(item)
        row.pop("raw_node", None)
        cleaned.append(row)
    return json.dumps(cleaned, ensure_ascii=False, indent=2)
