import copy
import json
import os
import sys
import tempfile
import unittest

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import bot
from bot.comments import export_comments_to_spreadsheet


def load_sample(name):
    path = os.path.join(BASE_DIR, "samples", name)
    if not os.path.exists(path):
        folder = "replies" if "repl" in name else "comments"
        path = os.path.join(BASE_DIR, "samples", folder, name)
    with open(path, encoding="utf-8") as file:
        return json.load(file)


class FakeCommentBot(bot.FacebookBot):
    def __init__(self):
        super().__init__()
        self.comment_requests = []
        self.reply_requests = []
        self.comment_pages = []
        self.reply_page = None

    def fetch_comments_page(self, post_id, cursor=None, count=-1, **kwargs):
        self.comment_requests.append((post_id, cursor, count))
        if not self.comment_pages:
            return {"data": {}}
        return self.comment_pages.pop(0)

    def fetch_replies_page(
        self,
        post_id,
        parent_comment_id,
        expansion_token,
        cursor=None,
        **kwargs,
    ):
        self.reply_requests.append(
            (post_id, parent_comment_id, expansion_token, cursor)
        )
        page = copy.deepcopy(self.reply_page) if self.reply_page else {"data": {}}
        edges = (
            page.get("data", {})
            .get("node", {})
            .get("replies_connection", {})
            .get("edges", [])
        )
        for index, edge in enumerate(edges):
            edge["node"]["legacy_fbid"] = f"{parent_comment_id}{index}"
        return page


class CollectCommentsTest(unittest.TestCase):
    def setUp(self):
        self.worker = FakeCommentBot()
        first_page = load_sample("comments.json")
        second_page = load_sample("comments_2.json")
        second_page["data"]["node"][
            "comment_rendering_instance_for_feed_location"
        ]["comments"]["page_info"]["has_next_page"] = False
        self.worker.comment_pages = [first_page, second_page]

        reply_page = load_sample("replies.json")
        reply_page["data"]["node"]["replies_connection"]["page_info"][
            "has_next_page"
        ] = False
        self.worker.reply_page = reply_page

    def test_collects_both_pages_and_attaches_replies(self):
        comments = self.worker.collect_post_comments(
            "1473471161654707", include_replies=True
        )

        self.assertEqual(len(self.worker.comment_requests), 2)
        self.assertIsNone(self.worker.comment_requests[0][1])
        self.assertEqual(
            self.worker.comment_requests[1][1],
            parse_end_cursor(load_sample("comments.json")),
        )
        self.assertEqual(len(self.worker.reply_requests), 2)
        self.assertEqual(
            {request[1] for request in self.worker.reply_requests},
            {"1481862277212024", "1120631127236271"},
        )

        self.assertEqual(len(comments), 28)
        self.assertEqual(comments[0]["comment_id"], "1812644306743133")
        self.assertEqual(comments[1]["comment_id"], "1481862277212024")
        self.assertTrue(comments[2]["is_reply"])
        self.assertEqual(
            comments[2]["parent_comment_id"], "1481862277212024"
        )

    def test_max_comments_limits_parent_and_replies(self):
        comments = self.worker.collect_post_comments(
            "1473471161654707", include_replies=True, max_comments=2
        )

        self.assertEqual(len(comments), 2)
        self.assertEqual(comments[0]["comment_id"], "1812644306743133")
        self.assertEqual(comments[1]["comment_id"], "1481862277212024")

    def test_max_replies_per_comment(self):
        first_page = load_sample("comments.json")
        first_page["data"]["node"][
            "comment_rendering_instance_for_feed_location"
        ]["comments"]["page_info"]["has_next_page"] = False
        self.worker.comment_pages = [first_page]

        comments = self.worker.collect_post_comments(
            "1473471161654707",
            include_replies=True,
            max_replies_per_comment=2,
        )

        self.assertEqual(len(comments), 14)
        self.assertEqual(
            [item["comment_id"] for item in comments[2:4]],
            ["14818622772120240", "14818622772120241"],
        )

    def test_include_replies_false_does_not_fetch_replies(self):
        comments = self.worker.collect_post_comments(
            "1473471161654707", include_replies=False
        )

        self.assertEqual(len(comments), 20)
        self.assertEqual(self.worker.reply_requests, [])

    def test_scan_saves_json_and_exports_csv_xlsx(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.worker.data_dir = os.path.join(temp_dir, "raw")
            self.worker.exports_dir = os.path.join(temp_dir, "exports")

            result = self.worker.scan_post_comments(
                "1473471161654707",
                include_replies=False,
                max_comments=3,
                source_url="https://www.facebook.com/reel/1/",
            )

            self.assertTrue(os.path.exists(result["json_path"]))
            self.assertEqual(set(result["export_paths"]), {"csv", "xlsx"})
            with open(result["json_path"], encoding="utf-8") as file:
                payload = json.load(file)
            self.assertEqual(payload["post_id"], "1473471161654707")
            self.assertEqual(payload["comment_count"], 3)
            self.assertNotIn("raw_node", payload["comments"][0])

            csv_df = pd.read_csv(
                result["export_paths"]["csv"],
                encoding="utf-8-sig",
                dtype={"comment_id": str},
            )
            self.assertEqual(
                list(csv_df.columns), list(bot.COMMENT_EXPORT_COLUMNS)
            )
            self.assertEqual(len(csv_df), 3)
            self.assertEqual(csv_df.loc[0, "comment_id"], "1812644306743133")
            self.assertEqual(csv_df.loc[0, "reaction_count"], 27)


class ExportCommentsTest(unittest.TestCase):
    def test_exports_comments_from_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = os.path.join(temp_dir, "comments_147.json")
            comments = [
                {
                    "post_id": "147",
                    "comment_id": "181",
                    "parent_comment_id": "",
                    "depth": 0,
                    "is_reply": False,
                    "author_id": "100",
                    "author_name": "Nguyễn Văn A",
                    "author_url": "https://facebook.com/a",
                    "content": "Nội dung bình luận",
                    "reaction_count": 27,
                    "reply_count": 1,
                    "created_at": "2026-10-22T03:10:46+00:00",
                    "permalink": "https://facebook.com/reel/1/?comment_id=181",
                    "attachment_urls": ["https://example.com/a.jpg"],
                    "scraped_at": "2026-10-23T10:00:00",
                }
            ]
            with open(json_path, "w", encoding="utf-8") as file:
                json.dump(
                    {"post_id": "147", "comment_count": 1, "comments": comments},
                    file,
                    ensure_ascii=False,
                )

            paths = export_comments_to_spreadsheet(
                json_path, output_dir=temp_dir
            )

            self.assertEqual(set(paths), {"csv", "xlsx"})
            csv_df = pd.read_csv(
                paths["csv"], encoding="utf-8-sig", dtype={"comment_id": str}
            )
            self.assertEqual(
                list(csv_df.columns), list(bot.COMMENT_EXPORT_COLUMNS)
            )
            self.assertEqual(csv_df.loc[0, "reaction_count"], 27)
            self.assertEqual(csv_df.loc[0, "attachment_count"], 1)

            excel_df = pd.read_excel(paths["xlsx"], sheet_name="Comments")
            self.assertEqual(len(excel_df), 1)


class FakeDriver:
    def __init__(self, page_source=""):
        self.page_source = page_source
        self.visited = []

    def get(self, url):
        self.visited.append(url)


class ResolvePostFeedbackIdTest(unittest.TestCase):
    def setUp(self):
        self.worker = FakeCommentBot()

    def test_numeric_id_is_returned_directly(self):
        self.assertEqual(
            self.worker.resolve_post_feedback_id("1473471161654707"),
            "1473471161654707",
        )

    def test_normal_post_url_extracts_id_without_navigation(self):
        self.worker.driver = FakeDriver()

        post_id = self.worker.resolve_post_feedback_id(
            "https://www.facebook.com/page/posts/123456789/"
        )

        self.assertEqual(post_id, "123456789")
        self.assertEqual(self.worker.driver.visited, [])

    def test_reel_url_reads_post_id_from_page_source(self):
        self.worker.driver = FakeDriver(
            page_source=(
                '{"sponsored_data":null,"post_id":"1473471161654707",'
                '"tracking":"{\\"top_level_post_id\\":\\"1153984243975661\\"}"}'
            )
        )

        post_id = self.worker.resolve_post_feedback_id(
            "https://www.facebook.com/reel/1153984243975661/",
            wait_seconds=0,
        )

        self.assertEqual(post_id, "1473471161654707")
        self.assertEqual(
            self.worker.driver.visited,
            ["https://www.facebook.com/reel/1153984243975661/"],
        )

    def test_missing_post_id_raises_vietnamese_error(self):
        self.worker.driver = FakeDriver(page_source="<html>no id</html>")

        with self.assertRaises(ValueError) as context:
            self.worker.resolve_post_feedback_id(
                "https://www.facebook.com/reel/1/", wait_seconds=0
            )

        self.assertIn("Không tìm thấy ID feedback", str(context.exception))


def parse_end_cursor(response):
    return response["data"]["node"][
        "comment_rendering_instance_for_feed_location"
    ]["comments"]["page_info"]["end_cursor"]


if __name__ == "__main__":
    unittest.main()
