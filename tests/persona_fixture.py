"""Deterministic golden Persona Council bundle for Part 9 contract tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from insynergy_cinematic.schema_validation import COUNCIL_ROLES, PROPOSAL_ROLES
from insynergy_cinematic.util import content_hash


def _hash(character: str) -> str:
    return "sha256:" + character * 64


def _seal(value: dict[str, Any]) -> dict[str, Any]:
    value["content_hash"] = content_hash(value)
    return value


def _provenance() -> dict[str, Any]:
    return {
        "sdk_version": "0.16.0",
        "manager_agent_version": "persona-manager-v1",
        "prompt_version": "persona-council-v1",
        "policy_version": "persona-policy/1",
        "models_by_role": {role: "fake-provider-v1" for role in COUNCIL_ROLES},
    }


def _usage() -> dict[str, Any]:
    return {
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
        "estimated_cost_usd": 0.0,
    }


def _field(value: str, basis: str = "SOURCE", reference: str = "ev-article") -> dict[str, Any]:
    return {"value": value, "basis": basis, "evidence_refs": [reference]}


def golden_persona_bundle() -> dict[str, dict[str, Any]]:
    build_id = "20260722-001"
    deliberation_key = _hash("d")
    article_hash = _hash("a")
    brief_hash = _hash("b")
    generated_at = "2026-07-22T00:00:00Z"
    field_values = {
        "role": _field("Chief Operating Officer"),
        "job_to_be_done": _field("Approve an AI operating model without losing accountability"),
        "dominant_desire": _field("Move quickly while preserving clear authority"),
        "dominant_fear": _field("An automated decision no one is authorized to stop"),
        "internal_contradiction": _field("Demands speed but distrusts unowned automation"),
        "decision_pressure": _field("The governance vote closes today", "ASSUMPTION", "asm-pressure"),
        "authority_boundary": _field("May halt deployment but cannot rewrite policy alone"),
        "current_workaround": _field("Escalates ambiguous cases to a weekly committee"),
        "emotional_arc_candidate": _field("Control to doubt to deliberate authority"),
    }
    evidence = [
        {
            "evidence_id": "ev-article",
            "artifact_hash": article_hash,
            "json_pointer": "/claims/0",
            "summary": "The source identifies an unowned approval boundary.",
        }
    ]
    assumptions = [
        {
            "assumption_id": "asm-pressure",
            "statement": "A governance vote creates immediate decision pressure.",
            "rationale": "A bounded deadline makes the source conflict filmable.",
            "risk": "MEDIUM",
            "requires_human_attention": False,
        }
    ]
    proposals = []
    for index, role in enumerate(PROPOSAL_ROLES, 1):
        proposal = {
            "proposal_id": f"PRP-{role.replace('_', '.')}.000{index}",
            "role": role,
            "persona_fields": deepcopy(field_values),
            "evidence": deepcopy(evidence),
            "assumptions": deepcopy(assumptions),
        }
        proposal["proposal_hash"] = content_hash(proposal)
        proposals.append(proposal)
    proposal_set = _seal(
        {
            "schema_version": "3.3.0",
            "contract_version": "persona-council/1",
            "build_id": build_id,
            "deliberation_key": deliberation_key,
            "article_hash": article_hash,
            "creative_brief_hash": brief_hash,
            "proposals": proposals,
            "agent_provenance": _provenance(),
            "usage": _usage(),
            "generated_at": generated_at,
        }
    )
    objection_id = "OBJ-evidence.gap.0001"
    red_team = _seal(
        {
            "schema_version": "3.3.0",
            "contract_version": "persona-council/1",
            "report_id": "PRT-red.team.0001",
            "build_id": build_id,
            "deliberation_key": deliberation_key,
            "article_hash": article_hash,
            "creative_brief_hash": brief_hash,
            "proposal_set_hash": proposal_set["content_hash"],
            "objections": [
                {
                    "objection_id": objection_id,
                    "code": "EVIDENCE_GAP",
                    "severity": "WARNING",
                    "blocking": False,
                    "proposal_hash": proposals[0]["proposal_hash"],
                    "evidence_refs": ["ev-article"],
                    "summary": "The deadline is an explicit creative assumption.",
                }
            ],
            "critic_provenance": _provenance(),
            "usage": _usage(),
            "generated_at": generated_at,
        }
    )
    deliberation = _seal(
        {
            "schema_version": "3.3.0",
            "contract_version": "persona-council/1",
            "deliberation_id": "DEL-persona.0001",
            "build_id": build_id,
            "deliberation_key": deliberation_key,
            "article_hash": article_hash,
            "creative_brief_hash": brief_hash,
            "proposal_set_hash": proposal_set["content_hash"],
            "red_team_report_hash": red_team["content_hash"],
            "resolutions": [
                {
                    "objection_id": objection_id,
                    "disposition": "EXPOSED",
                    "changed_fields": ["decision_pressure"],
                    "summary": "The deadline remains visible as a medium-risk assumption.",
                }
            ],
            "selected_elements": [
                {
                    "proposal_hash": proposals[0]["proposal_hash"],
                    "field": "job_to_be_done",
                    "summary": "Strongest source-grounded executive decision.",
                }
            ],
            "rejected_elements": [],
            "invocation_ledger": [
                {
                    "role": role,
                    "attempt": 1,
                    "accepted": True,
                    "input_hash": deliberation_key,
                    "output_hash": _hash(str(index)),
                }
                for index, role in enumerate(COUNCIL_ROLES, 1)
            ],
            "manager_provenance": _provenance(),
            "usage": _usage(),
            "generated_at": generated_at,
        }
    )
    persona = _seal(
        {
            "schema_version": "3.3.0",
            "contract_version": "persona-council/1",
            "persona_id": "PER-executive.0001",
            "build_id": build_id,
            "deliberation_key": deliberation_key,
            "article_hash": article_hash,
            "creative_brief_hash": brief_hash,
            **deepcopy(field_values),
            "evidence": deepcopy(evidence),
            "assumptions": deepcopy(assumptions),
            "prohibited_inventions": [
                "DEMOGRAPHICS",
                "FABRICATED_QUOTE",
                "MEDICAL_CONDITION",
                "TRAUMA",
                "VULNERABLE_SETTING",
                "PERSONAL_HISTORY",
                "UNSUPPORTED_RELATIONSHIP",
            ],
            "unresolved_questions": ["Should the governance deadline come from the Creative Brief?"],
            "source_fidelity": 0.95,
            "story_usability": 0.92,
            "agent_provenance": _provenance(),
            "generated_at": generated_at,
        }
    )
    check_ids = (
        "proposal_cardinality",
        "red_team_resolution",
        "manager_synthesis",
        "factual_evidence",
        "assumption_lineage",
        "prohibited_inventions",
        "persona_singularity",
        "story_usability",
        "identity_integrity",
        "security_hygiene",
    )
    quality = _seal(
        {
            "schema_version": "3.3.0",
            "contract_version": "persona-quality/1",
            "report_id": "PQR-quality.0001",
            "build_id": build_id,
            "deliberation_key": deliberation_key,
            "article_hash": article_hash,
            "creative_brief_hash": brief_hash,
            "proposal_set_hash": proposal_set["content_hash"],
            "red_team_report_hash": red_team["content_hash"],
            "deliberation_hash": deliberation["content_hash"],
            "persona_hash": persona["content_hash"],
            "status": "PASS",
            "checks": [
                {"check_id": check_id, "passed": True, "evidence_hashes": [persona["content_hash"]]}
                for check_id in check_ids
            ],
            "non_waivable_failures": [],
            "findings": [],
            "policy_version": "persona-policy/1",
            "generated_at": generated_at,
        }
    )
    approval = _seal(
        {
            "schema_version": "3.3.0",
            "contract_version": "persona-approval/1",
            "approval_id": "PAB-approval.0001",
            "build_id": build_id,
            "approver": "editor@example.com",
            "decision": "APPROVED",
            "approved_at": generated_at,
            "article_hash": article_hash,
            "creative_brief_hash": brief_hash,
            "persona_hash": persona["content_hash"],
            "quality_report_hash": quality["content_hash"],
            "deliberation_hash": deliberation["content_hash"],
            "deliberation_contract_version": "persona-council/1",
            "policy_version": "persona-policy/1",
        }
    )
    return {
        "persona-proposals": proposal_set,
        "persona-red-team-report": red_team,
        "persona-deliberation": deliberation,
        "persona": persona,
        "persona-quality-report": quality,
        "persona-approval-binding": approval,
    }
