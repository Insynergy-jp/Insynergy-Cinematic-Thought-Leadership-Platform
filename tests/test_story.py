from pathlib import Path
import unittest

from insynergy_cinematic.article import load_article
from insynergy_cinematic.models import Article
from insynergy_cinematic.story import StoryEngine
from insynergy_cinematic.util import canonical_json


ROOT = Path(__file__).resolve().parents[1]


class StoryEngineTests(unittest.TestCase):
    def test_story_is_deterministic_and_singular(self) -> None:
        article = load_article(ROOT / "examples" / "decision-boundary.md")
        first = StoryEngine().generate(article)
        second = StoryEngine().generate(article)
        self.assertEqual(canonical_json(first), canonical_json(second))
        self.assertEqual(first["conflict"]["conflict_count"], 1)
        self.assertEqual(first["three_act_structure"]["act_count"], 3)
        self.assertEqual(first["dramatic_question"]["resolved_in_act"], 3)
        self.assertTrue(first["story_quality_report"]["passed"])
        protagonist = next(
            character
            for character in first["character_bible"]["characters"]
            if character["role"] == "protagonist"
        )
        self.assertEqual(protagonist["name"], "Enterprise Risk Director")

    def test_numeric_stakes_preserve_the_source_claim(self) -> None:
        article = Article(
            title="A 31-Second Correction",
            body=(
                "A security team saw an automated attack fail and adapt. "
                "The corrective payload arrived 31 seconds after the failed action. "
                "Those 31 seconds describe one failure-to-correction sequence, not a threshold. "
                "A Chief Information Security Officer must assign containment authority before "
                "an incident begins so reversible action can proceed without inventing approval facts."
            ),
        )

        artifacts = StoryEngine().generate(article)

        measurable_stake = artifacts["stakes"]["measurable_stakes"][0]
        self.assertEqual(
            measurable_stake,
            "The corrective payload arrived 31 seconds after the failed action.",
        )
        self.assertNotIn("documented threshold", measurable_stake.casefold())

    def test_logline_is_complete_without_mid_sentence_truncation(self) -> None:
        article = load_article(ROOT / "articles" / "insights" / "jadepuffer-31-second-correction-cyber-defense-authority.md")

        logline = StoryEngine().generate(article)["logline"]["logline"]

        self.assertLessEqual(len(logline.split()), 50)
        self.assertTrue(logline.endswith("becomes real."))
        self.assertNotIn("will accept a.", logline)


if __name__ == "__main__":
    unittest.main()
