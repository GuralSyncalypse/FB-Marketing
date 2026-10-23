import json
import os
import sys
import unittest

import base64

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from bot.graphql import (
    GROUP_MEMBERS_DOC_ID,
    GROUP_MEMBERS_FRIENDLY_NAME,
    RECENT_POSTS_FILTER,
    RECENT_POSTS_URL_FILTER,
    SEARCH_POSTS_DOC_ID,
    SEARCH_POSTS_FRIENDLY_NAME,
    GraphQLMixin,
)


class FakeDriver:
    def __init__(self, response=None):
        self.response = response or {"data": {}}
        self.calls = []

    def execute_async_script(self, script, *args):
        self.calls.append((script, args))
        return self.response


class GraphQLMixinTest(unittest.TestCase):
    def setUp(self):
        self.driver = FakeDriver()
        self.mixin = GraphQLMixin()
        self.mixin.driver = self.driver

    def test_fetch_group_members_passes_cursor_and_doc_id(self):
        raw = self.mixin.fetch_group_members(
            "123", cursor="CUR", count=25, doc_id="42", friendly_name="Query"
        )

        self.assertEqual(raw, {"data": {}})
        script, args = self.driver.calls[0]
        self.assertIn("/api/graphql/", script)
        self.assertEqual(args, ("123", "CUR", 25, "42", "Query"))

    def test_fetch_group_members_uses_default_metadata(self):
        self.mixin.fetch_group_members("123")

        _, args = self.driver.calls[0]
        self.assertEqual(args[3], GROUP_MEMBERS_DOC_ID)
        self.assertEqual(args[4], GROUP_MEMBERS_FRIENDLY_NAME)

    def test_fetch_search_posts_serializes_variables(self):
        self.mixin.fetch_search_posts(
            "python", cursor="NEXT", count=7, doc_id="77", friendly_name="Search"
        )

        script, args = self.driver.calls[0]
        self.assertIn("/api/graphql/", script)
        self.assertEqual(args[1], "77")
        self.assertEqual(args[2], "Search")

        variables = json.loads(args[0])
        self.assertEqual(variables["args"]["text"], "python")
        self.assertEqual(variables["cursor"], "NEXT")
        self.assertEqual(variables["count"], 7)

    def test_fetch_search_posts_uses_default_metadata(self):
        self.mixin.fetch_search_posts("python")

        _, args = self.driver.calls[0]
        self.assertEqual(args[1], SEARCH_POSTS_DOC_ID)
        self.assertEqual(args[2], SEARCH_POSTS_FRIENDLY_NAME)
        self.assertIn("bsid", json.loads(args[0])["args"]["context"])

    def test_fetch_search_posts_recent_filter_matches_sample(self):
        self.mixin.fetch_search_posts("vlu", recent_posts=True)

        variables = json.loads(self.driver.calls[0][1][0])
        self.assertEqual(variables["args"]["filters"], [RECENT_POSTS_FILTER])
        self.assertEqual(
            variables["args"]["filters"][0],
            '{"name":"recent_posts","args":""}',
        )

    def test_fetch_search_posts_without_recent_has_empty_filters(self):
        self.mixin.fetch_search_posts("vlu")

        variables = json.loads(self.driver.calls[0][1][0])
        self.assertEqual(variables["args"]["filters"], [])

    def test_recent_posts_url_filter_matches_facebook_format(self):
        decoded = base64.urlsafe_b64decode(RECENT_POSTS_URL_FILTER).decode("utf-8")

        self.assertEqual(
            json.loads(decoded),
            {"recent_posts:0": '{"name":"recent_posts","args":""}'},
        )


if __name__ == "__main__":
    unittest.main()
