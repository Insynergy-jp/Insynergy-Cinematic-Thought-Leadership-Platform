"""Bounded Persona Council runtime and deterministic pre-Story quality gate."""

from __future__ import annotations

import json
import re
import threading
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .creative_scenario import extract_creative_scenario
from .errors import PersonaCouncilError, ValidationError
from .schema_validation import COUNCIL_ROLES, PROPOSAL_ROLES, validate_schema_document
from .util import DETERMINISTIC_TIME, atomic_write_json, content_hash, read_json


PERSONA_CONTRACT_VERSION = "persona-council/1"
PERSONA_QUALITY_VERSION = "persona-quality/1"
PERSONA_POLICY_VERSION = "persona-policy/1"
PERSONA_PROMPT_VERSION = "persona-council-v3"
PERSONA_MANAGER_VERSION = "persona-manager-v2"
PERSONA_PREAPPROVAL_ARTIFACTS = (
    "persona-proposals",
    "persona-red-team-report",
    "persona-deliberation",
    "persona",
    "persona-quality-report",
)
PERSONA_FIELDS = (
    "role",
    "job_to_be_done",
    "dominant_desire",
    "dominant_fear",
    "internal_contradiction",
    "decision_pressure",
    "authority_boundary",
    "current_workaround",
    "emotional_arc_candidate",
)
PROHIBITED_INVENTIONS = (
    "DEMOGRAPHICS",
    "FABRICATED_QUOTE",
    "MEDICAL_CONDITION",
    "TRAUMA",
    "VULNERABLE_SETTING",
    "PERSONAL_HISTORY",
    "UNSUPPORTED_RELATIONSHIP",
)
PERSONA_CHECKS = (
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


@dataclass(frozen=True)
class CreativeBrief:
    title: str
    body: str
    source_path: str

    @property
    def data(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "body": self.body,
            "source_path": self.source_path,
        }

    @property
    def content_hash(self) -> str:
        return content_hash({"title": self.title, "body": self.body})

    @property
    def scenario(self) -> dict[str, Any] | None:
        return extract_creative_scenario(
            self.body, creative_brief_hash=self.content_hash
        )


def load_creative_brief(path: Path) -> CreativeBrief:
    try:
        body = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValidationError(f"Unable to load Creative Brief: {path}") from exc
    if not body:
        raise ValidationError("Creative Brief must not be empty")
    if len(body.encode("utf-8")) > 131_072:
        raise ValidationError("Creative Brief exceeds the 128 KiB limit")
    title = path.stem.replace("-", " ").replace("_", " ").strip()
    for line in body.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    return CreativeBrief(title=title or "Creative Brief", body=body, source_path=str(path.resolve()))


@dataclass(frozen=True)
class PersonaCouncilRequest:
    build_id: str
    article_hash: str
    creative_brief_hash: str
    article: dict[str, Any]
    creative_brief: dict[str, Any]
    deliberation_key: str
    model: str
    reasoning_effort: str
    max_output_tokens: int
    timeout_seconds: int
    manager_agent_version: str
    prompt_version: str
    policy_version: str

    @property
    def model_input(self) -> str:
        return json.dumps(
            {
                "boundary": {
                    "article_hash": self.article_hash,
                    "creative_brief_hash": self.creative_brief_hash,
                    "deliberation_key": self.deliberation_key,
                    "untrusted_data": True,
                },
                "evidence_contract": {
                    "SOURCE": {
                        "artifact_hash": self.article_hash,
                        "rule": "Every SOURCE field must reference only evidence carrying this exact artifact_hash.",
                    },
                    "CREATIVE_BRIEF": {
                        "artifact_hash": self.creative_brief_hash,
                        "rule": "Every CREATIVE_BRIEF field must reference only evidence carrying this exact artifact_hash.",
                    },
                    "ASSUMPTION": {
                        "rule": "Every ASSUMPTION field must reference only a declared assumption_id, never an evidence_id.",
                    },
                    "identity_rule": "Use distinct evidence_id values when evidence comes from different artifacts.",
                },
                "article": self.article,
                "creative_brief": self.creative_brief,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True)
class PersonaCouncilProviderResult:
    output: dict[str, Any]
    invocation_roles: tuple[str, ...]
    sdk_version: str
    model_resolved: str
    usage: dict[str, int | float]
    response_id: str | None = None


class PersonaCouncilProvider(Protocol):
    def deliberate(self, request: PersonaCouncilRequest) -> PersonaCouncilProviderResult:
        ...


class PersonaCouncilCache:
    """Immutable exact-key cache for the first accepted model selection."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()
        self.last_corrupt = False

    def _path(self, deliberation_key: str) -> Path:
        digest = deliberation_key.removeprefix("sha256:")
        return self.root / f"{digest}.json"

    def get(self, deliberation_key: str) -> PersonaCouncilProviderResult | None:
        path = self._path(deliberation_key)
        if not path.is_file():
            self.last_corrupt = False
            return None
        try:
            document = read_json(path)
            if document.get("deliberation_key") != deliberation_key:
                raise ValidationError("Persona cache key mismatch")
            selection = document.get("selection")
            if not isinstance(selection, dict):
                raise ValidationError("Persona cache payload is invalid")
            if document.get("content_hash") != content_hash(selection):
                raise ValidationError("Persona cache integrity failure")
            result = PersonaCouncilProviderResult(
                output=selection["output"],
                invocation_roles=tuple(selection["invocation_roles"]),
                sdk_version=selection["sdk_version"],
                model_resolved=selection["model_resolved"],
                usage=selection["usage"],
                response_id=selection.get("response_id"),
            )
        except (OSError, KeyError, TypeError, ValueError, ValidationError):
            self.last_corrupt = True
            return None
        self.last_corrupt = False
        return deepcopy(result)

    def put(
        self,
        deliberation_key: str,
        result: PersonaCouncilProviderResult,
    ) -> None:
        selection = {
            "output": result.output,
            "invocation_roles": list(result.invocation_roles),
            "sdk_version": result.sdk_version,
            "model_resolved": result.model_resolved,
            "usage": result.usage,
            "response_id": result.response_id,
        }
        document = {
            "deliberation_key": deliberation_key,
            "selection": selection,
            "content_hash": content_hash(selection),
        }
        with self._lock:
            path = self._path(deliberation_key)
            if path.is_file():
                existing = read_json(path)
                if existing == document:
                    return
                raise ValidationError("Persona cache entry is immutable")
            atomic_write_json(path, document)


def _seal(document: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(document)
    value.pop("content_hash", None)
    value["content_hash"] = content_hash(value)
    return value


def _identifier(prefix: str, value: Any) -> str:
    return f"{prefix}-{content_hash(value).removeprefix('sha256:')[:20]}"


def _usage(value: dict[str, int | float]) -> dict[str, Any]:
    input_tokens = max(0, int(value.get("input_tokens", 0)))
    output_tokens = max(0, int(value.get("output_tokens", 0)))
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "estimated_cost_usd": max(0.0, float(value.get("estimated_cost_usd", 0.0))),
    }


def _contains_forbidden_runtime_data(value: Any) -> bool:
    forbidden_keys = {
        "chain_of_thought",
        "reasoning_trace",
        "raw_transcript",
        "raw_prompt",
        "raw_response",
        "api_key",
        "authorization",
        "credentials",
        "environment",
    }
    secret_patterns = (
        re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
        re.compile(r"\bBearer\s+[A-Za-z0-9._-]{12,}\b", re.IGNORECASE),
    )
    if isinstance(value, dict):
        return any(
            str(key).casefold() in forbidden_keys
            or _contains_forbidden_runtime_data(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_runtime_data(child) for child in value)
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in secret_patterns)
    return False


def _validate_field(field: Any, evidence_ids: set[str], assumption_ids: set[str]) -> bool:
    if not isinstance(field, dict) or set(field) != {"value", "basis", "evidence_refs"}:
        return False
    if not isinstance(field.get("value"), str) or not field["value"].strip():
        return False
    basis = field.get("basis")
    references = field.get("evidence_refs")
    if basis not in {"SOURCE", "CREATIVE_BRIEF", "ASSUMPTION"} or not isinstance(references, list):
        return False
    allowed = assumption_ids if basis == "ASSUMPTION" else evidence_ids
    return bool(references) and set(references).issubset(allowed)


def _evidence_lineage_valid(
    fields: dict[str, Any],
    evidence: list[Any],
    *,
    article_hash: str,
    creative_brief_hash: str,
) -> bool:
    by_id = {
        str(item.get("evidence_id")): item
        for item in evidence
        if isinstance(item, dict)
    }
    allowed_hashes = {article_hash, creative_brief_hash}
    if not by_id or any(item.get("artifact_hash") not in allowed_hashes for item in by_id.values()):
        return False
    expected_by_basis = {
        "SOURCE": article_hash,
        "CREATIVE_BRIEF": creative_brief_hash,
    }
    for field in fields.values():
        if not isinstance(field, dict) or field.get("basis") not in expected_by_basis:
            continue
        expected = expected_by_basis[field["basis"]]
        if any(by_id.get(reference, {}).get("artifact_hash") != expected for reference in field.get("evidence_refs", [])):
            return False
    return True


def _prohibited_invention_free(fields: dict[str, Any], assumptions: list[Any]) -> bool:
    """Reject sensitive biography smuggled in as an unsupported assumption."""
    patterns = (
        re.compile(r"\b(?:diagnos(?:is|ed)|medical condition|mental illness|trauma|abuse)\b", re.IGNORECASE),
        re.compile(r"\b(?:race|ethnicity|religion|sexual orientation|pregnan(?:t|cy))\b", re.IGNORECASE),
        re.compile(r"\b(?:wife|husband|daughter|son|widow|divorc(?:e|ed))\b", re.IGNORECASE),
        re.compile(r"\b(?:homeless|refugee|survivor|victim)\b", re.IGNORECASE),
    )
    candidates = [
        field.get("value", "")
        for field in fields.values()
        if isinstance(field, dict) and field.get("basis") == "ASSUMPTION"
    ]
    candidates.extend(
        item.get("statement", "") for item in assumptions if isinstance(item, dict)
    )
    return not any(pattern.search(str(value)) for value in candidates for pattern in patterns)


def validate_persona_preapproval_bundle(
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if set(artifacts) != set(PERSONA_PREAPPROVAL_ARTIFACTS):
        raise ValidationError("Persona pre-approval bundle must contain exactly five artifacts")
    for name in PERSONA_PREAPPROVAL_ARTIFACTS:
        document = artifacts[name]
        validate_schema_document(name, document)
        expected = content_hash({key: value for key, value in document.items() if key != "content_hash"})
        if document.get("content_hash") != expected:
            raise ValidationError(f"Persona artifact integrity failure: {name}")
    proposals = artifacts["persona-proposals"]
    red_team = artifacts["persona-red-team-report"]
    deliberation = artifacts["persona-deliberation"]
    persona = artifacts["persona"]
    quality = artifacts["persona-quality-report"]
    identities = ("build_id", "deliberation_key", "article_hash", "creative_brief_hash")
    for field in identities:
        if len({document[field] for document in artifacts.values()}) != 1:
            raise ValidationError(f"Persona identity mismatch: {field}")
    roles = [proposal["role"] for proposal in proposals["proposals"]]
    if sorted(roles) != sorted(PROPOSAL_ROLES):
        raise ValidationError("Persona proposal roles are incomplete")
    proposal_hashes = set()
    for proposal in proposals["proposals"]:
        expected = content_hash({key: value for key, value in proposal.items() if key != "proposal_hash"})
        if proposal["proposal_hash"] != expected:
            raise ValidationError("Persona proposal hash mismatch")
        proposal_hashes.add(expected)
    if red_team["proposal_set_hash"] != proposals["content_hash"]:
        raise ValidationError("Persona Red-Team input hash mismatch")
    objection_ids = {item["objection_id"] for item in red_team["objections"]}
    if any(item["proposal_hash"] not in proposal_hashes for item in red_team["objections"]):
        raise ValidationError("Persona Red-Team proposal reference is invalid")
    if (
        deliberation["proposal_set_hash"] != proposals["content_hash"]
        or deliberation["red_team_report_hash"] != red_team["content_hash"]
        or {item["objection_id"] for item in deliberation["resolutions"]} != objection_ids
    ):
        raise ValidationError("Persona deliberation does not resolve its sealed inputs")
    ledger_roles = [item["role"] for item in deliberation["invocation_ledger"]]
    if sorted(ledger_roles) != sorted(COUNCIL_ROLES) or any(
        item["attempt"] != 1 or item["accepted"] is not True
        for item in deliberation["invocation_ledger"]
    ):
        raise ValidationError("Persona invocation ledger is not exactly one finite round")
    if (
        quality["proposal_set_hash"] != proposals["content_hash"]
        or quality["red_team_report_hash"] != red_team["content_hash"]
        or quality["deliberation_hash"] != deliberation["content_hash"]
        or quality["persona_hash"] != persona["content_hash"]
    ):
        raise ValidationError("Persona Quality Report evidence is stale")
    return {
        "passed": quality["status"] == "PASS",
        "status": quality["status"],
        "artifact_count": 5,
        "deliberation_key": persona["deliberation_key"],
        "persona_hash": persona["content_hash"],
        "quality_report_hash": quality["content_hash"],
    }


class PersonaCouncilService:
    """Own one bounded deliberation and emit the five pre-approval contracts."""

    _lock_guard = threading.Lock()
    _locks: dict[str, threading.Lock] = {}

    def __init__(
        self,
        *,
        provider: PersonaCouncilProvider,
        cache: PersonaCouncilCache,
        max_input_bytes: int,
        preflight_estimated_cost_usd: float,
        max_cost_usd: float,
    ) -> None:
        self.provider = provider
        self.cache = cache
        self.max_input_bytes = max_input_bytes
        self.preflight_estimated_cost_usd = preflight_estimated_cost_usd
        self.max_cost_usd = max_cost_usd
        self.last_cache_hit = False

    @classmethod
    def _lock_for(cls, key: str) -> threading.Lock:
        with cls._lock_guard:
            return cls._locks.setdefault(key, threading.Lock())

    def run(self, request: PersonaCouncilRequest) -> dict[str, dict[str, Any]]:
        encoded_size = len(request.model_input.encode("utf-8"))
        if encoded_size > self.max_input_bytes:
            raise PersonaCouncilError(
                "Persona Council input exceeds the configured limit",
                error_class="INPUT_LIMIT",
            )
        if self.preflight_estimated_cost_usd > self.max_cost_usd:
            raise PersonaCouncilError(
                "Persona Council preflight estimate exceeds the planning AI budget",
                error_class="BUDGET",
                details={
                    "preflight_estimated_cost_usd": self.preflight_estimated_cost_usd,
                    "max_cost_usd": self.max_cost_usd,
                    "provider_contacted": False,
                },
            )
        with self._lock_for(request.deliberation_key):
            result = self.cache.get(request.deliberation_key)
            if result is not None:
                self.last_cache_hit = True
            else:
                self.last_cache_hit = False
                try:
                    result = self.provider.deliberate(request)
                except PersonaCouncilError:
                    raise
                except Exception as exc:
                    raise PersonaCouncilError(
                        "Persona Council provider failed",
                        error_class="PROVIDER_UNAVAILABLE",
                        unavailable=True,
                    ) from exc
            artifacts = self._materialize(request, result)
            report = validate_persona_preapproval_bundle(artifacts)
            if not report["passed"]:
                quality = artifacts["persona-quality-report"]
                failed_checks = [
                    check["check_id"]
                    for check in quality["checks"]
                    if check["passed"] is not True
                ]
                raise PersonaCouncilError(
                    "Persona Quality Gate did not pass",
                    error_class="QUALITY",
                    details={
                        **report,
                        "failed_checks": failed_checks,
                        "findings": quality["findings"],
                        "non_waivable_failures": quality[
                            "non_waivable_failures"
                        ],
                    },
                )
            if not self.last_cache_hit:
                self.cache.put(request.deliberation_key, result)
            return artifacts

    def _materialize(
        self,
        request: PersonaCouncilRequest,
        result: PersonaCouncilProviderResult,
    ) -> dict[str, dict[str, Any]]:
        if tuple(result.invocation_roles) != COUNCIL_ROLES:
            raise PersonaCouncilError(
                "Persona Council did not execute the exact finite protocol",
                error_class="TOPOLOGY",
                details={"invocation_roles": list(result.invocation_roles)},
            )
        if _contains_forbidden_runtime_data(result.output):
            raise PersonaCouncilError(
                "Persona Council output contains prohibited runtime data",
                error_class="SECURITY",
            )
        output = result.output
        raw_proposals = output.get("proposals")
        if not isinstance(raw_proposals, list) or len(raw_proposals) != 3:
            raise PersonaCouncilError("Persona proposal cardinality is invalid", error_class="CARDINALITY")
        provenance = {
            "sdk_version": result.sdk_version,
            "manager_agent_version": request.manager_agent_version,
            "prompt_version": request.prompt_version,
            "policy_version": request.policy_version,
            "models_by_role": {role: result.model_resolved for role in COUNCIL_ROLES},
        }
        usage = _usage(result.usage)
        usage["estimated_cost_usd"] = max(
            usage["estimated_cost_usd"], self.preflight_estimated_cost_usd
        )
        if usage["estimated_cost_usd"] > self.max_cost_usd:
            raise PersonaCouncilError(
                "Persona Council cost exceeds the planning AI budget",
                error_class="BUDGET",
                details={"estimated_cost_usd": usage["estimated_cost_usd"]},
            )
        proposals: list[dict[str, Any]] = []
        proposal_by_role: dict[str, dict[str, Any]] = {}
        for raw in raw_proposals:
            if not isinstance(raw, dict):
                raise PersonaCouncilError("Persona proposal is not an object", error_class="SCHEMA")
            role = str(raw.get("role", ""))
            if role not in PROPOSAL_ROLES or role in proposal_by_role:
                raise PersonaCouncilError("Persona proposal roles are invalid", error_class="CARDINALITY")
            proposal = {
                "proposal_id": _identifier(f"PRP-{role}", raw),
                "role": role,
                "persona_fields": raw.get("persona_fields"),
                "evidence": raw.get("evidence", []),
                "assumptions": raw.get("assumptions", []),
            }
            proposal["proposal_hash"] = content_hash(proposal)
            proposals.append(proposal)
            proposal_by_role[role] = proposal
        proposal_set = _seal(
            {
                "schema_version": "3.3.0",
                "contract_version": PERSONA_CONTRACT_VERSION,
                "build_id": request.build_id,
                "deliberation_key": request.deliberation_key,
                "article_hash": request.article_hash,
                "creative_brief_hash": request.creative_brief_hash,
                "proposals": proposals,
                "agent_provenance": provenance,
                "usage": usage,
                "generated_at": DETERMINISTIC_TIME,
            }
        )

        objections: list[dict[str, Any]] = []
        for raw in output.get("objections", []):
            proposal_role = str(raw.get("proposal_role", ""))
            proposal = proposal_by_role.get(proposal_role)
            if proposal is None:
                raise PersonaCouncilError("Red-Team proposal reference is invalid", error_class="EVIDENCE")
            objection = {
                "objection_id": _identifier("OBJ-persona", raw),
                "code": raw.get("code"),
                "severity": raw.get("severity"),
                "blocking": raw.get("blocking"),
                "proposal_hash": proposal["proposal_hash"],
                "evidence_refs": raw.get("evidence_refs", []),
                "summary": raw.get("summary"),
            }
            objections.append(objection)
        red_team = _seal(
            {
                "schema_version": "3.3.0",
                "contract_version": PERSONA_CONTRACT_VERSION,
                "report_id": _identifier("PRT-red-team", objections),
                "build_id": request.build_id,
                "deliberation_key": request.deliberation_key,
                "article_hash": request.article_hash,
                "creative_brief_hash": request.creative_brief_hash,
                "proposal_set_hash": proposal_set["content_hash"],
                "objections": objections,
                "critic_provenance": provenance,
                "usage": usage,
                "generated_at": DETERMINISTIC_TIME,
            }
        )

        objection_ids = {item["objection_id"] for item in objections}
        resolutions = []
        for raw in output.get("resolutions", []):
            objection_index = raw.get("objection_index")
            if not isinstance(objection_index, int) or not 0 <= objection_index < len(objections):
                raise PersonaCouncilError("Persona objection resolution is invalid", error_class="EVIDENCE")
            resolutions.append(
                {
                    "objection_id": objections[objection_index]["objection_id"],
                    "disposition": raw.get("disposition"),
                    "changed_fields": raw.get("changed_fields", []),
                    "summary": raw.get("summary"),
                }
            )
        if {item["objection_id"] for item in resolutions} != objection_ids:
            raise PersonaCouncilError("Every Red-Team objection must be resolved or exposed", error_class="EVIDENCE")

        def element_decisions(name: str) -> list[dict[str, Any]]:
            decisions = []
            for raw in output.get(name, []):
                proposal = proposal_by_role.get(str(raw.get("proposal_role", "")))
                if proposal is None:
                    raise PersonaCouncilError("Persona element proposal does not resolve", error_class="EVIDENCE")
                decisions.append(
                    {
                        "proposal_hash": proposal["proposal_hash"],
                        "field": raw.get("field"),
                        "summary": raw.get("summary"),
                    }
                )
            return decisions

        manager_output_hash = content_hash(
            {
                "persona_fields": output.get("persona_fields"),
                "evidence": output.get("evidence"),
                "assumptions": output.get("assumptions"),
                "resolutions": resolutions,
            }
        )
        output_hashes = {
            **{role: proposal_by_role[role]["proposal_hash"] for role in PROPOSAL_ROLES},
            "red_team_critic": red_team["content_hash"],
            "persona_manager": manager_output_hash,
        }
        deliberation = _seal(
            {
                "schema_version": "3.3.0",
                "contract_version": PERSONA_CONTRACT_VERSION,
                "deliberation_id": _identifier("DEL-persona", request.deliberation_key),
                "build_id": request.build_id,
                "deliberation_key": request.deliberation_key,
                "article_hash": request.article_hash,
                "creative_brief_hash": request.creative_brief_hash,
                "proposal_set_hash": proposal_set["content_hash"],
                "red_team_report_hash": red_team["content_hash"],
                "resolutions": resolutions,
                "selected_elements": element_decisions("selected_elements"),
                "rejected_elements": element_decisions("rejected_elements"),
                "invocation_ledger": [
                    {
                        "role": role,
                        "attempt": 1,
                        "accepted": True,
                        "input_hash": request.deliberation_key,
                        "output_hash": output_hashes[role],
                    }
                    for role in COUNCIL_ROLES
                ],
                "manager_provenance": provenance,
                "usage": usage,
                "generated_at": DETERMINISTIC_TIME,
            }
        )

        persona_fields = output.get("persona_fields")
        evidence = output.get("evidence", [])
        assumptions = output.get("assumptions", [])
        if not isinstance(persona_fields, dict) or set(persona_fields) != set(PERSONA_FIELDS):
            raise PersonaCouncilError("Persona Manager did not produce exactly one field set", error_class="CARDINALITY")
        evidence_ids = {
            str(item.get("evidence_id")) for item in evidence if isinstance(item, dict)
        }
        assumption_ids = {
            str(item.get("assumption_id")) for item in assumptions if isinstance(item, dict)
        }
        field_valid = all(
            _validate_field(persona_fields[field], evidence_ids, assumption_ids)
            for field in PERSONA_FIELDS
        ) and _evidence_lineage_valid(
            persona_fields,
            evidence,
            article_hash=request.article_hash,
            creative_brief_hash=request.creative_brief_hash,
        )
        assumptions_valid = all(
            isinstance(item, dict)
            and item.get("risk") in {"LOW", "MEDIUM", "HIGH"}
            and (item.get("risk") != "HIGH" or item.get("requires_human_attention") is True)
            for item in assumptions
        )
        persona = _seal(
            {
                "schema_version": "3.3.0",
                "contract_version": PERSONA_CONTRACT_VERSION,
                "persona_id": _identifier("PER-executive", persona_fields),
                "build_id": request.build_id,
                "deliberation_key": request.deliberation_key,
                "article_hash": request.article_hash,
                "creative_brief_hash": request.creative_brief_hash,
                **deepcopy(persona_fields),
                "evidence": deepcopy(evidence),
                "assumptions": deepcopy(assumptions),
                "prohibited_inventions": list(PROHIBITED_INVENTIONS),
                "unresolved_questions": output.get("unresolved_questions", []),
                "source_fidelity": output.get("source_fidelity"),
                "story_usability": output.get("story_usability"),
                "agent_provenance": provenance,
                "generated_at": DETERMINISTIC_TIME,
            }
        )

        checks = {
            "proposal_cardinality": len(proposals) == 3 and set(proposal_by_role) == set(PROPOSAL_ROLES),
            "red_team_resolution": {item["objection_id"] for item in resolutions} == objection_ids,
            "manager_synthesis": set(persona_fields) == set(PERSONA_FIELDS),
            "factual_evidence": field_valid,
            "assumption_lineage": assumptions_valid,
            "prohibited_inventions": (
                list(persona["prohibited_inventions"]) == list(PROHIBITED_INVENTIONS)
                and _prohibited_invention_free(persona_fields, assumptions)
            ),
            "persona_singularity": bool(persona_fields["role"]["value"]),
            "story_usability": isinstance(persona["story_usability"], (int, float)) and persona["story_usability"] >= 0.8,
            "identity_integrity": all((request.build_id, request.article_hash, request.creative_brief_hash, request.deliberation_key)),
            "security_hygiene": not _contains_forbidden_runtime_data(persona),
        }
        status = "PASS" if all(checks.values()) else "MANUAL_REVIEW_REQUIRED"
        failed = [check_id for check_id, passed in checks.items() if not passed]
        quality = _seal(
            {
                "schema_version": "3.3.0",
                "contract_version": PERSONA_QUALITY_VERSION,
                "report_id": _identifier("PQR-persona", persona["content_hash"]),
                "build_id": request.build_id,
                "deliberation_key": request.deliberation_key,
                "article_hash": request.article_hash,
                "creative_brief_hash": request.creative_brief_hash,
                "proposal_set_hash": proposal_set["content_hash"],
                "red_team_report_hash": red_team["content_hash"],
                "deliberation_hash": deliberation["content_hash"],
                "persona_hash": persona["content_hash"],
                "status": status,
                "checks": [
                    {
                        "check_id": check_id,
                        "passed": checks[check_id],
                        "evidence_hashes": [persona["content_hash"]],
                    }
                    for check_id in PERSONA_CHECKS
                ],
                "non_waivable_failures": (
                    ["EVIDENCE"] if any(check in failed for check in ("factual_evidence", "assumption_lineage")) else []
                ),
                "findings": [
                    {
                        "code": f"PQ-{check_id.upper()}",
                        "severity": "BLOCKING",
                        "waivable": False,
                        "summary": f"Persona check failed: {check_id}",
                        "evidence_refs": [persona["persona_id"]],
                    }
                    for check_id in failed
                ],
                "policy_version": request.policy_version,
                "generated_at": DETERMINISTIC_TIME,
            }
        )
        artifacts = {
            "persona-proposals": proposal_set,
            "persona-red-team-report": red_team,
            "persona-deliberation": deliberation,
            "persona": persona,
            "persona-quality-report": quality,
        }
        for name, document in artifacts.items():
            try:
                validate_schema_document(name, document)
            except ValidationError as exc:
                raise PersonaCouncilError(
                    f"Persona Council emitted invalid {name}",
                    error_class="INVALID_STRUCTURED_OUTPUT",
                    details=exc.details,
                ) from exc
        return artifacts


def deliberation_key(
    *,
    article_hash: str,
    creative_brief_hash: str,
    model: str,
    reasoning_effort: str,
    manager_agent_version: str,
    prompt_version: str,
    policy_version: str,
) -> str:
    return content_hash(
        {
            "article_hash": article_hash,
            "creative_brief_hash": creative_brief_hash,
            "contract_version": PERSONA_CONTRACT_VERSION,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "manager_agent_version": manager_agent_version,
            "prompt_version": prompt_version,
            "policy_version": policy_version,
            "rounds": {"proposals": 1, "red_team": 1, "synthesis": 1},
        }
    )
