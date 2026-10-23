import copy
import json
import os
import sys
import unittest
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.graphql_post_extractor import (
    POST_ROLES,
    extract_posts_from_graphql_response,
)

SEARCH_RESPONSE = Path(BASE_DIR) / "samples" / "response.json"


def load_payload(path):
    return json.loads(path.read_text(encoding="utf-8"))


def first_public_post_edge(payload):
    for edge in payload["data"]["serpResponse"]["results"]["edges"]:
        node = edge.get("node") or {}
        if node.get("role") == "PUBLIC_POSTS":
            return copy.deepcopy(edge)
    raise AssertionError("Fixture không có edge PUBLIC_POSTS")


def single_edge_payload(edge):
    return {
        "data": {
            "serpResponse": {
                "results": {
                    "edges": [edge],
                    "page_info": {"has_next_page": False, "end_cursor": None},
                }
            }
        }
    }


class TopPublicPostsRoleTest(unittest.TestCase):
    """Regression: tab Bài đăng gần đây trả role TOP_PUBLIC_POSTS."""

    @classmethod
    def setUpClass(cls):
        cls.sample_payload = load_payload(SEARCH_RESPONSE)
        cls.edge = first_public_post_edge(cls.sample_payload)
        cls.edge["node"]["role"] = "TOP_PUBLIC_POSTS"
        cls.payload = single_edge_payload(cls.edge)
        cls.posts = extract_posts_from_graphql_response(
            cls.payload, scope="search"
        )

    def test_top_public_posts_is_supported(self):
        self.assertIn("TOP_PUBLIC_POSTS", POST_ROLES)
        self.assertEqual(len(self.posts), 1)

    def test_extracts_story_under_click_model(self):
        story = self.edge["rendering_strategy"]["view_model"]["click_model"]["story"]
        post = self.posts[0]

        self.assertEqual(post["post_id"], str(story["post_id"]))
        self.assertTrue(post["author_name"])
        self.assertTrue(post["published_at"])
        self.assertTrue(post["permalink"])

    def test_keeps_content_and_metrics(self):
        post = self.posts[0]
        self.assertTrue(post["content"])
        self.assertIsNotNone(post["reactions"])
        self.assertIsNotNone(post["comments"])
        self.assertIsNotNone(post["shares"])

    def test_other_roles_are_still_ignored(self):
        self.assertNotIn("SEARCH_ADS", POST_ROLES)
        self.assertNotIn("SEARCH_SURVEY", POST_ROLES)


class RegularSearchResponseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = load_payload(SEARCH_RESPONSE)
        cls.edges = cls.payload["data"]["serpResponse"]["results"]["edges"]
        cls.posts = extract_posts_from_graphql_response(
            cls.payload, scope="search"
        )

    def test_public_posts_still_extracted(self):
        self.assertEqual(
            len(self.posts), sum(
                1 for edge in self.edges
                if (edge.get("node") or {}).get("role") == "PUBLIC_POSTS"
            )
        )
        self.assertTrue(all(post["post_id"] for post in self.posts))

    def test_skips_ads_and_survey_roles(self):
        roles = [(edge.get("node") or {}).get("role") for edge in self.edges]

        self.assertIn("SEARCH_ADS", roles)
        self.assertIn("SEARCH_SURVEY", roles)
        self.assertEqual(
            len(self.posts), roles.count("PUBLIC_POSTS")
        )

    def test_all_posts_have_minimum_fields(self):
        for post in self.posts:
            with self.subTest(post_id=post["post_id"]):
                self.assertTrue(post["post_id"])
                self.assertTrue(post["author_name"])
                self.assertTrue(post["content"])
                self.assertTrue(post["published_at"])
                self.assertIn(
                    post["media_type"], {"text", "image", "video", "link"}
                )


if __name__ == "__main__":
    unittest.main()
