from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from insynergy_cinematic.errors import ValidationError
from insynergy_cinematic.github_actions import (
    create_workflow_evidence,
    part8_coverage_report,
    resolve_github_environment_policy,
    resolve_github_environment_review,
    validate_storyboard_preview_recovery_bundle,
    verify_workflow_evidence,
    workflow_summary,
)
from insynergy_cinematic.util import atomic_write_json, content_hash, read_json
from tools.validate_workflows import ROOT, _validate_workflow, validate


BUILD_ID = "20260722-001"
SOURCE_SHA = "a" * 40


class GitHubActionsArchitectureTests(unittest.TestCase):
    @staticmethod
    def _workflow_run(
        run_id: str, *, name: str, path: str, conclusion: str
    ) -> dict:
        repository = {"full_name": "Insynergy-jp/platform"}
        return {
            "id": int(run_id),
            "name": name,
            "path": path,
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": conclusion,
            "head_branch": "main",
            "head_sha": SOURCE_SHA,
            "repository": repository,
            "head_repository": repository,
        }

    def _environment_approval(
        self,
        *,
        reviewer: str = "persona-reviewer",
        reviewer_id: int = 987654,
        state: str = "approved",
    ) -> dict:
        return {
            "state": state,
            "comment": "Reviewed sealed Persona evidence.",
            "environments": [{"id": 18541388227, "name": "persona-approval"}],
            "user": {"login": reviewer, "id": reviewer_id},
        }

    def _environment_configuration(self, *, prevent_self_review: bool) -> dict:
        return {
            "id": 18541388227,
            "name": "persona-approval",
            "protection_rules": [
                {
                    "id": 12345,
                    "type": "required_reviewers",
                    "prevent_self_review": prevent_self_review,
                    "reviewers": [
                        {
                            "type": "User",
                            "reviewer": {"login": "Insynergy-jp", "id": 238604656},
                        }
                    ],
                }
            ],
            "deployment_branch_policy": {
                "protected_branches": False,
                "custom_branch_policies": True,
            },
        }

    @staticmethod
    def _main_branch_policy() -> dict:
        return {
            "total_count": 1,
            "branch_policies": [{"id": 4815162342, "name": "main", "type": "branch"}],
        }

    def _create(self, root: Path) -> dict:
        (root / "bundle").mkdir()
        (root / "bundle" / "manifest.json").write_text(
            '{"state":"READY"}\n', encoding="utf-8"
        )
        (root / "build-id.txt").write_text(BUILD_ID + "\n", encoding="utf-8")
        return create_workflow_evidence(
            root=root,
            paths=(Path("bundle"), Path("build-id.txt")),
            output=Path("workflow-evidence.json"),
            stage="execution",
            build_id=BUILD_ID,
            profile="preview",
            workflow="Execute Approved Plan",
            repository="Insynergy-jp/platform",
            run_id="12345",
            run_attempt="1",
            source_sha=SOURCE_SHA,
        )

    def _verify(self, root: Path) -> dict:
        return verify_workflow_evidence(
            Path("workflow-evidence.json"),
            root=root,
            expected_stage="execution",
            expected_build_id=BUILD_ID,
            expected_profile="preview",
            expected_workflow="Execute Approved Plan",
            expected_repository="Insynergy-jp/platform",
            expected_run_id="12345",
            expected_source_sha=SOURCE_SHA,
        )

    def test_part8_coverage_includes_isolated_persona_workflow(self) -> None:
        report = part8_coverage_report()
        self.assertEqual(report["cluster_count"], 20)
        self.assertEqual((report["full"], report["partial"], report["missing"]), (18, 2, 0))
        self.assertEqual(report["coverage_percent"], 95.0)
        self.assertEqual(
            {
                row["cluster"]
                for row in report["clusters"]
                if row["status"] == "FULL"
            },
            {
                "host_domain_boundary",
                "trigger_and_input_contracts",
                "deterministic_planning",
                "agent_review_isolation",
                "independent_approvals",
                "execution_preflight",
                "quality_gated_delivery",
                "concurrency_and_idempotency",
                "manifest_resume_projection",
                "backpressure_and_cost",
                "secret_scoping",
                "token_least_privilege",
                "action_supply_chain",
                "untrusted_input_protection",
                "artifact_integrity",
                "observability_and_diagnostics",
                "workflow_testing_and_runbooks",
                "persona_council_workflow",
            },
        )

    def test_transport_evidence_round_trip_is_hash_and_source_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = self._create(root)
            verification = self._verify(root)
            self.assertTrue(verification["passed"])
            self.assertEqual(verification["bundle_hash"], evidence["bundle_hash"])
            with self.assertRaises(ValidationError):
                verify_workflow_evidence(
                    Path("workflow-evidence.json"),
                    root=root,
                    expected_stage="execution",
                    expected_build_id=BUILD_ID,
                    expected_profile="final",
                    expected_workflow="Execute Approved Plan",
                    expected_repository="Insynergy-jp/platform",
                    expected_run_id="12345",
                    expected_source_sha=SOURCE_SHA,
                )

    def test_file_and_evidence_tampering_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._create(root)
            (root / "bundle" / "manifest.json").write_text(
                '{"state":"PUBLISHED"}\n', encoding="utf-8"
            )
            with self.assertRaises(ValidationError):
                self._verify(root)

            self._create_fresh_over_existing(root)
            evidence = read_json(root / "workflow-evidence.json")
            tampered = deepcopy(evidence)
            tampered["profile"] = "final"
            atomic_write_json(root / "workflow-evidence.json", tampered)
            with self.assertRaises(ValidationError):
                self._verify(root)

    def _create_fresh_over_existing(self, root: Path) -> None:
        (root / "bundle" / "manifest.json").write_text(
            '{"state":"READY"}\n', encoding="utf-8"
        )
        create_workflow_evidence(
            root=root,
            paths=(Path("bundle"), Path("build-id.txt")),
            output=Path("workflow-evidence.json"),
            stage="execution",
            build_id=BUILD_ID,
            profile="preview",
            workflow="Execute Approved Plan",
            repository="Insynergy-jp/platform",
            run_id="12345",
            run_attempt="1",
            source_sha=SOURCE_SHA,
        )

    def test_secret_patterns_and_symlinks_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bundle").mkdir()
            (root / "bundle" / "result.json").write_text(
                '{"OPENAI_API_KEY":"sk-example-key-material-123456"}', encoding="utf-8"
            )
            (root / "build-id.txt").write_text(BUILD_ID + "\n", encoding="utf-8")
            with self.assertRaises(ValidationError):
                create_workflow_evidence(
                    root=root,
                    paths=(Path("bundle"),),
                    output=Path("workflow-evidence.json"),
                    stage="execution",
                    build_id=BUILD_ID,
                    profile="preview",
                    workflow="Execute Approved Plan",
                    repository="Insynergy-jp/platform",
                    run_id="12345",
                    run_attempt="1",
                    source_sha=SOURCE_SHA,
                )
            (root / "bundle" / "result.json").write_text("{}\n", encoding="utf-8")
            (root / "bundle" / "link.json").symlink_to(root / "bundle" / "result.json")
            with self.assertRaises(ValidationError):
                create_workflow_evidence(
                    root=root,
                    paths=(Path("bundle"),),
                    output=Path("workflow-evidence.json"),
                    stage="execution",
                    build_id=BUILD_ID,
                    profile="preview",
                    workflow="Execute Approved Plan",
                    repository="Insynergy-jp/platform",
                    run_id="12345",
                    run_attempt="1",
                    source_sha=SOURCE_SHA,
                )

    def test_summary_is_allowlisted_and_never_includes_payload_body(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self._create(Path(temporary))
            summary = workflow_summary(
                evidence,
                result={"state": "READY", "article": "unpublished source body"},
            )
            self.assertIn(BUILD_ID, summary)
            self.assertIn("READY", summary)
            self.assertNotIn("unpublished source body", summary)

    def test_repository_workflows_pass_the_structural_policy(self) -> None:
        self.assertEqual(validate(), [])

    def test_storyboard_preview_workflow_is_zero_runway_and_separates_approvals(self) -> None:
        preview = (ROOT / ".github" / "workflows" / "preview.yml").read_text(
            encoding="utf-8"
        )
        execute = (ROOT / ".github" / "workflows" / "execute.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("environment: planning-ai", preview)
        self.assertIn("environment: storyboard-preview-approval", preview)
        self.assertIn("needs: preflight", preview)
        self.assertIn("preview-preflight", preview)
        self.assertIn("provider_run_id", preview)
        self.assertIn("Validate failed-run recovery binding", preview)
        self.assertIn("github_preview_recovery.py", preview)
        self.assertIn("recomposition_verification", preview)
        self.assertIn("if: always() && needs.compose.result == 'success'", preview)
        self.assertNotIn("RUNWAY_API_KEY", preview)
        self.assertNotIn("api.dev.runwayml.com", preview)
        self.assertIn("Resolve actual Storyboard Preview reviewer", preview)
        self.assertIn("--gate storyboard-preview", preview)
        self.assertIn("--environment-reviewer-id", preview)
        self.assertIn("--environment-policy-hash", preview)
        self.assertIn("environment: render-approval", execute)
        self.assertIn("--pre-render-preview-mode", execute)

    def test_storyboard_preview_recovery_binds_failed_run_without_provider_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build = root / ".insynergy" / "builds" / BUILD_ID
            artifacts = build / "artifacts"
            artifacts.mkdir(parents=True)
            (root / "build-id.txt").write_text(BUILD_ID + "\n", encoding="utf-8")

            files = [{"path": "build-id.txt", "size": 13, "sha256": "sha256:test"}]
            evidence = {
                "schema_version": "1.0.0",
                "contract_version": "workflow-evidence/1",
                "stage": "planning",
                "build_id": BUILD_ID,
                "profile": "preview",
                "source": {
                    "workflow": "Plan Article",
                    "repository": "Insynergy-jp/platform",
                    "run_id": "12345",
                    "run_attempt": "1",
                    "source_sha": SOURCE_SHA,
                },
                "secret_scan": {"status": "PASS", "policy": "artifact-patterns/1"},
                "files": files,
                "bundle_hash": content_hash(files),
            }
            evidence["evidence_hash"] = content_hash(evidence)
            atomic_write_json(root / "workflow-evidence.json", evidence)

            preflight = {
                "build_id": BUILD_ID,
                "passed": True,
                "openai_provider_initialized": False,
                "runway_provider_initialized": False,
                "runway_api_calls": 0,
            }
            preflight["content_hash"] = content_hash(preflight)
            atomic_write_json(root / "preview-preflight-result.json", preflight)

            preview_data = {
                "runway_contacted": False,
                "provider_calls": {"gpt_plan": 1, "gpt_image": 8, "runway": 0},
            }
            preview_document = {
                "build_id": BUILD_ID,
                "content_hash": content_hash(preview_data),
                "data": preview_data,
            }
            atomic_write_json(
                artifacts / "storyboard_preview_manifest.json", preview_document
            )
            manifest = {
                "build_id": BUILD_ID,
                "profile": "preview",
                "state": "AWAITING_STORYBOARD_PREVIEW_APPROVAL",
                "previsualization": {"runway_api_calls": 0},
                "artifacts": {
                    "storyboard_preview_manifest": {
                        "content_hash": preview_document["content_hash"]
                    }
                },
            }
            atomic_write_json(build / "manifest.json", manifest)
            atomic_write_json(
                root / "preview-result.json",
                {
                    "build_id": BUILD_ID,
                    "state": "AWAITING_STORYBOARD_PREVIEW_APPROVAL",
                    "previsualization": {
                        "status": "PREVIEW_READY",
                        "runway_api_calls": 0,
                    },
                },
            )

            provider_run = self._workflow_run(
                "67890",
                name="Storyboard Preview",
                path=".github/workflows/preview.yml",
                conclusion="failure",
            )
            planning_run = self._workflow_run(
                "12345",
                name="Plan Article",
                path=".github/workflows/plan.yml",
                conclusion="success",
            )
            result = validate_storyboard_preview_recovery_bundle(
                root=root,
                repository="Insynergy-jp/platform",
                provider_run_id="67890",
                planning_run_id="12345",
                build_id=BUILD_ID,
                profile="preview",
                provider_run=provider_run,
                planning_run=planning_run,
            )
            self.assertTrue(result["passed"])
            self.assertEqual(result["openai_api_calls"], 0)
            self.assertEqual(result["runway_api_calls"], 0)

            invalid = deepcopy(provider_run)
            invalid["conclusion"] = "success"
            with self.assertRaises(ValidationError):
                validate_storyboard_preview_recovery_bundle(
                    root=root,
                    repository="Insynergy-jp/platform",
                    provider_run_id="67890",
                    planning_run_id="12345",
                    build_id=BUILD_ID,
                    profile="preview",
                    provider_run=invalid,
                    planning_run=planning_run,
                )

    def test_environment_review_resolves_actual_reviewer_separately(self) -> None:
        record = resolve_github_environment_review(
            [self._environment_approval()],
            repository="Insynergy-jp/platform",
            run_id="12345",
            run_attempt="1",
            environment="persona-approval",
            workflow_initiator="workflow-owner",
            require_distinct_reviewer=True,
        )
        self.assertEqual(record["workflow_initiator"], "workflow-owner")
        self.assertEqual(record["environment_reviewer"], "persona-reviewer")
        self.assertEqual(record["environment_reviewer_id"], 987654)
        self.assertTrue(record["prevent_self_review"])
        self.assertTrue(record["content_hash"].startswith("sha256:"))

    def test_environment_review_missing_ambiguous_rejected_and_self_fail_closed(self) -> None:
        base = {
            "repository": "Insynergy-jp/platform",
            "run_id": "12345",
            "run_attempt": "1",
            "environment": "persona-approval",
            "workflow_initiator": "workflow-owner",
            "require_distinct_reviewer": True,
        }
        invalid_histories = (
            [],
            [self._environment_approval(state="rejected")],
            [self._environment_approval(reviewer="workflow-owner")],
            [
                self._environment_approval(reviewer="persona-reviewer"),
                {
                    **self._environment_approval(reviewer="second-reviewer"),
                    "user": {"login": "second-reviewer", "id": 123456},
                },
            ],
        )
        for history in invalid_histories:
            with self.subTest(history=history), self.assertRaises(ValidationError):
                resolve_github_environment_review(history, **base)

    def test_environment_policy_allows_configured_self_review_only_when_disabled(self) -> None:
        policy = resolve_github_environment_policy(
            self._environment_configuration(prevent_self_review=False),
            environment="persona-approval",
            branch_policies=self._main_branch_policy(),
        )
        record = resolve_github_environment_review(
            [
                self._environment_approval(
                    reviewer="Insynergy-jp", reviewer_id=238604656
                )
            ],
            repository="Insynergy-jp/platform",
            run_id="12345",
            run_attempt="1",
            environment="persona-approval",
            workflow_initiator="Insynergy-jp",
            require_distinct_reviewer=policy["prevent_self_review"],
            required_reviewer_ids=frozenset(
                reviewer["id"] for reviewer in policy["required_reviewers"]
            ),
            environment_policy_hash=policy["content_hash"],
        )
        self.assertFalse(record["prevent_self_review"])
        self.assertEqual(record["workflow_initiator"], "Insynergy-jp")
        self.assertEqual(record["environment_reviewer"], "Insynergy-jp")
        self.assertEqual(record["environment_policy_hash"], policy["content_hash"])

        enabled = resolve_github_environment_policy(
            self._environment_configuration(prevent_self_review=True),
            environment="persona-approval",
            branch_policies=self._main_branch_policy(),
        )
        with self.assertRaises(ValidationError):
            resolve_github_environment_review(
                [
                    self._environment_approval(
                        reviewer="Insynergy-jp", reviewer_id=238604656
                    )
                ],
                repository="Insynergy-jp/platform",
                run_id="12345",
                run_attempt="1",
                environment="persona-approval",
                workflow_initiator="Insynergy-jp",
                require_distinct_reviewer=enabled["prevent_self_review"],
                required_reviewer_ids=frozenset(
                    reviewer["id"] for reviewer in enabled["required_reviewers"]
                ),
                environment_policy_hash=enabled["content_hash"],
            )

    def test_environment_policy_without_required_reviewers_fails_closed(self) -> None:
        with self.assertRaises(ValidationError):
            resolve_github_environment_policy(
                {
                    "id": 18541388227,
                    "name": "persona-approval",
                    "protection_rules": [],
                    "deployment_branch_policy": {
                        "protected_branches": False,
                        "custom_branch_policies": True,
                    },
                },
                environment="persona-approval",
                branch_policies=self._main_branch_policy(),
            )

    def test_environment_policy_rejects_non_main_or_multiple_branches(self) -> None:
        configuration = self._environment_configuration(prevent_self_review=False)
        for branch_policies in (
            {
                "total_count": 1,
                "branch_policies": [{"id": 1, "name": "release/*", "type": "branch"}],
            },
            {
                "total_count": 2,
                "branch_policies": [
                    {"id": 1, "name": "main", "type": "branch"},
                    {"id": 2, "name": "release/*", "type": "branch"},
                ],
            },
        ):
            with self.subTest(branch_policies=branch_policies), self.assertRaises(
                ValidationError
            ):
                resolve_github_environment_policy(
                    configuration,
                    environment="persona-approval",
                    branch_policies=branch_policies,
                )

    def test_structural_policy_rejects_broad_permissions_and_shell_injection(self) -> None:
        path = ROOT / ".github" / "workflows" / "ci.yml"
        compliant = path.read_text(encoding="utf-8")
        broad = compliant.replace("contents: read", "contents: write", 1)
        self.assertTrue(
            any("permission contents: write" in error for error in _validate_workflow(path, broad))
        )
        broad_job = compliant.replace(
            "  quality:\n    runs-on:",
            "  quality:\n    permissions:\n      contents: write\n    runs-on:",
            1,
        )
        self.assertTrue(
            any(
                "job quality permission contents: write" in error
                for error in _validate_workflow(path, broad_job)
            )
        )
        injected = compliant.replace(
            "set -euo pipefail\n          sudo apt-get update",
            "echo ${{ github.event.pull_request.title }}\n          sudo apt-get update",
            1,
        )
        errors = _validate_workflow(path, injected)
        self.assertTrue(any("must start with set -euo pipefail" in error for error in errors))
        self.assertTrue(any("expressions must reach shell" in error for error in errors))

    def test_structural_policy_rejects_environment_secret_and_timeout_drift(self) -> None:
        path = ROOT / ".github" / "workflows" / "plan.yml"
        compliant = path.read_text(encoding="utf-8")
        drifted = compliant.replace("environment: planning-ai", "environment: render-approval")
        drifted = drifted.replace("timeout-minutes: 15", "", 1)
        drifted = drifted.replace(
            "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}",
            "RUNWAY_API_KEY: ${{ secrets.RUNWAY_API_KEY }}",
        )
        errors = _validate_workflow(path, drifted)
        self.assertTrue(any("must use environment planning-ai" in error for error in errors))
        self.assertTrue(any("has no timeout-minutes" in error for error in errors))
        self.assertTrue(any("uses disallowed secrets" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
