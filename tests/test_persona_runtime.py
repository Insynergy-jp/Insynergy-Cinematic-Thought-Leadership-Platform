from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import get_args
import tempfile
import time
import unittest

from insynergy_cinematic.errors import PersonaCouncilError, ValidationError
from insynergy_cinematic.models import BuildState
from insynergy_cinematic.orchestrator import BuildOrchestrator
from insynergy_cinematic.persona import (
    COUNCIL_ROLES,
    PersonaCouncilCache,
    PersonaCouncilProviderResult,
    PersonaCouncilRequest,
    PersonaCouncilService,
    deliberation_key,
)
from insynergy_cinematic.providers.openai_persona import (
    OpenAIAgentsPersonaProvider,
    _normalize_council_output,
    _output_types,
)
from insynergy_cinematic.util import atomic_write_json, content_hash, read_json


ROOT = Path(__file__).resolve().parents[1]


class FakePersonaProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.roles = COUNCIL_ROLES
        self.mutate = None
        self.delay_seconds = 0.0

    def deliberate(self, request):
        self.calls += 1
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        evidence = [
            {
                "evidence_id": "ev-article",
                "artifact_hash": request.article_hash,
                "json_pointer": "/body",
                "summary": "The Article identifies an unowned decision boundary.",
            }
        ]
        assumptions = [
            {
                "assumption_id": "asm-deadline",
                "statement": "A governance vote closes today.",
                "rationale": "The explicit Creative Brief requests visible time pressure.",
                "risk": "MEDIUM",
                "requires_human_attention": False,
            }
        ]

        def field(value, basis="SOURCE", reference="ev-article"):
            return {"value": value, "basis": basis, "evidence_refs": [reference]}

        fields = {
            "role": field("Chief Operating Officer"),
            "job_to_be_done": field("Approve an AI operating model without losing accountability"),
            "dominant_desire": field("Move quickly while preserving explicit authority"),
            "dominant_fear": field("An automated decision no one is authorized to stop"),
            "internal_contradiction": field("Demands speed but distrusts unowned automation"),
            "decision_pressure": field("The governance vote closes today", "ASSUMPTION", "asm-deadline"),
            "authority_boundary": field("May halt deployment but cannot rewrite policy alone"),
            "current_workaround": field("Escalates ambiguous decisions to a governance committee"),
            "emotional_arc_candidate": field("Control to doubt to deliberate authority"),
        }
        output = {
            "proposals": [
                {
                    "role": role,
                    "persona_fields": deepcopy(fields),
                    "evidence": deepcopy(evidence),
                    "assumptions": deepcopy(assumptions),
                }
                for role in (
                    "audience_researcher",
                    "empathy_narrative_analyst",
                    "brand_strategist",
                )
            ],
            "objections": [
                {
                    "code": "EVIDENCE_GAP",
                    "severity": "WARNING",
                    "blocking": False,
                    "proposal_role": "audience_researcher",
                    "evidence_refs": ["ev-article"],
                    "summary": "The deadline remains an explicit assumption.",
                }
            ],
            "resolutions": [
                {
                    "objection_index": 0,
                    "disposition": "EXPOSED",
                    "changed_fields": ["decision_pressure"],
                    "summary": "Keep the deadline visible as an assumption.",
                }
            ],
            "selected_elements": [
                {
                    "proposal_role": "audience_researcher",
                    "field": "job_to_be_done",
                    "summary": "The strongest evidence-bound executive decision.",
                }
            ],
            "rejected_elements": [],
            "persona_fields": deepcopy(fields),
            "evidence": deepcopy(evidence),
            "assumptions": deepcopy(assumptions),
            "unresolved_questions": ["Confirm the exact governance deadline."],
            "source_fidelity": 0.95,
            "story_usability": 0.92,
        }
        if self.mutate is not None:
            self.mutate(output)
        return PersonaCouncilProviderResult(
            output=output,
            invocation_roles=tuple(self.roles),
            sdk_version="fake-agents-1",
            model_resolved=request.model,
            usage={
                "input_tokens": 100,
                "output_tokens": 50,
                "estimated_cost_usd": 0.01,
            },
            response_id="response-fake",
        )


class PersonaRuntimeTests(unittest.TestCase):
    def _brief(self, root: Path) -> Path:
        path = root / "creative-brief.md"
        path.write_text(
            "# Executive Governance Trailer\n\n"
            "Use one executive protagonist. Make the decision clock visible and preserve "
            "the Article's authority boundary.",
            encoding="utf-8",
        )
        return path

    def _request(self, build_id: str) -> PersonaCouncilRequest:
        article = {"title": "Decision Boundary", "body": "An unowned decision boundary."}
        brief = {"title": "Executive trailer", "body": "Use one executive protagonist."}
        article_hash = content_hash(article)
        brief_hash = content_hash(brief)
        key = deliberation_key(
            article_hash=article_hash,
            creative_brief_hash=brief_hash,
            model="gpt-5.6-sol",
            reasoning_effort="medium",
            manager_agent_version="persona-manager-v1",
            prompt_version="persona-council-v1",
            policy_version="persona-policy/1",
        )
        return PersonaCouncilRequest(
            build_id=build_id,
            article_hash=article_hash,
            creative_brief_hash=brief_hash,
            article=article,
            creative_brief=brief,
            deliberation_key=key,
            model="gpt-5.6-sol",
            reasoning_effort="medium",
            max_output_tokens=20_000,
            timeout_seconds=30,
            manager_agent_version="persona-manager-v1",
            prompt_version="persona-council-v1",
            policy_version="persona-policy/1",
        )

    def test_council_stops_before_story_then_approval_unlocks_planning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            provider = FakePersonaProvider()
            orchestrator = BuildOrchestrator(
                root,
                profile="preview",
                persona_mode="council",
                persona_provider=provider,
                environ={},
            )
            brief = self._brief(root)
            first = orchestrator.plan(
                ROOT / "examples" / "decision-boundary.md",
                creative_brief_path=brief,
            )
            self.assertEqual(
                first["state"], BuildState.AWAITING_PERSONA_APPROVAL.value
            )
            self.assertEqual(provider.calls, 1)
            self.assertTrue(first["gates"]["persona_quality_gate"]["passed"])
            self.assertNotIn("story_quality_report", first["artifacts"])
            self.assertTrue(
                {
                    "persona-proposals",
                    "persona-red-team-report",
                    "persona-deliberation",
                    "persona",
                    "persona-quality-report",
                }.issubset(first["artifacts"])
            )

            held = orchestrator.plan(
                ROOT / "examples" / "decision-boundary.md",
                creative_brief_path=brief,
            )
            self.assertEqual(held["state"], BuildState.AWAITING_PERSONA_APPROVAL.value)
            self.assertEqual(provider.calls, 1)

            approved = orchestrator.approve(
                first["build_id"],
                gate="persona",
                actor="persona-editor@example.com",
                comment="Source and assumptions reviewed.",
            )
            self.assertTrue(approved["gates"]["persona_approval"]["passed"])
            self.assertIn("persona-approval-binding", approved["artifacts"])

            planned = orchestrator.plan(
                ROOT / "examples" / "decision-boundary.md",
                creative_brief_path=brief,
            )
            self.assertEqual(
                planned["state"], BuildState.AWAITING_EXECUTION_APPROVAL.value
            )
            self.assertIn("story_quality_report", planned["artifacts"])
            manifest = orchestrator.repository.load(planned["build_id"])
            story = orchestrator.repository.load_artifact(
                manifest, "character_bible"
            )["data"]
            self.assertEqual(
                story["protagonist"]["name"], "Chief Operating Officer"
            )

    def test_exact_selection_cache_reuses_provider_across_build_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            provider = FakePersonaProvider()
            brief = self._brief(root)
            preview = BuildOrchestrator(
                root,
                profile="preview",
                persona_mode="council",
                persona_provider=provider,
                environ={},
            ).plan(
                ROOT / "examples" / "decision-boundary.md",
                creative_brief_path=brief,
            )
            draft = BuildOrchestrator(
                root,
                profile="draft",
                persona_mode="council",
                persona_provider=provider,
                environ={},
            ).plan(
                ROOT / "examples" / "decision-boundary.md",
                creative_brief_path=brief,
            )
            self.assertNotEqual(preview["build_id"], draft["build_id"])
            self.assertEqual(provider.calls, 1)
            self.assertTrue(draft["persona_council"]["cache_hit"])
            self.assertNotEqual(
                preview["artifacts"]["persona"]["content_hash"],
                draft["artifacts"]["persona"]["content_hash"],
            )

    def test_github_persona_approval_records_distinct_reviewer_and_fails_self_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            orchestrator = BuildOrchestrator(
                root,
                persona_mode="council",
                persona_provider=FakePersonaProvider(),
                environ={},
            )
            awaiting = orchestrator.plan(
                ROOT / "examples" / "decision-boundary.md",
                creative_brief_path=self._brief(root),
            )
            review_hash = "sha256:" + "d" * 64
            with self.assertRaises(ValidationError):
                orchestrator.approve(
                    awaiting["build_id"],
                    gate="persona",
                    actor="workflow-owner",
                    workflow_initiator="workflow-owner",
                    environment_reviewer="workflow-owner",
                    prevent_self_review=True,
                    environment_review_hash=review_hash,
                )

            approved = orchestrator.approve(
                awaiting["build_id"],
                gate="persona",
                actor="persona-reviewer",
                workflow_initiator="workflow-owner",
                environment_reviewer="persona-reviewer",
                prevent_self_review=True,
                environment_review_hash=review_hash,
            )
            manifest = orchestrator.repository.load(approved["build_id"])
            binding = orchestrator.repository.load_artifact(
                manifest, "persona-approval-binding"
            )
            self.assertEqual(binding["workflow_initiator"], "workflow-owner")
            self.assertEqual(binding["environment_reviewer"], "persona-reviewer")
            self.assertEqual(binding["approver"], "persona-reviewer")
            self.assertTrue(binding["prevent_self_review"])
            self.assertEqual(binding["environment_review_hash"], review_hash)

    def test_wrong_topology_secret_and_high_risk_assumption_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            brief = self._brief(root)

            topology = FakePersonaProvider()
            topology.roles = (*COUNCIL_ROLES, "audience_researcher")
            orchestrator = BuildOrchestrator(
                root / "topology",
                persona_mode="council",
                persona_provider=topology,
                environ={},
            )
            with self.assertRaises(PersonaCouncilError):
                orchestrator.plan(
                    ROOT / "examples" / "decision-boundary.md",
                    creative_brief_path=brief,
                )

            secret = FakePersonaProvider()
            secret.mutate = lambda output: output.update(
                {"raw_response": "sk-secretvalue1234567890"}
            )
            orchestrator = BuildOrchestrator(
                root / "secret",
                persona_mode="council",
                persona_provider=secret,
                environ={},
            )
            with self.assertRaises(PersonaCouncilError):
                orchestrator.plan(
                    ROOT / "examples" / "decision-boundary.md",
                    creative_brief_path=brief,
                )

            risk = FakePersonaProvider()
            risk.mutate = lambda output: output["assumptions"][0].update(
                {"risk": "HIGH", "requires_human_attention": False}
            )
            orchestrator = BuildOrchestrator(
                root / "risk",
                persona_mode="council",
                persona_provider=risk,
                environ={},
            )
            with self.assertRaises(PersonaCouncilError):
                orchestrator.plan(
                    ROOT / "examples" / "decision-boundary.md",
                    creative_brief_path=brief,
                )

    def test_council_requires_brief_and_off_mode_rejects_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ValidationError):
                BuildOrchestrator(
                    root / "council",
                    persona_mode="council",
                    persona_provider=FakePersonaProvider(),
                    environ={},
                ).plan(ROOT / "examples" / "decision-boundary.md")
            brief = self._brief(root)
            with self.assertRaises(ValidationError):
                BuildOrchestrator(
                    root / "off", persona_mode="off", environ={}
                ).plan(
                    ROOT / "examples" / "decision-boundary.md",
                    creative_brief_path=brief,
                )

    def test_duplicate_exact_key_is_single_flight_and_budget_rejects_pre_contact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            provider = FakePersonaProvider()
            provider.delay_seconds = 0.1

            def run(request: PersonaCouncilRequest):
                return PersonaCouncilService(
                    provider=provider,
                    cache=PersonaCouncilCache(root / "cache"),
                    max_input_bytes=524_288,
                    preflight_estimated_cost_usd=1.0,
                    max_cost_usd=5.0,
                ).run(request)

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(
                    executor.map(
                        run,
                        (self._request("20260722-101"), self._request("20260722-102")),
                    )
                )
            self.assertEqual(provider.calls, 1)
            self.assertEqual(len(results), 2)
            self.assertNotEqual(
                results[0]["persona"]["content_hash"],
                results[1]["persona"]["content_hash"],
            )

            blocked_provider = FakePersonaProvider()
            service = PersonaCouncilService(
                provider=blocked_provider,
                cache=PersonaCouncilCache(root / "blocked-cache"),
                max_input_bytes=524_288,
                preflight_estimated_cost_usd=2.0,
                max_cost_usd=1.0,
            )
            with self.assertRaises(PersonaCouncilError) as raised:
                service.run(self._request("20260722-103"))
            self.assertEqual(raised.exception.error_class, "BUDGET")
            self.assertEqual(blocked_provider.calls, 0)

    def test_missing_live_key_fails_before_sdk_import(self) -> None:
        provider = OpenAIAgentsPersonaProvider(SimpleNamespace(openai_api_key=None))
        with self.assertRaises(PersonaCouncilError) as raised:
            provider.deliberate(self._request("20260722-104"))
        self.assertEqual(raised.exception.error_class, "AUTHENTICATION")

    def test_quality_failure_reports_structured_failed_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            provider = FakePersonaProvider()
            provider.mutate = lambda output: output.update({"story_usability": 0.5})
            service = PersonaCouncilService(
                provider=provider,
                cache=PersonaCouncilCache(Path(temporary) / "cache"),
                max_input_bytes=524_288,
                preflight_estimated_cost_usd=1.0,
                max_cost_usd=5.0,
            )
            with self.assertRaises(PersonaCouncilError) as raised:
                service.run(self._request("20260722-105"))
            self.assertEqual(raised.exception.error_class, "QUALITY")
            self.assertEqual(
                raised.exception.details["failed_checks"], ["story_usability"]
            )
            self.assertEqual(
                raised.exception.details["findings"][0]["code"],
                "PQ-STORY_USABILITY",
            )
            self.assertNotIn("persona", raised.exception.details)

    def test_live_output_contract_has_one_fixed_slot_per_proposal_role(self) -> None:
        council_output = _output_types()["CouncilOutput"]
        proposal_set = council_output.model_fields["proposals"].annotation
        self.assertEqual(set(proposal_set.model_fields), set(COUNCIL_ROLES[:3]))
        for role in COUNCIL_ROLES[:3]:
            proposal = proposal_set.model_fields[role].annotation
            self.assertEqual(get_args(proposal.model_fields["role"].annotation), (role,))

        payload = {
            "proposals": {
                role: {"role": role}
                for role in COUNCIL_ROLES[:3]
            }
        }
        normalized = _normalize_council_output(payload)
        self.assertEqual(
            [proposal["role"] for proposal in normalized["proposals"]],
            list(COUNCIL_ROLES[:3]),
        )
        with self.assertRaises(PersonaCouncilError):
            _normalize_council_output(
                {"proposals": {"audience_researcher": {"role": "audience_researcher"}}}
            )

    def test_rejection_creates_no_binding_and_artifact_tamper_blocks_story(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            brief = self._brief(root)
            rejected_orchestrator = BuildOrchestrator(
                root / "rejected",
                persona_mode="council",
                persona_provider=FakePersonaProvider(),
                environ={},
            )
            rejected = rejected_orchestrator.plan(
                ROOT / "examples" / "decision-boundary.md",
                creative_brief_path=brief,
            )
            rejection = rejected_orchestrator.approve(
                rejected["build_id"],
                gate="persona",
                actor="persona-editor@example.com",
                decision="REJECTED",
                comment="The inferred pressure is not acceptable.",
            )
            self.assertFalse(rejection["gates"]["persona_approval"]["passed"])
            self.assertNotIn("persona-approval-binding", rejection["artifacts"])

            approved_orchestrator = BuildOrchestrator(
                root / "tampered",
                persona_mode="council",
                persona_provider=FakePersonaProvider(),
                environ={},
            )
            awaiting = approved_orchestrator.plan(
                ROOT / "examples" / "decision-boundary.md",
                creative_brief_path=brief,
            )
            approved_orchestrator.approve(
                awaiting["build_id"],
                gate="persona",
                actor="persona-editor@example.com",
                comment="Approved against sealed evidence.",
            )
            manifest = approved_orchestrator.repository.load(awaiting["build_id"])
            binding_path = Path(
                manifest["artifacts"]["persona-approval-binding"]["path"]
            )
            binding = read_json(binding_path)
            binding["persona_hash"] = "sha256:" + "0" * 64
            binding["content_hash"] = content_hash(
                {key: value for key, value in binding.items() if key != "content_hash"}
            )
            atomic_write_json(binding_path, binding)
            with self.assertRaises(ValidationError):
                approved_orchestrator.plan(
                    ROOT / "examples" / "decision-boundary.md",
                    creative_brief_path=brief,
                )


if __name__ == "__main__":
    unittest.main()
