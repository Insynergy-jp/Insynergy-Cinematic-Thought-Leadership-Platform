"""JSON Schema registry defined by specification Part 9."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .util import atomic_write_json


SCHEMA_NAMES = (
    "product-contract",
    "layer-contract",
    "data-flow",
    "asset-selection",
    "approval-record",
    "argument-map",
    "theme",
    "dramatic-question",
    "dramatic-premise",
    "logline",
    "character-bible",
    "conflict",
    "stakes",
    "time-pressure",
    "story-arc",
    "three-act-structure",
    "emotional-arc",
    "concept-placement",
    "story-quality-report",
    "story-metrics",
    "story-cache-key",
    "screenplay",
    "scene",
    "scene-index",
    "dialogue",
    "continuity",
    "screenplay-metrics",
    "screenplay-config",
    "screenplay-state",
    "shot-list",
    "shot",
    "camera-plan",
    "blocking",
    "storyboard",
    "continuity-report",
    "render-strategy",
    "shot-metrics",
    "shot-gate-report",
    "storyboard-gate-report",
    "shot-cache-key",
    "render-manifest",
    "render-queue",
    "render-results",
    "metadata",
    "render-task",
    "provider-capability",
    "retry-policy",
    "prompt-assembly",
    "location-bible",
    "performance-budget",
    "execution-plan",
    "dependency-graph",
    "build-profile",
    "performance-config",
    "operational-state",
    "quality-gate-registry",
    "agent-review-report",
    "review-approval-binding",
)


def common_definitions() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://schemas.insynergy.co/cttp/v2.0/common/defs.schema.json",
        "title": "CTTP Common Definitions",
        "$defs": {
            "SchemaVersion": {"type": "string", "const": "2.0"},
            "ContentHash": {"type": "string", "pattern": r"^sha256:[a-f0-9]{64}$"},
            "CacheKey": {"type": "string", "pattern": r"^sha256:[a-f0-9]{64}$"},
            "BuildId": {"type": "string", "pattern": r"^[0-9]{8}-[0-9]{3}$"},
            "SceneId": {"type": "string", "pattern": r"^scene-[0-9]{3}$"},
            "ShotId": {
                "type": "string",
                "pattern": r"^scene-[0-9]{3}-shot-[0-9]{2}$",
            },
            "StoryboardId": {"type": "string", "minLength": 1},
            "RefId": {"type": "string", "pattern": r"^[a-z0-9_]+_v[0-9]+$"},
            "ArtifactId": {"type": "string", "minLength": 1},
            "ApprovalRef": {"type": "string", "minLength": 1},
            "Iso8601": {"type": "string", "format": "date-time"},
            "DurationSeconds": {"type": "number", "exclusiveMinimum": 0},
            "Ratio": {"type": "number", "minimum": 0, "maximum": 1},
            "Score": {"type": "number", "minimum": 0, "maximum": 1},
            "Act": {"type": "integer", "enum": [1, 2, 3]},
            "ShotType": {
                "type": "string",
                "enum": [
                    "establishing",
                    "wide",
                    "medium",
                    "medium_close_up",
                    "close_up",
                    "extreme_close_up",
                    "over_shoulder",
                    "point_of_view",
                    "insert",
                    "tracking",
                    "static",
                ],
            },
            "RenderStrategy": {
                "type": "string",
                "enum": [
                    "runway_video",
                    "animated_still",
                    "motion_graphics",
                    "title_card",
                    "svg_animation",
                    "cached_clip",
                ],
            },
            "BuildType": {"type": "string", "enum": ["preview", "final"]},
            "ArtifactEnvelope": {
                "type": "object",
                "properties": {
                    "schema_version": {"$ref": "#/$defs/SchemaVersion"},
                    "build_id": {"$ref": "#/$defs/BuildId"},
                    "approved": {"type": "boolean"},
                    "approval_ref": {"$ref": "#/$defs/ApprovalRef"},
                    "generated_at": {"$ref": "#/$defs/Iso8601"},
                    "content_hash": {"$ref": "#/$defs/ContentHash"},
                },
                "required": ["schema_version", "build_id", "generated_at", "content_hash"],
            },
        },
    }


def _bundled_schema_root() -> Path:
    packaged = Path(__file__).resolve().parent / "schema_data"
    if packaged.is_dir():
        return packaged
    return Path(__file__).resolve().parents[2] / "schemas"


def _generic_schema(name: str) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://schemas.insynergy.co/cttp/v2.0/{name}.schema.json",
        "title": "".join(word.title() for word in name.split("-")),
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "contract_version",
            "artifact_type",
            "artifact_id",
            "build_id",
            "content_hash",
            "generated_at",
            "provenance",
            "data",
        ],
        "properties": {
            "schema_version": {"$ref": "common/defs.schema.json#/$defs/SchemaVersion"},
            "contract_version": {"$ref": "common/defs.schema.json#/$defs/SchemaVersion"},
            "artifact_type": {"type": "string"},
            "artifact_id": {"$ref": "common/defs.schema.json#/$defs/ArtifactId"},
            "build_id": {"$ref": "common/defs.schema.json#/$defs/BuildId"},
            "content_hash": {"$ref": "common/defs.schema.json#/$defs/ContentHash"},
            "generated_at": {"$ref": "common/defs.schema.json#/$defs/Iso8601"},
            "provenance": {
                "type": "object",
                "additionalProperties": False,
                "required": ["generator", "input_hashes", "deterministic"],
                "properties": {
                    "generator": {"type": "string", "minLength": 1},
                    "input_hashes": {
                        "type": "array",
                        "items": {"$ref": "common/defs.schema.json#/$defs/ContentHash"},
                    },
                    "deterministic": {"const": True},
                },
            },
            "data": {"type": "object"},
        },
    }


def schema_for(name: str) -> dict[str, Any]:
    normalized = name.removesuffix(".schema.json")
    if normalized not in SCHEMA_NAMES:
        raise ValidationError(f"Unknown schema: {name}")
    bundled = _bundled_schema_root() / f"{normalized}.schema.json"
    if bundled.is_file():
        with bundled.open(encoding="utf-8") as handle:
            return json.load(handle)
    schema = _generic_schema(normalized)
    data = schema["properties"]["data"]
    required_by_name: dict[str, list[str]] = {
        "argument-map": ["claims", "institutional_problem", "proposed_solution", "dramatic_candidates"],
        "theme": ["primary_theme", "theme_score"],
        "dramatic-question": ["dramatic_question", "resolved_in_act"],
        "dramatic-premise": ["premise", "protagonist_situation", "required_decision"],
        "logline": ["logline", "protagonist", "goal", "stakes", "loss"],
        "character-bible": ["protagonist_id", "characters"],
        "conflict": ["primary_conflict", "conflict_count"],
        "stakes": ["measurable_stakes"],
        "time-pressure": ["deadline", "irreversible"],
        "three-act-structure": ["acts", "act_count"],
        "screenplay": ["title", "scenes", "act_count", "scene_count"],
        "shot-list": ["shots", "shot_count", "ordering"],
        "storyboard": ["frames", "frame_count", "source"],
        "render-manifest": ["build_id", "all_ready", "results", "metrics"],
        "quality-gate-registry": ["gates"],
    }
    required = required_by_name.get(normalized, [])
    if required:
        data["required"] = required
        data["properties"] = {field: {} for field in required}
        if normalized in {"theme"}:
            data["properties"]["theme_score"] = {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            }
        if normalized == "three-act-structure":
            data["properties"]["act_count"] = {"const": 3}
        if normalized == "conflict":
            data["properties"]["conflict_count"] = {"const": 1}
        if normalized == "storyboard":
            data["properties"]["source"] = {"const": "screenplay_only"}
    return schema


def registry() -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "schemas": [
            {
                "name": name,
                "file": f"{name}.schema.json",
                "id": schema_for(name)["$id"],
            }
            for name in SCHEMA_NAMES
        ],
    }


def export_schemas(destination: Path) -> int:
    destination.mkdir(parents=True, exist_ok=True)
    bundled = _bundled_schema_root()
    if bundled.is_dir() and bundled.resolve() != destination.resolve():
        for source in sorted(bundled.rglob("*.json")):
            relative = source.relative_to(bundled)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        return len(list(bundled.rglob("*.json")))
    common = destination / "common"
    common.mkdir(exist_ok=True)
    atomic_write_json(common / "defs.schema.json", common_definitions())
    for name in SCHEMA_NAMES:
        atomic_write_json(destination / f"{name}.schema.json", schema_for(name))
    atomic_write_json(destination / "schema-registry.json", registry())
    return len(SCHEMA_NAMES) + 2


def validate_envelope(document: dict[str, Any], *, expected_type: str | None = None) -> None:
    required = set(_generic_schema("artifact")["required"])
    missing = required.difference(document)
    if missing:
        raise ValidationError(f"Artifact envelope missing fields: {sorted(missing)}")
    if document.get("provenance", {}).get("deterministic") is not True:
        raise ValidationError("Artifact provenance must assert determinism")
    if not str(document.get("content_hash", "")).startswith("sha256:"):
        raise ValidationError("Artifact content hash is invalid")
    from .util import content_hash

    if content_hash(document.get("data")) != document.get("content_hash"):
        raise ValidationError("Artifact content hash does not match its canonical body")
    if document.get("schema_version") != "2.0":
        raise ValidationError("Artifact schema_version must be 2.0")
    if not document.get("generated_at"):
        raise ValidationError("Artifact generated_at is required")
    if document.get("approved") is True and not document.get("approval_ref"):
        raise ValidationError("Approved artifacts require approval_ref")
    if expected_type and document.get("artifact_type") != expected_type:
        raise ValidationError(
            f"Expected artifact type {expected_type}, got {document.get('artifact_type')}"
        )
