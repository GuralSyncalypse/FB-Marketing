import os
import sys
import unittest
from unittest import mock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import bot
from bot import FacebookBot, is_recent_posts_label


class FakeToggle:
    def __init__(self, label="Recent posts", checked=False):
        self.label = label
        self.checked = checked
        self.clicks = 0

    def get_attribute(self, name):
        if name == "aria-label":
            return self.label
        if name == "aria-checked":
            return "true" if self.checked else "false"
        return None

    def click(self):
        self.clicks += 1
        self.checked = True


class FakeParent:
    text = "Recent posts"


class FakeToggleWithoutAria(FakeToggle):
    def __init__(self, checked=False):
        super().__init__(label="", checked=checked)

    def find_element(self, by, selector):
        return FakeParent()


class FakeDriver:
    def __init__(self, toggles):
        self.toggles = list(toggles)

    def find_elements(self, by, selector):
        return list(self.toggles)

    def execute_script(self, script, element):
        element.click()


class RecentPostsLabelTest(unittest.TestCase):
    def test_matches_english_label(self):
        self.assertTrue(is_recent_posts_label("Recent posts"))
        self.assertTrue(is_recent_posts_label("RECENT POSTS"))

    def test_matches_vietnamese_label_with_and_without_accents(self):
        self.assertTrue(is_recent_posts_label("Bài đăng gần đây"))
        self.assertTrue(is_recent_posts_label("Bài viết gần đây"))
        self.assertTrue(is_recent_posts_label("Bai dang gan day"))
        self.assertTrue(is_recent_posts_label("Bài đăng mới nhất"))

    def test_ignores_other_switches(self):
        self.assertFalse(is_recent_posts_label("Posts you've seen"))
        self.assertFalse(is_recent_posts_label("Bài viết đã xem"))


class EnsureRecentPostsToggleTest(unittest.TestCase):
    def setUp(self):
        self.bot = FacebookBot()

    def test_returns_true_when_toggle_already_on(self):
        toggle = FakeToggle(checked=True)
        self.bot.driver = FakeDriver([toggle])

        self.assertTrue(self.bot._ensure_recent_posts_toggle())
        self.assertEqual(toggle.clicks, 0)

    def test_clicks_toggle_when_off(self):
        toggle = FakeToggle(checked=False)
        self.bot.driver = FakeDriver([toggle])

        with mock.patch.object(bot, "RECENT_POSTS_SETTLE_SECONDS", 0):
            self.assertTrue(self.bot._ensure_recent_posts_toggle())

        self.assertEqual(toggle.clicks, 1)
        self.assertTrue(toggle.checked)

    def test_supports_vietnamese_label(self):
        toggle = FakeToggle(label="Bài đăng gần đây", checked=False)
        self.bot.driver = FakeDriver([toggle])

        with mock.patch.object(bot, "RECENT_POSTS_SETTLE_SECONDS", 0):
            self.assertTrue(self.bot._ensure_recent_posts_toggle())

        self.assertEqual(toggle.clicks, 1)

    def test_finds_toggle_from_parent_label(self):
        toggle = FakeToggleWithoutAria(checked=False)
        self.bot.driver = FakeDriver([toggle])

        with mock.patch.object(bot, "RECENT_POSTS_SETTLE_SECONDS", 0):
            self.assertTrue(self.bot._ensure_recent_posts_toggle())

        self.assertEqual(toggle.clicks, 1)

    def test_returns_false_when_toggle_missing(self):
        self.bot.driver = FakeDriver([])

        self.assertFalse(self.bot._ensure_recent_posts_toggle(timeout=0.1))


if __name__ == "__main__":
    unittest.main()
