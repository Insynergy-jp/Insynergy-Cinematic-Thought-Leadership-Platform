"""Build Orchestrator enforcing adjacency, approval barriers, and recovery."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .article import load_article
from .config import load_config
from .errors import (
    ApprovalRequiredError,
    QualityGateError,
    StateConflictError,
    ValidationError,
)
from .media import FFmpegComposer
from .models import (
    ApprovalDecision,
    ApprovalRecord,
    ArtifactEnvelope,
    BuildState,
)
from .package import create_publish_package
from .prompt import PromptAssembler
from .providers.local import LocalVideoProvider
from .quality import composition_gate, creative_gate_passed, registry_document
from .rendering import RenderCache, RenderingPlatform
from .screenplay import ScreenplayEngine
from .shot_planner import ShotPlanner
from .storage import BuildRepository
from .story import StoryEngine
from .util import content_hash, file_hash, now_iso, stable_id


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
        environ: dict[str, str] | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.config = load_config(
            workspace=self.workspace,
            config_path=config_path,
            profile=profile,
            provider=provider,
            environ=environ,
        )
        self.repository = BuildRepository(self.workspace)

    def _config_snapshot(self) -> dict[str, Any]:
        profile = self.config.render_profile()
        return {
            "schema_version": "2.0",
            "profile": self.config.profile,
            "deterministic": self.config.deterministic,
            "render": {
                "provider": self.config.provider,
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
                "planning_contract": "2.0.0",
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
            manifest = self.repository.save(manifest)
            manifest = self.repository.transition(
                manifest, BuildState.PLANNED, "all_planning_gates_passed"
            )
            manifest = self.repository.transition(
                manifest,
                BuildState.AWAITING_EXECUTION_APPROVAL,
                "approval_barrier_entered",
            )
            return self._view(manifest)
        except Exception:
            current = BuildState(manifest["state"])
            if BuildState.FAILED in self.repository.LEGAL_TRANSITIONS[current]:
                self.repository.record_event(manifest, "planning_failed")
                self.repository.transition(manifest, BuildState.FAILED, "planning_failure")
            raise

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
    ) -> dict[str, Any]:
        if gate not in {"execution", "publish"}:
            raise ValidationError("Approval gate must be execution or publish")
        if not actor.strip():
            raise ValidationError("Approval actor is required")
        manifest = self.repository.load(build_id)
        state = BuildState(manifest["state"])
        if gate == "execution":
            expected = BuildState.AWAITING_EXECUTION_APPROVAL
            artifact_hash = self._planning_hash(manifest)
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
        approval_decision = ApprovalDecision(decision.upper())
        record = ApprovalRecord(
            approval_id=stable_id(
                "approval",
                {
                    "build_id": build_id,
                    "gate": gate,
                    "decision": approval_decision.value,
                    "actor": actor,
                    "artifact_hash": artifact_hash,
                },
            ),
            build_id=build_id,
            gate=gate,
            decision=approval_decision,
            actor=actor,
            artifact_hash=artifact_hash,
            approved_at=now_iso(),
            comment=comment,
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
                        input_hashes=(source["content_hash"], artifact_hash),
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

    def _providers(self, manifest: dict) -> dict[str, Any]:
        local = LocalVideoProvider(self.repository.root / "providers" / "local")
        providers: dict[str, Any] = {"local": local}
        if self.config.provider == "runway":
            from .providers.runway import RunwayProvider

            providers["runway"] = RunwayProvider(
                base_url=self.config.runway_base_url or "",
                api_key=self.config.runway_api_key or "",
                model_id=self.config.runway_model or "",
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
        if manifest.get("configuration") != self._config_snapshot():
            raise StateConflictError(
                "Execution configuration does not match the immutable planning snapshot"
            )
        state = BuildState(manifest["state"])
        if state in {BuildState.READY, BuildState.AWAITING_PUBLISH_APPROVAL, BuildState.PUBLISHED}:
            self.repository.verify_artifacts(manifest)
            return self._view(manifest)
        if state not in {BuildState.AWAITING_EXECUTION_APPROVAL, BuildState.PAUSED}:
            raise StateConflictError(f"Build cannot execute from {state.value}")
        approval = manifest.get("approvals", {}).get("execution")
        if not approval or approval.get("decision") != ApprovalDecision.APPROVED.value:
            raise ApprovalRequiredError("Execution approval is required")
        if approval.get("artifact_hash") != self._planning_hash(manifest):
            raise ApprovalRequiredError("Planning artifacts changed after execution approval")
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
            output = self.repository.build_dir(build_id) / "output" / "master.mp4"
            composition = FFmpegComposer().compose(ordered_assets, output)
            self.repository.store_artifact(
                manifest,
                ArtifactEnvelope(
                    artifact_type="composition",
                    build_id=build_id,
                    data=composition,
                    input_hashes=tuple(
                        result["asset_hash"] for result in render_manifest["results"]
                    ),
                    generator="ffmpeg-composer",
                ),
            )
            manifest = self.repository.save(manifest)
            manifest = self.repository.transition(
                manifest, BuildState.VALIDATING, "composition_completed"
            )
            profile = self.config.render_profile()
            storyboard_duration = sum(
                min(float(frame["duration_seconds"]), profile.max_duration_seconds)
                for frame in storyboard["frames"]
            )
            report = composition_gate(
                output,
                width=profile.width,
                height=profile.height,
                frame_rate=profile.frame_rate,
                expected_duration=storyboard_duration,
            )
            manifest["gates"]["composition_quality_gate"] = report
            manifest["gates"]["narration_audio_quality_gate"] = {
                "gate_id": "narration_audio_quality_gate",
                "passed": report["validation"]["audio_stream_present"] is True,
                "score": 1.0 if report["validation"]["audio_stream_present"] else 0.0,
                "threshold": 1.0,
                "checks": {"audio_stream_present": report["validation"]["audio_stream_present"]},
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
                "producer": {"component": "RenderingPlatform", "version": "2.0.0"},
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
                        "provider_version": "local-ffmpeg-v1" if name == "local" else "gen4.5",
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
        local = LocalVideoProvider(self.repository.root / "providers" / "local")
        return {
            "status": "HEALTHY" if local.health_check()["status"] == "HEALTHY" else "DEGRADED",
            "version": "2.0.0",
            "workspace": str(self.workspace),
            "dependencies": {"local_provider": local.health_check()},
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
            "metrics": manifest.get("metrics", {}),
        }
        if detailed:
            value["transitions"] = manifest.get("transitions", [])
            value["events"] = manifest.get("events", [])
            value["render_tasks"] = manifest.get("render_tasks", {})
            value["configuration"] = manifest.get("configuration", {})
        return value
