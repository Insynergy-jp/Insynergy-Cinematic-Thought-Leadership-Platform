"""Agent Review Mode domain contract, exact cache, and deterministic guardrails."""

from __future__ import annotations

import re
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol, TYPE_CHECKING

from .errors import AgentReviewError, StateConflictError, ValidationError
from .models import AgentReviewStatus
from .util import atomic_write_json, canonical_json, content_hash, now_iso, read_json

if TYPE_CHECKING:
    from .config import PlatformConfig
    from .storage import BuildRepository


AGENT_REVIEW_CONTRACT_VERSION = "agent-review/1"
AGENT_REVIEW_AGENT_NAME = "insynergy_planning_reviewer"
WAIVABLE_ERROR_CLASSES = frozenset(
    {
        "AUTHENTICATION",
        "AUTHORIZATION",
        "RATE_LIMIT",
        "QUOTA",
        "TIMEOUT",
        "PROVIDER_UNAVAILABLE",
    }
)
DIMENSION_CODES = (
    "SOURCE_FIDELITY",
    "DRAMATIC_COHERENCE",
    "STRUCTURE_AND_CONCEPT",
    "SCREENPLAY_OBSERVABILITY",
    "VISUAL_COVERAGE",
    "CONTINUITY",
    "DECISION_BOUNDARY",
    "EXECUTION_FEASIBILITY",
)
STORY_ARTIFACT_TYPES = (
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
    "story_metrics",
)
SCREENPLAY_ARTIFACT_TYPES = (
    "screenplay",
    "scene_index",
    "continuity",
    "screenplay_metrics",
)
QUALITY_EVIDENCE_TYPES = (
    "story_quality_report",
    "screenplay_quality_report",
    "shot_gate_report",
    "storyboard_gate_report",
)
REVIEWED_ARTIFACT_TYPES = (
    "structured_article",
    *STORY_ARTIFACT_TYPES,
    *SCREENPLAY_ARTIFACT_TYPES,
    "shot_list",
    "storyboard",
    *QUALITY_EVIDENCE_TYPES,
)
SECRET_PATTERN = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9._~-]{20,})",
    flags=re.IGNORECASE,
)
SPECIFICATION_REF = re.compile(r"^(?:INV|ADR|AC)-[A-Za-z0-9._-]{2,128}$")
FINDING_CODE = re.compile(r"^AR-[A-Z0-9_]{3,64}$")
BLOCKING_FINDING_CODES = frozenset(
    {
        "AR-SOURCE_CLAIM",
        "AR-MULTIPLE_PREMISES",
        "AR-EARLY_CONCEPT_DISCLOSURE",
        "AR-NON_OBSERVABLE_ACTION",
        "AR-MISSING_SCENE_COVERAGE",
        "AR-CONTINUITY_BREAK",
        "AR-DECISION_BOUNDARY",
        "AR-PROVIDER_LEAKAGE",
        "AR-EXECUTION_INFEASIBLE",
    }
)


@dataclass(frozen=True)
class AgentReviewProviderResult:
    output: dict[str, Any]
    sdk_version: str
    model_resolved: str
    usage: dict[str, int] = field(
        default_factory=lambda: {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }
    )
    response_id: str | None = None
    created_at: str = field(default_factory=now_iso)


@dataclass(frozen=True)
class AgentReviewRequest:
    build_id: str
    review_key: str
    inputs: dict[str, Any]
    artifacts: dict[str, dict[str, Any]]
    model_input: str


class AgentReviewProvider(Protocol):
    def review(self, request: AgentReviewRequest) -> AgentReviewProviderResult: ...


class AgentReviewStore:
    """Stores provider review cores; cached cores are never silently replaced."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, review_key: str) -> Path:
        digest = review_key.removeprefix("sha256:")
        return self.root / digest[:2] / f"{digest}.json"

    def get(self, review_key: str) -> AgentReviewProviderResult | None:
        path = self.path_for(review_key)
        if not path.exists():
            return None
        document = read_json(path)
        if document.get("review_key") != review_key:
            raise ValidationError("Agent Review cache identity mismatch")
        result = document.get("provider_result")
        if not isinstance(result, dict):
            raise ValidationError("Agent Review cache is malformed")
        return AgentReviewProviderResult(
            output=result.get("output", {}),
            sdk_version=str(result.get("sdk_version", "")),
            model_resolved=str(result.get("model_resolved", "")),
            usage=dict(result.get("usage", {})),
            response_id=result.get("response_id"),
            created_at=str(result.get("created_at", "")),
        )

    def put(self, review_key: str, result: AgentReviewProviderResult) -> None:
        path = self.path_for(review_key)
        document = {"review_key": review_key, "provider_result": asdict(result)}
        if path.exists():
            if read_json(path) != document:
                raise StateConflictError(
                    "Agent Review cache entry is immutable",
                    details={"review_key": review_key},
                )
            return
        atomic_write_json(path, document)


class FakeAgentReviewProvider:
    """Deterministic test provider; it performs no network or SDK import."""

    def __init__(
        self,
        output: dict[str, Any] | None = None,
        *,
        error: AgentReviewError | None = None,
    ) -> None:
        self.output = output or clean_review_output()
        self.error = error
        self.calls = 0

    def review(self, request: AgentReviewRequest) -> AgentReviewProviderResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return AgentReviewProviderResult(
            output=self.output,
            sdk_version="fake-3.0.0",
            model_resolved="fake-review-model",
            response_id=f"fake-{request.review_key[-12:]}",
            created_at="1970-01-01T00:00:00Z",
        )


def clean_review_output() -> dict[str, Any]:
    return {
        "status": AgentReviewStatus.PASS.value,
        "dimensions": [
            {
                "code": code,
                "score": 1.0,
                "passed": True,
                "summary": "No material issue found in the reviewed evidence.",
            }
            for code in DIMENSION_CODES
        ],
        "findings": [],
        "summary": "The sealed planning bundle is coherent and ready for human review.",
    }


def build_review_request(
    manifest: dict[str, Any],
    repository: BuildRepository,
    config: PlatformConfig,
) -> AgentReviewRequest:
    artifacts, inputs = _review_artifacts_and_inputs(manifest, repository)
    review_identity = {
        "article_hash": inputs["article"]["content_hash"],
        "story_artifact_hashes": [item["content_hash"] for item in inputs["story_artifacts"]],
        "screenplay_artifact_hashes": [
            item["content_hash"] for item in inputs["screenplay_artifacts"]
        ],
        "shot_list_hash": inputs["shot_list"]["content_hash"],
        "storyboard_hash": inputs["storyboard"]["content_hash"],
        "quality_evidence_hashes": [
            item["content_hash"] for item in inputs["quality_evidence"]
        ],
        "agent_contract_version": AGENT_REVIEW_CONTRACT_VERSION,
        "agent_version": config.agent_review_agent_version,
        "prompt_version": config.agent_review_prompt_version,
        "model_requested": config.agent_review_model,
        "reasoning_effort": config.agent_review_reasoning_effort,
        "max_output_tokens": config.agent_review_max_output_tokens,
    }
    review_key = content_hash(review_identity)
    payload = {
        "review_contract": AGENT_REVIEW_CONTRACT_VERSION,
        "build_id": manifest["build_id"],
        "review_key": review_key,
        "artifacts": artifacts,
    }
    return AgentReviewRequest(
        build_id=manifest["build_id"],
        review_key=review_key,
        inputs=inputs,
        artifacts=artifacts,
        model_input=canonical_json(payload),
    )


def build_report_validation_request(
    manifest: dict[str, Any],
    repository: BuildRepository,
    review_key: str,
) -> AgentReviewRequest:
    """Rebuild exact evidence refs without depending on live model configuration."""
    artifacts, inputs = _review_artifacts_and_inputs(manifest, repository)
    return AgentReviewRequest(
        build_id=manifest["build_id"],
        review_key=review_key,
        inputs=inputs,
        artifacts=artifacts,
        model_input="",
    )


def _review_artifacts_and_inputs(
    manifest: dict[str, Any], repository: BuildRepository
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for artifact_type in REVIEWED_ARTIFACT_TYPES:
        document = repository.load_artifact(manifest, artifact_type)
        artifacts[artifact_type] = {
            "artifact_type": artifact_type,
            "artifact_id": document["artifact_id"],
            "content_hash": document["content_hash"],
            "data": document["data"],
        }

    def reference(artifact_type: str) -> dict[str, str]:
        value = artifacts[artifact_type]
        return {
            "artifact_type": artifact_type,
            "artifact_id": value["artifact_id"],
            "content_hash": value["content_hash"],
        }

    inputs = {
        "article": reference("structured_article"),
        "story_artifacts": [reference(name) for name in STORY_ARTIFACT_TYPES],
        "screenplay_artifacts": [reference(name) for name in SCREENPLAY_ARTIFACT_TYPES],
        "shot_list": reference("shot_list"),
        "storyboard": reference("storyboard"),
        "quality_evidence": [reference(name) for name in QUALITY_EVIDENCE_TYPES],
    }
    return artifacts, inputs


class AgentReviewService:
    _lock_guard = threading.Lock()
    _locks: dict[str, threading.Lock] = {}

    def __init__(
        self,
        *,
        config: PlatformConfig,
        store: AgentReviewStore,
        provider: AgentReviewProvider,
    ) -> None:
        self.config = config
        self.store = store
        self.provider = provider

    @classmethod
    def _lock_for(cls, review_key: str) -> threading.Lock:
        with cls._lock_guard:
            return cls._locks.setdefault(review_key, threading.Lock())

    def run(self, request: AgentReviewRequest) -> tuple[dict[str, Any], bool]:
        trace_id = (
            f"trace_{request.review_key.removeprefix('sha256:')[:32]}"
            if self.config.agent_review_trace_mode == "metadata"
            else None
        )
        with self._lock_for(request.review_key):
            try:
                self._preflight(request)
                provider_result = self.store.get(request.review_key)
                cache_hit = provider_result is not None
                if provider_result is None:
                    provider_result = self.provider.review(request)
                    validate_provider_output(provider_result.output, request)
                    self.store.put(request.review_key, provider_result)
                else:
                    validate_provider_output(provider_result.output, request)
                report = self._report_from_result(
                    request,
                    provider_result,
                    trace_id=trace_id,
                )
            except AgentReviewError as exc:
                cache_hit = False
                report = self._error_report(request, exc, trace_id=trace_id)
            except Exception as exc:
                cache_hit = False
                wrapped = AgentReviewError(
                    "Agent Review provider failed",
                    error_class=_classify_exception(exc),
                    retryable=_classify_exception(exc)
                    in {"RATE_LIMIT", "TIMEOUT", "PROVIDER_UNAVAILABLE"},
                    unavailable=_classify_exception(exc)
                    in {"RATE_LIMIT", "TIMEOUT", "PROVIDER_UNAVAILABLE"},
                    details={"exception_type": type(exc).__name__},
                )
                report = self._error_report(request, wrapped, trace_id=trace_id)
        validate_agent_review_report(report, request)
        return report, cache_hit

    def _preflight(self, request: AgentReviewRequest) -> None:
        encoded_size = len(request.model_input.encode("utf-8"))
        if encoded_size > self.config.agent_review_max_input_bytes:
            raise AgentReviewError(
                "Agent Review input exceeds the configured byte limit",
                error_class="INPUT_LIMIT",
                details={
                    "input_bytes": encoded_size,
                    "maximum": self.config.agent_review_max_input_bytes,
                },
            )
        secret_values = tuple(
            value
            for value in (
                self.config.openai_api_key,
                self.config.runway_api_key,
                self.config.api_token,
            )
            if value
        )
        if SECRET_PATTERN.search(request.model_input) or any(
            value in request.model_input for value in secret_values
        ):
            raise AgentReviewError(
                "Agent Review input was rejected by secret scanning",
                error_class="INTERNAL",
            )

    def _agent_provenance(
        self,
        *,
        sdk_version: str,
        model_resolved: str,
        trace_id: str | None,
        response_id: str | None,
    ) -> dict[str, Any]:
        return {
            "sdk_name": "openai-agents",
            "sdk_version": sdk_version,
            "agent_name": AGENT_REVIEW_AGENT_NAME,
            "agent_version": self.config.agent_review_agent_version,
            "prompt_version": self.config.agent_review_prompt_version,
            "model_requested": self.config.agent_review_model,
            "model_resolved": model_resolved,
            "reasoning_effort": self.config.agent_review_reasoning_effort,
            "trace_id": trace_id,
            "response_id": response_id,
        }

    def _report_from_result(
        self,
        request: AgentReviewRequest,
        result: AgentReviewProviderResult,
        *,
        trace_id: str | None,
    ) -> dict[str, Any]:
        usage = _normalize_usage(result.usage)
        report = {
            "schema_version": "2.1.0",
            "contract_version": AGENT_REVIEW_CONTRACT_VERSION,
            "review_id": f"ARV-{request.review_key.removeprefix('sha256:')[:16]}",
            "build_id": request.build_id,
            "review_key": request.review_key,
            "mode": "review",
            "status": result.output["status"],
            "agent": self._agent_provenance(
                sdk_version=result.sdk_version,
                model_resolved=result.model_resolved,
                trace_id=trace_id,
                response_id=result.response_id,
            ),
            "inputs": request.inputs,
            "dimensions": result.output["dimensions"],
            "findings": result.output["findings"],
            "summary": result.output["summary"],
            "usage": usage,
            "error": None,
            "generated_at": result.created_at,
        }
        report["content_hash"] = content_hash(report)
        return report

    def _error_report(
        self,
        request: AgentReviewRequest,
        error: AgentReviewError,
        *,
        trace_id: str | None,
    ) -> dict[str, Any]:
        status = (
            AgentReviewStatus.UNAVAILABLE.value
            if error.unavailable
            else AgentReviewStatus.ERROR.value
        )
        report = {
            "schema_version": "2.1.0",
            "contract_version": AGENT_REVIEW_CONTRACT_VERSION,
            "review_id": f"ARV-{request.review_key.removeprefix('sha256:')[:16]}",
            "build_id": request.build_id,
            "review_key": request.review_key,
            "mode": "review",
            "status": status,
            "agent": self._agent_provenance(
                sdk_version="unavailable",
                model_resolved=self.config.agent_review_model,
                trace_id=trace_id,
                response_id=None,
            ),
            "inputs": request.inputs,
            "dimensions": [],
            "findings": [],
            "summary": error.message,
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "error": {
                "class": error.error_class,
                "retryable": error.retryable,
                "message": error.message,
            },
            "generated_at": now_iso(),
        }
        report["content_hash"] = content_hash(report)
        return report


def validate_provider_output(output: dict[str, Any], request: AgentReviewRequest) -> None:
    if not isinstance(output, dict):
        raise AgentReviewError(
            "Agent Review output is not an object",
            error_class="INVALID_STRUCTURED_OUTPUT",
        )
    expected = {"status", "dimensions", "findings", "summary"}
    if set(output) != expected:
        raise AgentReviewError(
            "Agent Review output fields do not match the contract",
            error_class="INVALID_STRUCTURED_OUTPUT",
        )
    status = output["status"]
    if status not in {
        AgentReviewStatus.PASS.value,
        AgentReviewStatus.MANUAL_REVIEW_REQUIRED.value,
    }:
        raise AgentReviewError(
            "Model output contains an invalid disposition",
            error_class="INVALID_STRUCTURED_OUTPUT",
        )
    dimensions = output["dimensions"]
    if not isinstance(dimensions, list) or len(dimensions) != len(DIMENSION_CODES):
        raise AgentReviewError(
            "Agent Review must return all registered dimensions",
            error_class="INVALID_STRUCTURED_OUTPUT",
        )
    observed: list[str] = []
    for dimension in dimensions:
        if not isinstance(dimension, dict) or set(dimension) != {
            "code",
            "score",
            "passed",
            "summary",
        }:
            raise AgentReviewError(
                "Agent Review dimension is malformed",
                error_class="INVALID_STRUCTURED_OUTPUT",
            )
        observed.append(dimension["code"])
        if (
            dimension["code"] not in DIMENSION_CODES
            or isinstance(dimension["score"], bool)
            or not isinstance(dimension["score"], (int, float))
            or not 0 <= float(dimension["score"]) <= 1
            or not isinstance(dimension["passed"], bool)
            or not isinstance(dimension["summary"], str)
            or not dimension["summary"].strip()
            or len(dimension["summary"]) > 1000
        ):
            raise AgentReviewError(
                "Agent Review dimension violates its contract",
                error_class="INVALID_STRUCTURED_OUTPUT",
            )
    if set(observed) != set(DIMENSION_CODES) or len(set(observed)) != len(DIMENSION_CODES):
        raise AgentReviewError(
            "Agent Review dimension codes must be complete and unique",
            error_class="INVALID_STRUCTURED_OUTPUT",
        )
    findings = output["findings"]
    if not isinstance(findings, list) or len(findings) > 100:
        raise AgentReviewError(
            "Agent Review findings are malformed",
            error_class="INVALID_STRUCTURED_OUTPUT",
        )
    blocking = 0
    for finding in findings:
        _validate_finding(finding, request)
        blocking += int(finding["blocking"] is True)
    if status == AgentReviewStatus.PASS.value and blocking:
        raise AgentReviewError(
            "PASS cannot contain a blocking finding",
            error_class="INVALID_STRUCTURED_OUTPUT",
        )
    if status == AgentReviewStatus.MANUAL_REVIEW_REQUIRED.value and not blocking:
        raise AgentReviewError(
            "MANUAL_REVIEW_REQUIRED needs a blocking finding",
            error_class="INVALID_STRUCTURED_OUTPUT",
        )
    if not isinstance(output["summary"], str) or not output["summary"].strip():
        raise AgentReviewError(
            "Agent Review summary is required",
            error_class="INVALID_STRUCTURED_OUTPUT",
        )


def _validate_finding(finding: Any, request: AgentReviewRequest) -> None:
    expected = {
        "code",
        "dimension",
        "severity",
        "blocking",
        "title",
        "rationale",
        "evidence_refs",
        "specification_refs",
        "recommendation",
    }
    if not isinstance(finding, dict) or set(finding) != expected:
        raise AgentReviewError(
            "Agent Review finding is malformed",
            error_class="INVALID_STRUCTURED_OUTPUT",
        )
    if not FINDING_CODE.fullmatch(str(finding["code"])):
        raise AgentReviewError("Finding code is invalid", error_class="SCHEMA_VALIDATION")
    if finding["dimension"] not in DIMENSION_CODES:
        raise AgentReviewError("Finding dimension is invalid", error_class="SCHEMA_VALIDATION")
    if finding["severity"] not in {"INFO", "WARNING", "BLOCKING"}:
        raise AgentReviewError("Finding severity is invalid", error_class="SCHEMA_VALIDATION")
    if not isinstance(finding["blocking"], bool) or (
        (finding["severity"] == "BLOCKING") != finding["blocking"]
    ):
        raise AgentReviewError(
            "Blocking severity and flag must agree",
            error_class="SCHEMA_VALIDATION",
        )
    if finding["blocking"] and finding["code"] not in BLOCKING_FINDING_CODES:
        raise AgentReviewError(
            "Blocking finding code is not allow-listed",
            error_class="SCHEMA_VALIDATION",
        )
    for name, maximum in (("title", 200), ("rationale", 2000), ("recommendation", 2000)):
        value = finding[name]
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise AgentReviewError(
                f"Finding {name} is invalid", error_class="SCHEMA_VALIDATION"
            )
    refs = finding["specification_refs"]
    if (
        not isinstance(refs, list)
        or not refs
        or len(refs) > 20
        or len(set(refs)) != len(refs)
        or any(not SPECIFICATION_REF.fullmatch(str(value)) for value in refs)
    ):
        raise AgentReviewError(
            "Finding specification references are invalid",
            error_class="SCHEMA_VALIDATION",
        )
    evidence = finding["evidence_refs"]
    if not isinstance(evidence, list) or not evidence or len(evidence) > 20:
        raise AgentReviewError(
            "Finding evidence is required", error_class="EVIDENCE_RESOLUTION"
        )
    for reference in evidence:
        _validate_evidence(reference, request)


def _validate_evidence(reference: Any, request: AgentReviewRequest) -> None:
    expected = {"artifact_type", "artifact_id", "content_hash", "json_pointer"}
    if not isinstance(reference, dict) or set(reference) != expected:
        raise AgentReviewError(
            "Evidence reference is malformed", error_class="EVIDENCE_RESOLUTION"
        )
    artifact = request.artifacts.get(str(reference["artifact_type"]))
    if (
        artifact is None
        or reference["artifact_id"] != artifact["artifact_id"]
        or reference["content_hash"] != artifact["content_hash"]
    ):
        raise AgentReviewError(
            "Evidence does not resolve to the reviewed input set",
            error_class="EVIDENCE_RESOLUTION",
        )
    _resolve_json_pointer(artifact["data"], reference["json_pointer"])


def _resolve_json_pointer(document: Any, pointer: Any) -> Any:
    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
        raise AgentReviewError(
            "Evidence JSON Pointer is invalid", error_class="EVIDENCE_RESOLUTION"
        )
    current = document
    if pointer == "":
        return current
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(current, list):
                if token == "-" or not token.isdigit():
                    raise KeyError(token)
                current = current[int(token)]
            elif isinstance(current, dict):
                current = current[token]
            else:
                raise KeyError(token)
        except (KeyError, IndexError) as exc:
            raise AgentReviewError(
                "Evidence JSON Pointer does not resolve",
                error_class="EVIDENCE_RESOLUTION",
                details={"json_pointer": pointer},
            ) from exc
    return current


def validate_agent_review_report(
    report: dict[str, Any], request: AgentReviewRequest | None = None
) -> None:
    required = {
        "schema_version",
        "contract_version",
        "review_id",
        "build_id",
        "review_key",
        "mode",
        "status",
        "agent",
        "inputs",
        "dimensions",
        "findings",
        "summary",
        "usage",
        "error",
        "generated_at",
        "content_hash",
    }
    if not isinstance(report, dict) or set(report) != required:
        raise ValidationError("Agent Review Report fields do not match the schema")
    if report["schema_version"] != "2.1.0" or report["contract_version"] != AGENT_REVIEW_CONTRACT_VERSION:
        raise ValidationError("Agent Review Report version is invalid")
    if (
        not re.fullmatch(r"ARV-[A-Za-z0-9._:-]{8,128}", str(report["review_id"]))
        or not isinstance(report["build_id"], str)
        or not 1 <= len(report["build_id"]) <= 128
        or not _is_hash(report["review_key"])
    ):
        raise ValidationError("Agent Review Report identity is invalid")
    if report["mode"] != "review" or report["status"] not in {
        AgentReviewStatus.PASS.value,
        AgentReviewStatus.MANUAL_REVIEW_REQUIRED.value,
        AgentReviewStatus.UNAVAILABLE.value,
        AgentReviewStatus.ERROR.value,
    }:
        raise ValidationError("Agent Review Report disposition is invalid")
    if content_hash({key: value for key, value in report.items() if key != "content_hash"}) != report["content_hash"]:
        raise ValidationError("Agent Review Report content hash is invalid")
    _validate_agent_provenance(report["agent"])
    _validate_report_inputs(report["inputs"])
    usage = report["usage"]
    if (
        not isinstance(usage, dict)
        or not {"input_tokens", "output_tokens", "total_tokens"}.issubset(usage)
        or not set(usage).issubset(
            {"input_tokens", "output_tokens", "total_tokens", "cached_input_tokens"}
        )
        or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in usage.values())
        or usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]
    ):
        raise ValidationError("Agent Review usage is invalid")
    if (
        not isinstance(report["summary"], str)
        or not 1 <= len(report["summary"].strip()) <= 4000
        or not isinstance(report["dimensions"], list)
        or len(report["dimensions"]) > len(DIMENSION_CODES)
        or not isinstance(report["findings"], list)
        or len(report["findings"]) > 100
        or not isinstance(report["generated_at"], str)
        or not report["generated_at"].strip()
    ):
        raise ValidationError("Agent Review Report body is invalid")
    if request is not None:
        if (
            report["build_id"] != request.build_id
            or report["review_key"] != request.review_key
            or report["inputs"] != request.inputs
        ):
            raise ValidationError("Agent Review Report identity is invalid")
        if report["status"] in {
            AgentReviewStatus.PASS.value,
            AgentReviewStatus.MANUAL_REVIEW_REQUIRED.value,
        }:
            validate_provider_output(
                {
                    "status": report["status"],
                    "dimensions": report["dimensions"],
                    "findings": report["findings"],
                    "summary": report["summary"],
                },
                request,
            )
    error = report["error"]
    if report["status"] in {
        AgentReviewStatus.UNAVAILABLE.value,
        AgentReviewStatus.ERROR.value,
    }:
        if not isinstance(error, dict) or set(error) != {"class", "retryable", "message"}:
            raise ValidationError("Agent Review error evidence is required")
        if (
            error["class"]
            not in {
                "AUTHENTICATION",
                "AUTHORIZATION",
                "BUDGET",
                "INPUT_LIMIT",
                "RATE_LIMIT",
                "QUOTA",
                "TIMEOUT",
                "PROVIDER_UNAVAILABLE",
                "INVALID_STRUCTURED_OUTPUT",
                "SCHEMA_VALIDATION",
                "EVIDENCE_RESOLUTION",
                "INTERNAL",
            }
            or not isinstance(error["retryable"], bool)
            or not isinstance(error["message"], str)
            or not 1 <= len(error["message"].strip()) <= 1000
        ):
            raise ValidationError("Agent Review error evidence is invalid")
    elif error is not None:
        raise ValidationError("Successful Agent Review cannot contain an error")


def _validate_agent_provenance(agent: Any) -> None:
    required = {
        "sdk_name",
        "sdk_version",
        "agent_name",
        "agent_version",
        "prompt_version",
        "model_requested",
        "model_resolved",
        "reasoning_effort",
    }
    allowed = required | {"trace_id", "response_id"}
    if (
        not isinstance(agent, dict)
        or not required.issubset(agent)
        or not set(agent).issubset(allowed)
        or agent["sdk_name"] != "openai-agents"
        or agent["agent_name"] != AGENT_REVIEW_AGENT_NAME
    ):
        raise ValidationError("Agent Review provenance is invalid")
    for name in required - {"sdk_name", "agent_name"}:
        value = agent[name]
        maximum = (
            128
            if name in {"model_requested", "model_resolved"}
            else 32 if name == "reasoning_effort" else 64
        )
        if not isinstance(value, str) or not 1 <= len(value) <= maximum:
            raise ValidationError("Agent Review provenance is invalid")
    for name in ("trace_id", "response_id"):
        value = agent.get(name)
        if value is not None and (not isinstance(value, str) or len(value) > 256):
            raise ValidationError("Agent Review provenance is invalid")


def _validate_report_inputs(inputs: Any) -> None:
    expected = {
        "article",
        "story_artifacts",
        "screenplay_artifacts",
        "shot_list",
        "storyboard",
        "quality_evidence",
    }
    if not isinstance(inputs, dict) or set(inputs) != expected:
        raise ValidationError("Agent Review inputs are invalid")
    groups = (
        [inputs["article"]],
        inputs["story_artifacts"],
        inputs["screenplay_artifacts"],
        [inputs["shot_list"]],
        [inputs["storyboard"]],
        inputs["quality_evidence"],
    )
    if any(not isinstance(group, list) or not group for group in groups):
        raise ValidationError("Agent Review inputs are invalid")
    for group in groups:
        for reference in group:
            if (
                not isinstance(reference, dict)
                or set(reference) != {"artifact_type", "artifact_id", "content_hash"}
                or not re.fullmatch(
                    r"[a-z][a-z0-9_-]{0,63}", str(reference["artifact_type"])
                )
                or not isinstance(reference["artifact_id"], str)
                or not 1 <= len(reference["artifact_id"]) <= 256
                or not _is_hash(reference["content_hash"])
            ):
                raise ValidationError("Agent Review input reference is invalid")


def validate_review_approval_binding(binding: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "build_id",
        "gate",
        "approval_ref",
        "mode",
        "execution_plan_content_hash",
        "agent_review_report_content_hash",
        "agent_disposition",
        "bound_at",
        "content_hash",
    }
    if not isinstance(binding, dict) or set(binding) != required:
        raise ValidationError("Review Approval Binding fields do not match the schema")
    if binding["schema_version"] != "2.1.0" or binding["gate"] != "story_approval":
        raise ValidationError("Review Approval Binding identity is invalid")
    if binding["mode"] not in {"off", "review"}:
        raise ValidationError("Review Approval Binding mode is invalid")
    if not _is_hash(binding["execution_plan_content_hash"]):
        raise ValidationError("Review Approval Binding plan hash is invalid")
    if binding["mode"] == "review":
        if not _is_hash(binding["agent_review_report_content_hash"]) or binding[
            "agent_disposition"
        ] not in {
            AgentReviewStatus.PASS.value,
            AgentReviewStatus.MANUAL_REVIEW_REQUIRED.value,
            AgentReviewStatus.UNAVAILABLE.value,
            AgentReviewStatus.ERROR.value,
        }:
            raise ValidationError("Review Approval Binding review evidence is invalid")
    elif (
        binding["agent_review_report_content_hash"] is not None
        or binding["agent_disposition"] is not None
    ):
        raise ValidationError("Off-mode binding cannot contain Agent Review evidence")
    if content_hash({key: value for key, value in binding.items() if key != "content_hash"}) != binding["content_hash"]:
        raise ValidationError("Review Approval Binding content hash is invalid")


def _normalize_usage(usage: dict[str, Any]) -> dict[str, int]:
    input_tokens = max(0, int(usage.get("input_tokens", 0)))
    output_tokens = max(0, int(usage.get("output_tokens", 0)))
    result = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }
    if "cached_input_tokens" in usage:
        result["cached_input_tokens"] = max(0, int(usage["cached_input_tokens"]))
    return result


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"sha256:[a-f0-9]{64}", value) is not None


def _classify_exception(error: Exception) -> str:
    name = type(error).__name__.casefold()
    status = getattr(error, "status_code", None)
    if status == 401 or "authentication" in name:
        return "AUTHENTICATION"
    if status == 403 or "permission" in name or "authorization" in name:
        return "AUTHORIZATION"
    if status == 429 or "rate" in name:
        return "RATE_LIMIT"
    if "timeout" in name:
        return "TIMEOUT"
    if isinstance(status, int) and status >= 500:
        return "PROVIDER_UNAVAILABLE"
    if "validation" in name or "behavior" in name:
        return "INVALID_STRUCTURED_OUTPUT"
    return "INTERNAL"
