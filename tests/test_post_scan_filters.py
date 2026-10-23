import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import bot
from bot import (
    FacebookBot,
    _normalize_post_type,
    _normalize_time_range,
    _parse_published_at,
    _post_matches_filters,
)
from selenium.webdriver.common.keys import Keys


NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


class NormalizeFilterTest(unittest.TestCase):
    def test_time_range_labels_and_keys(self):
        self.assertEqual(_normalize_time_range("24 giờ gần đây"), 24)
        self.assertEqual(_normalize_time_range("7 ngày gần đây"), 168)
        self.assertEqual(_normalize_time_range("30 ngày gần đây"), 720)
        self.assertEqual(_normalize_time_range("24h"), 24)
        self.assertEqual(_normalize_time_range("7d"), 168)
        self.assertEqual(_normalize_time_range("30d"), 720)
        self.assertIsNone(_normalize_time_range("Không giới hạn"))
        self.assertIsNone(_normalize_time_range("all"))
        self.assertIsNone(_normalize_time_range(""))

    def test_post_type_labels_and_keys(self):
        self.assertIsNone(_normalize_post_type("Tất cả"))
        self.assertIsNone(_normalize_post_type("all"))
        self.assertEqual(
            _normalize_post_type("Bài có ảnh/video"), frozenset({"image", "video"})
        )
        self.assertEqual(_normalize_post_type("media"), frozenset({"image", "video"}))
        self.assertEqual(_normalize_post_type("Bài có link"), frozenset({"link"}))
        self.assertEqual(_normalize_post_type("Bài văn bản"), frozenset({"text"}))

    def test_parse_published_at(self):
        self.assertEqual(
            _parse_published_at("2026-10-22T09:25:11+00:00"),
            datetime(2026, 10, 22, 9, 25, 11, tzinfo=timezone.utc),
        )
        self.assertEqual(
            _parse_published_at("2026-10-22T09:25:11Z"),
            datetime(2026, 10, 22, 9, 25, 11, tzinfo=timezone.utc),
        )
        self.assertEqual(
            _parse_published_at(1792661111),
            datetime(2026, 10, 22, 9, 25, 11, tzinfo=timezone.utc),
        )
        self.assertIsNone(_parse_published_at(None))
        self.assertIsNone(_parse_published_at("not-a-date"))


class PostMatchesFiltersTest(unittest.TestCase):
    def test_post_type_filter(self):
        image_post = {"media_type": "image", "published_at": None}
        text_post = {"media_type": "text", "published_at": None}

        self.assertTrue(_post_matches_filters(image_post))
        self.assertTrue(
            _post_matches_filters(image_post, post_type=frozenset({"image", "video"}))
        )
        self.assertFalse(
            _post_matches_filters(text_post, post_type=frozenset({"image", "video"}))
        )
        self.assertTrue(
            _post_matches_filters(text_post, post_type=frozenset({"text"}))
        )

    def test_time_range(self):
        recent = {
            "media_type": "image",
            "published_at": (NOW - timedelta(hours=23)).isoformat(),
        }
        old = {
            "media_type": "image",
            "published_at": (NOW - timedelta(hours=25)).isoformat(),
        }
        unknown = {"media_type": "image", "published_at": None}

        self.assertTrue(
            _post_matches_filters(recent, time_range_hours=24, now=NOW)
        )
        self.assertFalse(_post_matches_filters(old, time_range_hours=24, now=NOW))
        self.assertFalse(
            _post_matches_filters(unknown, time_range_hours=24, now=NOW)
        )
        self.assertTrue(_post_matches_filters(unknown, time_range_hours=None))


class GraphQLFilterPaginationTest(unittest.TestCase):
    def test_continues_paging_when_page_is_filtered_out(self):
        pages = [
            {
                "data": {
                    "serpResponse": {
                        "results": {
                            "page_info": {
                                "has_next_page": True,
                                "end_cursor": "CUR2",
                            }
                        }
                    }
                }
            },
            {
                "data": {
                    "serpResponse": {
                        "results": {
                            "page_info": {
                                "has_next_page": False,
                                "end_cursor": None,
                            }
                        }
                    }
                }
            },
        ]
        old_post = {
            "post_id": "old",
            "group_id": None,
            "media_type": "image",
            "published_at": (NOW - timedelta(days=10)).isoformat(),
        }
        new_post = {
            "post_id": "new",
            "group_id": None,
            "media_type": "image",
            "published_at": (NOW - timedelta(hours=1)).isoformat(),
        }

        class PagingBot(FacebookBot):
            def __init__(self):
                self.driver = None
                self.pages = list(pages)
                self.calls = 0

            def is_stopped(self):
                return False

            def fetch_search_posts(self, keyword, **kwargs):
                self.calls += 1
                return self.pages.pop(0)

        worker = PagingBot()
        with mock.patch(
            "bot.extract_posts_from_graphql_response",
            side_effect=[[old_post], [new_post]],
        ), mock.patch("builtins.open", mock.mock_open()), mock.patch(
            "bot.time.sleep"
        ), mock.patch("bot.random.uniform", return_value=0):
            posts = worker._collect_search_posts_from_graphql(
                "python",
                max_posts=1,
                time_range_hours=24,
                now=NOW,
            )

        self.assertEqual([post["post_id"] for post in posts], ["new"])
        self.assertEqual(worker.calls, 2)


class FakeSearchElement:
    def __init__(self, driver, kind, label=""):
        self.driver = driver
        self.kind = kind
        self.label = label
        self.text = label
        self.clicks = 0
        self.sent_keys = []

    def is_displayed(self):
        return True

    def is_enabled(self):
        return True

    def get_attribute(self, name):
        if name == "aria-label":
            return self.label
        return None

    def click(self):
        self.clicks += 1
        if self.kind == "tab":
            self.driver.current_url = (
                "https://www.facebook.com/search/posts/?q=python"
            )

    def send_keys(self, *keys):
        self.sent_keys.extend(keys)
        if self.kind == "search" and Keys.ENTER in keys:
            self.driver.current_url = (
                "https://www.facebook.com/search/top/?q=python"
            )


class FakeSearchDriver:
    def __init__(self):
        self.current_url = "https://www.facebook.com/me"
        self.search_bar = FakeSearchElement(self, "search", "Search Facebook")
        self.posts_tab = FakeSearchElement(self, "tab", "Posts")

    def find_elements(self, by, selector):
        if "/search/posts" in selector:
            return [self.posts_tab]
        if "search" in selector:
            return [self.search_bar]
        if "role='link'" in selector or "role='tab'" in selector:
            return [self.posts_tab]
        return []

    def execute_script(self, script, element):
        if "click" in script:
            element.click()


class FakeSearchDriverNoPostsTab(FakeSearchDriver):
    def find_elements(self, by, selector):
        if "/search/posts" in selector:
            return []
        if "role='link'" in selector or "role='tab'" in selector:
            return []
        return super().find_elements(by, selector)


class SearchBarFlowTest(unittest.TestCase):
    def test_searches_from_search_bar_then_opens_posts_tab(self):
        worker = FacebookBot()
        driver = FakeSearchDriver()
        worker.driver = driver

        self.assertTrue(worker._search_via_search_bar("python"))

        self.assertIn("python", driver.search_bar.sent_keys)
        self.assertEqual(driver.posts_tab.clicks, 1)
        self.assertIn("/search/posts", driver.current_url)

    def test_uses_all_search_page_when_posts_tab_is_absent(self):
        # UI mới của Facebook có sidebar Filters/All, không có tab Bài viết.
        worker = FacebookBot()
        driver = FakeSearchDriverNoPostsTab()
        worker.driver = driver

        self.assertTrue(worker._search_via_search_bar("python", timeout=1))

        self.assertIn("python", driver.search_bar.sent_keys)
        self.assertIn("/search/top", driver.current_url)


if __name__ == "__main__":
    unittest.main()
