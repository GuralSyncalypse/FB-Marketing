import base64
import json
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.comment_extractor import (
    CommentParseError,
    dedupe_comments,
    parse_comments_page,
    parse_replies_page,
)


def load_sample(name):
    path = os.path.join(BASE_DIR, "samples", name)
    if not os.path.exists(path):
        folder = "replies" if "repl" in name else "comments"
        path = os.path.join(BASE_DIR, "samples", folder, name)
    with open(path, encoding="utf-8") as file:
        return json.load(file)


class ParseCommentsTest(unittest.TestCase):
    def test_parse_first_page_matches_sample(self):
        page = parse_comments_page(load_sample("comments.json"))

        self.assertEqual(page["post_id"], "1473471161654707")
        self.assertEqual(len(page["comments"]), 10)
        self.assertTrue(page["page_info"]["has_previous_page"])
        self.assertTrue(page["page_info"]["has_next_page"])

        first = page["comments"][0]
        self.assertEqual(first["comment_id"], "1812644306743133")
        self.assertEqual(first["author_name"], "Vu Anh Lam")
        self.assertEqual(first["author_id"], "100003115068478")
        self.assertEqual(first["reaction_count"], 27)
        self.assertEqual(first["reply_count"], 0)
        self.assertEqual(first["depth"], 0)
        self.assertFalse(first["is_reply"])
        self.assertIn("Tôi ko cười", first["content"])
        self.assertTrue(first["created_at"].startswith("2026-10-22T03:10:46"))

    def test_parse_next_page_uses_current_post(self):
        page = parse_comments_page(load_sample("comments_2.json"))

        self.assertEqual(page["post_id"], "1473471161654707")
        self.assertEqual(len(page["comments"]), 10)
        self.assertEqual(page["comments"][0]["comment_id"], "4530223157219679")

    def test_next_page_cursor_matches_captured_payload(self):
        page = parse_comments_page(load_sample("comments.json"))
        payload_path = os.path.join(
            BASE_DIR, "samples", "comments-payload_2.json"
        )
        if not os.path.exists(payload_path):
            payload_path = os.path.join(
                BASE_DIR,
                "samples",
                "comments",
                "comments-payload_2.json",
            )
        with open(payload_path, encoding="utf-8") as file:
            payload = json.load(file)

        self.assertEqual(
            page["page_info"]["end_cursor"],
            payload["variables"]["commentsAfterCursor"],
        )

    def test_comment_hidden_and_disabled_flags_are_boolean(self):
        page = parse_comments_page(load_sample("comments.json"))

        for comment in page["comments"]:
            self.assertIsInstance(comment["is_hidden_by_viewer"], bool)
            self.assertIsInstance(comment["is_disabled"], bool)

    def test_invalid_response_raises_parse_error(self):
        with self.assertRaises(CommentParseError):
            parse_comments_page({"error": "MISSING_AUTH_TOKENS"})
        with self.assertRaises(CommentParseError):
            parse_comments_page({"data": {}})


class ParseRepliesTest(unittest.TestCase):
    def test_parse_replies_matches_sample(self):
        page = parse_replies_page(
            load_sample("replies.json"),
            post_id="1473471161654707",
            parent_comment_id="1192700106779015",
        )

        self.assertEqual(page["post_id"], "1473471161654707")
        self.assertEqual(page["parent_comment_id"], "1192700106779015")
        self.assertEqual(len(page["replies"]), 4)
        self.assertFalse(page["page_info"]["has_previous_page"])
        self.assertTrue(page["page_info"]["has_next_page"])

        first = page["replies"][0]
        self.assertEqual(first["comment_id"], "1693849645591439")
        self.assertEqual(first["parent_comment_id"], "1192700106779015")
        self.assertEqual(first["depth"], 1)
        self.assertTrue(first["is_reply"])
        self.assertEqual(first["author_name"], "Brownie Chung")
        self.assertEqual(first["reaction_count"], 0)
        self.assertIn("Kim Makasi", first["content"])
        self.assertIn("reply_comment_id=1693849645591439", first["permalink"])

    def test_reply_parent_is_filled_from_direct_parent_when_missing(self):
        page = parse_replies_page(load_sample("replies.json"))

        self.assertEqual(page["replies"][0]["parent_comment_id"], "1192700106779015")

    def test_dedupe_keeps_first_occurrence(self):
        page = parse_comments_page(load_sample("comments.json"))
        items = page["comments"] + page["comments"]

        deduped = dedupe_comments(items)

        self.assertEqual(len(deduped), 10)
        self.assertEqual(
            [item["comment_id"] for item in deduped],
            [item["comment_id"] for item in page["comments"]],
        )


class CommentGlobalIdTest(unittest.TestCase):
    def test_feedback_global_id(self):
        from services.comment_extractor import feedback_global_id

        encoded = feedback_global_id("1473471161654707")
        decoded = base64.b64decode(encoded).decode("utf-8")

        self.assertEqual(decoded, "feedback:1473471161654707")

    def test_reply_feedback_global_id(self):
        from services.comment_extractor import reply_feedback_global_id

        encoded = reply_feedback_global_id(
            "1473471161654707", "1192700106779015"
        )
        decoded = base64.b64decode(encoded).decode("utf-8")

        self.assertEqual(
            decoded,
            "feedback:1473471161654707_1192700106779015",
        )


if __name__ == "__main__":
    unittest.main()
