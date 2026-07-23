from copy import deepcopy
from pathlib import Path
import unittest

from insynergy_cinematic.article import load_article
from insynergy_cinematic.creative_scenario import validate_creative_scenario
from insynergy_cinematic.errors import ValidationError
from insynergy_cinematic.persona import load_creative_brief
from insynergy_cinematic.screenplay import ScreenplayEngine
from insynergy_cinematic.shot_planner import ShotPlanner
from insynergy_cinematic.story import StoryEngine


ROOT = Path(__file__).resolve().parents[1]
BRIEF = ROOT / "creative" / "full-auto-30s" / "creative-brief.md"
ARTICLE = ROOT / "creative" / "full-auto-30s" / "source-article.md"


def raw_scenario() -> tuple[dict, str]:
    brief = load_creative_brief(BRIEF)
    scenario = deepcopy(brief.scenario)
    assert scenario is not None
    scenario.pop("content_hash")
    scenario.pop("source")
    return scenario, brief.content_hash


class CreativeScenarioTests(unittest.TestCase):
    def test_full_auto_brief_seals_exact_timing_and_spoken_line(self) -> None:
        brief = load_creative_brief(BRIEF)
        scenario = brief.scenario

        self.assertIsNotNone(scenario)
        assert scenario is not None
        self.assertEqual(scenario["title"], "Full Auto")
        self.assertEqual(scenario["duration_seconds"], 30.0)
        self.assertEqual(len(scenario["scenes"]), 8)
        self.assertEqual(
            [scene["duration_seconds"] for scene in scenario["scenes"]],
            [3.5, 3.0, 4.0, 3.5, 4.0, 4.0, 4.0, 4.0],
        )
        self.assertEqual(
            [
                scene["dialogue"]["text"]
                for scene in scenario["scenes"]
                if not scene["dialogue"]["silence"]
            ],
            ["It'll be done by morning.", "I'm such a fucking idiot!"],
        )
        self.assertEqual(
            scenario["scenes"][2]["ui_overlays"],
            [
                "Creating Agent...",
                "Searching...",
                "Generating...",
                "Retry...",
                "Launching Parallel Worker...",
                "Expanding Context...",
                "Thinking...",
                "Run #18",
                "Run #37",
                "Run #96",
                "Run #184",
            ],
        )
        self.assertEqual(scenario["scenes"][2]["emotion_end"], "dread")
        self.assertEqual(scenario["scenes"][3]["emotion_start"], "dread")
        self.assertIn(
            "ending with agents packed across the entire screen",
            scenario["scenes"][2]["action"],
        )
        self.assertEqual(
            scenario["scenes"][4]["ui_overlays"],
            [
                "Completed",
                "184 Tasks",
                "Current Usage",
                "$731.88",
                "$734",
                "$739",
                "$744",
            ],
        )
        self.assertIn(
            "wakes the execution dashboard with one urgent keyboard tap and mouse movement",
            scenario["scenes"][4]["action"],
        )
        self.assertNotIn("laptop", scenario["scenes"][4]["action"].casefold())
        self.assertIn(
            "superficial veins across both temples and the upper forehead",
            scenario["scenes"][6]["shot"]["performance_note"],
        )
        self.assertIn(
            "taut neck veins along the sternocleidomastoid",
            scenario["scenes"][6]["shot"]["performance_note"],
        )
        self.assertIn(
            "the sclerae are predominantly warm white",
            scenario["scenes"][6]["shot"]["performance_note"],
        )
        self.assertIn(
            "only two or three extremely fine, faint capillaries",
            scenario["scenes"][6]["shot"]["performance_note"],
        )
        self.assertIn(
            "There is no broad red tint across the eyes",
            scenario["scenes"][6]["shot"]["performance_note"],
        )
        self.assertIn(
            "moves the on-screen arrow cursor",
            scenario["scenes"][5]["action"],
        )
        self.assertIn(
            "clicks the left mouse button once",
            scenario["scenes"][5]["action"],
        )
        self.assertIn(
            "The hand grips the physical mouse",
            scenario["scenes"][5]["shot"]["performance_note"],
        )
        self.assertEqual(
            scenario["source"]["creative_brief_hash"], brief.content_hash
        )

    def test_authored_screenplay_and_storyboard_preserve_full_auto(self) -> None:
        story = StoryEngine().generate(load_article(ARTICLE))
        scenario = load_creative_brief(BRIEF).scenario
        assert scenario is not None
        story["creative_scenario"] = scenario

        artifacts = ScreenplayEngine().generate(story)
        screenplay = artifacts["screenplay"]
        planned = ShotPlanner().generate(screenplay, story["character_bible"])

        self.assertEqual(screenplay["title"], "Full Auto")
        self.assertEqual(screenplay["duration_seconds"], 30.0)
        self.assertEqual(
            screenplay["source_contract"],
            "story_artifacts_only:authored_creative_scenario",
        )
        self.assertEqual(
            [
                line["text"]
                for scene in screenplay["scenes"]
                for line in scene["dialogue"]
                if not line["silence"]
            ],
            ["It'll be done by morning.", "I'm such a fucking idiot!"],
        )
        self.assertIn(
            "☑ FULL AUTO", screenplay["scenes"][0]["ui_overlays"]
        )
        self.assertEqual(
            screenplay["scenes"][5]["ui_overlays"],
            [
                "STOP",
                "Stopping...",
                "Waiting for active workers...",
                "12 Active Agents",
                "$744",
                "$746",
                "$748",
            ],
        )
        self.assertIn(
            "moves the on-screen arrow cursor",
            screenplay["scenes"][5]["actions"][0],
        )
        self.assertIn(
            "clicks the left mouse button once",
            screenplay["scenes"][5]["actions"][0],
        )
        self.assertIn("NO ONE DESIGNED", screenplay["scenes"][7]["actions"][0])
        self.assertEqual(
            [
                shot["render_strategy"]["asset_class"]
                for shot in planned["shot_list"]["shots"]
            ],
            [
                "runway_video",
                "animated_still",
                "motion_graphics",
                "animated_still",
                "animated_still",
                "runway_video",
                "animated_still",
                "title_card",
            ],
        )
        self.assertEqual(
            planned["storyboard"]["source"],
            "screenplay_authored_creative_scenario",
        )
        self.assertEqual(
            artifacts["narration_script"]["segments"],
            [
                {"scene_id": "scene-001", "text": "It'll be done by morning."},
                {"scene_id": "scene-007", "text": "I'm such a fucking idiot!"},
            ],
        )

    def test_timing_drift_and_off_mode_story_input_fail_closed(self) -> None:
        raw, brief_hash = raw_scenario()
        raw["scenes"][1]["duration_seconds"] = 3.5
        with self.assertRaises(ValidationError):
            validate_creative_scenario(raw, creative_brief_hash=brief_hash)

        scenario = load_creative_brief(BRIEF).scenario
        assert scenario is not None
        with self.assertRaises(ValidationError):
            StoryEngine().generate(
                load_article(ARTICLE), creative_scenario=scenario
            )


if __name__ == "__main__":
    unittest.main()
