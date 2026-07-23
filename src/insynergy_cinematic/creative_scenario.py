"""Strict Creative Brief scenario extraction for authored short films.

The default Story and Screenplay engines remain deterministic and unchanged
when a Creative Brief has no ``creative-scenario`` fence.  Council-mode briefs
may opt into an authored scenario by embedding exactly one JSON document in a
fenced block whose info string is ``creative-scenario``.  The enclosing brief
hash is the approval boundary for the extracted document.
"""

from __future__ import annotations

from copy import deepcopy
import json
import math
import re
from typing import Any

from .errors import ValidationError
from .util import content_hash


CREATIVE_SCENARIO_VERSION = "creative-scenario/1"
CREATIVE_SCENARIO_EXTRACTION_CONTRACT = "markdown-fence/1"
AUTHORED_SCENE_DURATION_MIN = 3.0
ALLOWED_PURPOSES = frozenset(
    {
        "Introduce protagonist",
        "Reveal hidden risk",
        "Increase urgency",
        "Create reversal",
        "Force decision",
        "Resolve conflict",
    }
)
ALLOWED_CONFLICTS = frozenset(
    {
        "Human vs Machine",
        "Human vs Institution",
        "Human vs Time",
        "Human vs Self",
        "Institution vs Reality",
    }
)
ALLOWED_TRANSITIONS = frozenset({"Hard Cut", "Fade", "Match Cut", "L Cut", "J Cut"})
ALLOWED_DIALOGUE_CATEGORIES = frozenset(
    {"Question", "Demand", "Refusal", "Warning", "Decision", "Revelation"}
)
STRATEGY_CAPABILITIES = {
    "runway_video": "generative_natural_motion",
    "animated_still": "static_live_action_tableau",
    "motion_graphics": "designed_graphical_motion",
    "title_card": "typographic_card",
}
_FENCE = re.compile(
    r"^```creative-scenario[ \t]*\r?\n(?P<body>.*?)^```[ \t]*$",
    flags=re.MULTILINE | re.DOTALL,
)
_ROOT_FIELDS = {
    "schema_version",
    "title",
    "duration_seconds",
    "language",
    "spoken_line_limit",
    "scenes",
}
_SCENE_FIELDS = {
    "scene_id",
    "title",
    "duration_seconds",
    "act",
    "purpose",
    "conflict",
    "heading",
    "action",
    "characters",
    "dialogue",
    "emotion_start",
    "emotion_end",
    "countdown_seconds",
    "props",
    "transition",
    "concepts",
    "shot",
    "ui_overlays",
    "sound",
}
_SHOT_FIELDS = {
    "framing",
    "lens",
    "movement",
    "speed",
    "angle",
    "composition",
    "lighting",
    "style",
    "forbidden_style",
    "render_strategy",
    "screen_direction",
    "performance_note",
}
_DIALOGUE_FIELDS = {"speaker", "text", "category", "silence"}
_HEADING_FIELDS = {"interior_exterior", "location", "time"}
_CHARACTER_ROLES = {"protagonist", "counterforce"}


def _object(value: Any, *, label: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValidationError(
            f"{label} has an invalid object contract",
            details={
                "missing": sorted(fields.difference(value) if isinstance(value, dict) else fields),
                "unexpected": sorted(set(value).difference(fields) if isinstance(value, dict) else []),
            },
        )
    return value


def _text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 20_000:
        raise ValidationError(f"{label} must be a non-empty bounded string")
    return value.strip()


def _string_list(
    value: Any, *, label: str, allow_empty: bool = True
) -> list[str]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or len(value) > 64
        or not all(isinstance(item, str) and bool(item.strip()) for item in value)
    ):
        raise ValidationError(f"{label} must be an array of non-empty strings")
    return [item.strip() for item in value]


def _duration(value: Any, *, label: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise ValidationError(f"{label} must be a finite number")
    return float(value)


def validate_creative_scenario(
    raw: dict[str, Any], *, creative_brief_hash: str
) -> dict[str, Any]:
    """Validate and seal one canonical authored scenario."""

    document = deepcopy(_object(raw, label="Creative Scenario", fields=_ROOT_FIELDS))
    if document["schema_version"] != CREATIVE_SCENARIO_VERSION:
        raise ValidationError("Creative Scenario schema_version is unsupported")
    document["title"] = _text(document["title"], label="Creative Scenario title")
    language = _text(document["language"], label="Creative Scenario language")
    if not re.fullmatch(r"[a-z]{2}(?:-[A-Z]{2})?", language):
        raise ValidationError("Creative Scenario language must be a BCP-47 language tag")
    document["language"] = language
    total_duration = _duration(
        document["duration_seconds"], label="Creative Scenario duration"
    )
    if not 5.0 <= total_duration <= 60.0:
        raise ValidationError("Creative Scenario duration must be within 5-60 seconds")
    document["duration_seconds"] = total_duration
    spoken_line_limit = document["spoken_line_limit"]
    if (
        not isinstance(spoken_line_limit, int)
        or isinstance(spoken_line_limit, bool)
        or not 0 <= spoken_line_limit <= 16
    ):
        raise ValidationError("Creative Scenario spoken_line_limit must be within 0-16")
    scenes = document["scenes"]
    if not isinstance(scenes, list) or len(scenes) != 8:
        raise ValidationError("Creative Scenario currently requires exactly eight scenes")

    spoken_lines = 0
    normalized_scenes: list[dict[str, Any]] = []
    for index, raw_scene in enumerate(scenes, start=1):
        scene = deepcopy(
            _object(
                raw_scene,
                label=f"Creative Scenario scene {index}",
                fields=_SCENE_FIELDS,
            )
        )
        expected_id = f"scene-{index:03d}"
        if scene["scene_id"] != expected_id:
            raise ValidationError(
                "Creative Scenario scene identity or ordering is invalid",
                details={"expected": expected_id, "actual": scene.get("scene_id")},
            )
        scene["title"] = _text(scene["title"], label=f"{expected_id} title")
        scene_duration = _duration(
            scene["duration_seconds"], label=f"{expected_id} duration"
        )
        if not AUTHORED_SCENE_DURATION_MIN <= scene_duration <= 10.0:
            raise ValidationError(
                f"{expected_id} duration must be within "
                f"{AUTHORED_SCENE_DURATION_MIN:g}-10 seconds"
            )
        scene["duration_seconds"] = scene_duration
        if scene["act"] not in {1, 2, 3}:
            raise ValidationError(f"{expected_id} has an invalid act")
        if scene["purpose"] not in ALLOWED_PURPOSES:
            raise ValidationError(f"{expected_id} has an invalid purpose")
        if scene["conflict"] not in ALLOWED_CONFLICTS:
            raise ValidationError(f"{expected_id} has an invalid conflict")
        if scene["transition"] not in ALLOWED_TRANSITIONS:
            raise ValidationError(f"{expected_id} has an invalid transition")

        heading = _object(
            scene["heading"], label=f"{expected_id} heading", fields=_HEADING_FIELDS
        )
        if heading["interior_exterior"] not in {"INT", "EXT", "INT./EXT."}:
            raise ValidationError(f"{expected_id} heading type is invalid")
        heading["location"] = _text(
            heading["location"], label=f"{expected_id} heading location"
        )
        heading["time"] = _text(heading["time"], label=f"{expected_id} heading time")
        scene["action"] = _text(scene["action"], label=f"{expected_id} action")
        characters = _string_list(
            scene["characters"], label=f"{expected_id} characters", allow_empty=False
        )
        if not set(characters).issubset(_CHARACTER_ROLES) or len(characters) != len(
            set(characters)
        ):
            raise ValidationError(f"{expected_id} character roles are invalid")
        scene["characters"] = characters

        dialogue = _object(
            scene["dialogue"],
            label=f"{expected_id} dialogue",
            fields=_DIALOGUE_FIELDS,
        )
        if dialogue["speaker"] not in characters:
            raise ValidationError(f"{expected_id} dialogue speaker is not in the scene")
        if dialogue["category"] not in ALLOWED_DIALOGUE_CATEGORIES:
            raise ValidationError(f"{expected_id} dialogue category is invalid")
        if not isinstance(dialogue["silence"], bool) or not isinstance(
            dialogue["text"], str
        ):
            raise ValidationError(f"{expected_id} dialogue value is invalid")
        dialogue["text"] = dialogue["text"].strip()
        if dialogue["silence"]:
            if dialogue["text"]:
                raise ValidationError(f"{expected_id} silence must have empty text")
        else:
            if not dialogue["text"] or len(dialogue["text"].split()) > 15:
                raise ValidationError(
                    f"{expected_id} spoken dialogue must contain 1-15 words"
                )
            spoken_lines += 1

        scene["emotion_start"] = _text(
            scene["emotion_start"], label=f"{expected_id} emotion_start"
        )
        scene["emotion_end"] = _text(
            scene["emotion_end"], label=f"{expected_id} emotion_end"
        )
        countdown = scene["countdown_seconds"]
        if (
            not isinstance(countdown, int)
            or isinstance(countdown, bool)
            or countdown < 0
        ):
            raise ValidationError(f"{expected_id} countdown_seconds is invalid")
        scene["props"] = _string_list(scene["props"], label=f"{expected_id} props")
        scene["concepts"] = _string_list(
            scene["concepts"], label=f"{expected_id} concepts"
        )
        if scene["act"] < 3 and scene["concepts"]:
            raise ValidationError("Creative Scenario concepts may appear only in Act 3")
        scene["ui_overlays"] = _string_list(
            scene["ui_overlays"], label=f"{expected_id} ui_overlays"
        )
        scene["sound"] = _text(scene["sound"], label=f"{expected_id} sound")

        shot = _object(
            scene["shot"], label=f"{expected_id} shot", fields=_SHOT_FIELDS
        )
        for field in (
            "framing",
            "lens",
            "movement",
            "speed",
            "angle",
            "composition",
            "lighting",
            "screen_direction",
            "performance_note",
        ):
            shot[field] = _text(shot[field], label=f"{expected_id} shot.{field}")
        shot["style"] = _string_list(
            shot["style"], label=f"{expected_id} shot.style", allow_empty=False
        )
        shot["forbidden_style"] = _string_list(
            shot["forbidden_style"],
            label=f"{expected_id} shot.forbidden_style",
            allow_empty=False,
        )
        strategy = shot["render_strategy"]
        if strategy not in STRATEGY_CAPABILITIES:
            raise ValidationError(f"{expected_id} render strategy is invalid")
        if strategy != "runway_video" and shot["movement"] != "static":
            raise ValidationError(
                f"{expected_id} non-video strategy requires a static camera"
            )
        if strategy == "runway_video" and shot["movement"] == "static":
            raise ValidationError(f"{expected_id} video strategy requires camera movement")
        if strategy == "title_card" and "title card reads:" not in scene[
            "action"
        ].casefold():
            raise ValidationError(
                f"{expected_id} title-card action must begin with a renderable title-card cue"
            )
        normalized_scenes.append(scene)

    if spoken_lines > spoken_line_limit:
        raise ValidationError(
            "Creative Scenario exceeds its spoken_line_limit",
            details={"actual": spoken_lines, "limit": spoken_line_limit},
        )
    if {scene["act"] for scene in normalized_scenes} != {1, 2, 3}:
        raise ValidationError("Creative Scenario must contain all three acts")
    if any(
        normalized_scenes[index - 1]["emotion_end"]
        != normalized_scenes[index]["emotion_start"]
        for index in range(1, len(normalized_scenes))
    ):
        raise ValidationError("Creative Scenario emotional continuity is invalid")
    countdowns = [scene["countdown_seconds"] for scene in normalized_scenes]
    if countdowns != sorted(countdowns, reverse=True) or len(countdowns) != len(
        set(countdowns)
    ):
        raise ValidationError("Creative Scenario countdown must strictly decrease")
    scene_total = sum(scene["duration_seconds"] for scene in normalized_scenes)
    if abs(scene_total - total_duration) > 0.001:
        raise ValidationError(
            "Creative Scenario scene timing does not equal the declared duration",
            details={"declared": total_duration, "scene_total": scene_total},
        )
    document["scenes"] = normalized_scenes
    document["source"] = {
        "creative_brief_hash": creative_brief_hash,
        "extraction_contract": CREATIVE_SCENARIO_EXTRACTION_CONTRACT,
    }
    document["content_hash"] = content_hash(document)
    return document


def extract_creative_scenario(
    body: str, *, creative_brief_hash: str
) -> dict[str, Any] | None:
    """Extract zero or one authored scenario from a Creative Brief body."""

    matches = list(_FENCE.finditer(body))
    if not matches:
        return None
    if len(matches) != 1:
        raise ValidationError("Creative Brief must contain at most one creative-scenario block")
    try:
        raw = json.loads(matches[0].group("body"))
    except json.JSONDecodeError as exc:
        raise ValidationError(
            "Creative Scenario block is not valid JSON",
            details={"line": exc.lineno, "column": exc.colno},
        ) from exc
    if not isinstance(raw, dict):
        raise ValidationError("Creative Scenario block must contain a JSON object")
    return validate_creative_scenario(raw, creative_brief_hash=creative_brief_hash)
