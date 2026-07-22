from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from insynergy_cinematic.errors import ValidationError
from insynergy_cinematic.models import ArtifactEnvelope
from insynergy_cinematic.orchestrator import BuildOrchestrator
from insynergy_cinematic.quality import (
    GATE_LIFECYCLE,
    MANDATORY_CHECKS,
    QualityGateEngine,
    build_quality_report,
    part7_coverage_report,
    quality_chain_report,
    verify_quality_gate_report,
)
from insynergy_cinematic.storage import BuildRepository
from insynergy_cinematic.util import atomic_write_json, read_json


ROOT = Path(__file__).resolve().parents[1]


def evidence(name: str = "storyboard") -> list[dict]:
    return [
        {
            "artifact_type": name,
            "artifact_id": f"{name}-001",
            "content_hash": "sha256:" + "a" * 64,
            "json_pointer": "/data",
        }
    ]


def passing_checks(gate_id: str) -> dict[str, bool]:
    return {check_id: True for check_id in MANDATORY_CHECKS[gate_id]}


class QualityGateArchitectureTests(unittest.TestCase):
    def test_part7_coverage_includes_persona_and_outcome_dashboard(self) -> None:
        report = part7_coverage_report()
        self.assertEqual(report["cluster_count"], 20)
        self.assertEqual((report["full"], report["partial"], report["missing"]), (19, 1, 0))
        self.assertEqual(report["coverage_percent"], 97.5)
        missing = {
            row["cluster"]
            for row in report["clusters"]
            if row["status"] == "MISSING"
        }
        self.assertEqual(missing, set())

    def test_evaluator_is_deterministic_evidence_bound_and_fail_closed(self) -> None:
        engine = QualityGateEngine()
        arguments = {
            "gate_id": "story_quality_gate",
            "build_id": "20260722-001",
            "checks": passing_checks("story_quality_gate"),
            "artifact_refs": evidence("dramatic_premise"),
        }
        first = engine.evaluate(**arguments)
        second = engine.evaluate(**arguments)
        self.assertEqual(first, second)
        self.assertEqual(first["lifecycle"], list(GATE_LIFECYCLE))
        self.assertTrue(first["passed"])

        failed = engine.evaluate(
            **{
                **arguments,
                "checks": {
                    **passing_checks("story_quality_gate"),
                    "stakes_defined": None,
                },
            }
        )
        self.assertFalse(failed["passed"])
        self.assertEqual(failed["decision"], "FAIL")
        self.assertEqual(failed["failed_checks"], ["stakes_defined"])

    def test_missing_evidence_and_unjustified_na_are_rejected(self) -> None:
        engine = QualityGateEngine()
        with self.assertRaises(ValidationError):
            engine.evaluate(
                gate_id="story_quality_gate",
                build_id="20260722-001",
                checks=passing_checks("story_quality_gate"),
                artifact_refs=[],
            )
        with self.assertRaises(ValidationError):
            engine.evaluate(
                gate_id="story_quality_gate",
                build_id="20260722-001",
                checks={
                    **passing_checks("story_quality_gate"),
                    "premise_defined": "NOT_APPLICABLE",
                },
                artifact_refs=evidence(),
            )

    def test_report_tampering_and_chain_bypass_fail_closed(self) -> None:
        engine = QualityGateEngine()
        story = engine.evaluate(
            gate_id="story_quality_gate",
            build_id="20260722-001",
            checks={
                **passing_checks("story_quality_gate"),
                "premise_defined": False,
            },
            artifact_refs=evidence("story"),
        )
        screenplay = engine.evaluate(
            gate_id="screenplay_quality_gate",
            build_id="20260722-001",
            checks=passing_checks("screenplay_quality_gate"),
            artifact_refs=evidence("screenplay"),
        )
        with self.assertRaises(ValidationError):
            quality_chain_report([story, screenplay])

        tampered = deepcopy(story)
        tampered["decision"] = "PASS"
        with self.assertRaises(ValidationError):
            verify_quality_gate_report(tampered)

    def test_build_quality_report_records_local_regression_without_rescuing_gate(self) -> None:
        report = QualityGateEngine().evaluate(
            gate_id="story_quality_gate",
            build_id="20260722-001",
            checks={
                **passing_checks("story_quality_gate"),
                "article_traceable": False,
            },
            artifact_refs=evidence("story"),
        )
        summary = build_quality_report(
            build_id="20260722-001",
            reports=[report],
            baseline_scores={"story_quality_gate": 1.0},
        )
        self.assertEqual(summary["failed_gate_count"], 1)
        self.assertEqual(summary["regressions"][0]["gate_id"], "story_quality_gate")
        self.assertFalse(summary["regression_blocking"])

    def test_repository_quality_report_is_cas_backed_and_tamper_evident(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = BuildRepository(Path(temporary))
            manifest = repository.create(
                "20260722-001", {"content_hash": "sha256:x"}, "preview", {}
            )
            repository.store_artifact(
                manifest,
                ArtifactEnvelope(
                    artifact_type="story",
                    build_id=manifest["build_id"],
                    data={"valid": True},
                ),
            )
            report = QualityGateEngine().evaluate(
                gate_id="story_quality_gate",
                build_id=manifest["build_id"],
                checks=passing_checks("story_quality_gate"),
                artifact_refs=[
                    {
                        "artifact_type": "story",
                        "artifact_id": manifest["artifacts"]["story"]["artifact_id"],
                        "content_hash": manifest["artifacts"]["story"]["content_hash"],
                    }
                ],
            )
            manifest = repository.record_quality_report(manifest, report)
            verification = repository.verify_quality(manifest)
            self.assertTrue(verification["valid"])
            reference = manifest["quality"]["reports"][0]
            envelope = read_json(Path(reference["path"]))
            envelope["data"]["decision"] = "FAIL"
            atomic_write_json(Path(reference["path"]), envelope)
            with self.assertRaises(ValidationError):
                repository.verify_quality(manifest)

    def test_planning_emits_canonical_stage_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            orchestrator = BuildOrchestrator(Path(temporary), profile="preview")
            planned = orchestrator.plan(ROOT / "examples" / "decision-boundary.md")
            manifest = orchestrator.repository.load(planned["build_id"])
            reports = orchestrator.repository.load_quality_reports(manifest)
            self.assertEqual(
                [report["gate_id"] for report in reports],
                [
                    "story_quality_gate",
                    "screenplay_quality_gate",
                    "shot_quality_gate",
                    "storyboard_quality_gate",
                ],
            )
            story_checks = {
                value["check_id"] for value in reports[0]["mandatory_checks"]
            }
            self.assertIn("article_traceable", story_checks)
            self.assertIn("human_grounded", story_checks)
            shot_report = reports[2]
            required_shot_checks = {
                "purpose_exists",
                "camera_defined",
                "blocking_defined",
                "emotion_defined",
                "continuity_valid",
                "render_strategy_defined",
                "single_action",
                "single_camera_move",
            }
            self.assertEqual(
                {item["check_id"] for item in shot_report["mandatory_checks"]},
                required_shot_checks,
            )

    def test_published_build_has_closed_gate_chain_and_quality_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            orchestrator = BuildOrchestrator(Path(temporary), profile="preview")
            planned = orchestrator.plan(ROOT / "examples" / "decision-boundary.md")
            build_id = planned["build_id"]
            orchestrator.approve(build_id, gate="execution", actor="quality-test")
            ready = orchestrator.execute(build_id)
            self.assertIn("build_quality_report", ready["artifacts"])
            self.assertTrue(Path(ready["artifacts"]["metadata"]["path"]).is_file())
            orchestrator.approve(build_id, gate="publish", actor="quality-test")
            published = orchestrator.publish(build_id)
            self.assertTrue(published["gates"]["publication_quality_gate"]["passed"])
            self.assertIn("published_build_quality_report", published["artifacts"])
            verification = orchestrator.verify(build_id)
            self.assertTrue(verification["quality_integrity"])
            self.assertGreaterEqual(verification["quality"]["report_count"], 13)
            self.assertIsNone(verification["quality"]["chain"]["halted_at"])
            self.assertGreaterEqual(
                verification["quality"]["approval_audit_count"], 3
            )


if __name__ == "__main__":
    unittest.main()
