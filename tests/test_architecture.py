from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from insynergy_cinematic.architecture import (
    ArchitectureValidator,
    architecture_audit,
    architecture_contract,
    part1_coverage_report,
    provider_isolation_audit,
)
from insynergy_cinematic.cli import main
from insynergy_cinematic.errors import ValidationError
from insynergy_cinematic.orchestrator import BuildOrchestrator, PLANNING_ARTIFACTS
from insynergy_cinematic.util import content_hash


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "insynergy_cinematic"


class ArchitectureTests(unittest.TestCase):
    def test_part1_coverage_reaches_full_runtime_observability(self) -> None:
        report = part1_coverage_report()
        self.assertEqual(report["cluster_count"], 20)
        self.assertEqual(report["counts"], {"full": 20, "partial": 0, "missing": 0})
        self.assertEqual(report["points"], 20.0)
        self.assertEqual(report["coverage_percent"], 100.0)
        self.assertTrue(report["target_met"])

    def test_canonical_contract_and_source_provider_isolation_pass(self) -> None:
        contract = architecture_contract()
        report = ArchitectureValidator().assert_valid(contract)
        self.assertTrue(report["passed"])
        self.assertEqual(report["check_count"], 20)
        self.assertEqual(len(contract["layers"]), 8)
        self.assertEqual(
            [item["id"] for item in contract["objectives"]],
            [f"O{index}" for index in range(1, 8)],
        )
        self.assertEqual(
            [item["id"] for item in contract["non_objectives"]],
            [f"N{index}" for index in range(1, 6)],
        )
        audit = architecture_audit(PACKAGE)
        self.assertTrue(audit["source_provider_isolation"]["passed"])

    def test_contract_is_deterministic(self) -> None:
        first = architecture_contract()
        second = architecture_contract()
        self.assertEqual(first, second)
        self.assertEqual(content_hash(first), content_hash(second))

    def test_layer_skip_and_provider_leak_fail_closed(self) -> None:
        skipped = deepcopy(architecture_contract())
        skipped["layers"][5]["depends_on"] = 4
        report = ArchitectureValidator().validate(skipped)
        self.assertFalse(report["passed"])
        self.assertIn("adjacent_layer_dependencies_only", report["violations"])

        leaked = deepcopy(architecture_contract())
        leaked["layers"][1]["rendering_provider_aware"] = True
        report = ArchitectureValidator().validate(leaked)
        self.assertFalse(report["passed"])
        self.assertIn("rendering_provider_confined", report["violations"])
        with self.assertRaises(ValidationError):
            ArchitectureValidator().assert_valid(leaked)

    def test_shortcuts_secondary_branches_and_approval_bypass_fail(self) -> None:
        for source, destination, payload, expected in (
            (
                "article_loader",
                "render_strategy",
                "structured_article_model",
                "shortcuts_and_gate_bypass_prohibited",
            ),
            (
                "story_engine",
                "render_strategy",
                "story_model",
                "sole_render_branch_and_composer_convergence",
            ),
            (
                "quality_gates",
                "publish_package",
                "validated_build",
                "shortcuts_and_gate_bypass_prohibited",
            ),
        ):
            with self.subTest(edge=(source, destination)):
                damaged = deepcopy(architecture_contract())
                damaged["flow"]["edges"].append(
                    {"from": source, "to": destination, "payload": payload}
                )
                report = ArchitectureValidator().validate(damaged)
                self.assertFalse(report["passed"])
                self.assertIn(expected, report["violations"])

    def test_agent_authority_and_persona_rounds_are_bounded(self) -> None:
        review = deepcopy(architecture_contract())
        review["authority_boundaries"]["agent_review"]["may_approve"] = True
        report = ArchitectureValidator().validate(review)
        self.assertIn("agent_review_read_only_and_fail_closed", report["violations"])

        council = deepcopy(architecture_contract())
        council["authority_boundaries"]["persona_council"]["rounds"]["critique"] = 2
        council["authority_boundaries"]["persona_council"]["handoffs"] = True
        report = ArchitectureValidator().validate(council)
        self.assertIn("persona_council_bounded_and_human_gated", report["violations"])

    def test_provider_import_audit_detects_protected_layer_leak(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            for filename in (
                "article.py",
                "story.py",
                "screenplay.py",
                "shot_planner.py",
                "prompt.py",
                "package.py",
            ):
                (target / filename).write_text("VALUE = 1\n", encoding="utf-8")
            (target / "story.py").write_text(
                "from .providers.runway import RunwayProvider\n", encoding="utf-8"
            )
            report = provider_isolation_audit(target)
            self.assertFalse(report["passed"])
            self.assertEqual(report["violations"][0]["module"], "story.py")

    def test_plan_seals_architecture_evidence_before_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            orchestrator = BuildOrchestrator(Path(temporary), profile="preview", environ={})
            view = orchestrator.plan(ROOT / "examples" / "decision-boundary.md")
            self.assertTrue(
                {"architecture_contract", "architecture_validation_report"}.issubset(
                    PLANNING_ARTIFACTS
                )
            )
            self.assertTrue(view["gates"]["architecture_conformance_gate"]["passed"])
            manifest = orchestrator.repository.load(view["build_id"])
            contract = orchestrator.repository.load_artifact(
                manifest, "architecture_contract"
            )
            report = orchestrator.repository.load_artifact(
                manifest, "architecture_validation_report"
            )
            execution_plan = orchestrator.repository.load_artifact(
                manifest, "execution_plan"
            )
            self.assertEqual(
                report["data"]["contract_content_hash"], contract["content_hash"]
            )
            self.assertIn(
                contract["content_hash"], execution_plan["provenance"]["input_hashes"]
            )
            self.assertIn(
                report["content_hash"], execution_plan["provenance"]["input_hashes"]
            )

    def test_cli_exposes_coverage_and_audit(self) -> None:
        coverage_output = StringIO()
        with redirect_stdout(coverage_output):
            result = main(["--compact", "part1-coverage"])
        self.assertEqual(result, 0)
        self.assertIn('"coverage_percent":100.0', coverage_output.getvalue())

        audit_output = StringIO()
        with redirect_stdout(audit_output):
            result = main(
                ["--compact", "audit-architecture", "--source-root", str(PACKAGE)]
            )
        self.assertEqual(result, 0)
        self.assertIn('"passed":true', audit_output.getvalue())


if __name__ == "__main__":
    unittest.main()
