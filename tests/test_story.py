from pathlib import Path
import unittest

from insynergy_cinematic.article import load_article
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


if __name__ == "__main__":
    unittest.main()

