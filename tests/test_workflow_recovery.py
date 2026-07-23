from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil
import tempfile
import unittest

from insynergy_cinematic.errors import ValidationError
from insynergy_cinematic.github_actions import (
    create_workflow_evidence,
    verify_workflow_evidence,
)
from tools.github_planning_source import resolve_planning_source
from tools.recover_planning_evidence import inspect_recovery, recover


RUN_ID = "29975671551"
SOURCE_SHA = "2e574ae951f88b2809b0c99a51bff8ba3873e93a"
REPOSITORY = "Insynergy-jp/Insynergy-Cinematic-Thought-Leadership-Platform"
BUILD_ID = "20260723-001"


class WorkflowRecoveryTests(unittest.TestCase):
    @staticmethod
    def _run_metadata() -> dict:
        repository = {"full_name": REPOSITORY}
        return {
            "id": int(RUN_ID),
            "name": "Plan Article",
            "path": ".github/workflows/plan.yml",
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
            "head_branch": "main",
            "head_sha": SOURCE_SHA,
            "repository": repository,
            "head_repository": repository,
        }

    @staticmethod
    def _sealed_planning_root(root: Path) -> bytes:
        persona_result = b'{"build_id":"20260723-001","gate":"persona"}\n'
        (root / "persona-approval-result.json").write_bytes(persona_result)
        (root / "planning-result.json").write_text(
            '{"build_id":"20260723-001"}\n', encoding="utf-8"
        )
        (root / "build-id.txt").write_text(BUILD_ID + "\n", encoding="utf-8")
        create_workflow_evidence(
            root=root,
            paths=(
                Path("planning-result.json"),
                Path("persona-approval-result.json"),
                Path("build-id.txt"),
            ),
            output=Path("workflow-evidence.json"),
            stage="planning",
            build_id=BUILD_ID,
            profile="final",
            workflow="Plan Article",
            repository=REPOSITORY,
            run_id=RUN_ID,
            run_attempt="1",
            source_sha=SOURCE_SHA,
        )
        return persona_result

    def test_planning_source_is_same_repository_successful_main_run(self) -> None:
        result = resolve_planning_source(
            self._run_metadata(),
            repository=REPOSITORY,
            run_id=RUN_ID,
            workflow="Plan Article",
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["source_sha"], SOURCE_SHA)

    def test_planning_source_rejects_failed_fork_or_non_main_run(self) -> None:
        invalid_values = (
            ("conclusion", "failure"),
            ("head_branch", "feature/recovery"),
            ("path", ".github/workflows/execute.yml"),
            ("head_sha", "not-a-sha"),
        )
        for field, value in invalid_values:
            metadata = deepcopy(self._run_metadata())
            metadata[field] = value
            with self.subTest(field=field), self.assertRaises(ValidationError):
                resolve_planning_source(
                    metadata,
                    repository=REPOSITORY,
                    run_id=RUN_ID,
                    workflow="Plan Article",
                )
        fork = deepcopy(self._run_metadata())
        fork["head_repository"] = {"full_name": "untrusted/fork"}
        with self.assertRaises(ValidationError):
            resolve_planning_source(
                fork,
                repository=REPOSITORY,
                run_id=RUN_ID,
                workflow="Plan Article",
            )

    def test_exact_persona_file_is_recovered_and_full_evidence_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            persona_result = self._sealed_planning_root(root)
            source_root = root / "planning-base"
            source_root.mkdir()
            shutil.copyfile(
                root / "persona-approval-result.json",
                source_root / "persona-approval-result.json",
            )
            (root / "persona-approval-result.json").unlink()

            inspection = inspect_recovery(root, Path("workflow-evidence.json"))
            self.assertTrue(inspection["recovery_required"])
            result = recover(root, Path("workflow-evidence.json"), source_root)
            self.assertTrue(result["passed"])
            self.assertEqual((root / "persona-approval-result.json").read_bytes(), persona_result)
            verification = verify_workflow_evidence(
                Path("workflow-evidence.json"),
                root=root,
                expected_stage="planning",
                expected_build_id=BUILD_ID,
                expected_profile="final",
                expected_workflow="Plan Article",
                expected_repository=REPOSITORY,
                expected_run_id=RUN_ID,
                expected_source_sha=SOURCE_SHA,
            )
            self.assertTrue(verification["passed"])

    def test_recovery_rejects_other_missing_files_and_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._sealed_planning_root(root)
            source_root = root / "planning-base"
            source_root.mkdir()
            (source_root / "persona-approval-result.json").write_text(
                '{"tampered":true}\n', encoding="utf-8"
            )
            (root / "persona-approval-result.json").unlink()
            with self.assertRaises(ValidationError):
                recover(root, Path("workflow-evidence.json"), source_root)

            (root / "planning-result.json").unlink()
            with self.assertRaises(ValidationError):
                inspect_recovery(root, Path("workflow-evidence.json"))

    def test_workflows_preserve_persona_evidence_and_bind_recovery_to_source(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        plan = (repository_root / ".github" / "workflows" / "plan.yml").read_text(
            encoding="utf-8"
        )
        execute = (
            repository_root / ".github" / "workflows" / "execute.yml"
        ).read_text(encoding="utf-8")
        finalize = plan.split("  finalize-off:", 1)[1].split("  agent-review:", 1)[0]
        self.assertIn("persona-approval-result.json", finalize)
        self.assertIn("tools/github_planning_source.py", execute)
        self.assertIn("tools/recover_planning_evidence.py", execute)
        self.assertIn("tools/verify_runtime_compatibility.py", execute)
        self.assertIn("source-sha: ${{ steps.planning_source.outputs.source_sha }}", execute)
        self.assertIn("fetch-depth: 0", execute)
        self.assertNotIn("Checkout approved planning source", execute)


if __name__ == "__main__":
    unittest.main()
