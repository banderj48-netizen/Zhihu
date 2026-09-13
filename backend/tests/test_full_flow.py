"""Deterministic portions of the initialization/question/card flow."""
import unittest
from datetime import datetime, timezone, timedelta

from agent.domains.catalog import CATALOG, search
from agent.domains.situational import evaluate_response
from agent.personality import public_questions, score_assessment
from agent.personality.assessment import ITEMS
from app.main import build_card


class FullFlowTests(unittest.TestCase):
    def test_domain_catalog_and_personality_assessment(self):
        self.assertGreaterEqual(len([x for x in CATALOG if x.level == "root"]), 18)
        self.assertTrue(any("电子游戏" in x["label"] for x in search("电子游戏")))
        questions = public_questions()
        self.assertEqual(len(questions["items"]), 50)
        answers = {item.id: (1 if item.reverse else 5) for item in ITEMS}
        result = score_assessment(answers, "assessment_full_flow")
        self.assertEqual(result["status"], "completed")
        self.assertIn("scores", result)

    def test_social_question_13_second_gate(self):
        start = datetime.now(timezone.utc)
        counted = evaluate_response(presented_at=start, submitted_at=start + timedelta(seconds=8), selected_option_id="opt_b")
        timeout = evaluate_response(presented_at=start, submitted_at=start + timedelta(seconds=15), selected_option_id="opt_b")
        self.assertTrue(counted["counted"])
        self.assertFalse(timeout["counted"])
        self.assertEqual(timeout["status"], "timeout")

    def test_role_card_json_projection(self):
        profile = {"revision": 0, "status": "draft", "data": {"name": "测试分身", "facts": ["后端工程师"], "domains": [{"domain_id": "entertainment.06.03"}], "memories": [], "personality": None}}
        card = build_card(profile, "test_user", "version_test")
        self.assertEqual(card["spec"], "chara_card_v2")
        self.assertEqual(card["data"]["extensions"]["twin"]["version_id"], "version_test")
        self.assertEqual(card["data"]["extensions"]["twin"]["domain_profile"], profile["data"]["domains"])
        self.assertEqual(card["data"]["character_book"]["name"], "三层世界书")


if __name__ == "__main__":
    unittest.main()
