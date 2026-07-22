"""Executable Vision / Architecture contracts and conformance audit."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .util import content_hash


ARCHITECTURE_CONTRACT_VERSION = "vision-architecture/3.4.0"

_LAYER_NAMES = (
    "Knowledge",
    "Narrative",
    "Screenplay",
    "Direction",
    "Rendering",
    "Composition",
    "Validation",
    "Publishing",
)

_LAYER_OUTPUTS = (
    "Structured Article Model",
    "Story Model",
    "Screenplay",
    "Shot Plan",
    "Visual Assets",
    "Master Video",
    "Approved Build",
    "Distributable Package",
)

_LAYER_RESPONSIBILITIES = (
    "ingest and normalize the source article",
    "derive one evidence-bound dramatic story",
    "translate the story into observable cinematic scenes",
    "derive shots, camera, blocking, and storyboard",
    "route and produce visual assets",
    "assemble picture, narration, audio, and subtitles",
    "validate the complete build and approval evidence",
    "prepare a package for downstream distribution",
)

_FLOW_COMPONENTS = (
    "article_loader",
    "story_engine",
    "screenplay_engine",
    "shot_planner",
    "planning_quality_gates",
    "agent_review_boundary",
    "storyboard_previsualization",
    "storyboard_preview_approval",
    "execution_approval",
    "render_strategy",
    "animated_assets",
    "external_video_provider",
    "ffmpeg_composer",
    "quality_gates",
    "final_approval",
    "publish_package",
)

_FLOW_EDGES = (
    ("article_loader", "story_engine", "structured_article_model"),
    ("story_engine", "screenplay_engine", "story_model"),
    ("screenplay_engine", "shot_planner", "screenplay"),
    ("shot_planner", "planning_quality_gates", "shot_plan_and_storyboard"),
    ("planning_quality_gates", "agent_review_boundary", "sealed_planning_bundle"),
    ("agent_review_boundary", "storyboard_previsualization", "review_evidence_or_not_applicable"),
    ("storyboard_previsualization", "storyboard_preview_approval", "zero_runway_preview_bundle_or_not_applicable"),
    ("storyboard_preview_approval", "execution_approval", "approved_preview_or_not_applicable"),
    ("execution_approval", "render_strategy", "approved_execution_plan"),
    ("render_strategy", "animated_assets", "deterministic_asset_work"),
    ("render_strategy", "external_video_provider", "provider_asset_work"),
    ("animated_assets", "ffmpeg_composer", "validated_visual_assets"),
    ("external_video_provider", "ffmpeg_composer", "validated_visual_assets"),
    ("ffmpeg_composer", "quality_gates", "master_video"),
    ("quality_gates", "final_approval", "validated_build"),
    ("final_approval", "publish_package", "approved_build"),
)

_OBJECTIVES = (
    (
        "O1",
        "executive_quality_cinematic_trailer",
        "Critical",
        "composition_and_visual_quality_gates",
    ),
    (
        "O2",
        "preserve_article_intellectual_structure",
        "Critical",
        "story_quality_gate",
    ),
    (
        "O3",
        "emotional_engagement_through_drama",
        "Critical",
        "story_and_screenplay_quality_gates",
    ),
    (
        "O4",
        "deterministic_reproducible_builds",
        "High",
        "content_hashes_caches_and_determinism_tests",
    ),
    (
        "O5",
        "minimize_regeneration_cost",
        "High",
        "exact_cache_and_incremental_execution_plan",
    ),
    (
        "O6",
        "separate_planning_from_rendering",
        "Critical",
        "fail_closed_execution_approval",
    ),
    (
        "O7",
        "provider_independence",
        "High",
        "rendering_facade_and_provider_isolation_audit",
    ),
)

_NON_OBJECTIVES = (
    ("N1", "movie_editor", "manual_timeline_and_clip_editing_are_rejected"),
    ("N2", "vfx_suite", "effects_without_narrative_value_are_rejected"),
    ("N3", "generic_ai_video_generator", "direct_article_to_video_is_rejected"),
    ("N4", "animation_tool", "animation_is_only_an_asset_class"),
    ("N5", "social_media_automation", "automatic_distribution_is_rejected"),
)

_PRINCIPLES = (
    ("AR1", "single_responsibility", "architecture_contract_and_module_tests"),
    ("AR2", "provider_abstraction", "provider_isolation_audit"),
    ("AR3", "deterministic_outputs", "canonical_content_hashes"),
    ("AR4", "immutable_planning", "content_addressable_artifact_store"),
    ("AR5", "incremental_build", "exact_stage_caches"),
    ("AR6", "fail_closed", "state_machine_and_blocking_gates"),
    ("AR7", "observable_pipeline", "events_metrics_and_quality_evidence"),
)


def architecture_contract() -> dict[str, Any]:
    """Return the canonical, deterministic Part 1 architecture contract."""
    layers = [
        {
            "id": index,
            "name": name,
            "responsibility": _LAYER_RESPONSIBILITIES[index - 1],
            "consumes": "Insight Article" if index == 1 else _LAYER_OUTPUTS[index - 2],
            "produces": _LAYER_OUTPUTS[index - 1],
            "depends_on": None if index == 1 else index - 1,
            "rendering_provider_aware": index == 5,
        }
        for index, name in enumerate(_LAYER_NAMES, start=1)
    ]
    return {
        "schema_version": "2.0",
        "contract_version": ARCHITECTURE_CONTRACT_VERSION,
        "product": {
            "category": "institutional_storytelling_system",
            "input": {
                "type": "insight_article",
                "cardinality": "exactly_one",
                "format": "structured_markdown",
            },
            "output": {
                "type": "cinematic_trailer",
                "cardinality": "exactly_one",
                "audience": "cxo",
            },
            "guarantees": {
                "conceptual_accuracy": "preserved",
                "communication": "required",
                "illustration_only": "rejected",
            },
            "scope": {
                "starts_at": "insight_article",
                "ends_at": "approved_trailer_package",
                "authoring": "upstream_out_of_scope",
                "distribution": "downstream_out_of_scope",
                "automatic_publication": False,
            },
        },
        "mission": {
            "statement": "make rigorous ideas emotionally engaging without reducing rigor",
            "design_filter": "story_is_the_product_video_is_the_medium",
            "decision_test": "helps_viewer_understand_why_the_idea_matters",
        },
        "objectives": [
            {
                "id": identifier,
                "objective": objective,
                "priority": priority,
                "enforced_by": enforcement,
            }
            for identifier, objective, priority, enforcement in _OBJECTIVES
        ],
        "priority_rule": "Critical_outranks_High",
        "non_objectives": [
            {"id": identifier, "capability": capability, "enforcement": enforcement}
            for identifier, capability, enforcement in _NON_OBJECTIVES
        ],
        "success": {
            "primary_criterion": "idea_comprehension",
            "requires": ["comprehension", "retention"],
            "failure_if_any": [
                "idea_not_understood",
                "medium_foregrounded",
                "rigor_lost",
                "emotion_without_meaning",
            ],
            "signals": [
                "idea_restatement_accuracy",
                "unaided_recall",
                "reaction_subject",
                "accuracy_gate_result",
            ],
            "measurement_status": "longitudinal_operational_dashboard",
            "outcome_observability": {
                "event_contract": "viewer-outcome/1",
                "dashboard_contract": "viewer-outcomes-dashboard/1",
                "storage": "append_only_hash_chained_ledger",
                "privacy": "hmac_pseudonymous_aggregate_only",
                "minimum_retention_hours": 168,
                "retention_buckets": [
                    "under_24h",
                    "1_to_6_days",
                    "7_to_29_days",
                    "30_days_plus",
                ],
                "dimensions": ["build", "cohort", "month"],
                "medium_foregrounding_is_decisive": True,
            },
        },
        "derivation": {
            "direction": ["Ideas", "Narrative", "Cinema", "Technology"],
            "reverse_influence": "prohibited",
            "technology_originates_creative_decisions": False,
        },
        "layers": layers,
        "flow": {
            "components": list(_FLOW_COMPONENTS),
            "edges": [
                {"from": source, "to": destination, "payload": payload}
                for source, destination, payload in _FLOW_EDGES
            ],
            "branch_point": "render_strategy",
            "convergence_point": "ffmpeg_composer",
            "prohibited_shortcuts": [
                "article_loader->render_strategy",
                "article_loader->external_video_provider",
                "planning_quality_gates->render_strategy",
                "quality_gates->publish_package",
            ],
        },
        "cost_domains": {
            "planning": [
                "story_engine",
                "screenplay_engine",
                "shot_planner",
                "planning_quality_gates",
                "agent_review_boundary",
                "storyboard_previsualization",
                "storyboard_preview_quality_gate",
            ],
            "approval_barrier": "execution_approval",
            "expensive_execution": [
                "render_strategy",
                "animated_assets",
                "external_video_provider",
                "ffmpeg_composer",
            ],
            "planning_mutable_after_approval": False,
            "speculative_rendering": "prohibited",
        },
        "story_first": {
            "required_before": [
                "screenplay_engine",
                "shot_planner",
                "render_strategy",
            ],
            "downstream_traceability": "content_hash_lineage",
            "story_change_invalidates_downstream": True,
        },
        "hybrid_rendering": {
            "selection_rule": "cheapest_sufficient_asset_class",
            "provider_agnostic": True,
            "asset_classes": [
                "external_video",
                "animated_still",
                "motion_graphics",
                "typography",
                "narration",
            ],
            "premium_ratio_max": {"preview": 0.4, "final": 0.5},
        },
        "governance": {
            "human_approvals": [
                {
                    "gate": "storyboard_preview_approval",
                    "position": "before_execution_approval",
                    "gates": "creative_preview",
                    "fail_closed": True,
                    "mode": "storyboard_animatic_or_not_applicable",
                },
                {
                    "gate": "execution_approval",
                    "position": "before_rendering",
                    "gates": "rendering",
                    "fail_closed": True,
                },
                {
                    "gate": "final_approval",
                    "position": "after_rendering",
                    "gates": "packaging",
                    "fail_closed": True,
                },
            ],
            "silence_is_consent": False,
            "automation_may_approve": False,
        },
        "principles": [
            {"id": identifier, "principle": principle, "verified_by": verification}
            for identifier, principle, verification in _PRINCIPLES
        ],
        "authority_boundaries": {
            "rendering_provider_access": {
                "allowed_layer": "Rendering",
                "all_other_transformation_layers": "prohibited",
            },
            "agent_review": {
                "modes": ["off", "review"],
                "position": "post_sealed_planning_pre_execution_approval",
                "agent_count": 1,
                "max_turns": 1,
                "tools": [],
                "handoffs": [],
                "agents_as_tools": [],
                "may_mutate_planning": False,
                "may_invoke_rendering": False,
                "may_approve": False,
                "may_publish": False,
                "failure_dispositions": [
                    "MANUAL_REVIEW_REQUIRED",
                    "UNAVAILABLE",
                    "ERROR",
                ],
                "failure_behavior": "hold_before_rendering",
                "approval_binds": [
                    "execution_plan_content_hash",
                    "agent_review_report_content_hash",
                ],
                "raw_chain_of_thought_persisted": False,
                "secrets_in_artifacts": False,
            },
            "persona_council": {
                "modes": ["off", "council"],
                "position": "post_article_pre_story",
                "ownership_pattern": "manager_owned_agents_as_tools",
                "specialists": [
                    "audience_researcher",
                    "empathy_narrative_analyst",
                    "brand_strategist",
                    "red_team_critic",
                    "persona_manager",
                ],
                "handoffs": False,
                "specialists_call_each_other": False,
                "rounds": {"proposal": 1, "critique": 1, "synthesis": 1},
                "sealed_artifacts": [
                    "persona-proposals",
                    "persona-red-team-report",
                    "persona-deliberation",
                    "persona",
                    "persona-quality-report",
                    "persona-approval-binding",
                ],
                "human_approval_before_story": True,
                "allowed_side_effects": [],
                "prohibited_side_effects": [
                    "story_generation",
                    "rendering",
                    "approval",
                    "publication",
                    "external_write",
                ],
                "raw_chain_of_thought_persisted": False,
                "runtime_status": "live_bounded_manager_owned_agents_as_tools",
            },
            "storyboard_previsualization": {
                "modes": ["off", "storyboard_animatic"],
                "position": "post_sealed_planning_pre_execution_approval",
                "planning_model": "gpt-5.6-sol",
                "image_tool": "image_generation",
                "video_provider_access": False,
                "runway_counters_before_approval": 0,
                "animatic_composer": "ffmpeg",
                "non_publishable": True,
                "final_cache_eligible": False,
                "human_approval_required_when_enabled": True,
                "render_approval_remains_independent": True,
            },
        },
    }


class ArchitectureValidator:
    """Fail-closed validator for the canonical Part 1 topology and authority model."""

    def validate(self, document: dict[str, Any]) -> dict[str, Any]:
        checks: dict[str, dict[str, Any]] = {}

        def record(check_id: str, passed: bool, evidence: str) -> None:
            checks[check_id] = {"passed": bool(passed), "evidence": evidence}

        product = document.get("product", {})
        record(
            "product_contract_fixed",
            product.get("category") == "institutional_storytelling_system"
            and product.get("input")
            == {
                "type": "insight_article",
                "cardinality": "exactly_one",
                "format": "structured_markdown",
            }
            and product.get("output")
            == {
                "type": "cinematic_trailer",
                "cardinality": "exactly_one",
                "audience": "cxo",
            },
            "/product",
        )
        guarantees = product.get("guarantees", {})
        scope = product.get("scope", {})
        record(
            "communication_accuracy_and_scope",
            guarantees
            == {
                "conceptual_accuracy": "preserved",
                "communication": "required",
                "illustration_only": "rejected",
            }
            and scope.get("authoring") == "upstream_out_of_scope"
            and scope.get("distribution") == "downstream_out_of_scope"
            and scope.get("automatic_publication") is False,
            "/product/guarantees;/product/scope",
        )

        objectives = document.get("objectives", [])
        record(
            "objectives_complete_and_enforced",
            [item.get("id") for item in objectives] == [f"O{i}" for i in range(1, 8)]
            and all(item.get("enforced_by") for item in objectives)
            and document.get("priority_rule") == "Critical_outranks_High"
            and all(
                item.get("priority") == ("Critical" if item.get("id") in {"O1", "O2", "O3", "O6"} else "High")
                for item in objectives
            ),
            "/objectives;/priority_rule",
        )
        non_objectives = document.get("non_objectives", [])
        record(
            "non_objectives_complete_and_enforced",
            [item.get("id") for item in non_objectives]
            == [f"N{i}" for i in range(1, 6)]
            and all(item.get("enforcement") for item in non_objectives),
            "/non_objectives",
        )
        success = document.get("success", {})
        outcomes = success.get("outcome_observability", {})
        record(
            "success_definition_controlled",
            success.get("primary_criterion") == "idea_comprehension"
            and success.get("requires") == ["comprehension", "retention"]
            and set(success.get("failure_if_any", []))
            == {
                "idea_not_understood",
                "medium_foregrounded",
                "rigor_lost",
                "emotion_without_meaning",
            }
            and success.get("measurement_status")
            == "longitudinal_operational_dashboard"
            and outcomes.get("event_contract") == "viewer-outcome/1"
            and outcomes.get("dashboard_contract")
            == "viewer-outcomes-dashboard/1"
            and outcomes.get("storage") == "append_only_hash_chained_ledger"
            and outcomes.get("privacy") == "hmac_pseudonymous_aggregate_only"
            and outcomes.get("minimum_retention_hours") == 168
            and outcomes.get("medium_foregrounding_is_decisive") is True,
            "/success",
        )

        derivation = document.get("derivation", {})
        record(
            "direction_is_idea_first",
            derivation.get("direction")
            == ["Ideas", "Narrative", "Cinema", "Technology"]
            and derivation.get("reverse_influence") == "prohibited"
            and derivation.get("technology_originates_creative_decisions") is False,
            "/derivation",
        )

        layers = document.get("layers", [])
        record(
            "exactly_eight_ordered_layers",
            [layer.get("id") for layer in layers] == list(range(1, 9))
            and [layer.get("name") for layer in layers] == list(_LAYER_NAMES),
            "/layers",
        )
        record(
            "adjacent_layer_dependencies_only",
            len(layers) == 8
            and all(
                layer.get("depends_on") == (None if index == 1 else index - 1)
                for index, layer in enumerate(layers, start=1)
            ),
            "/layers/*/depends_on",
        )
        record(
            "single_responsibility_and_output",
            len(layers) == 8
            and all(isinstance(layer.get("responsibility"), str) and layer["responsibility"] for layer in layers)
            and [layer.get("produces") for layer in layers] == list(_LAYER_OUTPUTS),
            "/layers/*/responsibility;/layers/*/produces",
        )
        provider_aware = [
            layer.get("name")
            for layer in layers
            if layer.get("rendering_provider_aware") is True
        ]
        record(
            "rendering_provider_confined",
            provider_aware == ["Rendering"],
            "/layers/*/rendering_provider_aware",
        )

        flow = document.get("flow", {})
        components = flow.get("components", [])
        raw_edges = flow.get("edges", [])
        edges = {
            (edge.get("from"), edge.get("to"), edge.get("payload"))
            for edge in raw_edges
            if isinstance(edge, dict)
        }
        expected_edges = set(_FLOW_EDGES)
        record(
            "declared_single_directed_flow",
            components == list(_FLOW_COMPONENTS) and edges == expected_edges,
            "/flow/components;/flow/edges",
        )
        outgoing = {component: 0 for component in components}
        incoming = {component: 0 for component in components}
        for source, destination, _payload in edges:
            if source in outgoing:
                outgoing[source] += 1
            if destination in incoming:
                incoming[destination] += 1
        branch_nodes = [node for node, degree in outgoing.items() if degree > 1]
        convergence_nodes = [node for node, degree in incoming.items() if degree > 1]
        record(
            "sole_render_branch_and_composer_convergence",
            branch_nodes == ["render_strategy"]
            and convergence_nodes == ["ffmpeg_composer"]
            and flow.get("branch_point") == "render_strategy"
            and flow.get("convergence_point") == "ffmpeg_composer",
            "/flow/branch_point;/flow/convergence_point",
        )
        edge_pairs = {(source, destination) for source, destination, _ in edges}
        prohibited = {
            tuple(item.split("->", 1))
            for item in flow.get("prohibited_shortcuts", [])
            if isinstance(item, str) and "->" in item
        }
        record(
            "shortcuts_and_gate_bypass_prohibited",
            prohibited
            == {
                ("article_loader", "render_strategy"),
                ("article_loader", "external_video_provider"),
                ("planning_quality_gates", "render_strategy"),
                ("quality_gates", "publish_package"),
            }
            and not (edge_pairs & prohibited),
            "/flow/prohibited_shortcuts",
        )

        cost_domains = document.get("cost_domains", {})
        record(
            "planning_rendering_approval_barrier",
            cost_domains.get("approval_barrier") == "execution_approval"
            and cost_domains.get("planning_mutable_after_approval") is False
            and cost_domains.get("speculative_rendering") == "prohibited"
            and ("execution_approval", "render_strategy") in edge_pairs,
            "/cost_domains",
        )
        story_first = document.get("story_first", {})
        record(
            "story_first_and_invalidation",
            story_first.get("required_before")
            == ["screenplay_engine", "shot_planner", "render_strategy"]
            and story_first.get("downstream_traceability") == "content_hash_lineage"
            and story_first.get("story_change_invalidates_downstream") is True,
            "/story_first",
        )
        hybrid = document.get("hybrid_rendering", {})
        record(
            "hybrid_cheapest_sufficient_selection",
            hybrid.get("selection_rule") == "cheapest_sufficient_asset_class"
            and hybrid.get("provider_agnostic") is True
            and hybrid.get("premium_ratio_max") == {"preview": 0.4, "final": 0.5}
            and len(hybrid.get("asset_classes", [])) >= 5,
            "/hybrid_rendering",
        )

        governance = document.get("governance", {})
        approvals = governance.get("human_approvals", [])
        record(
            "three_scoped_fail_closed_human_approvals",
            approvals
            == [
                {
                    "gate": "storyboard_preview_approval",
                    "position": "before_execution_approval",
                    "gates": "creative_preview",
                    "fail_closed": True,
                    "mode": "storyboard_animatic_or_not_applicable",
                },
                {
                    "gate": "execution_approval",
                    "position": "before_rendering",
                    "gates": "rendering",
                    "fail_closed": True,
                },
                {
                    "gate": "final_approval",
                    "position": "after_rendering",
                    "gates": "packaging",
                    "fail_closed": True,
                },
            ]
            and governance.get("silence_is_consent") is False
            and governance.get("automation_may_approve") is False,
            "/governance",
        )
        principles = document.get("principles", [])
        record(
            "architectural_principles_complete",
            [item.get("id") for item in principles] == [f"AR{i}" for i in range(1, 8)]
            and all(item.get("verified_by") for item in principles),
            "/principles",
        )

        boundaries = document.get("authority_boundaries", {})
        review = boundaries.get("agent_review", {})
        record(
            "agent_review_read_only_and_fail_closed",
            review.get("modes") == ["off", "review"]
            and review.get("position") == "post_sealed_planning_pre_execution_approval"
            and review.get("agent_count") == 1
            and review.get("max_turns") == 1
            and review.get("tools") == []
            and review.get("handoffs") == []
            and review.get("agents_as_tools") == []
            and all(
                review.get(field) is False
                for field in (
                    "may_mutate_planning",
                    "may_invoke_rendering",
                    "may_approve",
                    "may_publish",
                    "raw_chain_of_thought_persisted",
                    "secrets_in_artifacts",
                )
            )
            and review.get("failure_behavior") == "hold_before_rendering"
            and review.get("approval_binds")
            == [
                "execution_plan_content_hash",
                "agent_review_report_content_hash",
            ],
            "/authority_boundaries/agent_review",
        )
        council = boundaries.get("persona_council", {})
        preview = boundaries.get("storyboard_previsualization", {})
        record(
            "persona_council_bounded_and_human_gated",
            council.get("modes") == ["off", "council"]
            and council.get("position") == "post_article_pre_story"
            and council.get("ownership_pattern") == "manager_owned_agents_as_tools"
            and len(council.get("specialists", [])) == 5
            and council.get("handoffs") is False
            and council.get("specialists_call_each_other") is False
            and council.get("rounds") == {"proposal": 1, "critique": 1, "synthesis": 1}
            and len(council.get("sealed_artifacts", [])) == 6
            and council.get("human_approval_before_story") is True
            and council.get("allowed_side_effects") == []
            and set(council.get("prohibited_side_effects", []))
            == {
                "story_generation",
                "rendering",
                "approval",
                "publication",
                "external_write",
            }
            and council.get("raw_chain_of_thought_persisted") is False
            and council.get("runtime_status")
            == "live_bounded_manager_owned_agents_as_tools"
            and preview.get("modes") == ["off", "storyboard_animatic"]
            and preview.get("video_provider_access") is False
            and preview.get("runway_counters_before_approval") == 0
            and preview.get("animatic_composer") == "ffmpeg"
            and preview.get("non_publishable") is True
            and preview.get("final_cache_eligible") is False
            and preview.get("human_approval_required_when_enabled") is True
            and preview.get("render_approval_remains_independent") is True,
            "/authority_boundaries/persona_council",
        )

        violations = [check_id for check_id, check in checks.items() if not check["passed"]]
        return {
            "schema_version": "2.0",
            "contract_version": ARCHITECTURE_CONTRACT_VERSION,
            "contract_content_hash": content_hash(document),
            "passed": not violations,
            "fail_closed": True,
            "check_count": len(checks),
            "checks": checks,
            "violations": violations,
        }

    def assert_valid(self, document: dict[str, Any]) -> dict[str, Any]:
        report = self.validate(document)
        if not report["passed"]:
            raise ValidationError(
                "Vision / Architecture conformance failed",
                details=report,
            )
        return report


_PROTECTED_PROVIDER_ISOLATION_MODULES = (
    "article.py",
    "story.py",
    "screenplay.py",
    "shot_planner.py",
    "prompt.py",
    "package.py",
    "previsualization.py",
)


def provider_isolation_audit(source_root: Path | None = None) -> dict[str, Any]:
    """Verify narrative, direction, and publishing modules import no provider adapter."""
    root = source_root or Path(__file__).resolve().parent
    violations: list[dict[str, str]] = []
    scanned: list[str] = []
    for filename in _PROTECTED_PROVIDER_ISOLATION_MODULES:
        path = root / filename
        if not path.is_file():
            violations.append({"module": filename, "reason": "module_missing"})
            continue
        scanned.append(filename)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=filename)
        except (OSError, SyntaxError) as exc:
            violations.append({"module": filename, "reason": f"parse_error:{type(exc).__name__}"})
            continue
        for node in ast.walk(tree):
            imported = ""
            if isinstance(node, ast.ImportFrom):
                imported = node.module or ""
            elif isinstance(node, ast.Import):
                imported = ",".join(alias.name for alias in node.names)
            if ".providers" in f".{imported}" or imported.endswith("providers"):
                violations.append({"module": filename, "reason": f"provider_import:{imported}"})
    return {
        "passed": not violations,
        "policy": "rendering_provider_adapters_are_confined_outside_protected_layers",
        "scanned_modules": scanned,
        "violations": violations,
    }


def architecture_audit(source_root: Path | None = None) -> dict[str, Any]:
    contract = architecture_contract()
    report = ArchitectureValidator().validate(contract)
    source_audit = provider_isolation_audit(source_root)
    report["source_provider_isolation"] = source_audit
    report["passed"] = report["passed"] and source_audit["passed"]
    if not report["passed"]:
        raise ValidationError("Vision / Architecture audit failed", details=report)
    return report


def architecture_artifacts() -> dict[str, dict[str, Any]]:
    contract = architecture_contract()
    return {
        "architecture_contract": contract,
        "architecture_validation_report": ArchitectureValidator().assert_valid(contract),
    }


def part1_coverage_report() -> dict[str, Any]:
    """Return the fixed, auditable Part 1 coverage matrix."""
    clusters = [
        ("product_contract_and_scope", "FULL", "canonical product and boundary contract"),
        ("mission_and_design_filter", "FULL", "communication-over-illustration decision rule"),
        ("objectives_o1_o7", "FULL", "stable priorities and enforcement traceability"),
        ("non_objectives_n1_n5", "FULL", "machine-audited scope constraints"),
        ("success_and_failure_model", "FULL", "controlled comprehension and retention signals"),
        ("idea_first_direction", "FULL", "one-way derivation and reverse-influence rejection"),
        ("single_directed_flow", "FULL", "typed exact component adjacency graph"),
        ("eight_layer_architecture", "FULL", "single responsibility, output, and adjacent dependency"),
        ("provider_isolation", "FULL", "layer policy plus source import audit"),
        ("planning_render_separation", "FULL", "fail-closed approval before provider spend"),
        ("story_first_invalidation", "FULL", "content-hash lineage invalidates downstream derivations"),
        ("sole_branch_and_convergence", "FULL", "Render Strategy fork and FFmpeg convergence"),
        ("hybrid_render_strategy", "FULL", "cheapest-sufficient provider-agnostic selection"),
        ("three_scoped_human_approvals", "FULL", "preview, execution, and publication approvals fail closed"),
        ("determinism_immutability_incrementality", "FULL", "CAS artifacts and exact caches"),
        ("architectural_principles_ar1_ar7", "FULL", "stable rules with executable evidence"),
        ("agent_review_boundary", "FULL", "single-turn tool-free read-only reviewer"),
        ("architecture_artifact_and_gate", "FULL", "sealed contract and blocking conformance report"),
        (
            "persona_council_runtime",
            "FULL",
            "live bounded manager-owned agents-as-tools, immutable evidence, quality, and approval",
        ),
        (
            "long_horizon_outcome_observability",
            "FULL",
            "append-only pseudonymous outcomes, long-term recall windows, trends, and HTML/JSON dashboard",
        ),
    ]
    weights = {"FULL": 1.0, "PARTIAL": 0.5, "MISSING": 0.0}
    points = sum(weights[status] for _name, status, _evidence in clusters)
    counts = {
        status.casefold(): sum(item_status == status for _name, item_status, _evidence in clusters)
        for status in weights
    }
    return {
        "part": "1. Vision / Architecture",
        "method": "fixed_capability_clusters_full_1_partial_0.5_missing_0",
        "cluster_count": len(clusters),
        "counts": counts,
        "points": points,
        "coverage_percent": round(points / len(clusters) * 100, 1),
        "target_percent": 95.0,
        "target_met": points / len(clusters) >= 0.95,
        "clusters": [
            {"id": index, "capability": name, "status": status, "evidence": evidence}
            for index, (name, status, evidence) in enumerate(clusters, start=1)
        ],
    }
