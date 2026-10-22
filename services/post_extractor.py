"""Trích xuất bài viết từ HTML feed của Facebook.

Module này chỉ làm việc với HTML/DOM, không phụ thuộc Selenium để có thể
kiểm thử bằng snapshot trong thư mục ``samples``.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable

from bs4 import BeautifulSoup


AUTHOR_LABEL_RE = re.compile(r"^Actions for this post(?: by (.+))?$")
REACTION_LABEL_RE = re.compile(r"^Like:\s*([\d.,]+(?:\s*[KMB])?)\s+people$", re.IGNORECASE)
COUNT_RE = re.compile(r"^[\d.,]+(?:\s*[KMB])?$", re.IGNORECASE)
TRUNCATED_MARKERS = ("See more", "Xem thêm")

POST_ID_PATTERNS = (
    re.compile(r"multi_permalinks=(\d+)"),
    re.compile(r"set=gm\.(\d+)"),
    re.compile(r"/videos/pcb\.(\d+)"),
    re.compile(r"/posts/(\d+)"),
    re.compile(r"story_fbid=(\d+)"),
    re.compile(r"/permalink/(\d+)"),
)
GROUP_ID_RE = re.compile(r"/groups/(\d+)")
MEDIA_HREF_RE = re.compile(r"(/photo(?:\.php)?/|/photo/|/videos?/|video\.php)", re.IGNORECASE)
EXTERNAL_LINK_RE = re.compile(r"l\.facebook\.com/l\.php", re.IGNORECASE)
PROFILE_HREF_RE = re.compile(r"(/user/|profile\.php)", re.IGNORECASE)


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def _absolute_url(href: str | None) -> str | None:
    if not href:
        return None
    href = href.strip()
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return "https://www.facebook.com" + href
    if href.startswith("http"):
        return href
    return None


def _parse_count(value: str | None) -> int | None:
    """Chuyển '1,2K' / '1.2K' / '67' thành số nguyên."""
    if value is None:
        return None
    text = _clean_text(value).upper().replace(" ", "")
    multiplier = 1
    if text.endswith("K"):
        multiplier = 1_000
        text = text[:-1]
    elif text.endswith("M"):
        multiplier = 1_000_000
        text = text[:-1]
    elif text.endswith("B"):
        multiplier = 1_000_000_000
        text = text[:-1]
    text = text.replace(",", ".")
    try:
        return int(float(text) * multiplier)
    except (TypeError, ValueError):
        return None


def _derive_post_id(hrefs: Iterable[str]) -> str | None:
    for href in hrefs:
        if not href:
            continue
        for pattern in POST_ID_PATTERNS:
            match = pattern.search(href)
            if match:
                return match.group(1)
    return None


def _derive_group_id(hrefs: Iterable[str]) -> str | None:
    for href in hrefs:
        if not href:
            continue
        match = GROUP_ID_RE.search(href)
        if match:
            return match.group(1)
    return None


def _extract_author(wrapper, profile_name: str | None) -> str | None:
    label_nodes = wrapper.select("[aria-label]")
    for node in label_nodes:
        label = _clean_text(node.get("aria-label"))
        match = AUTHOR_LABEL_RE.match(label)
        if match and match.group(1):
            author = _clean_text(match.group(1))
            if author:
                return author

    # Fallback: link cá nhân trong post (không phải link group/page).
    for link in wrapper.select("a[href]"):
        href = link.get("href") or ""
        if not PROFILE_HREF_RE.search(href):
            continue
        label = _clean_text(link.get("aria-label"))
        if label:
            return label
        text = _clean_text(link.get_text(" ", strip=True))
        if text and text != profile_name:
            return text

    return profile_name


def _extract_counts(wrapper) -> tuple[int | None, int | None, int | None]:
    reactions = None
    for node in wrapper.select("[aria-label]"):
        match = REACTION_LABEL_RE.match(_clean_text(node.get("aria-label")))
        if match:
            reactions = _parse_count(match.group(1))
            break

    def count_near(role: str) -> int | None:
        node = wrapper.select_one(f'[data-ad-rendering-role="{role}"]')
        if not node:
            return None
        current = node
        for _ in range(4):
            if current is None:
                break
            for span in current.select("span"):
                text = _clean_text(span.get_text(" ", strip=True))
                if COUNT_RE.fullmatch(text):
                    parsed = _parse_count(text)
                    if parsed is not None:
                        return parsed
            current = current.parent
        return None

    comments = count_near("comment_button")
    shares = count_near("share_button")
    if reactions is None:
        reactions = count_near("like_button")
    return reactions, comments, shares


def _extract_content(wrapper) -> tuple[str | None, bool]:
    node = wrapper.select_one('[data-ad-rendering-role="story_message"]')
    if not node:
        return None, False
    content = _clean_text(node.get_text(" ", strip=True))
    truncated = any(marker in content for marker in TRUNCATED_MARKERS)
    for marker in TRUNCATED_MARKERS:
        content = content.replace(marker, "").strip()
    content = content.rstrip("… ").strip()
    return content or None, truncated


def _extract_media(wrapper) -> tuple[str, list[str]]:
    media_urls: list[str] = []
    has_video = bool(wrapper.select("video"))
    has_image = False
    has_external_link = False

    for link in wrapper.select("a[href]"):
        href = link.get("href") or ""
        if EXTERNAL_LINK_RE.search(href):
            has_external_link = True
            continue
        if not MEDIA_HREF_RE.search(href):
            continue
        absolute = _absolute_url(href)
        if not absolute:
            continue
        if "/video" in href.lower():
            has_video = True
        else:
            has_image = True
        if absolute not in media_urls:
            media_urls.append(absolute)

    if not media_urls:
        message = wrapper.select_one('[data-ad-rendering-role="story_message"]')
        if message:
            for image in message.select("img[src]"):
                src = image.get("src") or ""
                if not src.startswith("http"):
                    continue
                if src not in media_urls:
                    media_urls.append(src)
                has_image = True

    if has_video:
        media_type = "video"
    elif has_image:
        media_type = "image"
    elif has_external_link:
        media_type = "link"
    else:
        media_type = "text"
    return media_type, media_urls


def _extract_permalink(post_id: str | None, group_id: str | None, hrefs: Iterable[str]) -> str | None:
    if post_id and group_id:
        return f"https://www.facebook.com/groups/{group_id}/posts/{post_id}/"
    if post_id:
        for href in hrefs:
            absolute = _absolute_url(href)
            if absolute and re.search(r"(/posts/|story_fbid=|/permalink/)", absolute):
                return absolute
    return None


def parse_post_wrapper(
    wrapper_html: str,
    *,
    scope: str = "groups",
    fallback_group_id: str | None = None,
) -> dict[str, Any] | None:
    """Parse một wrapper bài viết (outerHTML) thành dict."""
    soup = BeautifulSoup(wrapper_html, "html.parser")
    wrapper = soup.find(True)
    if wrapper is None or not wrapper.select_one('[data-ad-rendering-role="story_message"]'):
        return None

    hrefs = [link.get("href") or "" for link in wrapper.select("a[href]")]
    profile_node = wrapper.select_one('[data-ad-rendering-role="profile_name"]')
    profile_name = _clean_text(profile_node.get_text(" ", strip=True)) if profile_node else None
    group_id = _derive_group_id(hrefs) or fallback_group_id
    post_id = _derive_post_id(hrefs)
    author_name = _extract_author(wrapper, profile_name)
    content, truncated = _extract_content(wrapper)
    reactions, comments, shares = _extract_counts(wrapper)
    media_type, media_urls = _extract_media(wrapper)

    author_url = None
    for link in wrapper.select("a[href]"):
        href = link.get("href") or ""
        if not PROFILE_HREF_RE.search(href):
            continue
        label = _clean_text(link.get("aria-label")) or _clean_text(link.get_text(" ", strip=True))
        if label and label == author_name:
            author_url = _absolute_url(href)
            break

    return {
        "post_id": post_id,
        "group_id": group_id,
        "scope": scope,
        "author_name": author_name,
        "author_url": author_url,
        "source_name": profile_name,
        "content": content,
        "content_truncated": truncated,
        "media_type": media_type,
        "media_urls": media_urls,
        "reactions": reactions,
        "comments": comments,
        "shares": shares,
        "published_at": None,
        "permalink": _extract_permalink(post_id, group_id, hrefs),
    }


def extract_posts(
    html: str,
    *,
    scope: str = "groups",
    fallback_group_id: str | None = None,
) -> list[dict[str, Any]]:
    """Trích xuất toàn bộ bài viết từ HTML của một trang feed."""
    soup = BeautifulSoup(html, "html.parser")
    feed = soup.select_one('div[role="feed"]')
    wrappers = []

    if feed is not None:
        for child in feed.find_all(recursive=False):
            if child.select_one('[data-ad-rendering-role="story_message"]'):
                wrappers.append(child)

    # Fallback cho DOM không có role=feed: lấy mỗi story_message một wrapper.
    if not wrappers:
        for message in soup.select('[data-ad-rendering-role="story_message"]'):
            wrapper = message
            while wrapper.parent is not None and len(
                wrapper.parent.select('[data-ad-rendering-role="story_message"]')
            ) == 1:
                wrapper = wrapper.parent
            if wrapper not in wrappers:
                wrappers.append(wrapper)

    posts = []
    for wrapper in wrappers:
        post = parse_post_wrapper(
            str(wrapper), scope=scope, fallback_group_id=fallback_group_id
        )
        if post:
            posts.append(post)
    return posts


def post_key(post: dict[str, Any]) -> str:
    """Khóa chống trùng: ưu tiên group + post id, fallback hash nội dung."""
    post_id = post.get("post_id")
    if post_id:
        return f"{post.get('group_id') or ''}:{post_id}"
    fingerprint = "|".join(
        [
            str(post.get("group_id") or ""),
            str(post.get("author_name") or ""),
            str(post.get("content") or "")[:160],
            str(post.get("media_type") or ""),
        ]
    )
    return "hash:" + hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()


def dedupe_posts(posts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Giữ thứ tự xuất hiện, loại bài trùng khóa."""
    seen: set[str] = set()
    result = []
    for post in posts:
        key = post_key(post)
        if key in seen:
            continue
        seen.add(key)
        result.append(post)
    return result
