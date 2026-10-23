"""Chuẩn hóa danh sách người thả reaction/like từ GraphQL Facebook.

Response mẫu nằm trong ``samples/reactions/reactions-all.json``. Module này
chỉ parse response thô, không gọi mạng và không phụ thuộc Selenium.
"""

from __future__ import annotations

import json

from services.comment_extractor import decode_global_id


class ReactionParseError(ValueError):
    """Response GraphQL không đúng cấu trúc danh sách reaction."""


# Facebook đã đổi tên reaction CARE thành SUPPORT nhưng vẫn dùng chung ID.
REACTION_TYPE_ALIASES = {"SUPPORT": "CARE"}


def normalize_reaction_type(value) -> str:
    """Chuẩn hóa tên reaction, gộp SUPPORT/CARE về cùng một loại."""
    key = str(value or "").strip().upper()
    return REACTION_TYPE_ALIASES.get(key, key)


def _to_int(value):
    """Đổi count GraphQL về int, trả ``None`` nếu không hợp lệ."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, dict):
        return _to_int(value.get("count"))
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _feedback_post_id(global_id) -> str:
    """Lấy post ID từ Global ID ``feedback:<post_id>``."""
    decoded = decode_global_id(global_id)
    if not decoded.startswith("feedback:"):
        return ""
    return decoded.split(":", 1)[1].split("_", 1)[0]


def parse_reaction_edge(edge: dict, post_id: str = "") -> dict | None:
    """Chuẩn hóa một edge ``reactors.edges``.

    Trả ``None`` nếu edge không có node người dùng (Facebook thỉnh thoảng
    trả edge rỗng ở cuối danh sách).
    """
    if not isinstance(edge, dict):
        raise ReactionParseError("Reaction edge không phải object.")

    user = edge.get("node") or {}
    if not isinstance(user, dict) or not user:
        return None

    reaction_info = (
        edge.get("feedback_reaction_info")
        or edge.get("reaction_info")
        or {}
    )
    if not isinstance(reaction_info, dict):
        reaction_info = {}

    reaction_type = str(reaction_info.get("reaction_type") or "").upper()
    reaction_type_id = str(reaction_info.get("id") or "")
    face_image = reaction_info.get("face_image") or {}
    reaction_icon_url = (
        face_image.get("uri") if isinstance(face_image, dict) else ""
    ) or ""

    profile_picture = user.get("profile_picture") or {}
    profile_picture_url = (
        profile_picture.get("uri")
        if isinstance(profile_picture, dict)
        else ""
    ) or ""

    mutual_friends = user.get("mutual_friends") or {}
    mutual_friends_count = _to_int(
        mutual_friends.get("count")
        if isinstance(mutual_friends, dict)
        else mutual_friends
    )

    return {
        "post_id": str(post_id or ""),
        "user_id": str(user.get("id") or ""),
        "user_name": user.get("name") or "",
        "profile_url": user.get("profile_url") or user.get("url") or "",
        "profile_picture": profile_picture_url,
        "reaction_type": reaction_type,
        "reaction_type_id": reaction_type_id,
        "reaction_icon_url": reaction_icon_url,
        "mutual_friends_count": mutual_friends_count,
        "friendship_status": user.get("friendship_status") or "",
        "subscribe_status": user.get("subscribe_status") or "",
        "cursor": edge.get("cursor") or "",
        "raw_node": user,
    }


def _page_info(value: dict) -> dict:
    page_info = (value or {}).get("page_info") or {}
    return {
        "start_cursor": page_info.get("start_cursor"),
        "end_cursor": page_info.get("end_cursor"),
        "has_previous_page": bool(page_info.get("has_previous_page")),
        "has_next_page": bool(page_info.get("has_next_page")),
    }


def parse_reactions_page(response: dict, post_id: str = "") -> dict:
    """Parse response ``CometUFIReactionsDialogTabContentRefetchQuery``."""
    if not isinstance(response, dict):
        raise ReactionParseError("Response GraphQL không phải object.")
    if response.get("error"):
        raise ReactionParseError(
            f"GraphQL trả lỗi: {response.get('error')}"
        )
    errors = response.get("errors")
    if errors:
        raise ReactionParseError(f"GraphQL trả lỗi: {errors}")

    data = response.get("data")
    if not isinstance(data, dict) or not data.get("node"):
        raise ReactionParseError("Response GraphQL thiếu data.node.")

    node = data["node"]
    reactors = node.get("reactors") or {}
    edges = reactors.get("edges") or []
    resolved_post_id = str(post_id or _feedback_post_id(node.get("id")))

    parsed = []
    for edge in edges:
        item = parse_reaction_edge(edge, post_id=resolved_post_id)
        if item is not None:
            parsed.append(item)

    return {
        "post_id": resolved_post_id,
        "post_feedback_id": node.get("id") or "",
        "reactions": parsed,
        "page_info": _page_info(reactors),
        "reactor_count": _to_int(
            reactors.get("total_count")
            or reactors.get("count")
            or reactors.get("count_reduced")
        ),
        "raw_edge_count": len(edges),
    }


def dedupe_reactions(items: list[dict]) -> list[dict]:
    """Bỏ người dùng trùng ID, giữ lần xuất hiện đầu tiên."""
    seen = set()
    result = []
    for item in items:
        key = item.get("user_id") or item.get("cursor")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def reactions_to_json(items: list[dict]) -> str:
    """Serialize list reaction đã chuẩn hóa, bỏ ``raw_node`` để nhẹ file."""
    cleaned = []
    for item in items:
        row = dict(item)
        row.pop("raw_node", None)
        cleaned.append(row)
    return json.dumps(cleaned, ensure_ascii=False, indent=2)
