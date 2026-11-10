"""Chuyển response GraphQL của Facebook Search thành schema bài viết.

Response mẫu nằm ở ``samples/response.json``. Dữ liệu bài viết không nằm
trực tiếp ở ``edge.node`` mà nằm trong
``edge.rendering_strategy.view_model``. Với kết quả PUBLIC_POSTS, story nằm ở
``view_model.click_model.story``; với ads, story nằm ở ``view_model.story``.

Facebook dùng nhiều role cho cùng một loại bài viết tuỳ luồng tìm kiếm:
``PUBLIC_POSTS`` (tab Bài viết) và ``TOP_PUBLIC_POSTS`` (tab Bài đăng gần đây).
"""

from __future__ import annotations

import datetime as _datetime
import re
from typing import Any, Iterable

GROUP_ID_RE = re.compile(r"/groups/(\d+)")
POST_ID_RE = re.compile(r"(?:/posts/|story_fbid=|multi_permalinks=)(\d+)")
POST_ROLES = frozenset({"PUBLIC_POSTS", "TOP_PUBLIC_POSTS"})
MESSAGE_PATHS = (
    ("message",),
    ("comet_sections", "content", "story", "comet_sections", "message", "story", "message"),
    ("comet_sections", "content", "story", "message"),
    ("comet_sections", "content", "story", "comet_sections", "message", "story"),
)


def _get_path(node: Any, path: Iterable[str]) -> Any:
    current = node
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _iter_dicts(node: Any):
    """Duyệt toàn bộ dict con theo chiều sâu, không cần đệ quy sâu."""
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            yield current
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def _text_from_message(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if not isinstance(value, dict):
        return None
    text = value.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return None


def _first_message_text(story: dict) -> str | None:
    for path in MESSAGE_PATHS:
        text = _text_from_message(_get_path(story, path))
        if text:
            return text

    # Fallback cho các biến thể story không theo đúng cấu trúc trên.
    for node in _iter_dicts(story):
        message = node.get("message")
        text = _text_from_message(message)
        if text:
            return text
    return None


def _first_dict_with_count(story: dict, key: str) -> dict | None:
    for node in _iter_dicts(story):
        value = node.get(key)
        if isinstance(value, dict):
            count = value.get("count")
            if isinstance(count, bool):
                continue
            if isinstance(count, (int, float)):
                return {"count": int(count)}
            if isinstance(count, str) and count.strip().lstrip('-').isdigit():
                return {"count": int(count.strip())}
            i18n = value.get("i18n_count") or value.get("i18n_share_count") or value.get("i18n_reaction_count")
            if i18n:
                return {"count": None, "i18n_count": i18n}
    # also try direct paths
    for path in (
        ("feedback", "reaction_count"),
        ("feedback", "comment_count"),
        ("feedback", "share_count"),
        ("comet_sections", "feedback", "story", "feedback", "reaction_count"),
        ("comet_sections", "feedback", "story", "feedback", "share_count"),
    ):
        v = _get_path(story, path)
        if isinstance(v, dict):
            count = v.get("count")
            if isinstance(count, (int, float)) and not isinstance(count, bool):
                return {"count": int(count)}
    return None


def _comment_count(story: dict) -> dict | None:
    for node in _iter_dicts(story):
        instance = node.get("comment_rendering_instance")
        if isinstance(instance, dict):
            comments = instance.get("comments")
            if isinstance(comments, dict):
                total = comments.get("total_count")
                if isinstance(total, bool):
                    continue
                if isinstance(total, (int, float)):
                    return {"count": int(total)}
        comments = node.get("comments")
        if isinstance(comments, dict):
            total = comments.get("total_count")
            if isinstance(total, bool):
                continue
            if isinstance(total, (int, float)):
                return {"count": int(total)}
    # direct
    for path in (
        ("feedback", "comment_rendering_instance", "comments", "total_count"),
        ("feedback", "total_comment_count"),
    ):
        v = _get_path(story, path)
        if isinstance(v, bool): continue
        if isinstance(v, (int, float)):
            return {"count": int(v)}
    return None


def _extract_author(story: dict) -> tuple[str | None, str | None]:
    actors = story.get("actors")
    if isinstance(actors, list):
        for actor in actors:
            if not isinstance(actor, dict):
                continue
            name = actor.get("name")
            url = actor.get("url")
            if name:
                return str(name).strip(), url if isinstance(url, str) else None
    owning = _get_path(story, ("feedback", "owning_profile"))
    if isinstance(owning, dict) and owning.get("name"):
        return str(owning["name"]).strip(), None
    # try deeper
    for node in _iter_dicts(story):
        if node.get("name") and node.get("__typename") in ("User", "Page"):
            # prefer actor-like
            if node.get("url") or "profile_picture" in node:
                return str(node.get("name")).strip(), node.get("url") if isinstance(node.get("url"), str) else None
    return None, None


def _extract_group_id(story: dict, fallback_group_id: str | None = None) -> str | None:
    to = story.get("to")
    if isinstance(to, dict) and to.get("__typename") == "Group" and to.get("id"):
        return str(to["id"])

    associated = _get_path(story, ("feedback", "associated_group"))
    if isinstance(associated, dict) and associated.get("id"):
        return str(associated["id"])

    for key in ("permalink_url", "url"):
        value = story.get(key)
        if isinstance(value, str):
            match = GROUP_ID_RE.search(value)
            if match:
                return match.group(1)

    # walk
    for node in _iter_dicts(story):
        if isinstance(node.get("id"), str) and node.get("__typename") == "Group":
            # check context
            if node.get("name") or "group" in str(node).lower():
                # but could be elsewhere; only take if near context
                pass
    return fallback_group_id


def _extract_permalink(story: dict, group_id: str | None, post_id: str | None) -> str | None:
    for path in (
        ("permalink_url",),
        ("url",),
        ("shareable_from_perspective_of_feed_ufi", "url"),
        ("shareable_from_perspective_of_feed_ufi", "permalink_url"),
        ("feedback", "url"),
        ("feedback", "permalink_url"),
        ("comet_sections", "content", "story", "permalink_url"),
        ("comet_sections", "content", "story", "url"),
        ("comet_sections", "content", "story", "comet_sections", "message", "story", "permalink_url"),
        ("comet_sections", "content", "story", "comet_sections", "message", "story", "url"),
    ):
        value = _get_path(story, path)
        if isinstance(value, str) and value.strip().startswith("http"):
            return value.strip()

    if group_id and post_id:
        return f"https://www.facebook.com/groups/{group_id}/posts/{post_id}/"
    if post_id:
        return f"https://www.facebook.com/posts/{post_id}/"
    return None


def _media_urls_from_attachment(attachment: dict) -> tuple[str | None, list[str]]:
    """Trả về (media_type, urls) cho một attachment GraphQL."""
    media_nodes: list[dict] = []
    styles = attachment.get("styles")
    if isinstance(styles, dict):
        style_attachment = styles.get("attachment")
        if isinstance(style_attachment, dict):
            media = style_attachment.get("media")
            if isinstance(media, dict):
                media_nodes.append(media)
            album = style_attachment.get("all_subattachments")
            if isinstance(album, dict):
                for item in album.get("nodes") or []:
                    if isinstance(item, dict) and isinstance(item.get("media"), dict):
                        media_nodes.append(item["media"])

    direct_media = attachment.get("media")
    if isinstance(direct_media, dict):
        media_nodes.append(direct_media)

    media_type = None
    urls: list[str] = []
    for media in media_nodes:
        typename = str(media.get("__typename") or "").lower()
        if typename == "video" or media.get("is_playable"):
            media_type = "video"
        elif typename == "photo" and media_type is None:
            media_type = "image"

        for key in ("playable_url_quality_hd", "playable_url", "video_url"):
            value = media.get(key)
            if isinstance(value, str) and value.startswith("http") and value not in urls:
                urls.append(value)
                media_type = "video"

        for key in ("photo_image", "image", "viewer_image"):
            image = media.get(key)
            if not isinstance(image, dict):
                continue
            for uri_key in ("uri", "url"):
                value = image.get(uri_key)
                if isinstance(value, str) and value.startswith("http") and value not in urls:
                    urls.append(value)
                    if media_type is None:
                        media_type = "image"

    return media_type, urls


def _extract_media(story: dict) -> tuple[str, list[str]]:
    attachments = story.get("attachments")
    if not isinstance(attachments, list):
        attachments = []

    nested = _get_path(story, ("comet_sections", "content", "story", "attachments"))
    if isinstance(nested, list):
        attachments = list(attachments) + nested

    media_type = None
    urls: list[str] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        current_type, current_urls = _media_urls_from_attachment(attachment)
        if current_type == "video":
            media_type = "video"
        elif current_type == "image" and media_type != "video":
            media_type = "image"
        for url in current_urls:
            if url not in urls:
                urls.append(url)

    if media_type:
        return media_type, urls

    shareable = story.get("shareable")
    if isinstance(shareable, dict) and shareable.get("__typename") == "ExternalUrl":
        return "link", []

    return "text", urls


def _published_at(story: dict) -> str | None:
    timestamp = story.get("creation_time")
    if timestamp is None:
        timestamp = _get_path(story, ("comet_sections", "timestamp", "story", "creation_time"))
    if timestamp is None:
        timestamp = _get_path(story, ("timestamp", "story", "creation_time"))
    if isinstance(timestamp, bool):
        return None
    if isinstance(timestamp, (int, float)):
        try:
            return _datetime.datetime.fromtimestamp(
                int(timestamp), tz=_datetime.timezone.utc
            ).isoformat().replace("+00:00", "Z")
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _source_name(story: dict, author_name: str | None) -> str | None:
    to = story.get("to")
    if isinstance(to, dict) and to.get("__typename") == "Group" and to.get("name"):
        return str(to["name"]).strip()
    owning = _get_path(story, ("feedback", "owning_profile"))
    if isinstance(owning, dict) and owning.get("name"):
        return str(owning["name"]).strip()
    return author_name


def parse_graphql_post(
    story: dict[str, Any],
    *,
    scope: str = "search",
    fallback_group_id: str | None = None,
) -> dict[str, Any] | None:
    """Chuẩn hóa một story GraphQL thành cùng schema với DOM extractor."""
    if not isinstance(story, dict):
        return None

    post_id = story.get("post_id")
    post_id = str(post_id) if post_id not in (None, "") else None
    group_id = _extract_group_id(story, fallback_group_id)
    author_name, author_url = _extract_author(story)
    content = _first_message_text(story)
    media_type, media_urls = _extract_media(story)

    return {
        "post_id": post_id,
        "group_id": group_id,
        "scope": scope,
        "author_name": author_name,
        "author_url": author_url,
        "source_name": _source_name(story, author_name),
        "content": content,
        "content_truncated": False,
        "media_type": media_type,
        "media_urls": media_urls,
        "reactions": _first_dict_with_count(story, "reaction_count"),
        "comments": _comment_count(story),
        "shares": _first_dict_with_count(story, "share_count"),
        "published_at": _published_at(story),
        "permalink": _extract_permalink(story, group_id, post_id),
    }


def extract_posts_from_graphql_response(
    payload: dict[str, Any],
    *,
    scope: str = "search",
    fallback_group_id: str | None = None,
) -> list[dict[str, Any]]:
    """Lấy các bài PUBLIC_POSTS/TOP_PUBLIC_POSTS từ response GraphQL."""
    if not isinstance(payload, dict):
        return []

    posts: list[dict[str, Any]] = []

    # Handle NDJSON/streaming responses - payload might have extensions.ndjson_objects
    # or be wrapped differently
    data = payload.get("data") if "data" in payload else payload

    # Group feed: data.node.group_feed.edges[].node (Story)
    if isinstance(data, dict):
        group_feed = _get_path(data, ("node", "group_feed")) or _get_path(
            data, ("group", "group_feed")
        )
        if isinstance(group_feed, dict):
            for edge in group_feed.get("edges") or []:
                if not isinstance(edge, dict):
                    continue
                story = edge.get("node")
                if not isinstance(story, dict):
                    continue
                t = story.get("__typename") or ""
                if t in ("GroupsSectionHeaderUnit", "GroupsFeedUnitHeader", "GroupsCometFeedUnitHeader", "GroupsSectionHeader"):
                    continue
                if t and t != "Story":
                    continue
                post = parse_graphql_post(
                    story, scope=scope, fallback_group_id=fallback_group_id
                )
                if post:
                    posts.append(post)
            if posts:
                return posts

        # Check if this is a streamed response with labeled data
        if payload.get("label") and payload.get("data"):
            labeled_data = payload.get("data")
            if isinstance(labeled_data, dict):
                node = labeled_data.get("node")
                if isinstance(node, dict) and node.get("__typename") == "Story":
                    post = parse_graphql_post(
                        node, scope=scope, fallback_group_id=fallback_group_id
                    )
                    if post:
                        posts.append(post)
                        return posts

    # Also check root payload for labeled entries
    if payload.get("label") and "GroupsCometFeedRegularStories" in str(payload.get("label", "")):
        labeled_data = payload.get("data")
        if isinstance(labeled_data, dict):
            node = labeled_data.get("node")
            if isinstance(node, dict):
                post = parse_graphql_post(
                    node, scope=scope, fallback_group_id=fallback_group_id
                )
                if post:
                    posts.append(post)
                    return posts

    results = _get_path(data, ("serpResponse", "results"))
    if isinstance(results, dict):
        for edge in results.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            node = edge.get("node")
            if not isinstance(node, dict) or node.get("role") not in POST_ROLES:
                continue

            view_model = _get_path(edge, ("rendering_strategy", "view_model"))
            if not isinstance(view_model, dict):
                continue

            click_model = view_model.get("click_model")
            story = None
            if isinstance(click_model, dict):
                story = click_model.get("story")
            if not isinstance(story, dict):
                story = view_model.get("story")
            if not isinstance(story, dict):
                continue

            post = parse_graphql_post(
                story, scope=scope, fallback_group_id=fallback_group_id
            )
            if post:
                posts.append(post)
        if posts:
            return posts

    return posts
