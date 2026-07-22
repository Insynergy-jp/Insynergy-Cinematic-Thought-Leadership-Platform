"""Build Orchestrator enforcing adjacency, approval barriers, and recovery."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from .agent_review import (
    AgentReviewProvider,
    AgentReviewService,
    AgentReviewStore,
    build_report_validation_request,
    build_review_request,
    validate_agent_review_report,
    validate_review_approval_binding,
    WAIVABLE_ERROR_CLASSES,
)

from .article import load_article
from .architecture import architecture_artifacts, part1_coverage_report
from .config import load_config
from .errors import (
    ApprovalRequiredError,
    PersonaCouncilError,
    QualityGateError,
    StateConflictError,
    ValidationError,
)
from .media import (
    FFmpegComposer,
    OfflineNarrator,
    OpenAITTSNarrator,
    YouTubeMastering,
    write_srt,
)
from .models import (
    AgentReviewStatus,
    ApprovalDecision,
    ApprovalRecord,
    ArtifactEnvelope,
    BuildState,
)
from .package import create_publish_package, create_thumbnail
from .persona import (
    PersonaCouncilCache,
    PersonaCouncilProvider,
    PersonaCouncilRequest,
    PersonaCouncilService,
    deliberation_key,
    load_creative_brief,
    validate_persona_preapproval_bundle,
)
from .prompt import PromptAssembler
from .providers.local import LocalVideoProvider
from .quality import (
    QualityGateEngine,
    build_quality_report,
    composition_gate,
    creative_gate_passed,
    part7_coverage_report,
    registry_document,
)
from .rendering import (
    RUNWAY_CREDIT_USD,
    RenderCache,
    RenderingPlatform,
    runway_credit_estimate,
    uses_runway,
)
from .runtime import DurableTaskQueue, part6_coverage_report
from .screenplay import ScreenplayCache, ScreenplayConfig, ScreenplayEngine
from .schema_validation import PERSONA_NAMES, validate_persona_bundle
from .shot_planner import ShotPlanner
from .storage import BuildRepository
from .story import StoryCache, StoryConfig, StoryEngine
from .util import (
    DETERMINISTIC_TIME,
    PLATFORM_VERSION,
    atomic_write_text,
    content_hash,
    file_hash,
    now_iso,
    stable_id,
)


PLANNING_ARTIFACTS = {
    "architecture_contract",
    "architecture_validation_report",
    "structured_article",
    "creative_brief",
    "persona-proposals",
    "persona-red-team-report",
    "persona-deliberation",
    "persona",
    "persona-quality-report",
    "persona-approval-binding",
    "argument_map",
    "theme",
    "dramatic_question",
    "dramatic_premise",
    "logline",
    "character_bible",
    "conflict",
    "stakes",
    "time_pressure",
    "story_arc",
    "three_act_structure",
    "emotional_arc",
    "concept_placement",
    "story_quality_report",
    "story_metrics",
    "story_config",
    "story_decision_log",
    "story_stage_records",
    "screenplay",
    "scene_index",
    "dialogue",
    "continuity",
    "screenplay_metrics",
    "screenplay_config",
    "screenplay_state",
    "screenplay_quality_report",
    "screenplay_fountain",
    "narration_script",
    "shot_list",
    "camera_plan",
    "blocking",
    "storyboard",
    "continuity_report",
    "render_strategy",
    "shot_metrics",
    "shot_gate_report",
    "storyboard_gate_report",
    "performance_budget",
    "dependency_graph",
    "build_profile",
    "performance_config",
    "execution_plan",
    "operational_state",
    "quality_gate_registry",
}


class BuildOrchestrator:
    def __init__(
        self,
        workspace: Path | str,
        *,
        config_path: Path | None = None,
        profile: str | None = None,
        provider: str | None = None,
        runway_scope: str | None = None,
        narration_provider: str | None = None,
        agent_review_mode: str | None = None,
        persona_mode: str | None = None,
        environ: dict[str, str] | None = None,
        review_provider: AgentReviewProvider | None = None,
        persona_provider: PersonaCouncilProvider | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.config = load_config(
            workspace=self.workspace,
            config_path=config_path,
            profile=profile,
            provider=provider,
            runway_scope=runway_scope,
            narration_provider=narration_provider,
            agent_review_mode=agent_review_mode,
            persona_mode=persona_mode,
            environ=environ,
        )
        self.repository = BuildRepository(self.workspace)
        self._review_provider_override = review_provider
        self._persona_provider_override = persona_provider

    def _config_snapshot(self) -> dict[str, Any]:
        profile = self.config.render_profile()
        story = self.config.story
        screenplay = self.config.screenplay
        return {
            "schema_version": "2.0",
            "platform_version": PLATFORM_VERSION,
            "profile": self.config.profile,
            "deterministic": self.config.deterministic,
            "render": {
                "provider": self.config.provider,
                "runway_scope": self.config.runway_scope,
                "max_runway_credits": self.config.max_runway_credits,
                "max_parallel_shots": self.config.max_parallel_shots,
                "max_attempts": self.config.max_attempts,
                "quality_threshold": self.config.quality_threshold,
                "budget_usd": self.config.budget_usd,
                "estimate_before_submission": self.config.estimate_before_submission,
                "width": profile.width,
                "height": profile.height,
                "frame_rate": profile.frame_rate,
                "max_duration_seconds": profile.max_duration_seconds,
            },
            "story": {
                "engine_version": "3.3.0",
                "profile": "draft" if self.config.profile == "draft" else "canonical",
                "concept_ratio_max": self.config.concept_ratio_max,
                "supporting_role_max": self.config.supporting_role_max,
                "duration_seconds": (
                    story.draft_duration_seconds
                    if self.config.profile == "draft"
                    else story.canonical_duration_seconds
                ),
                "genre": story.genre,
                "audience": story.audience,
                "author_style": list(story.author_style),
                "persona_mode": story.persona_mode,
                "thresholds": {
                    "dramatic_score": story.dramatic_score_min,
                    "conflict_score": story.conflict_score_min,
                    "stakes_score": story.stakes_score_min,
                    "emotional_progression": story.emotional_progression_min,
                },
            },
            "screenplay": {
                "engine_version": "3.3.0",
                "profile": "production" if self.config.profile == "final" else "preview",
                "scene_count_min": screenplay.scene_count_min,
                "scene_count_max": screenplay.scene_count_max,
                "scene_duration_min": screenplay.scene_duration_min,
                "scene_duration_target": screenplay.scene_duration_target,
                "scene_duration_max": screenplay.scene_duration_max,
                "words_per_line": screenplay.words_per_line,
                "lines_per_turn": screenplay.lines_per_turn,
                "continuity_dimensions": 7,
            },
            "quality": {"fail_closed": self.config.fail_closed},
            "performance": {
                "max_in_flight_tasks": self.config.max_in_flight_tasks,
                "provider_parallel_limits": self.config.provider_parallel_limits,
                "checkpoint_enabled": self.config.checkpoint_enabled,
                "event_hash_chain_enabled": self.config.event_hash_chain_enabled,
            },
            "narration": {
                "provider": self.config.narration_provider,
                "openai_model": self.config.narration_openai_model,
                "openai_voice": self.config.narration_openai_voice,
                "openai_instructions": self.config.narration_openai_instructions,
            },
            "youtube": {
                "video_bitrate": self.config.youtube_video_bitrate,
                "audio_bitrate": self.config.youtube_audio_bitrate,
                "audio_sample_rate": self.config.youtube_audio_sample_rate,
                "integrated_loudness_lufs": self.config.youtube_integrated_loudness_lufs,
                "true_peak_db": self.config.youtube_true_peak_db,
            },
            "agent_review": {
                "mode": self.config.agent_review_mode,
                "model": self.config.agent_review_model,
                "reasoning_effort": self.config.agent_review_reasoning_effort,
                "trace_mode": self.config.agent_review_trace_mode,
                "timeout_seconds": self.config.agent_review_timeout_seconds,
                "max_input_bytes": self.config.agent_review_max_input_bytes,
                "max_output_tokens": self.config.agent_review_max_output_tokens,
                "agent_version": self.config.agent_review_agent_version,
                "prompt_version": self.config.agent_review_prompt_version,
                "policy_version": self.config.agent_review_policy_version,
            },
            "persona_council": {
                "mode": story.persona_mode,
                "model": self.config.persona_model,
                "reasoning_effort": self.config.persona_reasoning_effort,
                "trace_mode": self.config.persona_trace_mode,
                "timeout_seconds": self.config.persona_timeout_seconds,
                "max_input_bytes": self.config.persona_max_input_bytes,
                "max_output_tokens": self.config.persona_max_output_tokens,
                "preflight_estimated_cost_usd": self.config.persona_preflight_estimated_cost_usd,
                "max_cost_usd": self.config.persona_max_cost_usd,
                "manager_agent_version": self.config.persona_manager_agent_version,
                "prompt_version": self.config.persona_prompt_version,
                "policy_version": self.config.persona_policy_version,
            },
            "secrets_recorded": False,
        }

    @staticmethod
    def _artifact_inputs(manifest: dict, *artifact_types: str) -> tuple[str, ...]:
        return tuple(
            manifest["artifacts"][artifact_type]["content_hash"]
            for artifact_type in artifact_types
            if artifact_type in manifest.get("artifacts", {})
        )

    def _store_many(
        self,
        manifest: dict,
        artifacts: dict[str, dict[str, Any]],
        *,
        inputs: tuple[str, ...],
        generator: str,
    ) -> None:
        for artifact_type, data in artifacts.items():
            self.repository.store_artifact(
                manifest,
                ArtifactEnvelope(
                    artifact_type=artifact_type,
                    build_id=manifest["build_id"],
                    data=data,
                    input_hashes=inputs,
                    generator=generator,
                ),
            )

    @staticmethod
    def _gate_evidence(
        manifest: dict[str, Any], *artifact_types: str
    ) -> list[dict[str, Any]]:
        evidence = []
        for artifact_type in artifact_types:
            reference = manifest.get("artifacts", {}).get(artifact_type)
            if not reference:
                continue
            evidence.append(
                {
                    "artifact_type": artifact_type,
                    "artifact_id": reference["artifact_id"],
                    "content_hash": reference["content_hash"],
                    "json_pointer": "/data",
                }
            )
        return evidence

    def _record_quality_gate(
        self,
        manifest: dict[str, Any],
        *,
        gate_id: str,
        projection: dict[str, Any],
        checks: dict[str, Any],
        evidence_types: tuple[str, ...],
        advisory_checks: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        report = QualityGateEngine().evaluate(
            gate_id=gate_id,
            build_id=manifest["build_id"],
            checks=checks,
            artifact_refs=self._gate_evidence(manifest, *evidence_types),
            advisory_checks=advisory_checks,
        )
        projection["quality_report_id"] = report["report_id"]
        projection["quality_report_content_hash"] = report["content_hash"]
        manifest["gates"][gate_id] = projection
        manifest = self.repository.record_quality_report(manifest, report)
        if not report["passed"]:
            raise QualityGateError(f"{gate_id} failed closed", details=report)
        return manifest, report

    def _store_performance_plan(
        self,
        manifest: dict[str, Any],
        shot_artifacts: dict[str, dict[str, Any]],
    ) -> None:
        shots = shot_artifacts["shot_list"]["shots"]
        shot_ids = [str(shot["shot_id"]) for shot in shots]
        frames = shot_artifacts["storyboard"]["frames"]
        build_type = "final" if self.config.profile == "final" else "preview"
        nodes = [
            {"id": "story", "kind": "story"},
            {"id": "screenplay", "kind": "screenplay"},
            {"id": "storyboard", "kind": "storyboard"},
            *[
                {"id": f"render:{shot_id}", "kind": "shot", "shot_id": shot_id}
                for shot_id in shot_ids
            ],
            {"id": "validation", "kind": "validation"},
            {"id": "composition", "kind": "composition"},
            {"id": "packaging", "kind": "packaging"},
        ]
        edges = [
            {"from": "screenplay", "to": "story"},
            {"from": "storyboard", "to": "screenplay"},
            *[
                {"from": f"render:{shot_id}", "to": "storyboard"}
                for shot_id in shot_ids
            ],
            *[
                {"from": "validation", "to": f"render:{shot_id}"}
                for shot_id in shot_ids
            ],
            {"from": "composition", "to": "validation"},
            {"from": "packaging", "to": "composition"},
        ]
        dependency_graph = {
            "schema_version": "2.0",
            "build_id": manifest["build_id"],
            "nodes": nodes,
            "edges": edges,
            "acyclic": True,
        }
        performance_budget = {
            "schema_version": "2.0",
            "build_type": build_type,
            "on_exceed": "fail",
            "stages": {
                "planning": {"max_duration": 300, "priority": "High"},
                "screenplay": {"max_duration": 60, "priority": "High"},
                "shot_planning": {"max_duration": 60, "priority": "High"},
                "storyboard": {"max_duration": 60, "priority": "High"},
                "render_submission": {"max_duration": 120, "priority": "Critical"},
                "provider_rendering": {"external": True},
                "download": {"max_duration": 600, "priority": "High"},
                "validation": {"max_duration": 300, "priority": "Critical"},
                "composition": {"max_duration": 600, "priority": "High"},
                "packaging": {"max_duration": 120, "priority": "Medium"},
            },
            "slo": {"total_max_duration": 2220, "priority": "High"},
        }
        build_profile = {
            "schema_version": "2.0",
            "profile": "production" if build_type == "final" else "preview",
            "build_type": build_type,
            "execution_mode": "incremental",
            "settings": {
                "rendering": "final" if build_type == "final" else "draft",
                "validation": "strict",
                "cache": "enabled",
                "concurrency": "medium",
                "placeholders": "prohibited",
                "render_ratio": 1.0,
                "retries": "enabled",
                "runway_profile": self.config.runway_scope,
                "target_duration": sum(float(frame["duration_seconds"]) for frame in frames),
            },
        }
        performance_config = {
            "schema_version": "2.0",
            "configuration": {
                "environment": "local",
                "profile_version": "2.0",
                "updated_at": DETERMINISTIC_TIME,
            },
            "performance": {
                "scheduler": {
                    "global_workers": self.config.max_in_flight_tasks,
                    "planning_workers": 1,
                    "render_workers": self.config.max_parallel_shots,
                    "validation_workers": 1,
                    "ffmpeg_workers": 1,
                    "packaging_workers": 1,
                },
                "providers": {
                    provider: {
                        "enabled": provider == self.config.provider or provider == "local",
                        "max_parallel_jobs": limit,
                        "polling_interval_seconds": 20,
                        "profile": self.config.profile,
                        "retry_limit": self.config.max_attempts,
                        "timeout_minutes": 45,
                    }
                    for provider, limit in self.config.provider_parallel_limits.items()
                },
                "cache": {
                    "enabled": True,
                    "local": {"enabled": True},
                    "shared": {"enabled": False},
                    "validation_cache": {"enabled": True},
                    "composition_cache": {"enabled": False},
                },
                "retry": {
                    "maximum_attempts": self.config.max_attempts,
                    "exponential_backoff": True,
                    "multiplier": 2,
                    "maximum_delay_seconds": 60,
                    "retryable_errors": ["timeout", "rate_limit", "temporary_network"],
                },
                "polling": {
                    "initial_seconds": 1,
                    "maximum_seconds": 20,
                    "multiplier": 2,
                    "jitter_ratio": 0,
                },
                "validation": {
                    "technical": {"enabled": True},
                    "cinematic": {"enabled": True},
                    "continuity": {"enabled": True},
                    "fail_fast": True,
                },
                "composition": {
                    "ffmpeg": {
                        "parallel_jobs": 1,
                        "hardware_acceleration": "auto",
                        "preserve_intermediate_files": False,
                        "temporary_directory": "runtime/tmp",
                    }
                },
                "budget": {
                    "estimate_before_submission": self.config.estimate_before_submission,
                    "stop_on_budget_exceeded": True,
                    "preview": {"maximum_usd": self.config.budget_usd},
                    "production": {"maximum_usd": self.config.budget_usd},
                },
                "telemetry": {
                    "metrics": {"enabled": True},
                    "structured_logs": {"enabled": True},
                    "tracing": {"enabled": False},
                    "performance_reports": {"enabled": True},
                },
                "recovery": {
                    "automatic_resume": False,
                    "checkpoint_interval": "every_stage",
                    "verify_assets_before_resume": True,
                },
            },
        }
        base_inputs = self._artifact_inputs(
            manifest, "shot_list", "storyboard", "render_strategy"
        )
        self._store_many(
            manifest,
            {
                "performance_budget": performance_budget,
                "dependency_graph": dependency_graph,
                "build_profile": build_profile,
                "performance_config": performance_config,
            },
            inputs=base_inputs,
            generator="performance-planner",
        )
        estimated_cost = float(
            manifest.get("metrics", {}).get("planning", {}).get(
                "estimated_provider_cost_usd", 0.0
            )
        )
        execution_plan = {
            "schema_version": "2.0",
            "build_id": manifest["build_id"],
            "build_type": build_type,
            "pipeline_version": "2.0",
            "dependency_graph_ref": content_hash(dependency_graph),
            "estimated_cost_usd": estimated_cost,
            "shots": [
                {
                    "shot_id": shot_id,
                    "render_strategy": "render",
                    "provider_profile": self.config.profile,
                }
                for shot_id in shot_ids
            ],
            "cached_assets": [],
            "render_queue": [
                {"shot_id": shot_id, "provider_profile": self.config.profile}
                for shot_id in shot_ids
            ],
            "validation_queue": shot_ids,
            "composition_plan": {
                "ordered_shots": shot_ids,
                "target_duration": sum(
                    float(frame["duration_seconds"]) for frame in frames
                ),
            },
        }
        execution_document = self.repository.store_artifact(
            manifest,
            ArtifactEnvelope(
                artifact_type="execution_plan",
                build_id=manifest["build_id"],
                data=execution_plan,
                input_hashes=(
                    *base_inputs,
                    manifest["artifacts"]["architecture_contract"]["content_hash"],
                    manifest["artifacts"]["architecture_validation_report"][
                        "content_hash"
                    ],
                    manifest["artifacts"]["dependency_graph"]["content_hash"],
                    manifest["artifacts"]["performance_budget"]["content_hash"],
                    manifest["artifacts"]["performance_config"]["content_hash"],
                ),
                generator="performance-planner",
            ),
        )
        operational_state = {
            "schema_version": "2.0",
            "build_id": manifest["build_id"],
            "artifact_ref": execution_document["content_hash"],
            "state": "VALIDATED",
            "owner": "Build Orchestrator",
            "transitions_logged": True,
            "transitions": [
                {
                    "previous_state": "CREATED",
                    "new_state": "VALIDATED",
                    "timestamp": DETERMINISTIC_TIME,
                }
            ],
        }
        self.repository.store_artifact(
            manifest,
            ArtifactEnvelope(
                artifact_type="operational_state",
                build_id=manifest["build_id"],
                data=operational_state,
                input_hashes=(execution_document["content_hash"],),
                generator="performance-planner",
            ),
        )

    def _persona_provider(self) -> PersonaCouncilProvider:
        if self._persona_provider_override is not None:
            return self._persona_provider_override
        from .providers.openai_persona import OpenAIAgentsPersonaProvider

        return OpenAIAgentsPersonaProvider(self.config)

    def _store_planning_foundation(
        self,
        manifest: dict[str, Any],
        *,
        article_data: dict[str, Any],
        source_hash: str,
        architecture: dict[str, dict[str, Any]],
        creative_brief_data: dict[str, Any] | None,
        creative_brief_hash: str | None,
    ) -> dict[str, Any]:
        if "structured_article" in manifest.get("artifacts", {}):
            article_document = self.repository.load_artifact(
                manifest, "structured_article"
            )
        else:
            article_document = self.repository.store_artifact(
                manifest,
                ArtifactEnvelope(
                    artifact_type="structured_article",
                    build_id=manifest["build_id"],
                    data=article_data,
                    input_hashes=(source_hash,),
                    generator="article-loader",
                ),
            )
        if creative_brief_data is not None and "creative_brief" not in manifest.get(
            "artifacts", {}
        ):
            self.repository.store_artifact(
                manifest,
                ArtifactEnvelope(
                    artifact_type="creative_brief",
                    build_id=manifest["build_id"],
                    data=creative_brief_data,
                    input_hashes=(str(creative_brief_hash),),
                    generator="creative-brief-loader",
                ),
            )
        if "architecture_contract" not in manifest.get("artifacts", {}):
            self.repository.store_artifact(
                manifest,
                ArtifactEnvelope(
                    artifact_type="architecture_contract",
                    build_id=manifest["build_id"],
                    data=architecture["architecture_contract"],
                    input_hashes=(),
                    generator="architecture-registry",
                ),
            )
            architecture_report = architecture["architecture_validation_report"]
            self.repository.store_artifact(
                manifest,
                ArtifactEnvelope(
                    artifact_type="architecture_validation_report",
                    build_id=manifest["build_id"],
                    data=architecture_report,
                    input_hashes=self._artifact_inputs(
                        manifest, "architecture_contract"
                    ),
                    generator="architecture-validator",
                ),
            )
            if not architecture_report["passed"]:
                raise QualityGateError(
                    "Architecture Conformance Gate failed",
                    details=architecture_report,
                )
            manifest["gates"]["architecture_conformance_gate"] = {
                "gate_id": "architecture_conformance_gate",
                "passed": True,
                "decision": "PASS",
                "blocking": True,
                "fail_closed": True,
                "check_count": architecture_report["check_count"],
                "contract_content_hash": architecture_report[
                    "contract_content_hash"
                ],
                "report_content_hash": manifest["artifacts"][
                    "architecture_validation_report"
                ]["content_hash"],
            }
            self.repository.record_event(
                manifest,
                "architecture_validated",
                {
                    "contract_version": architecture_report["contract_version"],
                    "check_count": architecture_report["check_count"],
                },
            )
        return article_document

    def _run_persona_council(
        self,
        manifest: dict[str, Any],
        *,
        article_data: dict[str, Any],
        article_hash: str,
        creative_brief_data: dict[str, Any],
        creative_brief_hash: str,
    ) -> dict[str, Any]:
        key = deliberation_key(
            article_hash=article_hash,
            creative_brief_hash=creative_brief_hash,
            model=self.config.persona_model,
            reasoning_effort=self.config.persona_reasoning_effort,
            manager_agent_version=self.config.persona_manager_agent_version,
            prompt_version=self.config.persona_prompt_version,
            policy_version=self.config.persona_policy_version,
        )
        request = PersonaCouncilRequest(
            build_id=manifest["build_id"],
            article_hash=article_hash,
            creative_brief_hash=creative_brief_hash,
            article=article_data,
            creative_brief=creative_brief_data,
            deliberation_key=key,
            model=self.config.persona_model,
            reasoning_effort=self.config.persona_reasoning_effort,
            max_output_tokens=self.config.persona_max_output_tokens,
            timeout_seconds=self.config.persona_timeout_seconds,
            manager_agent_version=self.config.persona_manager_agent_version,
            prompt_version=self.config.persona_prompt_version,
            policy_version=self.config.persona_policy_version,
        )
        self.repository.record_event(
            manifest,
            "persona_council.requested",
            {"deliberation_key": key},
        )
        service = PersonaCouncilService(
            provider=self._persona_provider(),
            cache=PersonaCouncilCache(self.repository.root / "persona-cache"),
            max_input_bytes=self.config.persona_max_input_bytes,
            preflight_estimated_cost_usd=self.config.persona_preflight_estimated_cost_usd,
            max_cost_usd=self.config.persona_max_cost_usd,
        )
        started = perf_counter()
        artifacts = service.run(request)
        latency_ms = round((perf_counter() - started) * 1000, 3)
        identity_fields = {
            "persona-proposals": "deliberation_key",
            "persona-red-team-report": "report_id",
            "persona-deliberation": "deliberation_id",
            "persona": "persona_id",
            "persona-quality-report": "report_id",
        }
        for artifact_type, document in artifacts.items():
            self.repository.store_sealed_document(
                manifest,
                artifact_type=artifact_type,
                document=document,
                artifact_id=str(document[identity_fields[artifact_type]]),
            )
        quality = artifacts["persona-quality-report"]
        manifest["persona_council"] = {
            "mode": "council",
            "status": quality["status"],
            "deliberation_key": key,
            "persona_content_hash": artifacts["persona"]["content_hash"],
            "quality_report_content_hash": quality["content_hash"],
            "approval_binding_content_hash": None,
            "model_requested": self.config.persona_model,
            "model_resolved": artifacts["persona"]["agent_provenance"][
                "models_by_role"
            ]["persona_manager"],
            "cache_hit": service.last_cache_hit,
        }
        manifest, _ = self._record_quality_gate(
            manifest,
            gate_id="persona_quality_gate",
            projection={
                "gate_id": "persona_quality_gate",
                "passed": quality["status"] == "PASS",
                "decision": quality["status"],
                "blocking": True,
                "fail_closed": True,
                "report_content_hash": quality["content_hash"],
            },
            checks={
                check["check_id"]: check["passed"]
                for check in quality["checks"]
            },
            evidence_types=(
                "persona-proposals",
                "persona-red-team-report",
                "persona-deliberation",
                "persona",
                "persona-quality-report",
            ),
        )
        manifest.setdefault("metrics", {})["persona_council"] = {
            "proposal_count": 3,
            "specialist_invocation_count": 5,
            "cache_hit": service.last_cache_hit,
            "latency_ms": latency_ms,
            "estimated_cost_usd": artifacts["persona-proposals"]["usage"][
                "estimated_cost_usd"
            ],
        }
        self.repository.record_event(
            manifest,
            "persona_council.cache_hit" if service.last_cache_hit else "persona_council.completed",
            {
                "deliberation_key": key,
                "persona_content_hash": artifacts["persona"]["content_hash"],
                "quality_report_content_hash": quality["content_hash"],
                "latency_ms": latency_ms,
            },
        )
        manifest = self.repository.save(manifest)
        manifest = self.repository.transition(
            manifest,
            BuildState.AWAITING_PERSONA_APPROVAL,
            "persona_quality_evidence_sealed",
        )
        return manifest

    def _approved_persona_context(self, manifest: dict[str, Any]) -> dict[str, Any]:
        documents = {
            name: self.repository.load_artifact(manifest, name)
            for name in PERSONA_NAMES
        }
        validate_persona_bundle(documents)
        return {
            "persona": documents["persona"],
            "persona_quality_report": documents["persona-quality-report"],
            "persona_approval_binding": documents["persona-approval-binding"],
            "creative_brief_hash": documents["persona"]["creative_brief_hash"],
        }

    def plan(
        self,
        article_path: Path | str,
        *,
        creative_brief_path: Path | str | None = None,
    ) -> dict[str, Any]:
        article = load_article(Path(article_path))
        architecture = architecture_artifacts()
        persona_mode = self.config.story.persona_mode
        if persona_mode == "council" and creative_brief_path is None:
            raise ValidationError("Council mode requires an explicit Creative Brief")
        if persona_mode == "off" and creative_brief_path is not None:
            raise ValidationError("Creative Brief is accepted only in council mode")
        creative_brief = (
            load_creative_brief(Path(creative_brief_path))
            if creative_brief_path is not None
            else None
        )
        creative_brief_hash = (
            creative_brief.content_hash if creative_brief is not None else None
        )
        persona_article_hash = StoryEngine.article_hash(article)
        source_hash = content_hash(
            {"title": article.title, "body": article.body, "metadata": article.metadata}
        )
        config_snapshot = self._config_snapshot()
        build_identity = content_hash(
            {
                "source_hash": source_hash,
                "profile": self.config.profile,
                "configuration_hash": content_hash(config_snapshot),
                "planning_contract": "3.3.0",
                "agent_review_mode": self.config.agent_review_mode,
                "persona_mode": persona_mode,
                "creative_brief_hash": creative_brief_hash,
                "architecture_contract_hash": content_hash(
                    architecture["architecture_contract"]
                ),
            }
        )
        existing = self.repository.find_by_identity(build_identity)
        build_id = existing["build_id"] if existing else self.repository.next_build_id()
        manifest = self.repository.create(
            build_id,
            {
                "article_id": article.article_id,
                "content_hash": source_hash,
                "build_identity": build_identity,
                "source_path": article.source_path,
                "creative_brief_hash": creative_brief_hash,
            },
            self.config.profile,
            config_snapshot,
        )
        state = BuildState(manifest["state"])
        if state == BuildState.AWAITING_PERSONA_APPROVAL:
            self.repository.verify_artifacts(manifest)
            if "persona-approval-binding" not in manifest.get("artifacts", {}):
                return self._view(manifest)
            self._approved_persona_context(manifest)
            manifest = self.repository.transition(
                manifest, BuildState.PLANNING, "persona_approval_verified"
            )
            state = BuildState.PLANNING
        if state not in {
            BuildState.CREATED,
            BuildState.PERSONA_PLANNING,
            BuildState.PLANNING,
        }:
            self.repository.verify_artifacts(manifest)
            return self._view(manifest)
        if state == BuildState.CREATED:
            manifest = self.repository.transition(
                manifest,
                (
                    BuildState.PERSONA_PLANNING
                    if persona_mode == "council"
                    else BuildState.PLANNING
                ),
                (
                    "persona_planning_started"
                    if persona_mode == "council"
                    else "planning_started"
                ),
            )
        try:
            article_data = {
                "article_id": article.article_id,
                "title": article.title,
                "subtitle": article.subtitle,
                "body": article.body,
                "metadata": article.metadata,
                "references": list(article.references),
            }
            article_document = self._store_planning_foundation(
                manifest,
                article_data=article_data,
                source_hash=source_hash,
                architecture=architecture,
                creative_brief_data=(
                    creative_brief.data if creative_brief is not None else None
                ),
                creative_brief_hash=creative_brief_hash,
            )
            if BuildState(manifest["state"]) == BuildState.PERSONA_PLANNING:
                if creative_brief is None or creative_brief_hash is None:
                    raise ValidationError("Council mode Creative Brief is unavailable")
                manifest = self._run_persona_council(
                    manifest,
                    article_data=article_data,
                    article_hash=persona_article_hash,
                    creative_brief_data=creative_brief.data,
                    creative_brief_hash=creative_brief_hash,
                )
                return self._view(manifest)
            persona_context = (
                self._approved_persona_context(manifest)
                if persona_mode == "council"
                else None
            )
            story_settings = self.config.story
            story = StoryEngine(
                config=StoryConfig(
                    profile=("draft" if self.config.profile == "draft" else "canonical"),
                    genre=story_settings.genre,
                    audience=story_settings.audience,
                    duration_seconds=(
                        story_settings.draft_duration_seconds
                        if self.config.profile == "draft"
                        else story_settings.canonical_duration_seconds
                    ),
                    supporting_role_max=self.config.supporting_role_max,
                    concept_ratio_max=self.config.concept_ratio_max,
                    dramatic_score_min=story_settings.dramatic_score_min,
                    conflict_score_min=story_settings.conflict_score_min,
                    stakes_score_min=story_settings.stakes_score_min,
                    emotional_progression_min=story_settings.emotional_progression_min,
                    author_style=story_settings.author_style,
                    persona_mode=story_settings.persona_mode,
                ),
                cache=StoryCache(self.repository.root / "story-cache"),
            ).generate(article, persona_context=persona_context)
            story_input_types = ["structured_article"]
            if persona_context is not None:
                story_input_types.extend(
                    [
                        "creative_brief",
                        "persona",
                        "persona-quality-report",
                        "persona-approval-binding",
                    ]
                )
            self._store_many(
                manifest,
                story,
                inputs=self._artifact_inputs(manifest, *story_input_types),
                generator="story-engine",
            )
            story_report = story["story_quality_report"]
            if not creative_gate_passed(story_report):
                raise QualityGateError("Story Quality Gate failed", details=story_report)
            manifest, _ = self._record_quality_gate(
                manifest,
                gate_id="story_quality_gate",
                projection=story_report,
                checks=story_report["checks"],
                evidence_types=(
                    "structured_article",
                    "dramatic_premise",
                    "dramatic_question",
                    "character_bible",
                    "conflict",
                    "stakes",
                    "time_pressure",
                    "story_arc",
                    "three_act_structure",
                    "emotional_arc",
                    "concept_placement",
                    "story_metrics",
                    "story_config",
                ),
            )

            screenplay = self.config.screenplay
            screenplay_artifacts = ScreenplayEngine(
                config=ScreenplayConfig(
                    profile=(
                        "production" if self.config.profile == "final" else "preview"
                    ),
                    scene_count_min=screenplay.scene_count_min,
                    scene_count_max=screenplay.scene_count_max,
                    scene_duration_min=screenplay.scene_duration_min,
                    scene_duration_target=screenplay.scene_duration_target,
                    scene_duration_max=screenplay.scene_duration_max,
                    words_per_line=screenplay.words_per_line,
                    lines_per_turn=screenplay.lines_per_turn,
                    exposition_allowed=screenplay.exposition_allowed,
                    silence_allowed=screenplay.silence_allowed,
                    all_dimensions_checked=screenplay.all_dimensions_checked,
                    violation_fails_validation=screenplay.violation_fails_validation,
                    fountain=screenplay.fountain,
                    json=screenplay.json,
                    custom_syntax=screenplay.custom_syntax,
                ),
                cache=ScreenplayCache(self.repository.root / "screenplay-cache"),
            ).generate(story)
            self._store_many(
                manifest,
                screenplay_artifacts,
                inputs=self._artifact_inputs(
                    manifest,
                    "dramatic_premise",
                    "character_bible",
                    "three_act_structure",
                ),
                generator="screenplay-engine",
            )
            screenplay_report = screenplay_artifacts["screenplay_quality_report"]
            if not creative_gate_passed(screenplay_report):
                raise QualityGateError(
                    "Screenplay Quality Gate failed", details=screenplay_report
                )
            manifest, _ = self._record_quality_gate(
                manifest,
                gate_id="screenplay_quality_gate",
                projection=screenplay_report,
                checks=screenplay_report["checks"],
                evidence_types=(
                    "screenplay",
                    "scene_index",
                    "dialogue",
                    "continuity",
                    "screenplay_config",
                    "screenplay_state",
                    "story_quality_report",
                ),
            )

            shot_artifacts = ShotPlanner().generate(
                screenplay_artifacts["screenplay"], story["character_bible"]
            )
            self._store_many(
                manifest,
                shot_artifacts,
                inputs=self._artifact_inputs(manifest, "screenplay", "character_bible"),
                generator="shot-planner",
            )
            for gate_id in ("shot_quality_gate", "storyboard_quality_gate"):
                report_type = (
                    "shot_gate_report" if gate_id == "shot_quality_gate" else "storyboard_gate_report"
                )
                report = shot_artifacts[report_type]
                if not creative_gate_passed(report):
                    raise QualityGateError(f"{gate_id} failed", details=report)
                manifest, _ = self._record_quality_gate(
                    manifest,
                    gate_id=gate_id,
                    projection=report,
                    checks=report["checks"],
                    evidence_types=(
                        "shot_list",
                        "storyboard",
                        "continuity_report",
                        "render_strategy",
                    ),
                )
            planned_shots = shot_artifacts["shot_list"]["shots"]
            expensive_shots = sum(
                uses_runway(self.config, shot) for shot in planned_shots
            )
            estimated_runway_credits = runway_credit_estimate(
                self.config, planned_shots
            )
            manifest["metrics"]["planning"] = {
                "shot_count": len(planned_shots),
                "provider_render_shot_count": expensive_shots,
                "estimated_runway_credits": estimated_runway_credits,
                "runway_credit_limit": self.config.max_runway_credits,
                "estimated_provider_cost_usd": round(
                    estimated_runway_credits * RUNWAY_CREDIT_USD, 2
                ),
                "render_budget_usd": self.config.budget_usd,
            }
            self._store_performance_plan(manifest, shot_artifacts)

            self.repository.store_artifact(
                manifest,
                ArtifactEnvelope(
                    artifact_type="quality_gate_registry",
                    build_id=build_id,
                    data=registry_document(),
                    input_hashes=(),
                    generator="quality-gate-registry",
                ),
            )
            self.repository.record_event(
                manifest,
                "planning_completed",
                {"planning_artifact_count": len(PLANNING_ARTIFACTS)},
            )
            manifest["agent_review"] = {
                "mode": self.config.agent_review_mode,
                "status": (
                    AgentReviewStatus.DISABLED.value
                    if self.config.agent_review_mode == "off"
                    else AgentReviewStatus.PENDING.value
                ),
                "review_key": None,
                "report_ref": None,
                "report_content_hash": None,
                "agent_contract_version": "agent-review/1",
                "agent_version": self.config.agent_review_agent_version,
                "prompt_version": self.config.agent_review_prompt_version,
                "policy_version": self.config.agent_review_policy_version,
                "model_requested": self.config.agent_review_model,
                "model_resolved": None,
                "cache_hit": False,
            }
            manifest = self.repository.save(manifest)
            manifest = self.repository.transition(
                manifest, BuildState.PLANNED, "all_planning_gates_passed"
            )
            if self.config.agent_review_mode == "off":
                manifest["gates"]["agent_review_gate"] = {
                    "gate_id": "agent_review_gate",
                    "passed": None,
                    "decision": "NOT_APPLICABLE",
                    "blocking": False,
                    "fail_closed": True,
                }
                manifest = self.repository.save(manifest)
                manifest = self.repository.transition(
                    manifest,
                    BuildState.AWAITING_EXECUTION_APPROVAL,
                    "agent_review_not_applicable",
                )
                manifest = self._checkpoint(
                    manifest, "planning-complete", clean=True
                )
            return self._view(manifest)
        except Exception:
            current = BuildState(manifest["state"])
            if BuildState.FAILED in self.repository.LEGAL_TRANSITIONS[current]:
                self.repository.record_event(manifest, "planning_failed")
                self.repository.transition(manifest, BuildState.FAILED, "planning_failure")
            raise

    def _agent_review_provider(self) -> AgentReviewProvider:
        if self._review_provider_override is not None:
            return self._review_provider_override
        from .providers.openai_agents import OpenAIAgentsReviewProvider

        return OpenAIAgentsReviewProvider(self.config)

    def review(self, build_id: str) -> dict[str, Any]:
        manifest = self.repository.load(build_id)
        review_projection = manifest.get("agent_review", {})
        if review_projection.get("mode") != "review":
            raise StateConflictError("Build was not planned for Agent Review Mode")
        if self.config.agent_review_mode != "review":
            raise StateConflictError(
                "Agent Review command requires INSYNERGY_AGENT_REVIEW_MODE=review"
            )
        state = BuildState(manifest["state"])
        if (
            state == BuildState.AWAITING_EXECUTION_APPROVAL
            and review_projection.get("report_content_hash")
        ):
            self.repository.verify_artifacts(manifest)
            return self._view(manifest)
        if state != BuildState.PLANNED:
            raise StateConflictError(f"Build cannot run Agent Review from {state.value}")
        self.repository.verify_artifacts(manifest)
        request = build_review_request(manifest, self.repository, self.config)
        self.repository.record_event(
            manifest,
            "agent_review.requested",
            {"review_key": request.review_key},
        )
        service = AgentReviewService(
            config=self.config,
            store=AgentReviewStore(self.repository.root / "agent-review-cache"),
            provider=self._agent_review_provider(),
        )
        review_started = perf_counter()
        report, cache_hit = service.run(request)
        review_latency_ms = round((perf_counter() - review_started) * 1000, 3)
        validate_agent_review_report(report, request)
        self.repository.store_sealed_document(
            manifest,
            artifact_type="agent_review_report",
            document=report,
            artifact_id=report["review_id"],
        )
        manifest["agent_review"] = {
            "mode": "review",
            "status": report["status"],
            "review_key": report["review_key"],
            "report_ref": "artifact://agent_review_report",
            "report_content_hash": report["content_hash"],
            "reviewed_input_hashes": report["inputs"],
            "agent_contract_version": report["contract_version"],
            "agent_version": report["agent"]["agent_version"],
            "prompt_version": report["agent"]["prompt_version"],
            "policy_version": self.config.agent_review_policy_version,
            "model_requested": report["agent"]["model_requested"],
            "model_resolved": report["agent"]["model_resolved"],
            "trace_ref": report["agent"].get("trace_id"),
            "cache_hit": cache_hit,
        }
        manifest["configuration"]["agent_review"] = self._config_snapshot()[
            "agent_review"
        ]
        status = report["status"]
        manifest["gates"]["agent_review_gate"] = {
            "gate_id": "agent_review_gate",
            "passed": status == AgentReviewStatus.PASS.value,
            "decision": status,
            "report_content_hash": report["content_hash"],
            "review_key": report["review_key"],
            "blocking": status != AgentReviewStatus.PASS.value,
            "fail_closed": True,
        }
        event_payload = {
            "review_key": report["review_key"],
            "report_content_hash": report["content_hash"],
            "status": status,
            "latency_ms": review_latency_ms,
            "provider_latency_ms": 0 if cache_hit else review_latency_ms,
            "usage": report["usage"],
        }
        if cache_hit:
            self.repository.record_event(
                manifest, "agent_review.cache_hit", event_payload
            )
        else:
            self.repository.record_event(
                manifest, "agent_review.submitted", event_payload
            )
            self.repository.record_event(
                manifest,
                (
                    "agent_review.failed"
                    if status
                    in {
                        AgentReviewStatus.UNAVAILABLE.value,
                        AgentReviewStatus.ERROR.value,
                    }
                    else "agent_review.completed"
                ),
                event_payload,
            )
        if status != AgentReviewStatus.PASS.value:
            self.repository.record_event(
                manifest,
                "agent_review.held",
                {
                    "status": status,
                    "error_class": (report.get("error") or {}).get("class"),
                },
            )
        manifest = self.repository.save(manifest)
        manifest = self.repository.transition(
            manifest,
            BuildState.AWAITING_EXECUTION_APPROVAL,
            "agent_review_evidence_sealed",
        )
        manifest = self._checkpoint(manifest, "planning-complete", clean=True)
        return self._view(manifest)

    @staticmethod
    def _planning_hash(manifest: dict) -> str:
        execution_plan = manifest.get("artifacts", {}).get("execution_plan")
        if execution_plan:
            return str(execution_plan["content_hash"])
        artifacts = {
            artifact_type: reference["content_hash"]
            for artifact_type, reference in manifest.get("artifacts", {}).items()
            if artifact_type in PLANNING_ARTIFACTS
        }
        if not artifacts:
            raise ValidationError("Build has no planning artifacts")
        return content_hash(artifacts)

    def _approve_persona(
        self,
        manifest: dict[str, Any],
        *,
        actor: str,
        decision: ApprovalDecision,
        comment: str,
        workflow_initiator: str | None,
        environment_reviewer: str | None,
        prevent_self_review: bool,
        environment_review_hash: str | None,
    ) -> dict[str, Any]:
        if BuildState(manifest["state"]) != BuildState.AWAITING_PERSONA_APPROVAL:
            raise StateConflictError(
                f"persona approval is invalid while build is {manifest['state']}"
            )
        existing = manifest.get("approvals", {}).get("persona")
        if existing and existing.get("decision") == ApprovalDecision.APPROVED.value:
            self.repository.verify_artifacts(manifest)
            return self._view(manifest)
        preapproval = {
            name: self.repository.load_artifact(manifest, name)
            for name in PERSONA_NAMES
            if name != "persona-approval-binding"
        }
        report = validate_persona_preapproval_bundle(preapproval)
        if report["status"] != "PASS" and decision == ApprovalDecision.APPROVED:
            raise ApprovalRequiredError(
                "Persona Quality Gate must PASS before human approval"
            )
        persona = preapproval["persona"]
        quality = preapproval["persona-quality-report"]
        deliberation = preapproval["persona-deliberation"]
        initiator = (workflow_initiator or actor).strip()
        reviewer = (environment_reviewer or actor).strip()
        github_review_context = any(
            value is not None
            for value in (
                workflow_initiator,
                environment_reviewer,
                environment_review_hash,
            )
        )
        if not initiator or not reviewer:
            raise ValidationError("Persona approval identities are required")
        if actor.casefold() != reviewer.casefold():
            raise ValidationError(
                "Persona approval actor must match the Environment reviewer"
            )
        if github_review_context:
            if not workflow_initiator or not environment_reviewer:
                raise ValidationError(
                    "GitHub Persona approval requires initiator and reviewer"
                )
            if (
                not environment_review_hash
                or not environment_review_hash.startswith("sha256:")
                or len(environment_review_hash) != 71
                or any(
                    character not in "0123456789abcdef"
                    for character in environment_review_hash.removeprefix("sha256:")
                )
            ):
                raise ValidationError(
                    "GitHub Persona approval requires a valid review history hash"
                )
        if prevent_self_review and initiator.casefold() == reviewer.casefold():
            raise ValidationError("Persona Environment self-review is prohibited")
        approved_at = now_iso()
        approval_identity = {
            "build_id": manifest["build_id"],
            "workflow_initiator": initiator,
            "environment_reviewer": reviewer,
            "environment_review_hash": environment_review_hash,
            "decision": decision.value,
            "article_hash": persona["article_hash"],
            "creative_brief_hash": persona["creative_brief_hash"],
            "persona_hash": persona["content_hash"],
            "quality_report_hash": quality["content_hash"],
            "deliberation_hash": deliberation["content_hash"],
        }
        approval_id = f"PAB-{content_hash(approval_identity).removeprefix('sha256:')[:20]}"
        record = ApprovalRecord(
            approval_id=approval_id,
            build_id=manifest["build_id"],
            gate="persona",
            decision=decision,
            actor=actor,
            artifact_hash=persona["content_hash"],
            approved_at=approved_at,
            comment=comment,
        )
        manifest["approvals"]["persona"] = record.as_dict()
        if decision == ApprovalDecision.APPROVED:
            binding = {
                "schema_version": "3.3.0",
                "contract_version": "persona-approval/2",
                "approval_id": approval_id,
                "build_id": manifest["build_id"],
                "approver": reviewer,
                "workflow_initiator": initiator,
                "environment_reviewer": reviewer,
                "prevent_self_review": prevent_self_review,
                "decision": "APPROVED",
                "approved_at": approved_at,
                "article_hash": persona["article_hash"],
                "creative_brief_hash": persona["creative_brief_hash"],
                "persona_hash": persona["content_hash"],
                "quality_report_hash": quality["content_hash"],
                "deliberation_hash": deliberation["content_hash"],
                "deliberation_contract_version": deliberation[
                    "contract_version"
                ],
                "policy_version": quality["policy_version"],
            }
            if environment_review_hash:
                binding["environment_review_hash"] = environment_review_hash
            if comment.strip():
                binding["rationale"] = comment.strip()
            binding["content_hash"] = content_hash(binding)
            self.repository.store_sealed_document(
                manifest,
                artifact_type="persona-approval-binding",
                document=binding,
                artifact_id=approval_id,
            )
            validate_persona_bundle(
                {
                    **preapproval,
                    "persona-approval-binding": binding,
                }
            )
            manifest["persona_council"][
                "approval_binding_content_hash"
            ] = binding["content_hash"]
        manifest["gates"]["persona_approval"] = {
            "gate_id": "persona_approval",
            "passed": decision == ApprovalDecision.APPROVED,
            "decision": decision.value,
            "approval_ref": approval_id,
            "artifact_hash": persona["content_hash"],
            "workflow_initiator": initiator,
            "environment_reviewer": reviewer,
            "prevent_self_review": prevent_self_review,
            "blocking": True,
            "fail_closed": True,
        }
        self.repository.record_approval_audit(
            manifest,
            gate="persona",
            state=decision.value,
            actor=actor,
            approval_ref=approval_id,
            artifact_hash=persona["content_hash"],
            rationale=comment or "recorded Persona human decision",
        )
        self.repository.record_event(
            manifest,
            "persona_approval_recorded",
            {
                "decision": decision.value,
                "workflow_initiator": initiator,
                "environment_reviewer": reviewer,
                "prevent_self_review": prevent_self_review,
                "persona_content_hash": persona["content_hash"],
            },
        )
        manifest = self.repository.save(manifest)
        return self._view(manifest)

    def approve(
        self,
        build_id: str,
        *,
        gate: str,
        actor: str,
        decision: str = "APPROVED",
        comment: str = "",
        allow_agent_exception: bool = False,
        agent_exception_reason: str = "",
        workflow_initiator: str | None = None,
        environment_reviewer: str | None = None,
        prevent_self_review: bool = False,
        environment_review_hash: str | None = None,
    ) -> dict[str, Any]:
        if gate not in {"persona", "execution", "publish"}:
            raise ValidationError("Approval gate must be persona, execution, or publish")
        if not actor.strip():
            raise ValidationError("Approval actor is required")
        try:
            approval_decision = ApprovalDecision(decision.upper())
        except ValueError as exc:
            raise ValidationError("Approval decision must be APPROVED or REJECTED") from exc
        manifest = self.repository.load(build_id)
        if gate == "persona":
            return self._approve_persona(
                manifest,
                actor=actor,
                decision=approval_decision,
                comment=comment,
                workflow_initiator=workflow_initiator,
                environment_reviewer=environment_reviewer,
                prevent_self_review=prevent_self_review,
                environment_review_hash=environment_review_hash,
            )
        state = BuildState(manifest["state"])
        review_mode = "off"
        review_report_hash: str | None = None
        review_disposition: str | None = None
        exception_code: str | None = None
        exception_rationale: str | None = None
        agent_policy_version: str | None = None
        if gate == "execution":
            expected = BuildState.AWAITING_EXECUTION_APPROVAL
            artifact_hash = self._planning_hash(manifest)
            (
                review_mode,
                review_report_hash,
                review_disposition,
                exception_code,
                exception_rationale,
            ) = self._execution_review_context(
                manifest,
                decision_approved=approval_decision == ApprovalDecision.APPROVED,
                permit_exception=(
                    approval_decision == ApprovalDecision.APPROVED
                    and allow_agent_exception
                ),
                exception_reason=agent_exception_reason,
            )
            if review_mode == "review":
                agent_policy_version = str(
                    (manifest.get("agent_review") or {}).get("policy_version", "")
                )
                if not agent_policy_version:
                    raise ApprovalRequiredError("Agent Review policy version is missing")
        else:
            if state == BuildState.READY:
                self.repository.record_approval_audit(
                    manifest,
                    gate="publish",
                    state="REQUESTED",
                    actor=actor,
                    approval_ref=None,
                    artifact_hash=file_hash(
                        self.repository.build_dir(build_id) / "output" / "master.mp4"
                    ),
                    rationale="publication approval requested",
                )
                manifest = self.repository.transition(
                    manifest,
                    BuildState.AWAITING_PUBLISH_APPROVAL,
                    "publish_approval_requested",
                )
                state = BuildState(manifest["state"])
            expected = BuildState.AWAITING_PUBLISH_APPROVAL
            master = self.repository.build_dir(build_id) / "output" / "master.mp4"
            if not master.exists():
                raise ValidationError("Master video is missing")
            artifact_hash = file_hash(master)
        if state != expected:
            raise StateConflictError(
                f"{gate} approval is invalid while build is {state.value}"
            )
        approval_identity = {
            "build_id": build_id,
            "gate": gate,
            "decision": approval_decision.value,
            "actor": actor,
            "artifact_hash": artifact_hash,
            "agent_review_report_hash": review_report_hash,
            "agent_disposition": review_disposition,
            "agent_exception_code": exception_code,
            "agent_exception_rationale": exception_rationale,
            "agent_policy_version": agent_policy_version,
        }
        approval_id = stable_id("approval", approval_identity)
        existing_approval = manifest.get("approvals", {}).get(gate)
        if (
            existing_approval
            and existing_approval.get("decision") == ApprovalDecision.APPROVED.value
        ):
            if gate == "execution":
                self._verify_execution_review_binding(manifest, existing_approval)
            self.repository.verify_artifacts(manifest)
            return self._view(manifest)
        record = ApprovalRecord(
            approval_id=approval_id,
            build_id=build_id,
            gate=gate,
            decision=approval_decision,
            actor=actor,
            artifact_hash=artifact_hash,
            approved_at=now_iso(),
            comment=comment,
            agent_review_mode=review_mode,
            agent_review_report_hash=review_report_hash,
            agent_disposition=review_disposition,
            agent_exception_code=exception_code,
            agent_exception_rationale=exception_rationale,
            agent_policy_version=agent_policy_version,
        )
        manifest["approvals"][gate] = record.as_dict()
        canonical_approval = {
            "schema_version": "2.0",
            "gate": "story_approval" if gate == "execution" else "final_approval",
            "outcome": approval_decision.value.casefold(),
            "position": "before_rendering" if gate == "execution" else "after_rendering",
            "confirms": (
                ["screenplay", "pacing", "dialogue", "dramatic_arc", "institutional_accuracy"]
                if gate == "execution"
                else [
                    "visual_quality",
                    "timing",
                    "branding",
                    "institutional_accuracy",
                    "publication_rights",
                    "child_safety",
                    "content_safety",
                    "publication_target",
                    "upstream_exceptions_reviewed",
                ]
            ),
            "gates": "rendering" if gate == "execution" else "packaging",
            "fail_closed": True,
            "approval_ref": record.approval_id,
        }
        self.repository.store_artifact(
            manifest,
            ArtifactEnvelope(
                artifact_type=f"approval_record_{record.approval_id}",
                build_id=build_id,
                data=canonical_approval,
                input_hashes=(artifact_hash,),
                generator="human-approval-gate",
                generated_at=record.approved_at,
                approved=approval_decision == ApprovalDecision.APPROVED,
                approval_ref=record.approval_id,
            ),
        )
        if gate == "execution" and approval_decision == ApprovalDecision.APPROVED:
            binding = {
                "schema_version": "2.1.0",
                "build_id": build_id,
                "gate": "story_approval",
                "approval_ref": record.approval_id,
                "mode": review_mode,
                "execution_plan_content_hash": artifact_hash,
                "agent_review_report_content_hash": review_report_hash,
                "agent_disposition": review_disposition,
                "bound_at": record.approved_at,
            }
            binding["content_hash"] = content_hash(binding)
            validate_review_approval_binding(binding)
            self.repository.store_sealed_document(
                manifest,
                artifact_type="review_approval_binding",
                document=binding,
                artifact_id=f"RAB-{record.approval_id}",
            )
            approved_inputs = tuple(
                value
                for value in (
                    artifact_hash,
                    review_report_hash,
                    binding["content_hash"],
                )
                if value is not None
            )
            for source_type, approved_type in (
                ("shot_list", "approved_shot_list"),
                ("storyboard", "approved_storyboard"),
            ):
                source = self.repository.load_artifact(manifest, source_type)
                approved_data = dict(source["data"])
                approved_data["approved"] = True
                approved_data["approval_ref"] = record.approval_id
                self.repository.store_artifact(
                    manifest,
                    ArtifactEnvelope(
                        artifact_type=approved_type,
                        build_id=build_id,
                        data=approved_data,
                        input_hashes=(source["content_hash"], *approved_inputs),
                        generator="human-approval-gate",
                        generated_at=record.approved_at,
                        approved=True,
                        approval_ref=record.approval_id,
                    ),
                )
        approval_projection = {
            "gate_id": f"{gate}_approval",
            "passed": approval_decision == ApprovalDecision.APPROVED,
            "decision": approval_decision.value,
            "approval_ref": record.approval_id,
            "artifact_hash": artifact_hash,
            "agent_review_report_hash": review_report_hash,
            "agent_disposition": review_disposition,
            "agent_exception_code": exception_code,
            "blocking": True,
            "fail_closed": True,
        }
        manifest["gates"][f"{gate}_approval"] = approval_projection
        self.repository.record_approval_audit(
            manifest,
            gate=gate,
            state=approval_decision.value,
            actor=actor,
            approval_ref=record.approval_id,
            artifact_hash=artifact_hash,
            rationale=comment or "recorded human decision",
        )
        approval_report = QualityGateEngine().evaluate(
            gate_id=f"{gate}_approval",
            build_id=build_id,
            checks={
                "human_decision_recorded": approval_decision
                == ApprovalDecision.APPROVED,
                "artifact_scope_matches": record.artifact_hash == artifact_hash,
                "actor_attributable": bool(actor.strip()),
                "approval_identity_bound": bool(record.approval_id),
            },
            artifact_refs=self._gate_evidence(
                manifest,
                f"approval_record_{record.approval_id}",
                "execution_plan" if gate == "execution" else "metadata",
            ),
        )
        manifest = self.repository.record_quality_report(manifest, approval_report)
        self.repository.record_event(
            manifest,
            "approval_recorded",
            {"gate": gate, "decision": approval_decision.value, "actor": actor},
        )
        manifest = self.repository.save(manifest)
        return self._view(manifest)

    def _execution_review_context(
        self,
        manifest: dict[str, Any],
        *,
        decision_approved: bool,
        permit_exception: bool,
        exception_reason: str,
    ) -> tuple[str, str | None, str | None, str | None, str | None]:
        projection = manifest.get("agent_review") or {"mode": "off"}
        mode = projection.get("mode", "off")
        if mode == "off":
            return "off", None, None, None, None
        if mode != "review":
            raise ApprovalRequiredError("Agent Review mode is invalid")
        reference = manifest.get("artifacts", {}).get("agent_review_report")
        if not reference:
            raise ApprovalRequiredError("Agent Review Report is required")
        report = self.repository.load_artifact(manifest, "agent_review_report")
        validation_request = build_report_validation_request(
            manifest, self.repository, report.get("review_key", "")
        )
        validate_agent_review_report(report, validation_request)
        if (
            report.get("build_id") != manifest["build_id"]
            or report.get("content_hash") != reference.get("content_hash")
            or report.get("content_hash") != projection.get("report_content_hash")
            or report.get("review_key") != projection.get("review_key")
            or report.get("status") != projection.get("status")
        ):
            raise ApprovalRequiredError("Agent Review evidence identity is invalid")
        input_groups = (
            [report["inputs"]["article"]],
            report["inputs"]["story_artifacts"],
            report["inputs"]["screenplay_artifacts"],
            [report["inputs"]["shot_list"]],
            [report["inputs"]["storyboard"]],
            report["inputs"]["quality_evidence"],
        )
        for group in input_groups:
            for evidence in group:
                current = manifest.get("artifacts", {}).get(evidence["artifact_type"])
                if not current or (
                    current.get("artifact_id") != evidence["artifact_id"]
                    or current.get("content_hash") != evidence["content_hash"]
                ):
                    raise ApprovalRequiredError(
                        "Planning evidence changed after Agent Review"
                    )
        disposition = report["status"]
        if disposition == AgentReviewStatus.PASS.value:
            return "review", report["content_hash"], disposition, None, None
        if not decision_approved:
            return "review", report["content_hash"], disposition, None, None
        if not permit_exception:
            raise ApprovalRequiredError(
                f"Agent Review disposition {disposition} requires an explicit human exception"
            )
        rationale = exception_reason.strip()
        if not rationale:
            raise ValidationError("Agent Review exception reason is required")
        error_class = (report.get("error") or {}).get("class")
        if disposition == AgentReviewStatus.ERROR.value and error_class not in WAIVABLE_ERROR_CLASSES:
            raise ApprovalRequiredError(
                f"Agent Review error class {error_class or 'UNKNOWN'} is non-waivable"
            )
        return (
            "review",
            report["content_hash"],
            disposition,
            (
                f"AGENT_REVIEW_{disposition}_{error_class}"
                if error_class
                else f"AGENT_REVIEW_{disposition}"
            ),
            rationale,
        )

    def _verify_execution_review_binding(
        self, manifest: dict[str, Any], approval: dict[str, Any]
    ) -> None:
        reference = manifest.get("artifacts", {}).get("review_approval_binding")
        if not reference:
            raise ApprovalRequiredError("Review Approval Binding is required")
        binding = self.repository.load_artifact(manifest, "review_approval_binding")
        validate_review_approval_binding(binding)
        expected_mode = (manifest.get("agent_review") or {}).get("mode", "off")
        expected_report_hash = (
            (manifest.get("agent_review") or {}).get("report_content_hash")
            if expected_mode == "review"
            else None
        )
        expected_disposition = (
            (manifest.get("agent_review") or {}).get("status")
            if expected_mode == "review"
            else None
        )
        if (
            binding["build_id"] != manifest["build_id"]
            or binding["approval_ref"] != approval.get("approval_id")
            or binding["mode"] != expected_mode
            or binding["execution_plan_content_hash"] != self._planning_hash(manifest)
            or binding["agent_review_report_content_hash"] != expected_report_hash
            or binding["agent_disposition"] != expected_disposition
            or approval.get("agent_review_mode", "off") != expected_mode
            or approval.get("agent_review_report_hash") != expected_report_hash
            or approval.get("agent_disposition") != expected_disposition
            or approval.get("agent_policy_version")
            != (
                (manifest.get("agent_review") or {}).get("policy_version")
                if expected_mode == "review"
                else None
            )
            or binding["bound_at"] != approval.get("approved_at")
        ):
            raise ApprovalRequiredError(
                "Execution approval is not bound to current review evidence"
            )
        if expected_mode == "review" and expected_disposition != AgentReviewStatus.PASS.value:
            if not approval.get("agent_exception_code") or not str(
                approval.get("agent_exception_rationale", "")
            ).strip():
                raise ApprovalRequiredError("Agent Review exception provenance is missing")
        expected_approval_id = stable_id(
            "approval",
            {
                "build_id": manifest["build_id"],
                "gate": "execution",
                "decision": approval.get("decision"),
                "actor": approval.get("actor"),
                "artifact_hash": approval.get("artifact_hash"),
                "agent_review_report_hash": approval.get("agent_review_report_hash"),
                "agent_disposition": approval.get("agent_disposition"),
                "agent_exception_code": approval.get("agent_exception_code"),
                "agent_exception_rationale": approval.get(
                    "agent_exception_rationale"
                ),
                "agent_policy_version": approval.get("agent_policy_version"),
            },
        )
        if approval.get("approval_id") != expected_approval_id:
            raise ApprovalRequiredError("Execution approval record identity is invalid")

    def _providers(self, manifest: dict) -> dict[str, Any]:
        local = LocalVideoProvider(self.repository.root / "providers" / "local")
        providers: dict[str, Any] = {"local": local}
        if self.config.provider == "runway":
            from .providers.runway import RunwayProvider

            providers["runway"] = RunwayProvider(
                base_url=self.config.runway_base_url or "",
                api_key=self.config.runway_api_key or "",
                model_id=self.config.runway_model or "",
                state_path=self.repository.root / "providers" / "runway" / "jobs.json",
            )
        return providers

    def _rendering_platform(self, manifest: dict) -> RenderingPlatform:
        return RenderingPlatform(
            config=self.config,
            build_root=self.repository.build_dir(manifest["build_id"]),
            provider_registry=self._providers(manifest),
            cache=RenderCache(self.repository.root / "render-cache", self.repository.cas),
            assembler=PromptAssembler(),
        )

    def _runtime_queue(self, manifest: dict[str, Any]) -> DurableTaskQueue:
        path = (
            self.repository.build_dir(manifest["build_id"])
            / "runtime"
            / "render-queue.json"
        )
        return DurableTaskQueue(
            path,
            build_id=manifest["build_id"],
            max_in_flight=self.config.max_in_flight_tasks,
            provider_limits=self.config.provider_parallel_limits,
            budget_usd=self.config.budget_usd,
        )

    def _checkpoint(
        self,
        manifest: dict[str, Any],
        stage: str,
        *,
        queue: DurableTaskQueue | None = None,
        clean: bool = False,
    ) -> dict[str, Any]:
        if not self.config.checkpoint_enabled:
            return manifest
        return self.repository.publish_checkpoint(
            manifest,
            stage,
            queue_snapshot=queue.snapshot() if queue and queue.path.exists() else None,
            clean=clean,
        )

    def execute(self, build_id: str) -> dict[str, Any]:
        manifest = self.repository.load(build_id)
        planned_config = dict(manifest.get("configuration", {}))
        runtime_config = self._config_snapshot()
        planned_config.pop("agent_review", None)
        runtime_config.pop("agent_review", None)
        if planned_config != runtime_config:
            raise StateConflictError(
                "Execution configuration does not match the immutable planning snapshot"
            )
        state = BuildState(manifest["state"])
        if state in {BuildState.READY, BuildState.AWAITING_PUBLISH_APPROVAL, BuildState.PUBLISHED}:
            self.repository.verify_artifacts(manifest)
            return self._view(manifest)
        if state not in {BuildState.AWAITING_EXECUTION_APPROVAL, BuildState.PAUSED}:
            raise StateConflictError(f"Build cannot execute from {state.value}")
        if state == BuildState.PAUSED:
            recovery = self.repository.recovery_plan(manifest)
            if recovery["outcome"] not in {"RESUME", "RECONCILE"}:
                raise StateConflictError(
                    "Build is not eligible for resume", details=recovery
                )
        if self.config.narration_provider == "openai" and not self.config.openai_tts_api_key:
            raise ValidationError(
                "OPENAI_TTS_API_KEY is required before any paid rendering begins"
            )
        approval = manifest.get("approvals", {}).get("execution")
        if not approval or approval.get("decision") != ApprovalDecision.APPROVED.value:
            raise ApprovalRequiredError("Execution approval is required")
        if approval.get("artifact_hash") != self._planning_hash(manifest):
            raise ApprovalRequiredError("Planning artifacts changed after execution approval")
        self._verify_execution_review_binding(manifest, approval)
        self.repository.verify_artifacts(manifest)
        manifest = self.repository.transition(
            manifest, BuildState.EXECUTING, "execution_approval_verified"
        )
        runtime = manifest.setdefault("runtime", {})
        runtime["execution_generation"] = int(
            runtime.get("execution_generation", 0)
        ) + 1
        queue = self._runtime_queue(manifest)
        runtime["queue_ref"] = str(queue.path)
        runtime["queue_snapshot"] = None
        runtime["execution_started_at"] = now_iso()
        self.repository.record_event(
            manifest,
            "execution_generation_started",
            {"generation": runtime["execution_generation"]},
            dedup_key=(
                f"execution-generation:{runtime['execution_generation']}"
            ),
        )
        manifest = self.repository.save(manifest)
        manifest = self._checkpoint(
            manifest, "execution-admitted", queue=queue, clean=False
        )
        try:
            storyboard = self.repository.load_artifact(manifest, "approved_storyboard")["data"]
            if storyboard.get("approved") is not True or storyboard.get("approval_ref") != approval["approval_id"]:
                raise ApprovalRequiredError("Approved Storyboard artifact is missing approval provenance")
            render_manifest = self._rendering_platform(manifest).render_build(
                storyboard,
                approved=True,
                runtime_queue=queue,
                execution_generation=runtime["execution_generation"],
            )
            queue_snapshot = render_manifest.pop("runtime_queue", None)
            self.repository.store_artifact(
                manifest,
                ArtifactEnvelope(
                    artifact_type="render_manifest",
                    build_id=build_id,
                    data=render_manifest,
                    input_hashes=self._artifact_inputs(
                        manifest, "approved_storyboard", "render_strategy"
                    ),
                    generator="rendering-platform",
                ),
            )
            strategy_by_shot = {
                frame["shot_id"]: frame["render_strategy"]["asset_class"]
                for frame in storyboard["frames"]
            }
            render_results = {
                "schema_version": "2.0",
                "build_id": build_id,
                "input_admission_ref": approval["approval_id"],
                "generated_at": now_iso(),
                "sealed": True,
                "overall_status": "complete" if render_manifest["all_ready"] else "partial_blocked",
                "shots": [
                    {
                        "shot_id": result["shot_id"],
                        "outcome": "cache_hit" if result["from_cache"] else (
                            "rendered" if result["state"] == "COMPLETED" else "manual_review"
                        ),
                        "strategy": strategy_by_shot[result["shot_id"]],
                        "attempts_used": result["attempts"],
                        **(
                            {"chosen_asset_uri": result["asset_uri"]}
                            if result.get("asset_uri")
                            else {}
                        ),
                        "quality_score": result["quality_score"],
                    }
                    for result in render_manifest["results"]
                ],
            }
            render_results["content_hash"] = content_hash(
                {key: value for key, value in render_results.items() if key != "content_hash"}
            )
            self.repository.store_artifact(
                manifest,
                ArtifactEnvelope(
                    artifact_type="render_results",
                    build_id=build_id,
                    data=render_results,
                    input_hashes=self._artifact_inputs(manifest, "render_manifest"),
                    generator="rendering-platform",
                    approved=True,
                    approval_ref=approval["approval_id"],
                ),
            )
            manifest["render_tasks"] = {
                result["render_task_id"]: result for result in render_manifest["results"]
            }
            manifest["metrics"]["rendering"] = render_manifest["metrics"]
            manifest["runtime"]["queue_snapshot"] = queue_snapshot
            technical_passed = all(
                result["validation"].get("passed") is True
                for result in render_manifest["results"]
            )
            editorial_score = min(
                result["quality_score"] for result in render_manifest["results"]
            )
            technical_projection = {
                "gate_id": "rendering_technical_gate",
                "passed": technical_passed,
                "score": 1.0 if technical_passed else 0.0,
                "threshold": 1.0,
                "blocking": True,
                "fail_closed": True,
            }
            editorial_projection = {
                "gate_id": "rendering_editorial_gate",
                "passed": editorial_score >= self.config.quality_threshold,
                "score": editorial_score,
                "threshold": self.config.quality_threshold,
                "blocking": True,
                "fail_closed": True,
            }
            manifest, _ = self._record_quality_gate(
                manifest,
                gate_id="rendering_technical_gate",
                projection=technical_projection,
                checks={
                    "all_assets_validate": technical_passed,
                    "all_provider_tasks_terminal": all(
                        result["state"] in {"COMPLETED", "CACHED"}
                        for result in render_manifest["results"]
                    ),
                },
                evidence_types=(
                    "approved_storyboard",
                    "render_manifest",
                    "render_results",
                ),
            )
            manifest, _ = self._record_quality_gate(
                manifest,
                gate_id="rendering_editorial_gate",
                projection=editorial_projection,
                checks={
                    "quality_threshold_met": editorial_score
                    >= self.config.quality_threshold,
                    "quality_scores_present": all(
                        isinstance(result.get("quality_score"), (int, float))
                        for result in render_manifest["results"]
                    ),
                },
                evidence_types=("render_manifest", "render_results"),
            )
            render_gate_checks = {
                "asset_present": all(
                    result.get("asset_uri")
                    and Path(result["asset_uri"]).is_file()
                    for result in render_manifest["results"]
                ),
                "asset_integrity": all(
                    result.get("asset_uri")
                    and result.get("asset_hash")
                    and Path(result["asset_uri"]).is_file()
                    and file_hash(Path(result["asset_uri"]))
                    == result["asset_hash"]
                    for result in render_manifest["results"]
                ),
                "provider_job_succeeded": all(
                    result["state"] in {"COMPLETED", "CACHED"}
                    for result in render_manifest["results"]
                ),
                "duration_conformance": all(
                    result["validation"].get("checks", {}).get("duration") is True
                    for result in render_manifest["results"]
                ),
                "resolution_conformance": all(
                    result["validation"].get("checks", {}).get("width") is True
                    and result["validation"].get("checks", {}).get("height") is True
                    for result in render_manifest["results"]
                ),
                "strategy_conformance": set(strategy_by_shot)
                == {result["shot_id"] for result in render_manifest["results"]},
                "no_corruption": all(
                    result["validation"].get("checks", {}).get("decodable") is True
                    and result["validation"].get("checks", {}).get("visual_content") is True
                    for result in render_manifest["results"]
                ),
                "provenance_bound": all(
                    result["shot_id"] in strategy_by_shot
                    and bool(result.get("render_task_id"))
                    and bool(result.get("cache_key"))
                    for result in render_manifest["results"]
                ),
            }
            render_projection = {
                "gate_id": "render_quality_gate",
                "passed": all(render_gate_checks.values()),
                "score": sum(render_gate_checks.values()) / len(render_gate_checks),
                "threshold": 1.0,
                "checks": render_gate_checks,
                "blocking": True,
                "fail_closed": True,
            }
            manifest, _ = self._record_quality_gate(
                manifest,
                gate_id="render_quality_gate",
                projection=render_projection,
                checks=render_gate_checks,
                evidence_types=(
                    "approved_storyboard",
                    "render_manifest",
                    "render_results",
                ),
            )
            storyboard_shot_ids = [
                frame["shot_id"] for frame in storyboard["frames"]
            ]
            rendered_shot_ids = [
                result["shot_id"] for result in render_manifest["results"]
            ]
            coherence_checks = {
                "shot_identity_matches": set(storyboard_shot_ids)
                == set(rendered_shot_ids),
                "shot_order_matches": storyboard_shot_ids == rendered_shot_ids,
                "strategy_identity_matches": set(strategy_by_shot)
                == set(rendered_shot_ids),
                "approval_binding_current": storyboard.get("approval_ref")
                == approval["approval_id"],
                "no_orphan_render": not set(rendered_shot_ids).difference(
                    storyboard_shot_ids
                ),
            }
            coherence_projection = {
                "gate_id": "render_storyboard_coherence_gate",
                "passed": all(coherence_checks.values()),
                "score": sum(coherence_checks.values()) / len(coherence_checks),
                "threshold": 1.0,
                "checks": coherence_checks,
                "blocking": True,
                "fail_closed": True,
            }
            manifest, _ = self._record_quality_gate(
                manifest,
                gate_id="render_storyboard_coherence_gate",
                projection=coherence_projection,
                checks=coherence_checks,
                evidence_types=(
                    "approved_storyboard",
                    "render_manifest",
                    "render_results",
                ),
            )
            if not render_manifest["all_ready"]:
                raise QualityGateError(
                    "Rendering failed closed and requires manual review",
                    details=render_manifest,
                )
            manifest = self.repository.save(manifest)
            manifest = self._checkpoint(
                manifest, "render-complete", queue=queue, clean=True
            )
            manifest = self.repository.transition(
                manifest, BuildState.COMPOSING, "all_render_assets_ready"
            )
            ordered_assets = [
                Path(result["asset_uri"])
                for result in render_manifest["results"]
                if result["state"] in {"COMPLETED", "CACHED"}
            ]
            profile = self.config.render_profile()
            scene_order: list[str] = []
            scene_durations: dict[str, float] = {}
            for frame in storyboard["frames"]:
                scene_id = str(frame["scene_id"])
                if scene_id not in scene_durations:
                    scene_order.append(scene_id)
                    scene_durations[scene_id] = 0.0
                scene_durations[scene_id] += min(
                    float(frame["duration_seconds"]), profile.max_duration_seconds
                )
            storyboard_duration = sum(scene_durations.values())
            output = self.repository.build_dir(build_id) / "output" / "master.mp4"
            composition = FFmpegComposer().compose(ordered_assets, output)
            narration_script = self.repository.load_artifact(manifest, "narration_script")["data"]
            narration_by_scene = {
                str(segment["scene_id"]): str(segment["text"])
                for segment in narration_script.get("segments", [])
            }
            narration_timeline: list[dict[str, Any]] = []
            scene_start = 0.0
            for scene_id in scene_order:
                text = narration_by_scene.get(scene_id, "").strip()
                if text:
                    segment_start = scene_start + 0.65
                    segment_end = scene_start + scene_durations[scene_id] - 0.35
                    narration_timeline.append(
                        {
                            "scene_id": scene_id,
                            "start_seconds": segment_start,
                            "end_seconds": max(segment_start + 0.25, segment_end),
                            "text": text,
                        }
                    )
                scene_start += scene_durations[scene_id]
            if self.config.narration_provider == "openai":
                narrator = OpenAITTSNarrator(
                    api_key=self.config.openai_tts_api_key or "",
                    model=self.config.narration_openai_model,
                    voice=self.config.narration_openai_voice,
                    instructions=self.config.narration_openai_instructions,
                )
                narration_mix = narrator.mix(
                    output,
                    narration_timeline,
                    duration_seconds=storyboard_duration,
                    integrated_loudness_lufs=(
                        self.config.youtube_integrated_loudness_lufs
                    ),
                    true_peak_db=self.config.youtube_true_peak_db,
                    audio_bitrate=self.config.youtube_audio_bitrate,
                )
            else:
                narration_mix = OfflineNarrator().mix(
                    output,
                    narration_timeline,
                    duration_seconds=storyboard_duration,
                )
            composition.update(narration_mix)
            captions_path = output.parent / "captions.en.srt"
            composition.update(
                write_srt(
                    captions_path,
                    narration_timeline,
                    duration_seconds=storyboard_duration,
                )
            )
            if self.config.profile == "final":
                composition.update(
                    YouTubeMastering().master(
                        output,
                        width=profile.width,
                        height=profile.height,
                        frame_rate=profile.frame_rate,
                        video_bitrate=self.config.youtube_video_bitrate,
                        audio_bitrate=self.config.youtube_audio_bitrate,
                        audio_sample_rate=self.config.youtube_audio_sample_rate,
                        integrated_loudness_lufs=(
                            self.config.youtube_integrated_loudness_lufs
                        ),
                        true_peak_db=self.config.youtube_true_peak_db,
                    )
                )
                article_data = self.repository.load_artifact(
                    manifest, "structured_article"
                )["data"]
                disclosure_path = output.parent / "youtube-description.txt"
                atomic_write_text(
                    disclosure_path,
                    f"{article_data['title']}\n\n"
                    "Disclosure: This video contains an AI-generated narration voice.\n",
                )
                composition.update(
                    {
                        "youtube_description_uri": str(disclosure_path.resolve()),
                        "youtube_description_hash": file_hash(disclosure_path),
                        "ai_voice_disclosure_required": True,
                    }
                )
            self.repository.store_artifact(
                manifest,
                ArtifactEnvelope(
                    artifact_type="composition",
                    build_id=build_id,
                    data=composition,
                    input_hashes=tuple(
                        result["asset_hash"] for result in render_manifest["results"]
                    )
                    + self._artifact_inputs(manifest, "narration_script"),
                    generator="ffmpeg-composer",
                ),
            )
            manifest = self.repository.save(manifest)
            manifest = self.repository.transition(
                manifest, BuildState.VALIDATING, "composition_completed"
            )
            manifest = self._checkpoint(
                manifest, "composition-complete", queue=queue, clean=True
            )
            report = composition_gate(
                output,
                width=profile.width,
                height=profile.height,
                frame_rate=profile.frame_rate,
                expected_duration=storyboard_duration,
                youtube_ready=self.config.profile == "final",
            )
            composition_checks = {
                "all_segments_present": composition["input_count"]
                == len(storyboard["frames"]),
                "segment_order_matches_plan": [
                    result["shot_id"] for result in render_manifest["results"]
                ]
                == [frame["shot_id"] for frame in storyboard["frames"]],
                "no_timeline_gaps": report["checks"]["duration"]
                and report["checks"]["visual_content"],
                "transitions_valid": composition["ffmpeg_copy_concat"] is True,
                "total_duration_matches": report["checks"]["duration"],
                "segment_boundaries_intact": report["checks"]["frame_rate"],
                "resolution_uniform": report["checks"]["resolution"],
                **report["checks"],
            }
            report["checks"] = composition_checks
            report["passed"] = all(composition_checks.values())
            report["score"] = sum(composition_checks.values()) / len(
                composition_checks
            )
            narration_checks = {
                "all_narration_present": len(narration_timeline)
                == len(narration_script.get("segments", [])),
                "narration_timing_matches": [
                    item["scene_id"] for item in narration_timeline
                ]
                == [item["scene_id"] for item in narration_script.get("segments", [])],
                "audio_video_sync": report["validation"]["checks"]["duration"]
                is True,
                "levels_within_spec": report["validation"]["audio_non_silent"]
                is True,
                "no_clipping": float(report["validation"]["audio_peak_dbfs"])
                <= -0.1,
                "no_dropouts": report["validation"]["audio_non_silent"] is True,
                "language_correct": narration_script.get("language") == "en",
                "audio_stream_present": report["validation"]["audio_stream_present"],
                "audio_non_silent": report["validation"]["audio_non_silent"],
                "production_voice": (
                    composition["narration_engine"] == "openai-speech-api"
                    if self.config.narration_provider == "openai"
                    else True
                ),
            }
            narration_projection = {
                "gate_id": "narration_audio_quality_gate",
                "passed": all(narration_checks.values()),
                "score": sum(narration_checks.values()) / len(narration_checks),
                "threshold": 1.0,
                "checks": narration_checks,
                "narration_engine": composition["narration_engine"],
                "audio_rms_dbfs": report["validation"]["audio_rms_dbfs"],
                "audio_peak_dbfs": report["validation"]["audio_peak_dbfs"],
                "blocking": True,
                "fail_closed": True,
            }
            self.repository.store_artifact(
                manifest,
                ArtifactEnvelope(
                    artifact_type="composition_quality_report",
                    build_id=build_id,
                    data=report,
                    input_hashes=(composition["asset_hash"],),
                    generator="composition-quality-gate",
                ),
            )
            manifest, _ = self._record_quality_gate(
                manifest,
                gate_id="composition_quality_gate",
                projection=report,
                checks=composition_checks,
                evidence_types=(
                    "render_manifest",
                    "composition",
                    "composition_quality_report",
                ),
            )
            manifest, _ = self._record_quality_gate(
                manifest,
                gate_id="narration_audio_quality_gate",
                projection=narration_projection,
                checks=narration_checks,
                evidence_types=(
                    "narration_script",
                    "composition",
                    "composition_quality_report",
                ),
            )
            if not creative_gate_passed(report):
                raise QualityGateError("Composition Quality Gate failed", details=report)
            thumbnail = create_thumbnail(
                output, output.parent / "thumbnail.jpg"
            )
            metadata = {
                "schema_version": "2.0",
                "build_id": build_id,
                "generated_at": now_iso(),
                "sealed": True,
                "producer": {
                    "component": "RenderingPlatform",
                    "version": PLATFORM_VERSION,
                },
                "input_lineage": [
                    {
                        "artifact": artifact_type + ".json",
                        "content_hash": manifest["artifacts"][artifact_type]["content_hash"],
                        "producer": producer,
                        "approval_ref": approval["approval_id"],
                    }
                    for artifact_type, producer in (
                        ("approved_shot_list", "HumanApprovalGate"),
                        ("approved_storyboard", "HumanApprovalGate"),
                        ("render_strategy", "ShotPlanner"),
                    )
                ],
                "provider_versions": [
                    {
                        "provider": name,
                        "provider_version": "local-ffmpeg-v2" if name == "local" else "gen4.5",
                    }
                    for name in sorted({result["provider"] for result in render_manifest["results"]})
                ],
                "output_index": {
                    "render_manifest": manifest["artifacts"]["render_manifest"]["content_hash"],
                    "render_results": manifest["artifacts"]["render_results"]["content_hash"],
                    "render_queue": content_hash({"queues": [], "terminal": True}),
                    "asset_directories": ["renders/", "output/"],
                    **thumbnail,
                },
            }
            metadata["content_hash"] = content_hash(
                {key: value for key, value in metadata.items() if key != "content_hash"}
            )
            self.repository.store_artifact(
                manifest,
                ArtifactEnvelope(
                    artifact_type="metadata",
                    build_id=build_id,
                    data=metadata,
                    input_hashes=(composition["asset_hash"],),
                    generator="metadata-packager",
                    approved=True,
                    approval_ref=approval["approval_id"],
                ),
            )
            captions_uri = Path(composition["caption_uri"])
            metadata_checks = {
                "all_artifacts_present": output.is_file()
                and captions_uri.is_file()
                and Path(thumbnail["thumbnail_uri"]).is_file(),
                "metadata_complete": bool(metadata["input_lineage"])
                and bool(metadata["provider_versions"])
                and bool(metadata["output_index"]),
                "metadata_valid": metadata["content_hash"]
                == content_hash(
                    {
                        key: value
                        for key, value in metadata.items()
                        if key != "content_hash"
                    }
                ),
                "container_format_valid": output.suffix.casefold() == ".mp4",
                "thumbnail_present": file_hash(
                    Path(thumbnail["thumbnail_uri"])
                )
                == thumbnail["thumbnail_hash"],
                "checksums_valid": file_hash(output) == composition["asset_hash"]
                and file_hash(captions_uri) == composition["caption_hash"],
                "manifest_consistent": all(
                    manifest["artifacts"].get(name)
                    for name in (
                        "approved_storyboard",
                        "render_manifest",
                        "render_results",
                        "composition",
                        "composition_quality_report",
                        "metadata",
                    )
                ),
            }
            metadata_projection = {
                "gate_id": "metadata_packaging_quality_gate",
                "passed": all(metadata_checks.values()),
                "score": sum(metadata_checks.values()) / len(metadata_checks),
                "threshold": 1.0,
                "checks": metadata_checks,
                "blocking": True,
                "fail_closed": True,
            }
            manifest, _ = self._record_quality_gate(
                manifest,
                gate_id="metadata_packaging_quality_gate",
                projection=metadata_projection,
                checks=metadata_checks,
                evidence_types=(
                    "metadata",
                    "composition",
                    "composition_quality_report",
                ),
            )
            quality_summary = build_quality_report(
                build_id=build_id,
                reports=self.repository.load_quality_reports(manifest),
                baseline_scores=self.repository.quality_baseline(
                    profile=manifest["profile"], exclude_build_id=build_id
                ),
            )
            self.repository.store_artifact(
                manifest,
                ArtifactEnvelope(
                    artifact_type="build_quality_report",
                    build_id=build_id,
                    data=quality_summary,
                    input_hashes=tuple(
                        reference["report_content_hash"]
                        for reference in manifest["quality"]["reports"]
                    ),
                    generator="quality-report-aggregator",
                ),
            )
            self.repository.record_event(
                manifest,
                "build_ready",
                {"master_video": str(output), "master_hash": composition["asset_hash"]},
            )
            manifest = self.repository.save(manifest)
            manifest = self.repository.transition(
                manifest, BuildState.READY, "all_automated_gates_passed"
            )
            manifest = self._checkpoint(manifest, "ready", queue=queue, clean=True)
            return self._view(manifest)
        except Exception:
            latest = self.repository.load(build_id)
            current = BuildState(latest["state"])
            if BuildState.FAILED in self.repository.LEGAL_TRANSITIONS[current]:
                self.repository.record_event(latest, "execution_failed")
                self.repository.transition(latest, BuildState.FAILED, "execution_failure")
            raise

    def publish(self, build_id: str) -> dict[str, Any]:
        manifest = self.repository.load(build_id)
        state = BuildState(manifest["state"])
        if state == BuildState.PUBLISHED:
            return self._view(manifest)
        if state != BuildState.AWAITING_PUBLISH_APPROVAL:
            raise StateConflictError(f"Build cannot publish from {state.value}")
        approval = manifest.get("approvals", {}).get("publish")
        if not approval or approval.get("decision") != ApprovalDecision.APPROVED.value:
            raise ApprovalRequiredError("Publish approval is required")
        master = self.repository.build_dir(build_id) / "output" / "master.mp4"
        if approval["artifact_hash"] != file_hash(master):
            raise ApprovalRequiredError("Master video changed after publish approval")
        package = create_publish_package(
            build_dir=self.repository.build_dir(build_id),
            manifest=manifest,
            master_video=master,
        )
        self.repository.store_artifact(
            manifest,
            ArtifactEnvelope(
                artifact_type="publish_package",
                build_id=build_id,
                data=package,
                input_hashes=(file_hash(master), approval["artifact_hash"]),
                generator="publish-packager",
            ),
        )
        metadata_projection = manifest["gates"]["metadata_packaging_quality_gate"]
        metadata_projection["checks"].update(
            {
                "package_exists": Path(package["package_uri"]).is_file(),
                "package_hashed": package["package_hash"].startswith("sha256:"),
                "publish_approval_bound": approval["artifact_hash"]
                == file_hash(master),
            }
        )
        approval_artifact_type = f"approval_record_{approval['approval_id']}"
        approval_artifact = self.repository.load_artifact(
            manifest, approval_artifact_type
        )["data"]
        confirmations = set(approval_artifact.get("confirms", []))
        publication_checks = {
            "publication_rights_cleared": "publication_rights" in confirmations,
            "child_safety_validated": "child_safety" in confirmations,
            "content_safety_validated": "content_safety" in confirmations,
            "editorial_approval_recorded": approval.get("decision")
            == ApprovalDecision.APPROVED.value,
            "approval_scope_matches": approval["artifact_hash"]
            == file_hash(master),
            "publish_target_valid": Path(package["package_uri"]).suffix == ".zip"
            and Path(package["package_uri"]).is_file(),
            "no_upstream_waivers_open": (
                not any(
                    value.get("agent_exception_code")
                    for value in manifest.get("approvals", {}).values()
                )
                or "upstream_exceptions_reviewed" in confirmations
            ),
        }
        publication_projection = {
            "gate_id": "publication_quality_gate",
            "passed": all(publication_checks.values()),
            "score": sum(publication_checks.values()) / len(publication_checks),
            "threshold": 1.0,
            "checks": publication_checks,
            "non_waivable_checks": [
                "publication_rights_cleared",
                "child_safety_validated",
                "content_safety_validated",
                "editorial_approval_recorded",
                "approval_scope_matches",
                "no_upstream_waivers_open",
            ],
            "blocking": True,
            "fail_closed": True,
        }
        manifest, _ = self._record_quality_gate(
            manifest,
            gate_id="publication_quality_gate",
            projection=publication_projection,
            checks=publication_checks,
            evidence_types=(
                "publish_package",
                "metadata",
                "composition",
                approval_artifact_type,
            ),
        )
        published_quality_summary = build_quality_report(
            build_id=build_id,
            reports=self.repository.load_quality_reports(manifest),
            baseline_scores=self.repository.quality_baseline(
                profile=manifest["profile"], exclude_build_id=build_id
            ),
        )
        self.repository.store_artifact(
            manifest,
            ArtifactEnvelope(
                artifact_type="published_build_quality_report",
                build_id=build_id,
                data=published_quality_summary,
                input_hashes=tuple(
                    reference["report_content_hash"]
                    for reference in manifest["quality"]["reports"]
                ),
                generator="quality-report-aggregator",
            ),
        )
        manifest = self.repository.save(manifest)
        manifest = self.repository.transition(
            manifest, BuildState.PUBLISHED, "publication_quality_gate_passed"
        )
        self.repository.record_event(manifest, "package_published", package)
        manifest = self.repository.save(manifest)
        manifest = self._checkpoint(manifest, "published", clean=True)
        return self._view(manifest)

    def build(
        self,
        article_path: Path | str,
        *,
        creative_brief_path: Path | str | None = None,
        auto_approve: bool = False,
        actor: str = "local-operator",
    ) -> dict[str, Any]:
        view = self.plan(
            article_path, creative_brief_path=creative_brief_path
        )
        build_id = view["build_id"]
        if view["state"] == BuildState.AWAITING_PERSONA_APPROVAL.value:
            if not auto_approve:
                return view
            self.approve(build_id, gate="persona", actor=actor)
            view = self.plan(
                article_path, creative_brief_path=creative_brief_path
            )
        if view["state"] == BuildState.PLANNED.value:
            view = self.review(build_id)
        if not auto_approve:
            return view
        if auto_approve and view["state"] == BuildState.AWAITING_EXECUTION_APPROVAL.value:
            self.approve(build_id, gate="execution", actor=actor)
        view = self.execute(build_id)
        if auto_approve and view["state"] == BuildState.READY.value:
            self.approve(build_id, gate="publish", actor=actor)
            view = self.publish(build_id)
        return view

    def inspect(self, build_id: str) -> dict[str, Any]:
        manifest = self.repository.load(build_id)
        value = self._view(manifest, detailed=True)
        value["runtime_verification"] = self.repository.verify_runtime(manifest)
        value["operations"] = self.repository.list_operations(build_id)
        return value

    def list_builds(self) -> list[dict[str, Any]]:
        return self.repository.list_builds()

    def pause(self, build_id: str) -> dict[str, Any]:
        manifest = self.repository.load(build_id)
        manifest = self.repository.transition(manifest, BuildState.PAUSED, "operator_pause")
        queue = self._runtime_queue(manifest)
        clean = True
        if queue.path.exists():
            snapshot = queue.pause()
            manifest["runtime"]["queue_snapshot"] = snapshot
            clean = snapshot["state_counts"].get("LEASED", 0) == 0
            manifest = self.repository.save(manifest)
        manifest = self._checkpoint(manifest, "paused", queue=queue, clean=clean)
        return self._view(manifest)

    def resume(self, build_id: str) -> dict[str, Any]:
        manifest = self.repository.load(build_id)
        recovery, manifest = self.repository.prepare_recovery(manifest)
        if recovery["outcome"] not in {"RESUME", "RECONCILE"}:
            raise StateConflictError(
                "Build is not eligible for resume", details=recovery
            )
        return self.execute(build_id)

    def cancel(self, build_id: str) -> dict[str, Any]:
        manifest = self.repository.load(build_id)
        manifest = self.repository.transition(
            manifest, BuildState.CANCELLED, "operator_cancel"
        )
        queue = self._runtime_queue(manifest)
        if queue.path.exists():
            manifest["runtime"]["queue_snapshot"] = queue.cancel_pending()
            manifest = self.repository.save(manifest)
        manifest = self._checkpoint(manifest, "cancelled", queue=queue, clean=True)
        return self._view(manifest)

    def recover(self, build_id: str) -> dict[str, Any]:
        return self.repository.recovery_plan(self.repository.load(build_id))

    def verify(self, build_id: str) -> dict[str, Any]:
        return self.repository.verify_runtime(self.repository.load(build_id))

    def health(self) -> dict[str, Any]:
        from importlib.util import find_spec
        from shutil import which

        local = LocalVideoProvider(self.repository.root / "providers" / "local")
        local_health = local.health_check()
        sdk_available = find_spec("agents") is not None
        if self.config.agent_review_mode == "off":
            review_health = {"status": "DISABLED", "mode": "off"}
        else:
            key_available = bool(self.config.openai_api_key)
            review_health = {
                "status": (
                    "HEALTHY" if sdk_available and key_available else "DEGRADED"
                ),
                "mode": "review",
                "sdk_available": sdk_available,
                "credential_available": key_available,
                "model": self.config.agent_review_model,
            }
        if self.config.story.persona_mode == "off":
            persona_health = {"status": "DISABLED", "mode": "off"}
        else:
            key_available = bool(self.config.openai_api_key)
            persona_health = {
                "status": (
                    "HEALTHY" if sdk_available and key_available else "DEGRADED"
                ),
                "mode": "council",
                "sdk_available": sdk_available,
                "credential_available": key_available,
                "model": self.config.persona_model,
            }
        if self.config.narration_provider == "openai":
            narration_health = {
                "status": "HEALTHY" if self.config.openai_tts_api_key else "DEGRADED",
                "provider": "openai",
                "credential_available": bool(self.config.openai_tts_api_key),
                "model": self.config.narration_openai_model,
                "voice": self.config.narration_openai_voice,
            }
        else:
            narration_health = {
                "status": "HEALTHY" if which("espeak-ng") else "DEGRADED",
                "provider": "offline",
                "binary_available": bool(which("espeak-ng")),
            }
        return {
            "status": (
                "HEALTHY"
                if local_health["status"] == "HEALTHY"
                and review_health["status"] in {"HEALTHY", "DISABLED"}
                and persona_health["status"] in {"HEALTHY", "DISABLED"}
                and narration_health["status"] == "HEALTHY"
                else "DEGRADED"
            ),
            "version": PLATFORM_VERSION,
            "workspace": str(self.workspace),
            "dependencies": {
                "local_provider": local_health,
                "agent_review": review_health,
                "persona_council": persona_health,
                "narration": narration_health,
            },
            "part6_coverage": part6_coverage_report(),
            "part7_coverage": part7_coverage_report(),
            "part1_coverage": part1_coverage_report(),
        }

    @staticmethod
    def _view(manifest: dict, *, detailed: bool = False) -> dict[str, Any]:
        value = {
            "build_id": manifest["build_id"],
            "state": manifest["state"],
            "profile": manifest["profile"],
            "version": manifest["version"],
            "source": manifest["source"],
            "artifacts": manifest.get("artifacts", {}),
            "gates": manifest.get("gates", {}),
            "approvals": manifest.get("approvals", {}),
            "agent_review": manifest.get("agent_review", {}),
            "persona_council": manifest.get("persona_council", {}),
            "metrics": manifest.get("metrics", {}),
            "runtime": manifest.get("runtime", {}),
            "quality": manifest.get("quality", {}),
        }
        planning_artifacts = {
            artifact_type: reference["content_hash"]
            for artifact_type, reference in manifest.get("artifacts", {}).items()
            if artifact_type in PLANNING_ARTIFACTS
        }
        if planning_artifacts:
            execution_plan = manifest.get("artifacts", {}).get("execution_plan")
            value["execution_plan_content_hash"] = (
                execution_plan["content_hash"]
                if execution_plan
                else content_hash(planning_artifacts)
            )
        if detailed:
            value["transitions"] = manifest.get("transitions", [])
            value["events"] = manifest.get("events", [])
            value["render_tasks"] = manifest.get("render_tasks", {})
            value["configuration"] = manifest.get("configuration", {})
            value["checkpoints"] = manifest.get("checkpoints", [])
        return value
