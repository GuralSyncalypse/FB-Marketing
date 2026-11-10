import base64
import json
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from bot.graphql import (
    REACTIONS_DOC_ID,
    REACTIONS_FRIENDLY_NAME,
    GraphQLMixin,
    build_reactions_variables,
    resolve_reaction_id,
)


class FakeDriver:
    def __init__(self, response=None):
        self.response = response or {"data": {}}
        self.calls = []

    def execute_async_script(self, script, *args):
        self.calls.append((script, args))
        return self.response


class ReactionGraphQLTest(unittest.TestCase):
    def setUp(self):
        self.driver = FakeDriver()
        self.mixin = GraphQLMixin()
        self.mixin.driver = self.driver

    def test_build_reactions_variables_first_page(self):
        variables = build_reactions_variables("1646854353510601")

        self.assertEqual(variables["count"], 10)
        self.assertIsNone(variables["cursor"])
        self.assertIsNone(variables["reactionID"])
        self.assertIsNone(variables["nameQuery"])
        self.assertEqual(
            base64.b64decode(variables["id"]).decode("utf-8"),
            "feedback:1646854353510601",
        )
        self.assertEqual(
            variables["feedbackTargetID"], variables["id"]
        )

    def test_build_reactions_variables_next_page_and_filter(self):
        variables = build_reactions_variables(
            "1646854353510601",
            cursor="CURSOR-2",
            count=20,
            reaction_type="LOVE",
        )

        self.assertEqual(variables["cursor"], "CURSOR-2")
        self.assertEqual(variables["count"], 20)
        self.assertEqual(variables["reactionID"], "1678524932434102")

    def test_resolve_reaction_id(self):
        self.assertIsNone(resolve_reaction_id("all"))
        self.assertEqual(
            resolve_reaction_id("LIKE"), "1635855486666999"
        )
        self.assertEqual(
            resolve_reaction_id("SUPPORT"), "613557422527858"
        )
        self.assertEqual(
            resolve_reaction_id(reaction_id="999"), "999"
        )
        with self.assertRaises(ValueError):
            resolve_reaction_id("UNKNOWN")

    def test_fetch_reactions_page_uses_defaults(self):
        self.mixin.fetch_reactions_page("1646854353510601")

        script, args = self.driver.calls[0]
        self.assertIn("/api/graphql/", script)
        self.assertEqual(args[1], REACTIONS_DOC_ID)
        self.assertEqual(args[2], REACTIONS_FRIENDLY_NAME)
        variables = json.loads(args[0])
        self.assertEqual(variables["count"], 10)
        self.assertIsNone(variables["cursor"])
        self.assertEqual(
            base64.b64decode(variables["id"]).decode("utf-8"),
            "feedback:1646854353510601",
        )


if __name__ == "__main__":
    unittest.main()
