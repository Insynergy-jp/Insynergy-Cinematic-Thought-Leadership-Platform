from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import time
import unittest

from insynergy_cinematic.agent_review import (
    DIMENSION_CODES,
    AgentReviewService,
    AgentReviewStore,
    FakeAgentReviewProvider,
    build_review_request,
    clean_review_output,
)
from insynergy_cinematic.config import DEFAULT_CONFIG
from insynergy_cinematic.errors import ApprovalRequiredError, ValidationError
from insynergy_cinematic.models import BuildState
from insynergy_cinematic.orchestrator import BuildOrchestrator


ROOT = Path(__file__).resolve().parents[1]
ARTICLE = ROOT / "examples" / "decision-boundary.md"


class AgentReviewTests(unittest.TestCase):
    def test_off_mode_preserves_existing_path_without_provider_call(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            provider = FakeAgentReviewProvider()
            orchestrator = BuildOrchestrator(
                Path(temporary), review_provider=provider, environ={}
            )
            view = orchestrator.plan(ARTICLE)
            self.assertEqual(
                view["state"], BuildState.AWAITING_EXECUTION_APPROVAL.value
            )
            self.assertEqual(view["agent_review"]["status"], "DISABLED")
            self.assertEqual(
                view["gates"]["agent_review_gate"]["decision"], "NOT_APPLICABLE"
            )
            self.assertEqual(provider.calls, 0)

    def test_pass_report_is_cached_bound_and_required_by_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            provider = FakeAgentReviewProvider()
            orchestrator = BuildOrchestrator(
                Path(temporary),
                profile="preview",
                agent_review_mode="review",
                review_provider=provider,
                environ={},
            )
            planned = orchestrator.plan(ARTICLE)
            self.assertEqual(planned["state"], BuildState.PLANNED.value)
            reviewed = orchestrator.review(planned["build_id"])
            self.assertEqual(
                reviewed["state"], BuildState.AWAITING_EXECUTION_APPROVAL.value
            )
            self.assertEqual(reviewed["agent_review"]["status"], "PASS")
            self.assertEqual(provider.calls, 1)
            orchestrator.review(planned["build_id"])
            self.assertEqual(provider.calls, 1)

            approved = orchestrator.approve(
                planned["build_id"], gate="execution", actor="test-reviewer"
            )
            approval = approved["approvals"]["execution"]
            self.assertEqual(
                approval["agent_review_report_hash"],
                reviewed["agent_review"]["report_content_hash"],
            )
            self.assertIn("review_approval_binding", approved["artifacts"])
            repeated = orchestrator.approve(
                planned["build_id"], gate="execution", actor="test-reviewer"
            )
            self.assertEqual(
                repeated["approvals"]["execution"]["approval_id"],
                approval["approval_id"],
            )
            ready = orchestrator.execute(planned["build_id"])
            self.assertEqual(ready["state"], BuildState.READY.value)

    def test_manual_disposition_requires_attributable_human_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            provider = FakeAgentReviewProvider()
            orchestrator = BuildOrchestrator(
                Path(temporary),
                agent_review_mode="review",
                review_provider=provider,
                environ={},
            )
            planned = orchestrator.plan(ARTICLE)
            manifest = orchestrator.repository.load(planned["build_id"])
            article = orchestrator.repository.load_artifact(
                manifest, "structured_article"
            )
            output = clean_review_output()
            output["status"] = "MANUAL_REVIEW_REQUIRED"
            output["dimensions"][0] = {
                "code": DIMENSION_CODES[0],
                "score": 0.4,
                "passed": False,
                "summary": "A source-fidelity decision needs human judgment.",
            }
            output["findings"] = [
                {
                    "code": "AR-SOURCE_CLAIM",
                    "dimension": "SOURCE_FIDELITY",
                    "severity": "BLOCKING",
                    "blocking": True,
                    "title": "Claim requires human confirmation",
                    "rationale": "The planning interpretation cannot be accepted automatically.",
                    "evidence_refs": [
                        {
                            "artifact_type": "structured_article",
                            "artifact_id": article["artifact_id"],
                            "content_hash": article["content_hash"],
                            "json_pointer": "/title",
                        }
                    ],
                    "specification_refs": ["INV-1.0.1-1"],
                    "recommendation": "Confirm the interpretation before rendering.",
                }
            ]
            output["summary"] = "Human source-fidelity review is required."
            provider.output = output
            reviewed = orchestrator.review(planned["build_id"])
            self.assertEqual(
                reviewed["agent_review"]["status"], "MANUAL_REVIEW_REQUIRED"
            )
            with self.assertRaises(ApprovalRequiredError):
                orchestrator.approve(
                    planned["build_id"], gate="execution", actor="test-reviewer"
                )
            approved = orchestrator.approve(
                planned["build_id"],
                gate="execution",
                actor="test-reviewer",
                allow_agent_exception=True,
                agent_exception_reason="Source owner confirmed the intended interpretation.",
            )
            approval = approved["approvals"]["execution"]
            self.assertEqual(
                approval["agent_exception_code"],
                "AGENT_REVIEW_MANUAL_REVIEW_REQUIRED",
            )
            self.assertIn("Source owner", approval["agent_exception_rationale"])

    def test_malformed_output_becomes_a_classified_nonpass_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            provider = FakeAgentReviewProvider(output={"unexpected": True})
            orchestrator = BuildOrchestrator(
                Path(temporary),
                agent_review_mode="review",
                review_provider=provider,
                environ={},
            )
            planned = orchestrator.plan(ARTICLE)
            reviewed = orchestrator.review(planned["build_id"])
            self.assertEqual(reviewed["agent_review"]["status"], "ERROR")
            manifest = orchestrator.repository.load(planned["build_id"])
            report = orchestrator.repository.load_artifact(
                manifest, "agent_review_report"
            )
            self.assertEqual(report["error"]["class"], "INVALID_STRUCTURED_OUTPUT")
            with self.assertRaises(ApprovalRequiredError):
                orchestrator.approve(
                    planned["build_id"],
                    gate="execution",
                    actor="test-reviewer",
                    allow_agent_exception=True,
                    agent_exception_reason="Attempted structural override.",
                )

    def test_missing_openai_key_is_a_classified_hold(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            orchestrator = BuildOrchestrator(
                Path(temporary), agent_review_mode="review", environ={}
            )
            planned = orchestrator.plan(ARTICLE)
            reviewed = orchestrator.review(planned["build_id"])
            self.assertEqual(reviewed["agent_review"]["status"], "ERROR")
            manifest = orchestrator.repository.load(planned["build_id"])
            report = orchestrator.repository.load_artifact(
                manifest, "agent_review_report"
            )
            self.assertEqual(report["error"]["class"], "AUTHENTICATION")

    def test_secret_scan_holds_without_calling_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            article_path = Path(temporary) / "secret-article.md"
            article_path.write_text(
                "# Decision Boundary\n\nLeaders define authority before automation so every "
                "important operational choice remains attributable, reviewable, and safe. "
                "Teams preserve evidence, escalation paths, and human approval boundaries "
                "while a key sk-abcdefghijklmnopqrstuvwxyz must never enter review.",
                encoding="utf-8",
            )
            provider = FakeAgentReviewProvider()
            orchestrator = BuildOrchestrator(
                Path(temporary),
                agent_review_mode="review",
                review_provider=provider,
                environ={},
            )
            planned = orchestrator.plan(article_path)
            reviewed = orchestrator.review(planned["build_id"])
            self.assertEqual(reviewed["agent_review"]["status"], "ERROR")
            self.assertEqual(provider.calls, 0)

    def test_exact_review_key_reuses_immutable_provider_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first_provider = FakeAgentReviewProvider()
            first = BuildOrchestrator(
                Path(temporary),
                agent_review_mode="review",
                review_provider=first_provider,
                environ={},
            )
            first_plan = first.plan(ARTICLE)
            first_review = first.review(first_plan["build_id"])
            self.assertEqual(first_provider.calls, 1)

            changed = deepcopy(DEFAULT_CONFIG)
            changed["render"]["budget_usd"] = 21.0
            config_path = Path(temporary) / "changed.json"
            config_path.write_text(json.dumps(changed), encoding="utf-8")
            second_provider = FakeAgentReviewProvider()
            second = BuildOrchestrator(
                Path(temporary),
                config_path=config_path,
                agent_review_mode="review",
                review_provider=second_provider,
                environ={},
            )
            second_plan = second.plan(ARTICLE)
            self.assertNotEqual(second_plan["build_id"], first_plan["build_id"])
            second_review = second.review(second_plan["build_id"])
            self.assertEqual(second_provider.calls, 0)
            self.assertTrue(second_review["agent_review"]["cache_hit"])
            self.assertEqual(
                second_review["agent_review"]["review_key"],
                first_review["agent_review"]["review_key"],
            )

    def test_concurrent_exact_key_has_only_one_provider_submission(self) -> None:
        class SlowProvider(FakeAgentReviewProvider):
            def review(self, request):  # type: ignore[no-untyped-def]
                time.sleep(0.05)
                return super().review(request)

        with tempfile.TemporaryDirectory() as temporary:
            provider = SlowProvider()
            orchestrator = BuildOrchestrator(
                Path(temporary),
                agent_review_mode="review",
                review_provider=provider,
                environ={},
            )
            planned = orchestrator.plan(ARTICLE)
            manifest = orchestrator.repository.load(planned["build_id"])
            request = build_review_request(
                manifest, orchestrator.repository, orchestrator.config
            )
            service = AgentReviewService(
                config=orchestrator.config,
                store=AgentReviewStore(
                    orchestrator.repository.root / "agent-review-cache"
                ),
                provider=provider,
            )
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: service.run(request), range(2)))
            self.assertEqual(provider.calls, 1)
            self.assertEqual({result[0]["review_key"] for result in results}, {request.review_key})
            self.assertEqual(sorted(result[1] for result in results), [False, True])

    def test_openai_secret_is_never_recorded_in_configuration_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            orchestrator = BuildOrchestrator(
                Path(temporary),
                agent_review_mode="review",
                review_provider=FakeAgentReviewProvider(),
                environ={"OPENAI_API_KEY": "sk-test-secret-value-abcdefghijklmnopqrstuvwxyz"},
            )
            self.assertNotIn(
                "sk-test-secret-value", json.dumps(orchestrator._config_snapshot())
            )

    def test_tampered_report_is_rejected_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            orchestrator = BuildOrchestrator(
                Path(temporary),
                agent_review_mode="review",
                review_provider=FakeAgentReviewProvider(),
                environ={},
            )
            planned = orchestrator.plan(ARTICLE)
            orchestrator.review(planned["build_id"])
            orchestrator.approve(
                planned["build_id"], gate="execution", actor="test-reviewer"
            )
            manifest = orchestrator.repository.load(planned["build_id"])
            report_path = Path(manifest["artifacts"]["agent_review_report"]["path"])
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["summary"] = "tampered"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaises(ValidationError):
                orchestrator.execute(planned["build_id"])


if __name__ == "__main__":
    unittest.main()
