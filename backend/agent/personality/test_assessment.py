from __future__ import annotations

import unittest

from .assessment import ITEMS, export_personality, public_questions, score_assessment


class PersonalityAssessmentTests(unittest.TestCase):
    def test_public_questionnaire_has_fifty_items_without_key_direction(self) -> None:
        payload = public_questions()
        self.assertEqual(len(payload["items"]), 50)
        self.assertTrue(all("reverse" not in item for item in payload["items"]))

    def test_neutral_answers_map_to_five(self) -> None:
        result = score_assessment({item.id: 3 for item in ITEMS}, "assessment_test")
        self.assertEqual(result["status"], "quality_review")
        self.assertEqual(result["validity"]["flags"], ["straightline_response"])
        self.assertEqual(set(result["scores"].values()), {5.0})

    def test_reverse_keyed_item_is_reversed(self) -> None:
        answers = {item.id: 3 for item in ITEMS}
        answers["E06"] = 1
        result = score_assessment(answers, "assessment_test")
        self.assertGreater(result["scores"]["extraversion"], 5.0)

    def test_invalid_answer_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            score_assessment({"E01": 6}, "assessment_test")

    def test_card_export_does_not_include_raw_answers(self) -> None:
        result = score_assessment({item.id: 3 for item in ITEMS}, "assessment_test")
        exported = export_personality(result)
        self.assertNotIn("raw_answers", exported)
        self.assertIn("scores", exported)


if __name__ == "__main__":
    unittest.main()
