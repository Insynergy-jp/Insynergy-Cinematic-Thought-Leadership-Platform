from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import tempfile
import unittest

from insynergy_cinematic.article import load_article
from insynergy_cinematic.config import DEFAULT_CONFIG, load_config
from insynergy_cinematic.errors import QualityGateError, ValidationError
from insynergy_cinematic.models import Article
from insynergy_cinematic.story import (
    EMOTIONAL_STATES,
    STORY_ARC_STAGES,
    ArgumentExtractor,
    LoglineGenerator,
    StoryCache,
    StoryConfig,
    StoryEngine,
    StoryMetricsCalculator,
    StoryQualityGate,
    part2_coverage_report,
)
from insynergy_cinematic.util import canonical_json, content_hash

from tests.persona_fixture import golden_persona_bundle


ROOT = Path(__file__).resolve().parents[1]


def _reseal(document: dict) -> None:
    document.pop("content_hash", None)
    document["content_hash"] = content_hash(document)


def persona_context(article: Article) -> dict:
    bundle = golden_persona_bundle()
    persona = bundle["persona"]
    quality = bundle["persona-quality-report"]
    approval = bundle["persona-approval-binding"]
    article_hash = StoryEngine.article_hash(article)
    brief_hash = "sha256:" + "b" * 64
    persona["article_hash"] = article_hash
    persona["creative_brief_hash"] = brief_hash
    for evidence in persona["evidence"]:
        evidence["artifact_hash"] = article_hash
    _reseal(persona)
    quality["article_hash"] = article_hash
    quality["creative_brief_hash"] = brief_hash
    quality["persona_hash"] = persona["content_hash"]
    for check in quality["checks"]:
        check["evidence_hashes"] = [persona["content_hash"]]
    _reseal(quality)
    approval["article_hash"] = article_hash
    approval["creative_brief_hash"] = brief_hash
    approval["persona_hash"] = persona["content_hash"]
    approval["quality_report_hash"] = quality["content_hash"]
    _reseal(approval)
    return {
        "persona": persona,
        "persona_quality_report": quality,
        "persona_approval_binding": approval,
        "creative_brief_hash": brief_hash,
    }


class StoryEngineTests(unittest.TestCase):
    def test_part2_coverage_credits_bounded_operational_dashboard(self) -> None:
        report = part2_coverage_report()

        self.assertEqual(report["cluster_count"], 20)
        self.assertEqual((report["full"], report["partial"], report["missing"]), (19, 1, 0))
        self.assertEqual(report["points"], 19.5)
        self.assertEqual(report["coverage_percent"], 97.5)
        self.assertEqual(
            [row["cluster"] for row in report["clusters"] if row["status"] == "PARTIAL"],
            ["operational_dashboard"],
        )

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

    def test_canonical_bundle_satisfies_every_structural_contract(self) -> None:
        article = load_article(ROOT / "examples" / "decision-boundary.md")
        artifacts = StoryEngine().generate(article)

        argument = artifacts["argument_map"]
        self.assertTrue(argument["dramatic_candidates"])
        self.assertTrue(
            all(
                candidate["classification"] in {"Tension", "Consequence"}
                for candidate in argument["dramatic_candidates"]
            )
        )
        self.assertEqual(artifacts["dramatic_premise"]["premise_count"], 1)
        self.assertLessEqual(artifacts["logline"]["word_count"], 50)
        protagonist = artifacts["character_bible"]["protagonist"]
        self.assertTrue(
            all(
                protagonist[field]
                for field in ("goal", "fear", "flaw", "competence", "decision_required", "arc")
            )
        )
        self.assertLessEqual(artifacts["character_bible"]["supporting_role_count"], 3)
        self.assertTrue(
            all(
                artifacts["conflict"][layer]
                for layer in ("external", "internal", "institutional")
            )
        )
        stake = artifacts["stakes"]["stakes"][0]
        self.assertTrue(stake["measurable"])
        self.assertFalse(stake["reversible"])
        self.assertTrue(artifacts["time_pressure"]["deadline_coherent"])
        self.assertTrue(artifacts["time_pressure"]["visible_to_audience"])
        self.assertEqual(
            [stage["name"] for stage in artifacts["story_arc"]["stages"]],
            list(STORY_ARC_STAGES),
        )
        acts = artifacts["three_act_structure"]
        self.assertEqual(sum(act["duration_seconds"] for act in acts["acts"]), 28)
        self.assertTrue(acts["act_budget"]["satisfied"])
        self.assertEqual(artifacts["emotional_arc"]["states"], list(EMOTIONAL_STATES))
        self.assertTrue(
            all(value["motivated_by"] for value in artifacts["emotional_arc"]["transitions"])
        )
        self.assertEqual(artifacts["concept_placement"]["placements"][0]["act"], 3)
        self.assertLessEqual(artifacts["story_metrics"]["concept_ratio"], 0.20)
        self.assertTrue(artifacts["story_quality_report"]["passed"])
        self.assertEqual(len(artifacts["story_stage_records"]["stages"]), 8)
        self.assertTrue(
            all(stage["budget_seconds"] > 0 for stage in artifacts["story_stage_records"]["stages"])
        )
        self.assertEqual(len(artifacts["story_decision_log"]["decisions"]), 8)
        self.assertTrue(artifacts["story_decision_log"]["deterministic"])

    def test_concept_only_article_fails_fast_with_machine_rejection(self) -> None:
        article = Article(
            title="Definitions",
            body=(
                "Decision architecture is a framework for organizational terminology. "
                "It contains categories and definitions for institutional vocabulary. "
                "The document describes a system and a structure for governance concepts."
            ),
        )

        with self.assertRaises(QualityGateError) as raised:
            StoryEngine().generate(article)

        self.assertEqual(raised.exception.details["forbidden_category"], "concept_list")
        self.assertEqual(
            raised.exception.details["failed_gate_items"],
            ["dramatic_candidates_present"],
        )

    def test_metrics_and_gate_fail_when_a_conflict_layer_is_removed(self) -> None:
        article = load_article(ROOT / "examples" / "decision-boundary.md")
        artifacts = StoryEngine().generate(article)
        damaged = deepcopy(artifacts)
        damaged["conflict"]["external"] = ""
        damaged["conflict"]["layer_count"] = 2

        metrics = StoryMetricsCalculator().calculate(damaged)
        report = StoryQualityGate().evaluate(
            damaged,
            metrics,
            StoryConfig(),
            True,
        )

        self.assertLess(metrics["conflict_score"], 0.80)
        self.assertFalse(report["passed"])
        self.assertFalse(report["checks"]["conflict_score_threshold"])
        self.assertEqual(report["forbidden_category"], "talking_heads")

    def test_public_argument_stage_is_isolated_and_deterministic(self) -> None:
        article = load_article(ROOT / "examples" / "decision-boundary.md")
        extractor = ArgumentExtractor()

        first = extractor.extract(article)
        second = extractor.extract(article)

        self.assertEqual(first, second)
        self.assertEqual(first["article_id"], article.article_id)
        self.assertNotIn("screenplay", first)

    def test_exact_cache_reuses_valid_bundle_and_recomputes_corruption(self) -> None:
        class NeverRunArgumentStage:
            def extract(self, article: Article) -> dict:
                raise AssertionError("cache did not bypass Story stages")

        article = load_article(ROOT / "examples" / "decision-boundary.md")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = StoryCache(root)
            first_engine = StoryEngine(cache=cache)
            first = first_engine.generate(article)
            second_engine = StoryEngine(cache=cache)
            second_engine.arguments = NeverRunArgumentStage()  # type: ignore[assignment]
            second = second_engine.generate(article)

            self.assertFalse(first_engine.last_cache_hit)
            self.assertTrue(second_engine.last_cache_hit)
            self.assertEqual(first, second)

            key = first["story_config"]["cache"]["cache_key"]
            path = root / f"{key.split(':', 1)[1]}.json"
            tampered = json.loads(path.read_text(encoding="utf-8"))
            tampered["artifacts"]["theme"]["primary_theme"] = "Tampered"
            path.write_text(json.dumps(tampered), encoding="utf-8")
            repaired_engine = StoryEngine(cache=cache)
            repaired = repaired_engine.generate(article)

            self.assertFalse(repaired_engine.last_cache_hit)
            self.assertTrue(repaired_engine.last_cache_corrupt)
            self.assertEqual(repaired, first)

    def test_profile_and_author_style_invalidate_story_cache(self) -> None:
        article = load_article(ROOT / "examples" / "decision-boundary.md")
        with tempfile.TemporaryDirectory() as temporary:
            cache = StoryCache(Path(temporary))
            canonical = StoryEngine(cache=cache).generate(article)
            draft_engine = StoryEngine(
                config=StoryConfig(profile="draft", duration_seconds=12), cache=cache
            )
            draft = draft_engine.generate(article)
            style_engine = StoryEngine(
                config=StoryConfig(author_style=("alternate terminology",)), cache=cache
            )
            styled = style_engine.generate(article)

        keys = {
            canonical["story_config"]["cache"]["cache_key"],
            draft["story_config"]["cache"]["cache_key"],
            styled["story_config"]["cache"]["cache_key"],
        }
        self.assertEqual(len(keys), 3)
        self.assertFalse(draft_engine.last_cache_hit)
        self.assertFalse(style_engine.last_cache_hit)

    def test_external_story_configuration_is_frozen_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            resolved = load_config(workspace=root, environ={})
            with self.assertRaises(FrozenInstanceError):
                resolved.story.canonical_duration_seconds = 31  # type: ignore[misc]

            weakened = deepcopy(DEFAULT_CONFIG)
            weakened["story"]["thresholds"]["dramatic_score"] = 0.70
            path = root / "weakened.json"
            path.write_text(json.dumps(weakened), encoding="utf-8")
            with self.assertRaises(ValidationError):
                load_config(workspace=root, config_path=path, environ={})

    def test_council_mode_enforces_approval_lineage_and_cache_invalidation(self) -> None:
        article = load_article(ROOT / "examples" / "decision-boundary.md")
        context = persona_context(article)
        with tempfile.TemporaryDirectory() as temporary:
            cache = StoryCache(Path(temporary))
            engine = StoryEngine(
                config=StoryConfig(persona_mode="council"), cache=cache
            )
            first = engine.generate(article, persona_context=context)
            changed = deepcopy(context)
            changed["persona"]["role"]["value"] = "Enterprise Risk Director"
            _reseal(changed["persona"])
            changed["persona_quality_report"]["persona_hash"] = changed["persona"]["content_hash"]
            for check in changed["persona_quality_report"]["checks"]:
                check["evidence_hashes"] = [changed["persona"]["content_hash"]]
            _reseal(changed["persona_quality_report"])
            changed["persona_approval_binding"]["persona_hash"] = changed["persona"]["content_hash"]
            changed["persona_approval_binding"]["quality_report_hash"] = changed["persona_quality_report"]["content_hash"]
            _reseal(changed["persona_approval_binding"])
            second = engine.generate(article, persona_context=changed)

        self.assertEqual(
            first["character_bible"]["protagonist"]["name"],
            context["persona"]["role"]["value"],
        )
        for artifact_type in (
            "dramatic_premise",
            "character_bible",
            "conflict",
            "emotional_arc",
        ):
            self.assertEqual(
                first[artifact_type]["persona_id"], first["persona_lineage"]["persona_id"]
            )
            self.assertEqual(
                first[artifact_type]["assumption_lineage"], ["asm-pressure"]
            )
        self.assertEqual(
            first["emotional_arc"]["persona_arc_constraint"],
            context["persona"]["emotional_arc_candidate"]["value"],
        )
        self.assertTrue(
            all(first["emotional_arc"]["persona_causal_bindings"].values())
        )
        self.assertNotEqual(
            first["story_config"]["cache"]["cache_key"],
            second["story_config"]["cache"]["cache_key"],
        )

    def test_unapproved_or_superseded_persona_cannot_start_story(self) -> None:
        article = load_article(ROOT / "examples" / "decision-boundary.md")
        config = StoryConfig(persona_mode="council")
        unapproved = persona_context(article)
        unapproved["persona_approval_binding"]["decision"] = "REJECTED"
        _reseal(unapproved["persona_approval_binding"])
        with self.assertRaises(ValidationError):
            StoryEngine(config=config).generate(article, persona_context=unapproved)

        superseded = persona_context(article)
        superseded["superseded_persona_hashes"] = [
            superseded["persona"]["content_hash"]
        ]
        with self.assertRaises(ValidationError):
            StoryEngine(config=config).generate(article, persona_context=superseded)

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

    def test_logline_compacts_long_persona_goal_at_a_semantic_boundary(self) -> None:
        protagonist = (
            "Engineering or product leader who authorizes autonomous AI-agent use and "
            "is accountable for its operational boundaries."
        )
        goal = (
            "Define a Decision Boundary before autonomous execution, including spending "
            "limits, approval events, escalation ownership, and stop-versus-retry conditions."
        )

        artifact = LoglineGenerator().generate(
            protagonist=protagonist,
            problem="The central failure is not model accuracy.",
            goal=goal,
            measurable_stake="$744 of unattended usage by morning.",
        )

        self.assertLessEqual(artifact["word_count"], 50)
        self.assertIn(protagonist.rstrip("."), artifact["logline"])
        self.assertIn("define the Decision Boundary", artifact["logline"])
        self.assertNotIn(". must", artifact["logline"])
        self.assertEqual(artifact["goal"], goal)


if __name__ == "__main__":
    unittest.main()
