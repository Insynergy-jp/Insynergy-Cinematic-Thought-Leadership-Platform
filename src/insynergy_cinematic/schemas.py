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
    "quality-gate-report",
    "build-quality-report",
    "agent-review-report",
    "review-approval-binding",
    "persona-proposals",
    "persona-red-team-report",
    "persona-deliberation",
    "persona",
    "persona-quality-report",
    "persona-approval-binding",
    "previsualization-plan",
    "image-prompt-set",
    "video-prompt-set",
    "storyboard-preview-manifest",
    "storyboard-preview-quality-report",
    "storyboard-preview-approval-binding",
)


_SCHEMA_GROUPS: dict[str, tuple[str, dict[str, str]]] = {
    "9.2": (
        "2.0",
        {
            "product-contract": "1.1.1",
            "layer-contract": "1.3.3",
            "data-flow": "1.3.2",
            "asset-selection": "1.3.6",
            "approval-record": "1.4.1",
        },
    ),
    "9.3": (
        "2.0",
        {
            "argument-map": "2.1.2",
            "theme": "2.1.2",
            "dramatic-question": "2.1.2",
            "dramatic-premise": "2.1.3",
            "logline": "2.1.3",
            "character-bible": "2.1.4",
            "conflict": "2.1.5",
            "stakes": "2.1.5",
            "time-pressure": "2.1.5",
            "story-arc": "2.1.6",
            "three-act-structure": "2.1.6",
            "emotional-arc": "2.1.6",
            "concept-placement": "2.1.6",
            "story-quality-report": "2.1.7",
            "story-metrics": "2.1.7",
            "story-cache-key": "2.1.8",
        },
    ),
    "9.4": (
        "2.0",
        {
            "screenplay": "3.1.7",
            "scene": "3.1.3",
            "scene-index": "3.1.7",
            "dialogue": "3.1.5",
            "continuity": "3.1.8",
            "screenplay-metrics": "3.1.8",
            "screenplay-config": "3.1.9",
            "screenplay-state": "3.1.11",
        },
    ),
    "9.5": (
        "2.0",
        {
            "shot-list": "4.1.2",
            "shot": "4.1.2",
            "camera-plan": "4.1.4",
            "blocking": "4.1.5",
            "storyboard": "4.1.6",
            "continuity-report": "4.1.8",
            "render-strategy": "4.1.9",
            "shot-metrics": "4.1.13",
            "shot-gate-report": "4.1.12",
            "storyboard-gate-report": "4.1.12",
            "shot-cache-key": "4.1.13",
        },
    ),
    "9.6": (
        "2.0",
        {
            "render-manifest": "5.1.4, 5.4.4",
            "render-queue": "5.1.4, 5.4.1",
            "render-results": "5.1.4",
            "metadata": "5.1.4",
            "render-task": "5.4.3",
            "provider-capability": "5.3.2",
            "retry-policy": "5.4.5",
            "prompt-assembly": "5.5.1",
            "location-bible": "5.1.4",
        },
    ),
    "9.7": (
        "2.0",
        {
            "performance-budget": "6.1.1",
            "execution-plan": "6.1.3",
            "dependency-graph": "6.1.3",
            "build-profile": "6.1.7",
            "performance-config": "6.1.8",
            "operational-state": "6.1.11",
            "quality-gate-registry": "6.1.6, 7.1.3",
            "quality-gate-report": "7.1.3",
            "build-quality-report": "7.1.12",
        },
    ),
    "9.0.1": (
        "2.1",
        {
            "agent-review-report": "1.0.1, 7.0.1",
            "review-approval-binding": "1.0.1, 8.0.1",
        },
    ),
    "9.0.2": (
        "3.3",
        {
            "persona-proposals": "1.0.2, 6.0.2",
            "persona-red-team-report": "1.0.2, 6.0.2",
            "persona-deliberation": "1.0.2, 6.0.2",
            "persona": "1.0.2",
            "persona-quality-report": "7.0.2",
            "persona-approval-binding": "1.0.2, 8.0.2",
        },
    ),
    "9.0.3": (
        "3.4",
        {
            "previsualization-plan": "1.0.3, 4.0.3, 5.0.3",
            "image-prompt-set": "4.0.3, 5.0.3",
            "video-prompt-set": "4.0.3, 5.0.3",
            "storyboard-preview-manifest": "4.0.3, 6.0.3",
            "storyboard-preview-quality-report": "7.0.3",
            "storyboard-preview-approval-binding": "1.0.3, 8.0.3",
        },
    ),
}

SCHEMA_METADATA = {
    name: {"version": version, "owner": owner, "chapter": chapter}
    for chapter, (version, entries) in _SCHEMA_GROUPS.items()
    for name, owner in entries.items()
}
SCHEMA_BUNDLE_FILE_COUNT = len(SCHEMA_NAMES) + 3


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


def _preview_schema(name: str) -> dict[str, Any]:
    """Return the closed v3.4 preview data contract for one canonical artifact."""
    string = {"type": "string", "minLength": 1, "maxLength": 20000}
    digest = {"type": "string", "pattern": r"^sha256:[a-f0-9]{64}$"}
    positive = {"type": "number", "exclusiveMinimum": 0}
    scene = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "scene_id", "shot_id", "order", "duration_seconds",
            "scene_composition", "direction", "camera_work", "narration",
            "tempo", "image_prompt", "video_prompt", "risk_flags",
        ],
        "properties": {
            "scene_id": string, "shot_id": string,
            "order": {"type": "integer", "minimum": 1},
            "duration_seconds": positive,
            "scene_composition": string, "direction": string,
            "camera_work": string, "narration": string, "tempo": string,
            "image_prompt": string, "video_prompt": string,
            "risk_flags": {"type": "array", "maxItems": 32, "items": string},
        },
    }
    prompt = {
        "type": "object",
        "additionalProperties": False,
        "required": ["prompt_id", "shot_id", "order", "prompt"],
        "properties": {
            "prompt_id": string, "shot_id": string,
            "order": {"type": "integer", "minimum": 1}, "prompt": string,
            "negative_constraints": {
                "type": "array", "maxItems": 32, "items": string,
            },
            "safety_constraints": {
                "type": "array", "maxItems": 32, "items": string,
            },
            "aspect_ratio": string,
            "execution_status": {"const": "SEALED_NOT_AUTHORIZED"},
        },
    }
    base: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://schemas.insynergy.co/cttp/v3.4/preview/{name}.schema.json",
        "title": "".join(word.title() for word in name.split("-")),
        "type": "object",
        "additionalProperties": False,
    }
    if name == "previsualization-plan":
        properties = {
            "schema_version": {"const": "3.4.0"},
            "contract_version": {"const": "previsualization-plan/1"},
            "build_id": string, "planning_hash": digest, "plan_key": digest,
            "status": {"const": "PREVIEW_READY"}, "summary": string,
            "scenes": {"type": "array", "minItems": 1, "maxItems": 128, "items": scene},
            "review_dimensions": {
                "type": "array", "minItems": 5, "maxItems": 5, "uniqueItems": True,
                "items": {"enum": ["scene_composition", "direction", "camera_work", "narration", "tempo"]},
            },
            "model_requested": string, "model_resolved": string,
            "reasoning_effort": {"enum": ["none", "low", "medium", "high", "xhigh", "max"]},
            "prompt_version": string, "provider_response_id": string,
            "usage": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "input_tokens": {"type": "integer", "minimum": 0},
                    "output_tokens": {"type": "integer", "minimum": 0},
                    "total_tokens": {"type": "integer", "minimum": 0},
                },
            },
            "cache_hit": {"type": "boolean"},
            "generated_at": {"type": "string", "format": "date-time"},
        }
    elif name == "image-prompt-set":
        properties = {
            "schema_version": {"const": "3.4.0"},
            "contract_version": {"const": "image-prompt-set/1"},
            "build_id": string, "plan_key": digest,
            "image_size": {"enum": ["1024x1024", "1536x1024", "1024x1536"]},
            "image_quality": {"enum": ["low", "medium", "high"]},
            "output_format": {"enum": ["png", "jpeg", "webp"]},
            "prompts": {"type": "array", "minItems": 1, "maxItems": 128, "items": prompt},
        }
    elif name == "video-prompt-set":
        properties = {
            "schema_version": {"const": "3.4.0"},
            "contract_version": {"const": "video-prompt-set/1"},
            "build_id": string, "plan_key": digest,
            "provider_submission_allowed": {"const": False},
            "prompts": {"type": "array", "minItems": 1, "maxItems": 128, "items": prompt},
        }
    elif name == "storyboard-preview-manifest":
        frame = {
            "type": "object", "additionalProperties": False,
            "required": ["frame_id", "scene_id", "shot_id", "order", "prompt_id", "asset_path", "asset_hash", "duration_seconds", "start_seconds", "end_seconds", "transition_seconds", "narration", "tempo", "cache_key", "cache_hit", "provider_response_id", "model_resolved"],
            "properties": {
                "frame_id": string, "scene_id": string, "shot_id": string,
                "order": {"type": "integer", "minimum": 1}, "prompt_id": string,
                "asset_path": string, "asset_hash": digest,
                "duration_seconds": positive, "cache_key": digest,
                "start_seconds": {"type": "number", "minimum": 0},
                "end_seconds": positive,
                "transition_seconds": {"type": "number", "minimum": 0},
                "narration": string, "tempo": string,
                "cache_hit": {"type": "boolean"},
                "provider_response_id": string, "model_resolved": string,
            },
        }
        asset = {
            "type": "object", "additionalProperties": False,
            "required": ["path", "content_hash"],
            "properties": {"path": string, "content_hash": digest},
        }
        properties = {
            "schema_version": {"const": "3.4.0"},
            "contract_version": {"const": "storyboard-preview-manifest/1"},
            "build_id": string, "plan_key": digest,
            "status": {"const": "PREVIEW_READY"},
            "frames": {"type": "array", "minItems": 1, "maxItems": 128, "items": frame},
            "animatic": {
                "type": "object", "additionalProperties": False,
                "required": ["path", "content_hash", "width", "height", "frame_rate", "duration_seconds", "expected_duration_seconds", "codec", "container", "watermark_version", "overlay_contract", "ffmpeg_version", "ffmpeg_argument_contract"],
                "properties": {
                    "path": string, "content_hash": digest,
                    "width": {"type": "integer", "minimum": 1},
                    "height": {"type": "integer", "minimum": 1},
                    "frame_rate": {"type": "integer", "minimum": 1},
                    "duration_seconds": positive, "expected_duration_seconds": positive,
                    "codec": {"const": "h264"},
                    "container": {"const": "mp4"},
                    "watermark_version": {"const": "storyboard-preview-watermark/1"},
                    "overlay_contract": {"const": "preview-shot-identity-timecode/1"},
                    "ffmpeg_version": string,
                    "ffmpeg_argument_contract": {"const": "preview-animatic/1"},
                },
            },
            "captions": asset, "review_html": asset,
            "provider_calls": {
                "type": "object", "additionalProperties": False,
                "required": ["gpt_plan", "gpt_image", "runway"],
                "properties": {
                    "gpt_plan": {"type": "integer", "minimum": 0},
                    "gpt_image": {"type": "integer", "minimum": 0},
                    "runway": {"const": 0},
                },
            },
            "usage_summary": {
                "type": "object", "additionalProperties": False,
                "required": ["input_tokens", "output_tokens", "total_tokens", "estimated_cost_usd", "max_cost_usd"],
                "properties": {
                    "input_tokens": {"type": "integer", "minimum": 0},
                    "output_tokens": {"type": "integer", "minimum": 0},
                    "total_tokens": {"type": "integer", "minimum": 0},
                    "estimated_cost_usd": positive, "max_cost_usd": positive,
                },
            },
            "timebase": string,
            "non_publishable": {"const": True},
            "final_cache_eligible": {"const": False},
            "limitations": {"type": "array", "minItems": 1, "maxItems": 16, "items": string},
            "runway_contacted": {"const": False},
        }
    elif name == "storyboard-preview-quality-report":
        check_names = [
            "all_shots_covered", "shot_order_preserved",
            "five_review_dimensions_present", "image_prompts_complete",
            "video_prompts_complete", "frames_hash_verified",
            "animatic_hash_verified", "captions_hash_verified",
            "review_html_hash_verified", "runway_not_contacted",
            "watermark_present", "shot_identity_overlay_present", "non_publishable",
        ]
        properties = {
            "schema_version": {"const": "3.4.0"},
            "contract_version": {"const": "storyboard-preview-quality/1"},
            "build_id": string,
            "gate_id": {"const": "storyboard_preview_quality_gate"},
            "decision": {"enum": ["PASS", "FAIL"]}, "passed": {"type": "boolean"},
            "fail_closed": {"const": True},
            "checks": {
                "type": "object", "additionalProperties": False,
                "required": check_names,
                "properties": {key: {"type": "boolean"} for key in check_names},
            },
            "deterministic_disposition": {"enum": ["PASS", "FAIL"]},
            "advisory": {
                "type": "object", "additionalProperties": False,
                "required": ["disposition", "findings"],
                "properties": {
                    "disposition": {"enum": ["NOT_RUN", "PASS", "MANUAL_REVIEW_REQUIRED"]},
                    "findings": {"type": "array", "maxItems": 128, "items": string},
                },
            },
            "limitations": {"type": "array", "minItems": 1, "maxItems": 16, "items": string},
            "openai_usage": {
                "type": "object", "additionalProperties": False,
                "required": ["input_tokens", "output_tokens", "total_tokens", "estimated_cost_usd", "max_cost_usd"],
                "properties": {
                    "input_tokens": {"type": "integer", "minimum": 0},
                    "output_tokens": {"type": "integer", "minimum": 0},
                    "total_tokens": {"type": "integer", "minimum": 0},
                    "estimated_cost_usd": positive, "max_cost_usd": positive,
                },
            },
            "runway_usage": {
                "type": "object", "additionalProperties": False,
                "required": ["request_count", "task_count", "attempt_count", "credit_count"],
                "properties": {
                    "request_count": {"const": 0}, "task_count": {"const": 0},
                    "attempt_count": {"const": 0}, "credit_count": {"const": 0},
                },
            },
            "review_dimensions": {
                "type": "array", "minItems": 5, "maxItems": 5,
                "items": string,
            },
            "plan_key": digest,
        }
    else:
        properties = {
            "schema_version": {"const": "3.4.0"},
            "contract_version": {"const": "storyboard-preview-approval/1"},
            "approval_id": string, "build_id": string,
            "decision": {"const": "APPROVED"}, "approver": string,
            "workflow_initiator": string, "environment_reviewer": string,
            "environment_reviewer_id": {"type": "integer", "minimum": 1},
            "prevent_self_review": {"type": "boolean"},
            "approved_at": {"type": "string", "format": "date-time"},
            "planning_hash": digest,
            "artifact_hashes": {
                "type": "object", "additionalProperties": False,
                "required": [
                    "previsualization_plan", "image_prompt_set", "video_prompt_set",
                    "storyboard_preview_manifest", "storyboard_preview_quality_report",
                ],
                "properties": {
                    key: digest
                    for key in (
                        "previsualization_plan", "image_prompt_set", "video_prompt_set",
                        "storyboard_preview_manifest", "storyboard_preview_quality_report",
                    )
                },
            },
            "environment_review_hash": digest,
            "environment_policy_hash": digest,
            "rationale": string,
            "content_hash": digest,
        }
    base["required"] = [
        key
        for key in properties
        if key
        not in {
            "environment_reviewer_id",
            "environment_review_hash",
            "environment_policy_hash",
            "rationale",
        }
    ]
    base["properties"] = properties
    if name == "storyboard-preview-approval-binding":
        github_evidence = [
            "environment_reviewer_id",
            "environment_review_hash",
            "environment_policy_hash",
        ]
        base["dependentRequired"] = {
            field: [other for other in github_evidence if other != field]
            for field in github_evidence
        }
    return base


def schema_for(name: str) -> dict[str, Any]:
    normalized = name.removesuffix(".schema.json")
    if normalized not in SCHEMA_NAMES:
        raise ValidationError(f"Unknown schema: {name}")
    if normalized in {
        "previsualization-plan",
        "image-prompt-set",
        "video-prompt-set",
        "storyboard-preview-manifest",
        "storyboard-preview-quality-report",
        "storyboard-preview-approval-binding",
    }:
        return _preview_schema(normalized)
    bundled = _bundled_schema_root() / f"{normalized}.schema.json"
    repository_schema = (
        Path(__file__).resolve().parents[2]
        / "schemas"
        / f"{normalized}.schema.json"
    )
    if not bundled.is_file() and repository_schema.is_file():
        bundled = repository_schema
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
    from .util import content_hash

    entries = [
        {
            "name": name,
            "file": f"{name}.schema.json",
            "id": schema_for(name)["$id"],
            **SCHEMA_METADATA[name],
        }
        for name in SCHEMA_NAMES
    ]
    value = {
        "schema_version": "3.4.0",
        "contract_version": "schema-registry/1",
        "dialect": "https://json-schema.org/draft/2020-12/schema",
        "schemas": entries,
    }
    value["content_hash"] = content_hash(entries)
    return value


def export_schemas(destination: Path) -> int:
    destination.mkdir(parents=True, exist_ok=True)
    bundled = _bundled_schema_root()
    if bundled.is_dir() and bundled.resolve() != destination.resolve():
        for source in sorted(bundled.rglob("*.json")):
            relative = source.relative_to(bundled)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        for name in SCHEMA_NAMES:
            target = destination / f"{name}.schema.json"
            if not target.is_file() or name.startswith(("previsualization-", "image-prompt-", "video-prompt-", "storyboard-preview-")):
                atomic_write_json(target, schema_for(name))
        atomic_write_json(destination / "schema-registry.json", registry())
        return len(list(destination.rglob("*.json")))
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
