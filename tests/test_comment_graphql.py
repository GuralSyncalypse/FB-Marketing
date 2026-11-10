import base64
import json
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from bot.graphql import (
    COMMENTS_DOC_ID,
    COMMENTS_FRIENDLY_NAME,
    REPLIES_DOC_ID,
    REPLIES_FRIENDLY_NAME,
    GraphQLMixin,
    build_comments_variables,
    build_replies_variables,
)


class FakeDriver:
    def __init__(self, response=None):
        self.response = response or {"data": {}}
        self.calls = []

    def execute_async_script(self, script, *args):
        self.calls.append((script, args))
        return self.response


class CommentGraphQLTest(unittest.TestCase):
    def setUp(self):
        self.driver = FakeDriver()
        self.mixin = GraphQLMixin()
        self.mixin.driver = self.driver

    def test_build_comments_variables_first_page(self):
        variables = build_comments_variables("1473471161654707")

        self.assertIsNone(variables["commentsAfterCursor"])
        self.assertEqual(variables["commentsAfterCount"], -1)
        self.assertEqual(variables["feedLocation"], "POST_PERMALINK_DIALOG")
        self.assertEqual(
            base64.b64decode(variables["id"]).decode("utf-8"),
            "feedback:1473471161654707",
        )
        self.assertTrue(
            variables[
                "__relay_internal__pv__CometUFICommentActionLinksRewriteEnabledrelayprovider"
            ]
        )

    def test_build_comments_variables_next_page(self):
        variables = build_comments_variables(
            "1473471161654707", cursor="CURSOR-2", count=-1
        )

        self.assertEqual(variables["commentsAfterCursor"], "CURSOR-2")
        self.assertEqual(variables["commentsBeforeCount"], None)

    def test_build_replies_variables_keeps_expansion_token(self):
        token = "MjoxNzkyNzI0Mjc2OgF_token"
        variables = build_replies_variables(
            "1473471161654707",
            "1192700106779015",
            token,
            cursor=None,
        )

        self.assertEqual(variables["expansionToken"], token)
        self.assertIsNone(variables["repliesAfterCursor"])
        self.assertIsNone(variables["repliesAfterCount"])
        self.assertEqual(
            base64.b64decode(variables["id"]).decode("utf-8"),
            "feedback:1473471161654707_1192700106779015",
        )

    def test_fetch_comments_page_uses_defaults_and_serializes_variables(self):
        self.mixin.fetch_comments_page("1473471161654707")

        script, args = self.driver.calls[0]
        self.assertIn("/api/graphql/", script)
        self.assertEqual(args[1], COMMENTS_DOC_ID)
        self.assertEqual(args[2], COMMENTS_FRIENDLY_NAME)
        variables = json.loads(args[0])
        self.assertEqual(variables["commentsAfterCount"], -1)
        self.assertIsNone(variables["commentsAfterCursor"])

    def test_fetch_replies_page_uses_defaults_and_cursor(self):
        self.mixin.fetch_replies_page(
            "1473471161654707",
            "1192700106779015",
            "TOKEN",
            cursor="REPLY-CURSOR",
        )

        script, args = self.driver.calls[0]
        self.assertIn("/api/graphql/", script)
        self.assertEqual(args[1], REPLIES_DOC_ID)
        self.assertEqual(args[2], REPLIES_FRIENDLY_NAME)
        variables = json.loads(args[0])
        self.assertEqual(variables["repliesAfterCursor"], "REPLY-CURSOR")
        self.assertEqual(variables["expansionToken"], "TOKEN")


if __name__ == "__main__":
    unittest.main()
