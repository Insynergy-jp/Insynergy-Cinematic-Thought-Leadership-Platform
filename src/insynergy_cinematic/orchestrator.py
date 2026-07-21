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
from .config import load_config
from .errors import (
    ApprovalRequiredError,
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
from .package import create_publish_package
from .prompt import PromptAssembler
from .providers.local import LocalVideoProvider
from .quality import composition_gate, creative_gate_passed, registry_document
from .rendering import (
    RUNWAY_CREDIT_USD,
    RenderCache,
    RenderingPlatform,
    runway_credit_estimate,
    uses_runway,
)
from .screenplay import ScreenplayEngine
from .shot_planner import ShotPlanner
from .storage import BuildRepository
from .story import StoryEngine
from .util import (
    PLATFORM_VERSION,
    atomic_write_text,
    content_hash,
    file_hash,
    now_iso,
    stable_id,
)


PLANNING_ARTIFACTS = {
    "structured_article",
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
    "screenplay",
    "scene_index",
    "continuity",
    "screenplay_metrics",
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
        environ: dict[str, str] | None = None,
        review_provider: AgentReviewProvider | None = None,
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
            environ=environ,
        )
        self.repository = BuildRepository(self.workspace)
        self._review_provider_override = review_provider

    def _config_snapshot(self) -> dict[str, Any]:
        profile = self.config.render_profile()
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
                "concept_ratio_max": self.config.concept_ratio_max,
                "supporting_role_max": self.config.supporting_role_max,
            },
            "quality": {"fail_closed": self.config.fail_closed},
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

    def plan(self, article_path: Path | str) -> dict[str, Any]:
        article = load_article(Path(article_path))
        source_hash = content_hash(
            {"title": article.title, "body": article.body, "metadata": article.metadata}
        )
        config_snapshot = self._config_snapshot()
        build_identity = content_hash(
            {
                "source_hash": source_hash,
                "profile": self.config.profile,
                "configuration_hash": content_hash(config_snapshot),
                "planning_contract": "3.0.0",
                "agent_review_mode": self.config.agent_review_mode,
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
            },
            self.config.profile,
            config_snapshot,
        )
        state = BuildState(manifest["state"])
        if state not in {BuildState.CREATED, BuildState.PLANNING}:
            self.repository.verify_artifacts(manifest)
            return self._view(manifest)
        if state == BuildState.CREATED:
            manifest = self.repository.transition(
                manifest, BuildState.PLANNING, "planning_started"
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
            article_document = self.repository.store_artifact(
                manifest,
                ArtifactEnvelope(
                    artifact_type="structured_article",
                    build_id=build_id,
                    data=article_data,
                    input_hashes=(source_hash,),
                    generator="article-loader",
                ),
            )
            story = StoryEngine().generate(article)
            self._store_many(
                manifest,
                story,
                inputs=(article_document["content_hash"],),
                generator="story-engine",
            )
            story_report = story["story_quality_report"]
            if not creative_gate_passed(story_report):
                raise QualityGateError("Story Quality Gate failed", details=story_report)
            manifest["gates"]["story_quality_gate"] = story_report

            screenplay_artifacts = ScreenplayEngine().generate(story)
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
            manifest["gates"]["screenplay_quality_gate"] = screenplay_report

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
                manifest["gates"][gate_id] = report
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
        return self._view(manifest)

    @staticmethod
    def _planning_hash(manifest: dict) -> str:
        artifacts = {
            artifact_type: reference["content_hash"]
            for artifact_type, reference in manifest.get("artifacts", {}).items()
            if artifact_type in PLANNING_ARTIFACTS
        }
        if not artifacts:
            raise ValidationError("Build has no planning artifacts")
        return content_hash(artifacts)

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
    ) -> dict[str, Any]:
        if gate not in {"execution", "publish"}:
            raise ValidationError("Approval gate must be execution or publish")
        if not actor.strip():
            raise ValidationError("Approval actor is required")
        try:
            approval_decision = ApprovalDecision(decision.upper())
        except ValueError as exc:
            raise ValidationError("Approval decision must be APPROVED or REJECTED") from exc
        manifest = self.repository.load(build_id)
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
                else ["visual_quality", "timing", "branding", "institutional_accuracy"]
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
        manifest["gates"][f"{gate}_approval"] = {
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
        try:
            storyboard = self.repository.load_artifact(manifest, "approved_storyboard")["data"]
            if storyboard.get("approved") is not True or storyboard.get("approval_ref") != approval["approval_id"]:
                raise ApprovalRequiredError("Approved Storyboard artifact is missing approval provenance")
            render_manifest = self._rendering_platform(manifest).render_build(
                storyboard, approved=True
            )
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
            technical_passed = all(
                result["validation"].get("passed") is True
                for result in render_manifest["results"]
            )
            editorial_score = min(
                result["quality_score"] for result in render_manifest["results"]
            )
            manifest["gates"]["rendering_technical_gate"] = {
                "gate_id": "rendering_technical_gate",
                "passed": technical_passed,
                "score": 1.0 if technical_passed else 0.0,
                "threshold": 1.0,
                "blocking": True,
                "fail_closed": True,
            }
            manifest["gates"]["rendering_editorial_gate"] = {
                "gate_id": "rendering_editorial_gate",
                "passed": editorial_score >= self.config.quality_threshold,
                "score": editorial_score,
                "threshold": self.config.quality_threshold,
                "blocking": True,
                "fail_closed": True,
            }
            if not render_manifest["all_ready"]:
                raise QualityGateError(
                    "Rendering failed closed and requires manual review",
                    details=render_manifest,
                )
            manifest = self.repository.save(manifest)
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
            report = composition_gate(
                output,
                width=profile.width,
                height=profile.height,
                frame_rate=profile.frame_rate,
                expected_duration=storyboard_duration,
                youtube_ready=self.config.profile == "final",
            )
            manifest["gates"]["composition_quality_gate"] = report
            manifest["gates"]["narration_audio_quality_gate"] = {
                "gate_id": "narration_audio_quality_gate",
                "passed": report["validation"]["audio_non_silent"] is True
                and (
                    composition["narration_engine"] == "openai-speech-api"
                    if self.config.narration_provider == "openai"
                    else True
                ),
                "score": 1.0
                if report["validation"]["audio_non_silent"]
                and (
                    composition["narration_engine"] == "openai-speech-api"
                    if self.config.narration_provider == "openai"
                    else True
                )
                else 0.0,
                "threshold": 1.0,
                "checks": {
                    "audio_stream_present": report["validation"]["audio_stream_present"],
                    "audio_non_silent": report["validation"]["audio_non_silent"],
                    "production_voice": (
                        composition["narration_engine"] == "openai-speech-api"
                        if self.config.narration_provider == "openai"
                        else True
                    ),
                },
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
            if not creative_gate_passed(report):
                raise QualityGateError("Composition Quality Gate failed", details=report)
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
            self.repository.record_event(
                manifest,
                "build_ready",
                {"master_video": str(output), "master_hash": composition["asset_hash"]},
            )
            manifest = self.repository.save(manifest)
            manifest = self.repository.transition(
                manifest, BuildState.READY, "all_automated_gates_passed"
            )
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
        manifest = self.repository.transition(
            manifest, BuildState.PUBLISHED, "publish_approval_verified"
        )
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
        manifest["gates"]["metadata_packaging_quality_gate"] = {
            "gate_id": "metadata_packaging_quality_gate",
            "passed": True,
            "score": 1.0,
            "threshold": 1.0,
            "checks": {
                "package_exists": Path(package["package_uri"]).exists(),
                "package_hashed": package["package_hash"].startswith("sha256:"),
                "publish_approval_bound": True,
            },
            "blocking": True,
            "fail_closed": True,
        }
        self.repository.record_event(manifest, "package_published", package)
        manifest = self.repository.save(manifest)
        return self._view(manifest)

    def build(
        self,
        article_path: Path | str,
        *,
        auto_approve: bool = False,
        actor: str = "local-operator",
    ) -> dict[str, Any]:
        view = self.plan(article_path)
        build_id = view["build_id"]
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
        return self._view(self.repository.load(build_id), detailed=True)

    def list_builds(self) -> list[dict[str, Any]]:
        return self.repository.list_builds()

    def pause(self, build_id: str) -> dict[str, Any]:
        manifest = self.repository.load(build_id)
        manifest = self.repository.transition(manifest, BuildState.PAUSED, "operator_pause")
        return self._view(manifest)

    def resume(self, build_id: str) -> dict[str, Any]:
        return self.execute(build_id)

    def cancel(self, build_id: str) -> dict[str, Any]:
        manifest = self.repository.load(build_id)
        manifest = self.repository.transition(
            manifest, BuildState.CANCELLED, "operator_cancel"
        )
        return self._view(manifest)

    def health(self) -> dict[str, Any]:
        from importlib.util import find_spec
        from shutil import which

        local = LocalVideoProvider(self.repository.root / "providers" / "local")
        local_health = local.health_check()
        if self.config.agent_review_mode == "off":
            review_health = {"status": "DISABLED", "mode": "off"}
        else:
            sdk_available = find_spec("agents") is not None
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
                and narration_health["status"] == "HEALTHY"
                else "DEGRADED"
            ),
            "version": PLATFORM_VERSION,
            "workspace": str(self.workspace),
            "dependencies": {
                "local_provider": local_health,
                "agent_review": review_health,
                "narration": narration_health,
            },
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
            "metrics": manifest.get("metrics", {}),
        }
        planning_artifacts = {
            artifact_type: reference["content_hash"]
            for artifact_type, reference in manifest.get("artifacts", {}).items()
            if artifact_type in PLANNING_ARTIFACTS
        }
        if planning_artifacts:
            value["execution_plan_content_hash"] = content_hash(planning_artifacts)
        if detailed:
            value["transitions"] = manifest.get("transitions", [])
            value["events"] = manifest.get("events", [])
            value["render_tasks"] = manifest.get("render_tasks", {})
            value["configuration"] = manifest.get("configuration", {})
        return value
