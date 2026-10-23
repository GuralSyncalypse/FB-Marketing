import copy
import json
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.reaction_extractor import (
    ReactionParseError,
    dedupe_reactions,
    normalize_reaction_type,
    parse_reaction_edge,
    parse_reactions_page,
)


def load_sample():
    with open(
        os.path.join(
            BASE_DIR, "samples", "reactions", "reactions-all.json"
        ),
        encoding="utf-8",
    ) as file:
        return json.load(file)


class ParseReactionsTest(unittest.TestCase):
    def test_parses_sample_page(self):
        page = parse_reactions_page(load_sample())

        self.assertEqual(page["post_id"], "1646854353510601")
        self.assertEqual(page["raw_edge_count"], 10)
        self.assertEqual(len(page["reactions"]), 10)
        self.assertTrue(page["page_info"]["has_next_page"])
        self.assertEqual(
            page["page_info"]["end_cursor"],
            (
                "AQHTMJHcfmfl213HjQMnccEu6rpO8wOxCjIckNtBW-SNuLL0zX0nqhF5"
                "VQBCGD7LsZayQYzmEO-E4bxhlmToYfS5iw"
            ),
        )

        first = page["reactions"][0]
        self.assertEqual(first["post_id"], "1646854353510601")
        self.assertEqual(first["user_id"], "61564271999035")
        self.assertEqual(first["user_name"], "Lupita Gómez")
        self.assertEqual(first["reaction_type"], "LIKE")
        self.assertEqual(first["reaction_type_id"], "1635855486666999")
        self.assertEqual(first["mutual_friends_count"], 0)
        self.assertEqual(first["friendship_status"], "CAN_REQUEST")
        self.assertTrue(first["profile_url"].startswith("https://"))
        self.assertTrue(first["profile_picture"].startswith("https://"))
        self.assertTrue(first["reaction_icon_url"].startswith("https://"))

    def test_none_node_is_skipped(self):
        edge = {"node": None, "feedback_reaction_info": {}}

        self.assertIsNone(parse_reaction_edge(edge, post_id="123"))

    def test_normalizes_support_alias_to_care(self):
        self.assertEqual(normalize_reaction_type("SUPPORT"), "CARE")
        self.assertEqual(normalize_reaction_type("care"), "CARE")
        self.assertEqual(normalize_reaction_type("LIKE"), "LIKE")

    def test_dedupes_by_user_id(self):
        page = parse_reactions_page(load_sample())
        items = page["reactions"] + copy.deepcopy(page["reactions"][:2])

        deduped = dedupe_reactions(items)

        self.assertEqual(len(deduped), 10)

    def test_graphql_errors_raise(self):
        with self.assertRaises(ReactionParseError):
            parse_reactions_page({"errors": [{"message": "rate limit"}]})

    def test_missing_node_raises(self):
        with self.assertRaises(ReactionParseError):
            parse_reactions_page({"data": {}})


if __name__ == "__main__":
    unittest.main()
