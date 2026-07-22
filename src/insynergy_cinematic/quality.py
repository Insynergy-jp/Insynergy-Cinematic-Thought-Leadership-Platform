"""Central fail-closed Quality Gate registry, evaluator, and evidence reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import QualityGateError, ValidationError
from .media import AssetValidator
from .util import DETERMINISTIC_TIME, content_hash, stable_id


QUALITY_GATE_REGISTRY = {
    "persona_quality_gate": ("persona_planning", "7.0.2"),
    "story_quality_gate": ("story", "2.3.3"),
    "screenplay_quality_gate": ("screenplay", "3.3.0"),
    "shot_quality_gate": ("shot_planning", "4.1.12"),
    "storyboard_quality_gate": ("storyboard", "4.1.12"),
    "agent_review_gate": ("planning_review", "7.0.1"),
    "rendering_technical_gate": ("rendering", "5.6.1"),
    "rendering_editorial_gate": ("validation", "5.6.2"),
    "composition_quality_gate": ("composition", "7.2.7"),
    "narration_audio_quality_gate": ("audio", "7.2.8"),
    "metadata_packaging_quality_gate": ("packaging", "7.2.9"),
    "execution_approval": ("approval", "1.4.1"),
    "publish_approval": ("publication", "1.4.1"),
    "render_quality_gate": ("rendering", "7.2.6"),
    "render_storyboard_coherence_gate": ("cross_stage", "7.2.11"),
    "publication_quality_gate": ("publication", "7.2.10"),
}


GATE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "persona_quality_gate": {
        "scope": "cross_stage",
        "judgment": "semantic",
        "threshold": 1.0,
        "dependencies": [],
        "non_waivable_checks": [
            "proposal_cardinality",
            "factual_evidence",
            "assumption_lineage",
            "prohibited_inventions",
            "identity_integrity",
            "security_hygiene",
        ],
    },
    "story_quality_gate": {
        "scope": "element",
        "judgment": "semantic",
        "threshold": 0.85,
        "dependencies": [],
    },
    "screenplay_quality_gate": {
        "scope": "sequence",
        "judgment": "semantic",
        "threshold": 0.85,
        "dependencies": ["story_quality_gate"],
    },
    "shot_quality_gate": {
        "scope": "element",
        "judgment": "structural",
        "threshold": 0.90,
        "dependencies": ["screenplay_quality_gate"],
    },
    "storyboard_quality_gate": {
        "scope": "sequence",
        "judgment": "semantic",
        "threshold": 0.90,
        "dependencies": ["shot_quality_gate"],
    },
    "agent_review_gate": {
        "scope": "cross_stage",
        "judgment": "hybrid_review",
        "threshold": 1.0,
        "dependencies": ["storyboard_quality_gate"],
    },
    "rendering_technical_gate": {
        "scope": "sequence",
        "judgment": "structural",
        "threshold": 1.0,
        "dependencies": ["storyboard_quality_gate"],
    },
    "rendering_editorial_gate": {
        "scope": "sequence",
        "judgment": "semantic",
        "threshold": 0.90,
        "dependencies": ["rendering_technical_gate"],
    },
    "render_quality_gate": {
        "scope": "element",
        "judgment": "structural",
        "threshold": 1.0,
        "dependencies": ["storyboard_quality_gate"],
    },
    "render_storyboard_coherence_gate": {
        "scope": "cross_stage",
        "judgment": "structural",
        "threshold": 1.0,
        "dependencies": ["render_quality_gate"],
    },
    "composition_quality_gate": {
        "scope": "sequence",
        "judgment": "structural",
        "threshold": 1.0,
        "dependencies": ["render_quality_gate"],
    },
    "narration_audio_quality_gate": {
        "scope": "sequence",
        "judgment": "structural",
        "threshold": 1.0,
        "dependencies": ["composition_quality_gate", "screenplay_quality_gate"],
    },
    "metadata_packaging_quality_gate": {
        "scope": "sequence",
        "judgment": "structural",
        "threshold": 1.0,
        "dependencies": ["narration_audio_quality_gate"],
    },
    "publication_quality_gate": {
        "scope": "sequence",
        "judgment": "human_approval",
        "threshold": 1.0,
        "dependencies": [
            "metadata_packaging_quality_gate",
            "render_storyboard_coherence_gate",
        ],
        "non_waivable_checks": [
            "publication_rights_cleared",
            "child_safety_validated",
            "content_safety_validated",
            "editorial_approval_recorded",
            "approval_scope_matches",
            "no_upstream_waivers_open",
        ],
    },
    "execution_approval": {
        "scope": "cross_stage",
        "judgment": "human_approval",
        "threshold": 1.0,
        "dependencies": ["storyboard_quality_gate"],
    },
    "publish_approval": {
        "scope": "cross_stage",
        "judgment": "human_approval",
        "threshold": 1.0,
        "dependencies": ["metadata_packaging_quality_gate"],
    },
}


GATE_CHAIN = (
    "persona_quality_gate",
    "story_quality_gate",
    "screenplay_quality_gate",
    "shot_quality_gate",
    "storyboard_quality_gate",
    "agent_review_gate",
    "execution_approval",
    "rendering_technical_gate",
    "rendering_editorial_gate",
    "render_quality_gate",
    "render_storyboard_coherence_gate",
    "composition_quality_gate",
    "narration_audio_quality_gate",
    "metadata_packaging_quality_gate",
    "publish_approval",
    "publication_quality_gate",
)

MANDATORY_CHECKS: dict[str, tuple[str, ...]] = {
    "persona_quality_gate": (
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
    ),
    "story_quality_gate": (
        "premise_defined",
        "protagonist_defined",
        "stakes_defined",
        "three_act_structure_valid",
        "emotional_arc_coherent",
        "single_dramatic_question",
        "human_grounded",
        "article_traceable",
        "dramatic_score_threshold",
        "conflict_score_threshold",
        "stakes_score_threshold",
        "emotional_progression_threshold",
        "concept_ratio_within_budget",
        "conflict_layers_complete",
        "measurable_irreversible_stake",
        "time_pressure_coherent",
        "arc_complete",
        "act_budget_satisfied",
        "concept_after_tension",
        "premise_logline_consistent",
        "character_premise_bound",
        "supporting_roles_bounded",
        "persona_binding_valid",
        "forbidden_story_absent",
    ),
    "screenplay_quality_gate": (
        "scene_count_in_range",
        "scene_order_valid",
        "three_acts_present",
        "one_purpose_per_scene",
        "one_conflict_per_scene",
        "heading_grammar_valid",
        "character_objectives_exist",
        "observable_actions_only",
        "dialogue_under_limit",
        "tension_dialogue_only",
        "silence_represented",
        "duration_within_bounds",
        "cinematic_transitions_only",
        "concepts_only_in_act_3",
        "continuity_valid",
        "persona_lineage_valid",
        "no_invented_biography_or_borrowed_stakes",
    ),
    "shot_quality_gate": (
        "purpose_exists",
        "camera_defined",
        "blocking_defined",
        "emotion_defined",
        "continuity_valid",
        "render_strategy_defined",
        "single_action",
        "single_camera_move",
    ),
    "storyboard_quality_gate": (
        "composition",
        "continuity",
        "pacing",
        "render_balance",
        "concept_ratio",
        "emotional_rhythm",
    ),
    "agent_review_gate": (
        "report_schema_valid",
        "evidence_resolves",
        "input_hashes_match",
        "disposition_policy_valid",
    ),
    "rendering_technical_gate": (
        "all_assets_validate",
        "all_provider_tasks_terminal",
    ),
    "rendering_editorial_gate": (
        "quality_threshold_met",
        "quality_scores_present",
    ),
    "render_quality_gate": (
        "asset_present",
        "asset_integrity",
        "provider_job_succeeded",
        "duration_conformance",
        "resolution_conformance",
        "strategy_conformance",
        "no_corruption",
        "provenance_bound",
    ),
    "render_storyboard_coherence_gate": (
        "shot_identity_matches",
        "shot_order_matches",
        "strategy_identity_matches",
        "approval_binding_current",
        "no_orphan_render",
    ),
    "composition_quality_gate": (
        "all_segments_present",
        "segment_order_matches_plan",
        "no_timeline_gaps",
        "transitions_valid",
        "total_duration_matches",
        "segment_boundaries_intact",
        "resolution_uniform",
    ),
    "narration_audio_quality_gate": (
        "all_narration_present",
        "narration_timing_matches",
        "audio_video_sync",
        "levels_within_spec",
        "no_clipping",
        "no_dropouts",
        "language_correct",
    ),
    "metadata_packaging_quality_gate": (
        "all_artifacts_present",
        "metadata_complete",
        "metadata_valid",
        "container_format_valid",
        "thumbnail_present",
        "checksums_valid",
        "manifest_consistent",
    ),
    "publication_quality_gate": (
        "publication_rights_cleared",
        "child_safety_validated",
        "content_safety_validated",
        "editorial_approval_recorded",
        "approval_scope_matches",
        "publish_target_valid",
        "no_upstream_waivers_open",
    ),
    "execution_approval": (
        "human_decision_recorded",
        "artifact_scope_matches",
        "actor_attributable",
        "approval_identity_bound",
    ),
    "publish_approval": (
        "human_decision_recorded",
        "artifact_scope_matches",
        "actor_attributable",
        "approval_identity_bound",
    ),
}

CHECK_RESULTS = {"PASS", "FAIL", "ERROR", "NOT_APPLICABLE"}
GATE_LIFECYCLE = (
    "INVOKED",
    "RESOLVING",
    "EVALUATING",
    "REDUCING",
    "REPORTING",
    "TERMINAL",
)


def registry_document() -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "gates": [
            {
                "gate_id": gate_id,
                "stage": stage,
                "gate_type": (
                    "human_approval"
                    if GATE_DEFINITIONS[gate_id]["judgment"] == "human_approval"
                    else "hybrid_review"
                    if gate_id == "agent_review_gate"
                    else "automated"
                ),
                "blocking": True,
                "fail_closed": True,
                "owning_section": section,
            }
            for gate_id in GATE_CHAIN
            for stage, section in (QUALITY_GATE_REGISTRY[gate_id],)
        ],
    }


def _artifact_evidence(reference: dict[str, Any]) -> dict[str, Any]:
    required = ("artifact_type", "artifact_id", "content_hash")
    if any(not reference.get(field) for field in required):
        raise ValidationError("Quality Gate evidence reference is incomplete")
    if not str(reference["content_hash"]).startswith("sha256:"):
        raise ValidationError("Quality Gate evidence hash is invalid")
    return {
        "artifact_type": str(reference["artifact_type"]),
        "artifact_id": str(reference["artifact_id"]),
        "content_hash": str(reference["content_hash"]),
        "json_pointer": str(reference.get("json_pointer", "/")),
    }


class QualityGateEngine:
    """One deterministic evaluator for every mechanical Quality Gate."""

    def __init__(self, *, configuration_version: str = "quality-gates/2.1") -> None:
        self.configuration_version = configuration_version

    def evaluate(
        self,
        *,
        gate_id: str,
        build_id: str,
        checks: dict[str, Any],
        artifact_refs: list[dict[str, Any]],
        advisory_checks: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if gate_id not in GATE_DEFINITIONS or gate_id not in QUALITY_GATE_REGISTRY:
            raise ValidationError(f"Unregistered Quality Gate: {gate_id}")
        if not checks:
            raise ValidationError("A Quality Gate must declare mandatory checks")
        evidence = [_artifact_evidence(value) for value in artifact_refs]
        definition = GATE_DEFINITIONS[gate_id]
        configuration = {
            "configuration_version": self.configuration_version,
            "gate_id": gate_id,
            "verdict_function": "all_mandatory_pass",
            "threshold": definition["threshold"],
            "mandatory_floor": "all_applicable_checks_pass",
            "fail_closed": True,
            "non_waivable_checks": definition.get("non_waivable_checks", []),
        }
        configuration_hash = content_hash(configuration)
        required_checks = MANDATORY_CHECKS[gate_id]
        complete_checks = {
            check_id: checks.get(check_id) for check_id in required_checks
        }
        complete_checks.update(
            {
                check_id: value
                for check_id, value in checks.items()
                if check_id not in complete_checks
            }
        )
        resolved_checks = [
            self._resolve_check(
                check_id,
                value,
                mandatory=True,
                default_evidence=evidence,
            )
            for check_id, value in sorted(complete_checks.items())
        ]
        resolved_advisory = [
            self._resolve_check(
                check_id,
                value,
                mandatory=False,
                default_evidence=evidence,
            )
            for check_id, value in sorted((advisory_checks or {}).items())
        ]
        failed = [
            value["check_id"]
            for value in resolved_checks
            if value["result"] not in {"PASS", "NOT_APPLICABLE"}
        ]
        advisory_failures = [
            value["check_id"]
            for value in resolved_advisory
            if value["result"] not in {"PASS", "NOT_APPLICABLE"}
        ]
        applicable = [
            value for value in resolved_checks if value["result"] != "NOT_APPLICABLE"
        ]
        score = round(
            sum(value["result"] == "PASS" for value in applicable)
            / max(1, len(applicable)),
            4,
        )
        passed = not failed and score >= float(definition["threshold"])
        artifact_binding_hash = content_hash(evidence)
        identity = {
            "build_id": build_id,
            "gate_id": gate_id,
            "artifact_binding_hash": artifact_binding_hash,
            "configuration_hash": configuration_hash,
            "mandatory_checks_hash": content_hash(resolved_checks),
            "advisory_checks_hash": content_hash(resolved_advisory),
        }
        stage, owning_section = QUALITY_GATE_REGISTRY[gate_id]
        report = {
            "schema_version": "2.0",
            "contract_version": "quality-gate-report/1",
            "report_id": stable_id("quality-gate-report", identity),
            "build_id": build_id,
            "gate_id": gate_id,
            "stage": stage,
            "owning_section": owning_section,
            "scope": definition["scope"],
            "judgment": definition["judgment"],
            "trigger": "stage-exit",
            "decision": "PASS" if passed else "FAIL",
            "passed": passed,
            "score": score,
            "threshold": definition["threshold"],
            "blocking": True,
            "fail_closed": True,
            "mandatory_checks": resolved_checks,
            "failed_checks": failed,
            "advisory_checks": resolved_advisory,
            "advisory_failures": advisory_failures,
            "artifact_refs": evidence,
            "artifact_binding_hash": artifact_binding_hash,
            "dependencies": list(definition["dependencies"]),
            "configuration": configuration,
            "configuration_hash": configuration_hash,
            "lifecycle": list(GATE_LIFECYCLE),
            "generated_at": DETERMINISTIC_TIME,
        }
        report["content_hash"] = content_hash(report)
        verify_quality_gate_report(report)
        return report

    @staticmethod
    def _resolve_check(
        check_id: str,
        value: Any,
        *,
        mandatory: bool,
        default_evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not check_id:
            raise ValidationError("Quality check identity is required")
        if isinstance(value, bool):
            result = "PASS" if value else "FAIL"
            message = "predicate satisfied" if value else "predicate failed"
            evidence = default_evidence
            justification = None
        elif value is None:
            result = "ERROR"
            message = "check result is absent"
            evidence = default_evidence
            justification = None
        elif isinstance(value, str):
            result = value
            message = value.casefold().replace("_", " ")
            evidence = default_evidence
            justification = None
        elif isinstance(value, dict):
            result = str(value.get("result", "ERROR"))
            message = str(value.get("message", "check evaluated"))
            evidence = [
                _artifact_evidence(item)
                for item in value.get("evidence", default_evidence)
            ]
            justification = value.get("justification")
        else:
            result = "ERROR"
            message = "unsupported check result"
            evidence = default_evidence
            justification = None
        if result not in CHECK_RESULTS:
            raise ValidationError(f"Invalid Quality check result: {result}")
        if result == "NOT_APPLICABLE" and not str(justification or "").strip():
            raise ValidationError("NOT_APPLICABLE requires a justification")
        if not evidence:
            result = "ERROR"
            message = "check evidence is absent"
        return {
            "check_id": check_id,
            "mandatory": mandatory,
            "result": result,
            "message": message,
            "evidence": evidence,
            "justification": justification,
        }

    def enforce(self, **kwargs: Any) -> dict[str, Any]:
        report = self.evaluate(**kwargs)
        if not report["passed"]:
            raise QualityGateError(
                f"{report['gate_id']} failed closed", details=report
            )
        return report


def verify_quality_gate_report(report: dict[str, Any]) -> None:
    required = {
        "report_id",
        "build_id",
        "gate_id",
        "decision",
        "passed",
        "score",
        "threshold",
        "mandatory_checks",
        "failed_checks",
        "artifact_refs",
        "artifact_binding_hash",
        "configuration",
        "configuration_hash",
        "lifecycle",
        "content_hash",
    }
    if required.difference(report):
        raise ValidationError("Quality Gate report is incomplete")
    if report["gate_id"] not in GATE_DEFINITIONS:
        raise ValidationError("Quality Gate report uses an unregistered gate")
    expected = content_hash(
        {key: value for key, value in report.items() if key != "content_hash"}
    )
    if report["content_hash"] != expected:
        raise ValidationError("Quality Gate report integrity failure")
    if report["artifact_binding_hash"] != content_hash(report["artifact_refs"]):
        raise ValidationError("Quality Gate artifact binding is invalid")
    if report["configuration_hash"] != content_hash(report["configuration"]):
        raise ValidationError("Quality Gate configuration binding is invalid")
    if report["lifecycle"] != list(GATE_LIFECYCLE):
        raise ValidationError("Quality Gate lifecycle is invalid")
    failures = [
        value["check_id"]
        for value in report["mandatory_checks"]
        if value.get("result") not in {"PASS", "NOT_APPLICABLE"}
    ]
    if failures != report.get("failed_checks"):
        raise ValidationError("Quality Gate failure reduction is inconsistent")
    passed = not failures and float(report["score"]) >= float(report["threshold"])
    if report["passed"] is not passed or report["decision"] != (
        "PASS" if passed else "FAIL"
    ):
        raise ValidationError("Quality Gate verdict is inconsistent")
    for check in [*report["mandatory_checks"], *report.get("advisory_checks", [])]:
        if not check.get("evidence"):
            raise ValidationError("Quality Gate check evidence is missing")
        if check.get("result") == "NOT_APPLICABLE" and not str(
            check.get("justification") or ""
        ).strip():
            raise ValidationError("Quality Gate N/A justification is missing")


def quality_chain_report(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate immutable reports without re-deriving any upstream verdict."""
    latest = {report["gate_id"]: report for report in reports}
    traversal: list[dict[str, Any]] = []
    halted_at: str | None = None
    for gate_id in GATE_CHAIN:
        report = latest.get(gate_id)
        if report is None:
            continue
        verify_quality_gate_report(report)
        if halted_at is not None:
            raise ValidationError("Quality Gate chain continued after a blocking failure")
        traversal.append(
            {
                "gate_id": gate_id,
                "report_id": report["report_id"],
                "content_hash": report["content_hash"],
                "decision": report["decision"],
            }
        )
        if report["decision"] != "PASS":
            halted_at = gate_id
    document = {
        "schema_version": "2.0",
        "contract_version": "quality-gate-chain/1",
        "traversal": traversal,
        "halted_at": halted_at,
        "passed": halted_at is None,
    }
    document["content_hash"] = content_hash(document)
    return document


def build_quality_report(
    *,
    build_id: str,
    reports: list[dict[str, Any]],
    baseline_scores: dict[str, float] | None = None,
) -> dict[str, Any]:
    latest = {report["gate_id"]: report for report in reports}
    for report in latest.values():
        verify_quality_gate_report(report)
    scores = {
        gate_id: float(report["score"])
        for gate_id, report in sorted(latest.items())
    }
    regressions = []
    for gate_id, score in scores.items():
        if gate_id not in (baseline_scores or {}):
            continue
        baseline = float((baseline_scores or {})[gate_id])
        delta = round(score - baseline, 4)
        if delta < -0.05 or (
            latest[gate_id]["passed"] is not True and baseline > score
        ):
            regressions.append(
                {
                    "gate_id": gate_id,
                    "baseline": baseline,
                    "current": score,
                    "delta": delta,
                    "blocking": False,
                }
            )
    document = {
        "schema_version": "2.0",
        "contract_version": "build-quality-report/1",
        "build_id": build_id,
        "report_count": len(latest),
        "passed_gate_count": sum(
            report["passed"] is True for report in latest.values()
        ),
        "failed_gate_count": sum(
            report["passed"] is not True for report in latest.values()
        ),
        "gate_scores": scores,
        "quality_score": round(sum(scores.values()) / max(1, len(scores)), 4),
        "regressions": regressions,
        "regression_blocking": False,
        "drill_down": {
            gate_id: {
                "report_id": report["report_id"],
                "content_hash": report["content_hash"],
            }
            for gate_id, report in sorted(latest.items())
        },
        "generated_at": DETERMINISTIC_TIME,
    }
    document["content_hash"] = content_hash(document)
    return document


def part7_coverage_report() -> dict[str, Any]:
    """Return the fixed twenty-cluster Part 7 implementation matrix."""
    full = [
        ("gate_registry_and_contract", "versioned registry and one evaluator"),
        ("deterministic_check_model", "pure predicates with controlled results and evidence"),
        ("fail_closed_verdict", "mandatory floor and closed PASS/FAIL reduction"),
        ("lifecycle_and_idempotency", "fixed lifecycle and content-derived report identity"),
        ("ordering_and_chain", "ordered non-bypassable chain with halt enforcement"),
        ("immutable_configuration", "versioned configuration hash bound into every report"),
        ("report_integrity_and_evidence", "CAS-backed reports with artifact evidence binding"),
        ("story_gate", "mandatory Story predicates and report"),
        ("screenplay_gate", "mandatory Screenplay predicates and report"),
        ("shot_gate", "eight mandatory shot predicates and report"),
        ("storyboard_gate", "six sequence predicates and report"),
        ("render_gate", "asset and rendering conformance gates"),
        ("composition_audio_gates", "timeline, narration, sync, and loudness enforcement"),
        ("metadata_publication_gates", "package integrity and scoped publication checks"),
        ("cross_stage_coherence", "approved storyboard to render identity checks"),
        ("agent_review_gate", "typed evidence, dispositions, and bounded human exception"),
        ("human_authority_and_audit", "artifact-bound approvals and append-only audit events"),
        ("scoring_regression_dashboard", "immutable quality evidence plus longitudinal viewer and production-context trends"),
        ("persona_quality_gate", "ten-check non-waivable Persona quality evidence and approval binding"),
    ]
    partial = [
        ("acceptance_evidence", "automated local invariants; live editorial/provider evidence remains external"),
    ]
    missing: list[tuple[str, str]] = []
    rows = [
        *(
            {"cluster": cluster, "status": "FULL", "evidence": evidence}
            for cluster, evidence in full
        ),
        *(
            {"cluster": cluster, "status": "PARTIAL", "evidence": evidence}
            for cluster, evidence in partial
        ),
        *(
            {"cluster": cluster, "status": "MISSING", "evidence": evidence}
            for cluster, evidence in missing
        ),
    ]
    points = len(full) + len(partial) * 0.5
    return {
        "method": "FULL=1, PARTIAL=0.5, MISSING=0",
        "cluster_count": len(rows),
        "full": len(full),
        "partial": len(partial),
        "missing": len(missing),
        "points": points,
        "coverage_percent": round(points / len(rows) * 100, 1),
        "clusters": rows,
    }


def creative_gate_passed(report: dict[str, Any]) -> bool:
    return (
        report.get("passed") is True
        and float(report.get("score", 0)) >= float(report.get("threshold", 1))
        and report.get("fail_closed") is True
    )


def composition_gate(
    master: Path,
    *,
    width: int,
    height: int,
    frame_rate: int,
    expected_duration: float,
    youtube_ready: bool = False,
) -> dict[str, Any]:
    validation = AssetValidator().validate(
        master,
        width=width,
        height=height,
        frame_rate=frame_rate,
        duration_seconds=expected_duration,
        require_audio=True,
        require_youtube_ready=youtube_ready,
    )
    checks = {
        "file_integrity": validation["checks"]["nonempty"],
        "decode": validation["checks"]["decodable"],
        "codec": validation["checks"]["codec"],
        "resolution": validation["checks"]["width"] and validation["checks"]["height"],
        "frame_rate": validation["checks"]["frame_rate"],
        "duration": validation["checks"]["duration"],
        "audio_stream": validation["checks"]["audio"],
        "audio_signal": validation["checks"]["audio_signal"],
        "visual_content": validation["checks"]["visual_content"],
        "youtube_delivery": validation["checks"]["youtube_delivery"],
    }
    score = sum(checks.values()) / len(checks)
    return {
        "gate_id": "composition_quality_gate",
        "passed": all(checks.values()),
        "score": score,
        "threshold": 1.0,
        "checks": checks,
        "validation": validation,
        "blocking": True,
        "fail_closed": True,
    }
