import json
import os
import sys
import tempfile
import unittest

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import bot
from bot import FacebookBot, export_posts_to_spreadsheet


POST = {
    "post_id": "123456",
    "group_id": None,
    "scope": "search",
    "author_name": "Nguyễn Văn A",
    "author_url": "https://www.facebook.com/nguyenvana",
    "source_name": "Page A",
    "content": "Nội dung bài viết có tiếng Việt",
    "content_truncated": False,
    "media_type": "image",
    "media_urls": [
        "https://example.com/image-1.jpg",
        "https://example.com/image-2.jpg",
    ],
    "reactions": 5,
    "comments": 2,
    "shares": 1,
    "published_at": "2026-10-23T00:00:00+00:00",
    "permalink": "https://www.facebook.com/nguyenvana/posts/123456",
    "scraped_at": "2026-10-23T09:00:00",
}


class ExportPostsToSpreadsheetTest(unittest.TestCase):
    def test_exports_both_csv_and_xlsx_from_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = os.path.join(temp_dir, "posts_search_food_20261023.json")
            with open(json_path, "w", encoding="utf-8") as file:
                json.dump(
                    {
                        "scope": "search",
                        "keyword": "food",
                        "post_count": 1,
                        "posts": [POST],
                    },
                    file,
                    ensure_ascii=False,
                )

            paths = export_posts_to_spreadsheet(json_path, output_dir=temp_dir)

            self.assertEqual(set(paths), {"csv", "xlsx"})
            self.assertEqual(
                paths["csv"],
                os.path.join(temp_dir, "posts_search_food_20261023.csv"),
            )
            self.assertEqual(
                paths["xlsx"],
                os.path.join(temp_dir, "posts_search_food_20261023.xlsx"),
            )
            self.assertTrue(os.path.exists(paths["csv"]))
            self.assertTrue(os.path.exists(paths["xlsx"]))

            csv_df = pd.read_csv(
                paths["csv"], encoding="utf-8-sig", dtype={"post_id": str}
            )
            self.assertEqual(list(csv_df.columns), list(bot.POST_EXPORT_COLUMNS))
            self.assertEqual(csv_df.loc[0, "post_id"], "123456")
            self.assertEqual(csv_df.loc[0, "author_name"], "Nguyễn Văn A")
            self.assertEqual(csv_df.loc[0, "media_count"], 2)
            self.assertEqual(
                csv_df.loc[0, "media_urls"],
                "https://example.com/image-1.jpg | https://example.com/image-2.jpg",
            )
            self.assertEqual(csv_df.loc[0, "reactions"], 5)

            excel_df = pd.read_excel(
                paths["xlsx"], sheet_name="Posts", dtype={"post_id": str}
            )
            self.assertEqual(list(excel_df.columns), list(bot.POST_EXPORT_COLUMNS))
            self.assertEqual(excel_df.loc[0, "post_id"], "123456")
            self.assertEqual(excel_df.loc[0, "comments"], 2)

    def test_accepts_plain_list_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = os.path.join(temp_dir, "posts.json")
            with open(json_path, "w", encoding="utf-8") as file:
                json.dump([POST], file, ensure_ascii=False)

            paths = export_posts_to_spreadsheet(json_path, output_dir=temp_dir)

            self.assertTrue(os.path.exists(paths["csv"]))
            self.assertTrue(os.path.exists(paths["xlsx"]))

    def test_integrates_with_saved_scan_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            worker = FacebookBot()
            worker.data_dir = os.path.join(temp_dir, "raw")
            worker.exports_dir = os.path.join(temp_dir, "exports")

            json_path = worker._save_posts_json(
                [dict(POST)],
                scope="search",
                keyword="food",
                group_ids=[],
                source_label="search:food",
                recent_posts=True,
                time_range="24 giờ gần đây",
                post_type="Tất cả",
            )
            paths = export_posts_to_spreadsheet(
                json_path, output_dir=worker.exports_dir
            )

            self.assertTrue(paths["csv"].startswith(worker.exports_dir))
            self.assertTrue(paths["xlsx"].startswith(worker.exports_dir))
            self.assertEqual(os.path.basename(paths["csv"]), os.path.basename(paths["xlsx"]).replace(".xlsx", ".csv"))
            self.assertEqual(
                os.path.splitext(os.path.basename(paths["csv"]))[0],
                os.path.splitext(os.path.basename(json_path))[0],
            )

    def test_missing_json_returns_empty_dict(self):
        self.assertEqual(
            export_posts_to_spreadsheet(
                os.path.join(tempfile.gettempdir(), "missing-posts.json")
            ),
            {},
        )


if __name__ == "__main__":
    unittest.main()
