from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import tempfile
import unittest

from insynergy_cinematic.article import load_article
from insynergy_cinematic.config import DEFAULT_CONFIG, load_config
from insynergy_cinematic.errors import StateConflictError, ValidationError
from insynergy_cinematic.screenplay import (
    CONTINUITY_DIMENSIONS,
    DialogueGenerator,
    ScreenplayCache,
    ScreenplayConfig,
    ScreenplayEngine,
    ScreenplayQualityGate,
    ScreenplayStateMachine,
    part3_coverage_report,
)
from insynergy_cinematic.shot_planner import ShotPlanner
from insynergy_cinematic.story import StoryEngine


ROOT = Path(__file__).resolve().parents[1]


def story_bundle() -> dict:
    article = load_article(ROOT / "examples" / "decision-boundary.md")
    return StoryEngine().generate(article)


class ScreenplayEngineTests(unittest.TestCase):
    def test_part3_coverage_credits_live_persona_and_dashboard(self) -> None:
        report = part3_coverage_report()

        self.assertEqual(report["cluster_count"], 20)
        self.assertEqual((report["full"], report["partial"], report["missing"]), (18, 2, 0))
        self.assertEqual(report["points"], 19.0)
        self.assertEqual(report["coverage_percent"], 95.0)
        self.assertEqual(
            {row["cluster"] for row in report["clusters"] if row["status"] == "PARTIAL"},
            {"human_screenplay_approval", "operational_dashboard"},
        )

    def test_generates_the_complete_canonical_screenplay_bundle(self) -> None:
        artifacts = ScreenplayEngine().generate(story_bundle())
        screenplay = artifacts["screenplay"]
        scenes = screenplay["scenes"]

        self.assertEqual(screenplay["source_contract"], "story_artifacts_only")
        self.assertEqual(len(scenes), 8)
        self.assertEqual([scene["order"] for scene in scenes], list(range(1, 9)))
        self.assertEqual({scene["act"] for scene in scenes}, {1, 2, 3})
        self.assertTrue(all(4 <= scene["duration_seconds"] <= 10 for scene in scenes))
        self.assertTrue(all(not scene["concepts"] for scene in scenes if scene["act"] < 3))
        self.assertTrue(any(line["silence"] for line in artifacts["dialogue"]["lines"]))
        self.assertTrue(
            all(
                line["silence"] or len(line["text"].split()) <= 15
                for line in artifacts["dialogue"]["lines"]
            )
        )
        self.assertEqual(
            set(artifacts["continuity"]["checks"]), set(CONTINUITY_DIMENSIONS)
        )
        self.assertTrue(all(artifacts["continuity"]["checks"].values()))
        self.assertTrue(artifacts["screenplay_quality_report"]["passed"])
        self.assertEqual(artifacts["screenplay_state"]["state"], "AwaitingApproval")
        self.assertIn("CUT TO:", artifacts["screenplay_fountain"]["content"])
        self.assertEqual(artifacts["screenplay_metrics"]["scene_count"], 8)
        self.assertEqual(artifacts["screenplay_metrics"]["average_scene_duration"], 4)
        self.assertTrue(artifacts["screenplay_config"]["immutable_at_runtime"])

    def test_downstream_shot_planner_preserves_exact_scene_coverage(self) -> None:
        story = story_bundle()
        screenplay = ScreenplayEngine().generate(story)["screenplay"]

        planned = ShotPlanner().generate(screenplay, story["character_bible"])

        shots = planned["shot_list"]["shots"]
        self.assertEqual(len(shots), len(screenplay["scenes"]))
        self.assertEqual(
            [shot["scene_id"] for shot in shots],
            [scene["scene_id"] for scene in screenplay["scenes"]],
        )
        self.assertTrue(planned["shot_gate_report"]["passed"])
        self.assertTrue(planned["storyboard_gate_report"]["passed"])

    def test_dialogue_validator_rejects_exposition_and_overlong_lines(self) -> None:
        scenes = ScreenplayEngine().generate(story_bundle())["screenplay"]["scenes"]
        exposition = deepcopy(scenes)
        exposition[0]["dialogue"][0]["text"] = "The framework is a definition of authority."
        with self.assertRaises(ValidationError):
            DialogueGenerator().validate(exposition, ScreenplayConfig())

        overlong = deepcopy(scenes)
        overlong[0]["dialogue"][0]["text"] = " ".join(["word"] * 16)
        with self.assertRaises(ValidationError):
            DialogueGenerator().validate(overlong, ScreenplayConfig())

    def test_quality_gate_rejects_interior_action_and_borrowed_biography(self) -> None:
        story = story_bundle()
        artifacts = ScreenplayEngine().generate(story)
        scenes = deepcopy(artifacts["screenplay"]["scenes"])
        scenes[0]["actions"] = ["The director thinks about a childhood trauma."]

        report = ScreenplayQualityGate().evaluate(
            scenes,
            artifacts["continuity"],
            ScreenplayConfig(),
            None,
        )

        self.assertFalse(report["passed"])
        self.assertFalse(report["checks"]["observable_actions_only"])
        self.assertFalse(
            report["checks"]["no_invented_biography_or_borrowed_stakes"]
        )

    def test_continuity_break_fails_closed(self) -> None:
        story = story_bundle()
        engine = ScreenplayEngine()
        artifacts = engine.generate(story)
        scenes = deepcopy(artifacts["screenplay"]["scenes"])
        scenes[3]["emotion_start"] = "unrelated"

        continuity = engine.continuity.validate(
            scenes, story["character_bible"], None
        )
        report = engine.quality.evaluate(scenes, continuity, engine.config, None)

        self.assertFalse(continuity["valid"])
        self.assertFalse(report["passed"])
        self.assertFalse(report["checks"]["continuity_valid"])

    def test_exact_cache_reuses_only_identical_story_version_profile_and_config(self) -> None:
        story = story_bundle()
        with tempfile.TemporaryDirectory() as temporary:
            cache_root = Path(temporary)
            cache = ScreenplayCache(cache_root)
            first_engine = ScreenplayEngine(cache=cache)
            first = first_engine.generate(story)
            second_engine = ScreenplayEngine(cache=cache)
            second = second_engine.generate(story)
            production_engine = ScreenplayEngine(
                config=ScreenplayConfig(profile="production"), cache=cache
            )
            production_engine.generate(story)

            self.assertFalse(first_engine.last_cache_hit)
            self.assertTrue(second_engine.last_cache_hit)
            self.assertEqual(first, second)
            self.assertFalse(production_engine.last_cache_hit)

            cache_key = first["screenplay_config"]["cache"]["cache_key"]
            cache_path = cache_root / f"{cache_key.split(':', 1)[1]}.json"
            tampered = json.loads(cache_path.read_text(encoding="utf-8"))
            tampered["artifacts"]["screenplay"]["title"] = "Tampered"
            cache_path.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaises(ValidationError):
                ScreenplayEngine(cache=cache).generate(story)

    def test_external_configuration_is_frozen_and_cannot_weaken_invariants(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            resolved = load_config(workspace=root, environ={})
            with self.assertRaises(FrozenInstanceError):
                resolved.screenplay.words_per_line = 16  # type: ignore[misc]

            weakened = deepcopy(DEFAULT_CONFIG)
            weakened["screenplay"]["dialogue"]["exposition_allowed"] = True
            path = root / "weakened.json"
            path.write_text(json.dumps(weakened), encoding="utf-8")
            with self.assertRaises(ValidationError):
                load_config(workspace=root, config_path=path, environ={})

    def test_persona_lineage_is_preserved_and_invalidates_cache_identity(self) -> None:
        story = story_bundle()
        lineage = {
            "persona_id": "persona-001",
            "persona_content_hash": "sha256:" + "1" * 64,
            "persona_approval_binding_hash": "sha256:" + "2" * 64,
            "assumption_lineage": ["assumption-001"],
        }
        story["persona_lineage"] = lineage
        with tempfile.TemporaryDirectory() as temporary:
            cache = ScreenplayCache(Path(temporary))
            engine = ScreenplayEngine(cache=cache)
            first = engine.generate(story)
            changed = deepcopy(story)
            changed["persona_lineage"]["persona_content_hash"] = "sha256:" + "3" * 64
            second = engine.generate(changed)

        for artifact_type in ("screenplay", "scene_index", "dialogue", "continuity"):
            self.assertEqual(first[artifact_type]["persona_lineage"], lineage)
        self.assertTrue(
            all(scene["persona_id"] == lineage["persona_id"] for scene in first["screenplay"]["scenes"])
        )
        self.assertNotEqual(
            first["screenplay_config"]["cache"]["cache_key"],
            second["screenplay_config"]["cache"]["cache_key"],
        )

    def test_incomplete_persona_lineage_and_illegal_state_transition_are_rejected(self) -> None:
        story = story_bundle()
        story["persona_lineage"] = {"persona_id": "persona-001"}
        with self.assertRaises(ValidationError):
            ScreenplayEngine().generate(story)
        with self.assertRaises(StateConflictError):
            ScreenplayStateMachine().transition("Pending", "Validated")


if __name__ == "__main__":
    unittest.main()
