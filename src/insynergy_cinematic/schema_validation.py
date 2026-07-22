"""Fail-closed Part 9 schema audit, instance validation, and bundle invariants."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .errors import ValidationError
from .schemas import SCHEMA_METADATA, SCHEMA_NAMES
from .util import canonical_json, content_hash, file_hash, read_json


DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_NAMESPACE = "https://schemas.insynergy.co/cttp/"
PERSONA_NAMES = (
    "persona-proposals",
    "persona-red-team-report",
    "persona-deliberation",
    "persona",
    "persona-quality-report",
    "persona-approval-binding",
)
PROPOSAL_ROLES = (
    "audience_researcher",
    "empathy_narrative_analyst",
    "brand_strategist",
)
COUNCIL_ROLES = (*PROPOSAL_ROLES, "red_team_critic", "persona_manager")
ERROR_CODES = {
    "E-SCHEMA-001": "required field is absent",
    "E-SCHEMA-002": "value has the wrong type",
    "E-SCHEMA-003": "unexpected property is present",
    "E-SCHEMA-004": "value is outside a controlled vocabulary",
    "E-SCHEMA-005": "identifier or text does not match its pattern",
    "E-SCHEMA-006": "formatted value is invalid",
    "E-SCHEMA-007": "cardinality or numeric constraint is violated",
    "E-REF-001": "schema or artifact reference does not resolve",
    "E-REF-002": "cross-artifact coverage is incomplete or duplicated",
    "E-REF-003": "ordering or dependency relation is invalid",
    "E-FIX-001": "content hash does not verify",
    "E-APPROVAL-001": "approval binding is absent, stale, or mismatched",
    "E-IMMUT-001": "compatibility baseline changed in place",
}


def _default_root() -> Path:
    packaged = Path(__file__).resolve().parent / "schema_data"
    if packaged.is_dir():
        return packaged
    return Path(__file__).resolve().parents[2] / "schemas"


def _documents(root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_filename: dict[str, dict[str, Any]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*.schema.json")):
        document = read_json(path)
        if not isinstance(document, dict):
            raise ValidationError(
                "Schema document must be an object",
                details={"code": "E-SCHEMA-002", "file": path.name},
            )
        by_filename[path.name] = document
        schema_id = document.get("$id")
        if isinstance(schema_id, str):
            if schema_id in by_id:
                raise ValidationError(
                    "Duplicate schema $id",
                    details={"code": "E-REF-002", "schema_id": schema_id},
                )
            by_id[schema_id] = document
    return by_filename, by_id


def _pointer(document: Any, fragment: str) -> Any:
    current = document
    if not fragment:
        return current
    if not fragment.startswith("/"):
        raise ValidationError(
            "Only JSON Pointer schema fragments are supported",
            details={"code": "E-REF-001", "fragment": fragment},
        )
    for token in fragment.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or token not in current:
            raise ValidationError(
                "Schema reference fragment does not resolve",
                details={"code": "E-REF-001", "fragment": fragment},
            )
        current = current[token]
    return current


def _resolve(
    reference: str,
    current: dict[str, Any],
    by_filename: dict[str, dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    target, _, fragment = reference.partition("#")
    document = current
    if target:
        document = by_id.get(target)  # type: ignore[assignment]
        if document is None:
            document = by_filename.get(Path(urlparse(target).path).name)  # type: ignore[assignment]
        if document is None:
            raise ValidationError(
                "Schema reference does not resolve",
                details={"code": "E-REF-001", "reference": reference},
            )
    schema = _pointer(document, fragment)
    if not isinstance(schema, dict):
        raise ValidationError(
            "Schema reference target is not a schema",
            details={"code": "E-REF-001", "reference": reference},
        )
    return schema, document


def _walk(value: Any, pointer: str = ""):
    if isinstance(value, dict):
        yield pointer, value
        for key, child in value.items():
            escaped = key.replace("~", "~0").replace("/", "~1")
            yield from _walk(child, f"{pointer}/{escaped}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{pointer}/{index}")


def audit_schema_bundle(root: Path | None = None) -> dict[str, Any]:
    """Audit dialect, identity, registry, references, closure, and compatibility."""
    root = (root or _default_root()).resolve()
    by_filename, by_id = _documents(root)
    errors: list[dict[str, Any]] = []
    allowed_ids = set()
    closed_objects = 0
    object_schemas = 0
    for filename, document in sorted(by_filename.items()):
        schema_id = document.get("$id")
        if document.get("$schema") != DIALECT:
            errors.append({"code": "E-SCHEMA-006", "file": filename, "message": "wrong dialect"})
        if not isinstance(schema_id, str) or not schema_id.startswith(SCHEMA_NAMESPACE):
            errors.append({"code": "E-SCHEMA-005", "file": filename, "message": "invalid $id namespace"})
        elif Path(urlparse(schema_id).path).name != filename:
            errors.append({"code": "E-SCHEMA-005", "file": filename, "message": "$id leaf mismatch"})
        else:
            allowed_ids.add(schema_id)
        persona = filename.removesuffix(".schema.json") in PERSONA_NAMES
        for pointer, schema in _walk(document):
            required = schema.get("required")
            if required is not None and (
                not isinstance(required, list)
                or len(required) != len(set(required))
                or not all(isinstance(item, str) for item in required)
            ):
                errors.append({"code": "E-SCHEMA-001", "file": filename, "pointer": pointer, "message": "invalid required list"})
            if schema.get("type") == "object":
                object_schemas += 1
                closed = "additionalProperties" in schema or schema.get("unevaluatedProperties") is False
                if closed:
                    closed_objects += 1
                if persona and not closed:
                    errors.append({"code": "E-SCHEMA-003", "file": filename, "pointer": pointer, "message": "Persona object boundary is not closed"})
            reference = schema.get("$ref")
            if isinstance(reference, str):
                try:
                    _resolve(reference, document, by_filename, by_id)
                except ValidationError as exc:
                    errors.append({"code": "E-REF-001", "file": filename, "pointer": pointer, "message": exc.message})

    registry_path = root / "schema-registry.json"
    if not registry_path.is_file():
        errors.append({"code": "E-REF-001", "file": "schema-registry.json", "message": "registry is missing"})
        registry = {}
    else:
        registry = read_json(registry_path)
    entries = registry.get("schemas", []) if isinstance(registry, dict) else []
    if registry.get("schema_version") != "3.3.0" or registry.get("dialect") != DIALECT:
        errors.append({"code": "E-SCHEMA-006", "file": "schema-registry.json", "message": "registry version or dialect is invalid"})
    if registry.get("content_hash") != content_hash(entries):
        errors.append({"code": "E-FIX-001", "file": "schema-registry.json", "message": "registry hash mismatch"})
    names: set[str] = set()
    files: set[str] = set()
    ids: set[str] = set()
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or set(entry) != {"name", "file", "id", "version", "owner", "chapter"}:
            errors.append({"code": "E-SCHEMA-001", "file": "schema-registry.json", "message": "registry entry contract mismatch"})
            continue
        name = entry["name"]
        filename = entry["file"]
        schema_id = entry["id"]
        if name in names or filename in files or schema_id in ids:
            errors.append({"code": "E-REF-002", "file": "schema-registry.json", "message": "duplicate registry identity"})
        names.add(name)
        files.add(filename)
        ids.add(schema_id)
        metadata = SCHEMA_METADATA.get(name)
        document = by_filename.get(filename)
        if metadata is None or any(entry[key] != metadata[key] for key in ("version", "owner", "chapter")):
            errors.append({"code": "E-REF-001", "file": filename, "message": "registry ownership metadata mismatch"})
        if document is None or document.get("$id") != schema_id:
            errors.append({"code": "E-REF-001", "file": filename, "message": "registry target mismatch"})
    if names != set(SCHEMA_NAMES) or files != {f"{name}.schema.json" for name in SCHEMA_NAMES}:
        errors.append({"code": "E-REF-002", "file": "schema-registry.json", "message": "registry is not exhaustive"})

    baseline_path = root / "compatibility-baseline.json"
    if not baseline_path.is_file():
        errors.append({"code": "E-IMMUT-001", "file": baseline_path.name, "message": "compatibility baseline is missing"})
        baseline = {}
    else:
        baseline = read_json(baseline_path)
    baseline_files = baseline.get("files", {}) if isinstance(baseline, dict) else {}
    if baseline.get("content_hash") != content_hash(baseline_files):
        errors.append({"code": "E-FIX-001", "file": baseline_path.name, "message": "baseline hash mismatch"})
    if isinstance(baseline_files, dict):
        for filename, expected in baseline_files.items():
            path = root / filename
            if not path.is_file() or file_hash(path) != expected:
                errors.append({"code": "E-IMMUT-001", "file": filename, "message": "released schema changed"})
    if errors:
        raise ValidationError("Part 9 schema audit failed", details={"errors": errors})
    return {
        "passed": True,
        "dialect": DIALECT,
        "schema_count": len(by_filename),
        "registered_count": len(entries),
        "unique_id_count": len(allowed_ids),
        "reference_integrity": True,
        "registry_integrity": True,
        "compatibility_integrity": True,
        "persona_closed_objects": True,
        "object_closure_percent": round(closed_objects / object_schemas * 100, 1),
        "error_code_count": len(ERROR_CODES),
    }


def _type_matches(expected: str, value: Any) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True


def _issue(errors: list[dict[str, Any]], code: str, path: str, message: str) -> None:
    errors.append({"code": code, "path": path or "/", "message": message})


def _declared_properties(
    schema: dict[str, Any],
    document: dict[str, Any],
    by_filename: dict[str, dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    depth: int = 0,
) -> set[str]:
    if depth > 30:
        return set()
    values = set(schema.get("properties", {}))
    if isinstance(schema.get("$ref"), str):
        target, target_document = _resolve(schema["$ref"], document, by_filename, by_id)
        values.update(_declared_properties(target, target_document, by_filename, by_id, depth + 1))
    for keyword in ("allOf", "anyOf", "oneOf"):
        for child in schema.get(keyword, []):
            if isinstance(child, dict):
                values.update(_declared_properties(child, document, by_filename, by_id, depth + 1))
    return values


def _validate(
    schema: dict[str, Any],
    value: Any,
    *,
    document: dict[str, Any],
    by_filename: dict[str, dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    path: str,
    errors: list[dict[str, Any]],
    depth: int = 0,
) -> None:
    if depth > 100:
        _issue(errors, "E-REF-001", path, "schema recursion limit exceeded")
        return
    arguments = dict(
        by_filename=by_filename,
        by_id=by_id,
        path=path,
        errors=errors,
        depth=depth + 1,
    )
    reference = schema.get("$ref")
    if isinstance(reference, str):
        target, target_document = _resolve(reference, document, by_filename, by_id)
        _validate(target, value, document=target_document, **arguments)
    for child in schema.get("allOf", []):
        _validate(child, value, document=document, **arguments)
    if "anyOf" in schema:
        if not any(not _branch_errors(child, value, document, by_filename, by_id, path, depth) for child in schema["anyOf"]):
            _issue(errors, "E-SCHEMA-002", path, "no anyOf branch matched")
    if "oneOf" in schema:
        matched = sum(not _branch_errors(child, value, document, by_filename, by_id, path, depth) for child in schema["oneOf"])
        if matched != 1:
            _issue(errors, "E-SCHEMA-002", path, "oneOf must match exactly one branch")
    condition = schema.get("if")
    if isinstance(condition, dict):
        matched = not _branch_errors(condition, value, document, by_filename, by_id, path, depth)
        branch = schema.get("then" if matched else "else")
        if isinstance(branch, dict):
            _validate(branch, value, document=document, **arguments)
    if "const" in schema and value != schema["const"]:
        _issue(errors, "E-SCHEMA-004", path, "value does not equal const")
    if "enum" in schema and value not in schema["enum"]:
        _issue(errors, "E-SCHEMA-004", path, "value is outside enum")
    expected = schema.get("type")
    if expected is not None:
        choices = expected if isinstance(expected, list) else [expected]
        if not any(_type_matches(choice, value) for choice in choices):
            _issue(errors, "E-SCHEMA-002", path, f"expected type {expected}")
            return
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 2**63):
            _issue(errors, "E-SCHEMA-007", path, "string length is outside bounds")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            _issue(errors, "E-SCHEMA-005", path, "string does not match pattern")
        if schema.get("format") == "date-time":
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError
            except ValueError:
                _issue(errors, "E-SCHEMA-006", path, "invalid RFC 3339 date-time")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            _issue(errors, "E-SCHEMA-007", path, "value is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            _issue(errors, "E-SCHEMA-007", path, "value is above maximum")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            _issue(errors, "E-SCHEMA-007", path, "value is not above exclusiveMinimum")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            _issue(errors, "E-SCHEMA-007", path, "value is not below exclusiveMaximum")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 2**63):
            _issue(errors, "E-SCHEMA-007", path, "array cardinality is outside bounds")
        if schema.get("uniqueItems") is True:
            encoded = [canonical_json(item) for item in value]
            if len(encoded) != len(set(encoded)):
                _issue(errors, "E-SCHEMA-007", path, "array items are not unique")
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                _validate(schema["items"], item, document=document, path=f"{path}/{index}", errors=errors, by_filename=by_filename, by_id=by_id, depth=depth + 1)
        if isinstance(schema.get("contains"), dict):
            count = sum(not _branch_errors(schema["contains"], item, document, by_filename, by_id, f"{path}/{index}", depth) for index, item in enumerate(value))
            if count < schema.get("minContains", 1) or count > schema.get("maxContains", 2**63):
                _issue(errors, "E-SCHEMA-007", path, "contains cardinality is outside bounds")
    if isinstance(value, dict):
        required = schema.get("required", [])
        for name in required:
            if name not in value:
                _issue(errors, "E-SCHEMA-001", f"{path}/{name}", "required property is absent")
        properties = schema.get("properties", {})
        for name, child in properties.items():
            if name in value:
                _validate(child, value[name], document=document, path=f"{path}/{name}", errors=errors, by_filename=by_filename, by_id=by_id, depth=depth + 1)
        if "minProperties" in schema and len(value) < schema["minProperties"]:
            _issue(errors, "E-SCHEMA-007", path, "object has too few properties")
        if "maxProperties" in schema and len(value) > schema["maxProperties"]:
            _issue(errors, "E-SCHEMA-007", path, "object has too many properties")
        if isinstance(schema.get("propertyNames"), dict):
            for name in value:
                _validate(schema["propertyNames"], name, document=document, path=f"{path}/{name}", errors=errors, by_filename=by_filename, by_id=by_id, depth=depth + 1)
        declared = _declared_properties(schema, document, by_filename, by_id)
        additional = schema.get("additionalProperties")
        if additional is False or schema.get("unevaluatedProperties") is False:
            for name in value.keys() - declared:
                _issue(errors, "E-SCHEMA-003", f"{path}/{name}", "unexpected property")
        elif isinstance(additional, dict):
            for name in value.keys() - set(properties):
                _validate(additional, value[name], document=document, path=f"{path}/{name}", errors=errors, by_filename=by_filename, by_id=by_id, depth=depth + 1)


def _branch_errors(
    schema: dict[str, Any],
    value: Any,
    document: dict[str, Any],
    by_filename: dict[str, dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    path: str,
    depth: int,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    _validate(schema, value, document=document, by_filename=by_filename, by_id=by_id, path=path, errors=errors, depth=depth + 1)
    return errors


def validate_schema_document(
    schema_name: str, instance: dict[str, Any], *, root: Path | None = None
) -> dict[str, Any]:
    root = (root or _default_root()).resolve()
    by_filename, by_id = _documents(root)
    normalized = schema_name.removesuffix(".schema.json")
    filename = f"{normalized}.schema.json"
    schema = by_filename.get(filename)
    if schema is None or normalized not in SCHEMA_NAMES:
        raise ValidationError(
            "Unknown schema",
            details={"code": "E-REF-001", "schema": schema_name},
        )
    errors: list[dict[str, Any]] = []
    _validate(schema, instance, document=schema, by_filename=by_filename, by_id=by_id, path="", errors=errors)
    if normalized in PERSONA_NAMES and isinstance(instance, dict) and "content_hash" in instance:
        expected = content_hash({key: value for key, value in instance.items() if key != "content_hash"})
        if instance["content_hash"] != expected:
            _issue(errors, "E-FIX-001", "/content_hash", "content hash does not match canonical body")
    if errors:
        raise ValidationError(
            "JSON Schema validation failed",
            details={"schema": normalized, "errors": errors[:100]},
        )
    return {"passed": True, "schema": normalized, "schema_id": schema["$id"]}


def _cross_error(code: str, message: str, **details: Any) -> None:
    raise ValidationError(message, details={"code": code, **details})


def validate_persona_bundle(
    documents: dict[str, dict[str, Any]], *, root: Path | None = None
) -> dict[str, Any]:
    """Validate all six Persona artifacts and their non-schema invariants."""
    if set(documents) != set(PERSONA_NAMES):
        _cross_error("E-REF-002", "Persona bundle must contain exactly six artifacts")
    for name in PERSONA_NAMES:
        validate_schema_document(name, documents[name], root=root)
    proposals = documents["persona-proposals"]
    red_team = documents["persona-red-team-report"]
    deliberation = documents["persona-deliberation"]
    persona = documents["persona"]
    quality = documents["persona-quality-report"]
    approval = documents["persona-approval-binding"]
    identity_fields = ("build_id", "deliberation_key", "article_hash", "creative_brief_hash")
    for field in identity_fields:
        values = {
            document[field]
            for document in (proposals, red_team, deliberation, persona, quality)
            if field in document
        }
        if len(values) != 1:
            _cross_error("E-REF-001", "Persona bundle identity mismatch", field=field)
    proposal_roles = [item["role"] for item in proposals["proposals"]]
    if sorted(proposal_roles) != sorted(PROPOSAL_ROLES):
        _cross_error("E-REF-002", "Persona proposal role coverage mismatch")
    proposal_hashes = set()
    for proposal in proposals["proposals"]:
        expected = content_hash({key: value for key, value in proposal.items() if key != "proposal_hash"})
        if proposal["proposal_hash"] != expected:
            _cross_error("E-FIX-001", "Persona proposal hash mismatch", proposal_id=proposal["proposal_id"])
        proposal_hashes.add(expected)
    if red_team["proposal_set_hash"] != proposals["content_hash"]:
        _cross_error("E-REF-001", "Red-Team proposal-set hash mismatch")
    objection_ids = set()
    for objection in red_team["objections"]:
        if objection["proposal_hash"] not in proposal_hashes:
            _cross_error("E-REF-001", "Red-Team objection proposal does not resolve")
        if objection["objection_id"] in objection_ids:
            _cross_error("E-REF-002", "Red-Team objection identity is duplicated")
        objection_ids.add(objection["objection_id"])
    if deliberation["proposal_set_hash"] != proposals["content_hash"] or deliberation["red_team_report_hash"] != red_team["content_hash"]:
        _cross_error("E-REF-001", "Deliberation input hash mismatch")
    resolution_ids = {item["objection_id"] for item in deliberation["resolutions"]}
    if resolution_ids != objection_ids:
        _cross_error("E-REF-002", "Deliberation does not resolve every objection")
    roles = [item["role"] for item in deliberation["invocation_ledger"]]
    if sorted(roles) != sorted(COUNCIL_ROLES):
        _cross_error("E-REF-002", "Persona invocation ledger is not finite and complete")
    assumption_ids = {item["assumption_id"] for item in persona["assumptions"]}
    evidence_ids = {item["evidence_id"] for item in persona["evidence"]}
    for field in (
        "role",
        "job_to_be_done",
        "dominant_desire",
        "dominant_fear",
        "internal_contradiction",
        "decision_pressure",
        "authority_boundary",
        "current_workaround",
        "emotional_arc_candidate",
    ):
        value = persona[field]
        references = set(value["evidence_refs"])
        if value["basis"] in {"SOURCE", "CREATIVE_BRIEF"} and not references.issubset(evidence_ids):
            _cross_error("E-REF-001", "Persona field evidence does not resolve", field=field)
        if value["basis"] == "ASSUMPTION" and not references.issubset(assumption_ids):
            _cross_error("E-REF-001", "Persona assumption does not resolve", field=field)
    for assumption in persona["assumptions"]:
        if assumption["risk"] == "HIGH" and assumption["requires_human_attention"] is not True:
            _cross_error("E-APPROVAL-001", "High-risk assumption lacks human attention")
    expected_quality = {
        "proposal_set_hash": proposals["content_hash"],
        "red_team_report_hash": red_team["content_hash"],
        "deliberation_hash": deliberation["content_hash"],
        "persona_hash": persona["content_hash"],
    }
    if any(quality[field] != value for field, value in expected_quality.items()):
        _cross_error("E-REF-001", "Persona Quality Report hash mismatch")
    expected_approval = {
        "article_hash": persona["article_hash"],
        "creative_brief_hash": persona["creative_brief_hash"],
        "persona_hash": persona["content_hash"],
        "quality_report_hash": quality["content_hash"],
        "deliberation_hash": deliberation["content_hash"],
        "policy_version": quality["policy_version"],
    }
    if quality["status"] != "PASS" or any(approval[field] != value for field, value in expected_approval.items()):
        _cross_error("E-APPROVAL-001", "Persona approval binding is stale or ineligible")
    return {
        "passed": True,
        "artifact_count": 6,
        "proposal_count": 3,
        "objection_count": len(objection_ids),
        "build_id": persona["build_id"],
        "persona_hash": persona["content_hash"],
        "approval_hash": approval["content_hash"],
    }


def part9_coverage_report() -> dict[str, Any]:
    """Return the fixed twenty-cluster Part 9 implementation matrix."""
    full = [
        ("draft_2020_12_dialect", "all governing schemas declare the canonical dialect"),
        ("stable_namespaced_ids", "unique versioned $id values and filename binding"),
        ("common_definitions", "shared identifiers, hashes, time, ratios, and envelope types"),
        ("envelope_and_provenance", "sealed artifact provenance and fixity contracts"),
        ("closed_schema_policy", "closed Persona boundaries and measured legacy closure"),
        ("authoritative_registry", "exhaustive owner/chapter/version/file/id registry"),
        ("canonical_export", "package and repository schema export remain byte-identical"),
        ("vision_story_schemas", "Vision and sixteen Story contracts"),
        ("screenplay_schemas", "Screenplay, Scene, Dialogue, Continuity, config, and state"),
        ("shot_storyboard_schemas", "Shot, camera, blocking, storyboard, gates, and cache"),
        ("rendering_schemas", "render manifest, queue, task, result, provider, and retry"),
        ("build_quality_schemas", "plans, graphs, profiles, runtime, Gate, and quality reports"),
        ("agent_review_schemas", "v2.1 report and exact approval binding"),
        ("persona_council_schemas", "six v3.3 sealed Persona Council contracts"),
        ("reference_resolution", "local, relative, and absolute JSON Pointer audit"),
        ("instance_and_fixity_validation", "deterministic validator and canonical hash checks"),
        ("error_codes_and_negative_tests", "stable routed codes with tamper and contract cases"),
    ]
    partial = [
        ("cross_schema_semantics", "Persona bundle and domain validators exist; one universal legacy artifact-set validator does not"),
        ("compatibility_acceptance", "byte baseline and local consumers are tested; external released-consumer matrix remains external"),
    ]
    missing = [
        ("public_schema_distribution", "the canonical $id namespace is not deployed as a public schema service"),
    ]
    rows = [
        *({"cluster": cluster, "status": "FULL", "evidence": evidence} for cluster, evidence in full),
        *({"cluster": cluster, "status": "PARTIAL", "evidence": evidence} for cluster, evidence in partial),
        *({"cluster": cluster, "status": "MISSING", "evidence": evidence} for cluster, evidence in missing),
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
