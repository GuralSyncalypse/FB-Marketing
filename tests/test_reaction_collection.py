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
from bot.reactions import export_reactions_to_spreadsheet


def load_sample():
    with open(
        os.path.join(
            BASE_DIR, "samples", "reactions", "reactions-all.json"
        ),
        encoding="utf-8",
    ) as file:
        return json.load(file)


def sample_end_cursor():
    return load_sample()["data"]["node"]["reactors"]["page_info"][
        "end_cursor"
    ]


class FakeReactionBot(bot.FacebookBot):
    def __init__(self):
        super().__init__()
        self.reaction_requests = []
        self.reaction_pages = []

    def fetch_reactions_page(
        self,
        post_id,
        cursor=None,
        count=10,
        reaction_type=None,
        reaction_id=None,
        name_query=None,
        **kwargs,
    ):
        self.reaction_requests.append(
            (
                post_id,
                cursor,
                count,
                reaction_type,
                reaction_id,
                name_query,
            )
        )
        if not self.reaction_pages:
            return {"data": {}}
        return self.reaction_pages.pop(0)


class CollectReactionsTest(unittest.TestCase):
    def setUp(self):
        self.worker = FakeReactionBot()
        first_page = load_sample()
        second_page = copy.deepcopy(first_page)
        second_page["data"]["node"]["reactors"]["page_info"][
            "has_next_page"
        ] = False
        for index, edge in enumerate(
            second_page["data"]["node"]["reactors"]["edges"]
        ):
            edge["node"]["id"] = f"900000000000{index:02d}"
            edge["node"]["name"] = f"Người dùng {index}"
        self.worker.reaction_pages = [first_page, second_page]

    def test_collects_both_pages(self):
        reactions = self.worker.collect_post_reactions(
            "1646854353510601", page_delay_seconds=0
        )

        self.assertEqual(len(reactions), 20)
        self.assertEqual(len(self.worker.reaction_requests), 2)
        self.assertIsNone(self.worker.reaction_requests[0][1])
        self.assertEqual(
            self.worker.reaction_requests[1][1], sample_end_cursor()
        )
        self.assertEqual(reactions[0]["user_id"], "61564271999035")
        self.assertEqual(reactions[0]["reaction_type"], "LIKE")
        self.assertEqual(reactions[10]["user_id"], "90000000000000")
        self.assertNotIn("raw_node", reactions[0])

    def test_max_reactions_stops_at_limit(self):
        reactions = self.worker.collect_post_reactions(
            "1646854353510601", max_reactions=5
        )

        self.assertEqual(len(reactions), 5)
        self.assertEqual(len(self.worker.reaction_requests), 1)

    def test_reaction_type_is_sent_to_graphql(self):
        self.worker.collect_post_reactions(
            "1646854353510601", reaction_type="LOVE", max_reactions=1
        )

        request = self.worker.reaction_requests[0]
        self.assertEqual(request[3], "LOVE")

    def test_care_filter_accepts_support_response(self):
        page = load_sample()
        reactors = page["data"]["node"]["reactors"]
        reactors["edges"] = [
            edge
            for edge in reactors["edges"]
            if edge["feedback_reaction_info"]["reaction_type"] == "SUPPORT"
        ]
        reactors["page_info"]["has_next_page"] = False
        self.worker.reaction_pages = [page]

        reactions = self.worker.collect_post_reactions(
            "1646854353510601", reaction_type="CARE"
        )

        self.assertEqual(len(reactions), 2)
        self.assertEqual(
            {item["reaction_type"] for item in reactions}, {"SUPPORT"}
        )

    def test_scan_saves_json_and_exports_csv_xlsx(self):
        first_page = load_sample()
        first_page["data"]["node"]["reactors"]["page_info"][
            "has_next_page"
        ] = False
        self.worker.reaction_pages = [first_page]

        with tempfile.TemporaryDirectory() as temp_dir:
            self.worker.data_dir = os.path.join(temp_dir, "raw")
            self.worker.exports_dir = os.path.join(temp_dir, "exports")

            result = self.worker.scan_post_reactions(
                "1646854353510601",
                max_reactions=3,
                source_url="https://www.facebook.com/reel/1/",
            )

            self.assertTrue(os.path.exists(result["json_path"]))
            self.assertEqual(set(result["export_paths"]), {"csv", "xlsx"})
            with open(result["json_path"], encoding="utf-8") as file:
                payload = json.load(file)
            self.assertEqual(payload["post_id"], "1646854353510601")
            self.assertEqual(payload["reaction_count"], 3)
            self.assertNotIn("raw_node", payload["reactions"][0])
            self.assertTrue(payload["reactions"][0]["scraped_at"])

            csv_df = pd.read_csv(
                result["export_paths"]["csv"],
                encoding="utf-8-sig",
                dtype={"user_id": str},
            )
            self.assertEqual(
                list(csv_df.columns), list(bot.REACTION_EXPORT_COLUMNS)
            )
            self.assertEqual(len(csv_df), 3)
            self.assertEqual(csv_df.loc[0, "user_id"], "61564271999035")
            self.assertEqual(csv_df.loc[0, "reaction_type"], "LIKE")


class ExportReactionsTest(unittest.TestCase):
    def test_exports_reactions_from_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = os.path.join(temp_dir, "reactions_164.json")
            reactions = [
                {
                    "post_id": "164",
                    "user_id": "100",
                    "user_name": "Nguyễn Văn A",
                    "reaction_type": "LOVE",
                    "reaction_type_id": "1678524932434102",
                    "profile_url": "https://facebook.com/a",
                    "profile_picture": "https://example.com/a.jpg",
                    "reaction_icon_url": "https://example.com/love.png",
                    "mutual_friends_count": 5,
                    "friendship_status": "CAN_REQUEST",
                    "subscribe_status": "CANNOT_SUBSCRIBE",
                    "scraped_at": "2026-10-23T10:00:00",
                }
            ]
            with open(json_path, "w", encoding="utf-8") as file:
                json.dump(
                    {
                        "post_id": "164",
                        "reaction_count": 1,
                        "reactions": reactions,
                    },
                    file,
                    ensure_ascii=False,
                )

            paths = export_reactions_to_spreadsheet(
                json_path, output_dir=temp_dir
            )

            self.assertEqual(set(paths), {"csv", "xlsx"})
            csv_df = pd.read_csv(
                paths["csv"], encoding="utf-8-sig", dtype={"user_id": str}
            )
            self.assertEqual(
                list(csv_df.columns), list(bot.REACTION_EXPORT_COLUMNS)
            )
            self.assertEqual(csv_df.loc[0, "reaction_type"], "LOVE")
            self.assertEqual(csv_df.loc[0, "mutual_friends_count"], 5)

            excel_df = pd.read_excel(paths["xlsx"], sheet_name="Reactions")
            self.assertEqual(len(excel_df), 1)


if __name__ == "__main__":
    unittest.main()
