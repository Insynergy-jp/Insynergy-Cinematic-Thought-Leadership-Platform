from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from insynergy_cinematic.errors import StateConflictError, ValidationError
from insynergy_cinematic.cli import main
from insynergy_cinematic.outcomes import OutcomeDashboard, OutcomeThresholds, ViewerOutcomeRepository
from insynergy_cinematic.storage import BuildRepository
from insynergy_cinematic.util import atomic_write_json, read_json


class ViewerOutcomeTests(unittest.TestCase):
    def _build(self, root: Path, sequence: int = 1) -> str:
        build_id = f"20260722-{sequence:03d}"
        BuildRepository(root).create(
            build_id,
            source={"content_hash": "sha256:" + "a" * 64},
            profile="preview",
            config={"platform_version": "3.3.0"},
        )
        return build_id

    def _record(
        self,
        repository: ViewerOutcomeRepository,
        build_id: str,
        index: int,
        **overrides,
    ):
        values = {
            "build_id": build_id,
            "viewer_id": f"person-{index}@example.com",
            "idea_restatement_accuracy": 0.92,
            "unaided_recall": 0.84,
            "reaction_subject": "IDEA",
            "accuracy_gate_result": "PASS",
            "retention_interval_hours": 168 + index,
            "cohort": "executive-pilot",
            "observed_at": f"2026-07-{10 + index:02d}T09:00:00Z",
            "idempotency_key": f"survey-{index}",
        }
        values.update(overrides)
        return repository.record(**values)

    def test_append_only_idempotency_privacy_and_tamper_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_id = self._build(root)
            repository = ViewerOutcomeRepository(root)
            first = self._record(repository, build_id, 1)
            repeated = self._record(repository, build_id, 1)
            self.assertTrue(first["created"])
            self.assertFalse(repeated["created"])
            self.assertNotIn("viewer", " ".join(first.keys()))
            event_path = repository.evaluations / f"{first['evaluation_id']}.json"
            self.assertNotIn("person-1@example.com", event_path.read_text(encoding="utf-8"))
            self.assertEqual(repository.events()[1]["version"], 1)
            with self.assertRaises(StateConflictError):
                self._record(
                    repository,
                    build_id,
                    1,
                    idea_restatement_accuracy=0.2,
                )

            implicit = repository.record(
                build_id=build_id,
                viewer_id="implicit@example.com",
                idea_restatement_accuracy=0.9,
                unaided_recall=0.8,
                reaction_subject="IDEA",
                accuracy_gate_result="PASS",
                retention_interval_hours=168,
                idempotency_key="implicit-time",
            )
            implicit_replay = repository.record(
                build_id=build_id,
                viewer_id="implicit@example.com",
                idea_restatement_accuracy=0.9,
                unaided_recall=0.8,
                reaction_subject="IDEA",
                accuracy_gate_result="PASS",
                retention_interval_hours=168,
                idempotency_key="implicit-time",
            )
            self.assertEqual(implicit["evaluation_id"], implicit_replay["evaluation_id"])
            self.assertFalse(implicit_replay["created"])

            tampered = read_json(event_path)
            tampered["unaided_recall"] = 0.1
            atomic_write_json(event_path, tampered)
            with self.assertRaises(ValidationError):
                repository.events()

    def test_concurrent_appends_preserve_one_hash_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_id = self._build(root)
            repository = ViewerOutcomeRepository(root)
            with ThreadPoolExecutor(max_workers=5) as executor:
                results = list(
                    executor.map(
                        lambda index: self._record(repository, build_id, index),
                        range(1, 11),
                    )
                )
            self.assertEqual(len({result["evaluation_id"] for result in results}), 10)
            events, ledger = repository.events()
            self.assertEqual((len(events), ledger["version"]), (10, 10))
            self.assertEqual(
                [entry["sequence"] for entry in ledger["entries"]],
                list(range(1, 11)),
            )

    def test_dashboard_success_requires_long_term_comprehension_and_retention(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_id = self._build(root)
            repository = ViewerOutcomeRepository(root)
            for index in range(1, 6):
                self._record(repository, build_id, index)
            dashboard = OutcomeDashboard(root)
            report = dashboard.report(
                generated_at="2026-07-22T12:00:00Z",
                thresholds=OutcomeThresholds(minimum_sample_size=5),
            )
            self.assertEqual(report["aggregate"]["verdict"], "SUCCESS")
            self.assertEqual(report["aggregate"]["retention_eligible_sample_size"], 5)
            self.assertEqual(report["aggregate"]["comprehension_pass_rate"], 1.0)
            self.assertEqual(report["aggregate"]["retention_pass_rate"], 1.0)
            self.assertTrue(report["integrity"]["verified"])
            rendered = dashboard.render_html(report)
            self.assertIn("Viewer understanding & memory", rendered)
            self.assertNotIn("person-1@example.com", rendered)
            self.assertNotIn("viewer-hmac:", rendered)

    def test_medium_foregrounding_is_decisive_and_short_term_is_not_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_id = self._build(root)
            repository = ViewerOutcomeRepository(root)
            self._record(
                repository,
                build_id,
                1,
                reaction_subject="MEDIUM",
            )
            failed = OutcomeDashboard(root).report(
                generated_at="2026-07-22T12:00:00Z"
            )
            self.assertEqual(failed["aggregate"]["verdict"], "FAIL")
            self.assertEqual(failed["aggregate"]["medium_foregrounding_count"], 1)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_id = self._build(root)
            repository = ViewerOutcomeRepository(root)
            for index in range(1, 6):
                self._record(
                    repository,
                    build_id,
                    index,
                    retention_interval_hours=24,
                )
            pending = OutcomeDashboard(root).report(
                generated_at="2026-07-22T12:00:00Z"
            )
            self.assertEqual(
                pending["aggregate"]["verdict"], "INSUFFICIENT_EVIDENCE"
            )
            self.assertEqual(
                pending["aggregate"]["outcome_counts"]["pending_retention"], 5
            )

    def test_cli_records_and_writes_html_and_json_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_id = self._build(root)
            output = StringIO()
            with redirect_stdout(output):
                result = main(
                    [
                        "--workspace",
                        str(root),
                        "--compact",
                        "record-viewer-outcome",
                        build_id,
                        "--viewer-id",
                        "cli-viewer@example.com",
                        "--idea-restatement-accuracy",
                        "0.9",
                        "--unaided-recall",
                        "0.8",
                        "--reaction-subject",
                        "IDEA",
                        "--accuracy-gate-result",
                        "PASS",
                        "--retention-hours",
                        "168",
                        "--idempotency-key",
                        "cli-event-1",
                    ]
                )
            self.assertEqual(result, 0)
            self.assertIn('"created":true', output.getvalue())
            html_path = root / "viewer-dashboard.html"
            json_path = root / "viewer-dashboard.json"
            with redirect_stdout(StringIO()):
                result = main(
                    [
                        "--workspace",
                        str(root),
                        "outcomes-dashboard",
                        "--output",
                        str(html_path),
                        "--json-output",
                        str(json_path),
                    ]
                )
            self.assertEqual(result, 0)
            self.assertTrue(html_path.is_file())
            self.assertTrue(json_path.is_file())


if __name__ == "__main__":
    unittest.main()
