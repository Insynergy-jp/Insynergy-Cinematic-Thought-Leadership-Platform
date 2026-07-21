"""Frozen public data contracts shared by all layers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from .util import CONTRACT_VERSION, DETERMINISTIC_TIME, SCHEMA_VERSION, content_hash, stable_id


class BuildProfile(StrEnum):
    DRAFT = "draft"
    PREVIEW = "preview"
    FINAL = "final"


class BuildState(StrEnum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    PLANNED = "PLANNED"
    AWAITING_EXECUTION_APPROVAL = "AWAITING_EXECUTION_APPROVAL"
    EXECUTING = "EXECUTING"
    COMPOSING = "COMPOSING"
    VALIDATING = "VALIDATING"
    READY = "READY"
    AWAITING_PUBLISH_APPROVAL = "AWAITING_PUBLISH_APPROVAL"
    PUBLISHED = "PUBLISHED"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class GateDecision(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


class ApprovalDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AgentReviewMode(StrEnum):
    OFF = "off"
    REVIEW = "review"


class AgentReviewStatus(StrEnum):
    DISABLED = "DISABLED"
    PENDING = "PENDING"
    PASS = "PASS"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


class RenderState(StrEnum):
    CREATED = "CREATED"
    PLANNED = "PLANNED"
    READY = "READY"
    QUEUED = "QUEUED"
    SUBMITTED = "SUBMITTED"
    RUNNING = "RUNNING"
    DOWNLOADING = "DOWNLOADING"
    VALIDATING = "VALIDATING"
    CACHED = "CACHED"
    COMPLETED = "COMPLETED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class Article:
    title: str
    body: str
    subtitle: str = ""
    source_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    references: tuple[str, ...] = ()

    @property
    def article_id(self) -> str:
        return stable_id(
            "article", {"title": self.title, "body": self.body, "metadata": self.metadata}
        )


@dataclass(frozen=True)
class ArtifactEnvelope:
    artifact_type: str
    build_id: str
    data: dict[str, Any]
    input_hashes: tuple[str, ...] = ()
    generator: str = "insynergy-cinematic"
    schema_version: str = SCHEMA_VERSION
    contract_version: str = CONTRACT_VERSION
    generated_at: str = DETERMINISTIC_TIME
    approved: bool | None = None
    approval_ref: str | None = None

    @property
    def artifact_id(self) -> str:
        return stable_id(self.artifact_type.replace("_", "-"), self.data)

    @property
    def content_hash(self) -> str:
        return content_hash(self.data)

    def as_dict(self) -> dict[str, Any]:
        value = {
            "schema_version": self.schema_version,
            "contract_version": self.contract_version,
            "artifact_type": self.artifact_type,
            "artifact_id": self.artifact_id,
            "build_id": self.build_id,
            "content_hash": self.content_hash,
            "generated_at": self.generated_at,
            "provenance": {
                "generator": self.generator,
                "input_hashes": list(self.input_hashes),
                "deterministic": True,
            },
            "data": self.data,
        }
        if self.approved is not None:
            value["approved"] = self.approved
        if self.approval_ref is not None:
            value["approval_ref"] = self.approval_ref
        return value


@dataclass(frozen=True)
class GateCheck:
    check_id: str
    passed: bool
    score: float
    threshold: float
    message: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    stage: str
    decision: GateDecision
    score: float
    threshold: float
    checks: tuple[GateCheck, ...]
    blocking: bool = True
    fail_closed: bool = True

    @property
    def passed(self) -> bool:
        return self.decision == GateDecision.PASS

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["decision"] = self.decision.value
        value["passed"] = self.passed
        return value


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    build_id: str
    gate: str
    decision: ApprovalDecision
    actor: str
    artifact_hash: str
    approved_at: str
    comment: str = ""
    agent_review_mode: str = "off"
    agent_review_report_hash: str | None = None
    agent_disposition: str | None = None
    agent_exception_code: str | None = None
    agent_exception_rationale: str | None = None
    agent_policy_version: str | None = None

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["decision"] = self.decision.value
        return value


@dataclass(frozen=True)
class RenderRequest:
    render_task_id: str
    shot_id: str
    build_id: str
    cache_key: str
    attempt: int
    render_profile: str
    assembled_prompt: str
    prompt_provenance: str
    duration_seconds: float
    width: int
    height: int
    frame_rate: int
    provider: str
    strategy: str
    camera_parameters: dict[str, Any] = field(default_factory=dict)
    style_tokens: tuple[str, ...] = ()
    negative_style_tokens: tuple[str, ...] = ()
    conditioning_image_ref: str | None = None


@dataclass(frozen=True)
class ProviderJobRef:
    provider: str
    provider_task_id: str
    idempotency_key: str
    state: RenderState


@dataclass(frozen=True)
class RenderResult:
    render_task_id: str
    shot_id: str
    state: RenderState
    asset_uri: str | None
    asset_hash: str | None
    cache_key: str
    provider: str
    from_cache: bool
    quality_score: float
    validation: dict[str, Any]
    attempts: int = 1
    error: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["state"] = self.state.value
        return value
