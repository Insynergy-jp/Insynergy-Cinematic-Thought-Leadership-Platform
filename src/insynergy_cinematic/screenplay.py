"""Deterministic, contract-driven Screenplay Engine.

The engine consumes Story artifacts only.  It produces an eight-scene minimum
screenplay, independently testable dialogue/continuity/export contracts, a
frozen configuration snapshot, and an explicit pre-approval lifecycle state.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any

from .creative_scenario import AUTHORED_SCENE_DURATION_MIN
from .errors import QualityGateError, StateConflictError, ValidationError
from .util import atomic_write_json, content_hash, read_json


SCREENPLAY_ENGINE_VERSION = "3.4.0"
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
ALLOWED_TRANSITIONS = frozenset(
    {"Hard Cut", "Fade", "Match Cut", "L Cut", "J Cut"}
)
ALLOWED_DIALOGUE_CATEGORIES = frozenset(
    {"Question", "Demand", "Refusal", "Warning", "Decision", "Revelation"}
)
CONTINUITY_DIMENSIONS = (
    "character",
    "wardrobe",
    "location",
    "time",
    "emotion",
    "countdown",
    "props",
)
PROHIBITED_INTERIOR_ACTION = re.compile(
    r"\b(?:thinks?|feels?|realizes?|remembers?|believes?|wonders?|imagines?)\b",
    flags=re.IGNORECASE,
)
PROHIBITED_EXPOSITION = re.compile(
    r"\b(?:the article|is defined as|means that|the framework is|the concept is)\b",
    flags=re.IGNORECASE,
)
PROHIBITED_BIOGRAPHY = re.compile(
    r"\b(?:hospital|funeral|trauma|diagnosis|childhood|disability|poverty)\b",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class ScreenplayConfig:
    """Resolved, immutable Part 3 generation contract."""

    profile: str = "preview"
    scene_count_min: int = 8
    scene_count_max: int = 12
    scene_duration_min: int = 4
    scene_duration_target: int = 7
    scene_duration_max: int = 10
    words_per_line: int = 15
    lines_per_turn: int = 2
    exposition_allowed: bool = False
    silence_allowed: bool = True
    all_dimensions_checked: bool = True
    violation_fails_validation: bool = True
    fountain: bool = True
    json: bool = True
    custom_syntax: bool = False

    def __post_init__(self) -> None:
        if self.profile not in {"preview", "production"}:
            raise ValidationError("Screenplay profile must be preview or production")
        if not 8 <= self.scene_count_min <= self.scene_count_max <= 12:
            raise ValidationError("Screenplay scene count must remain within 8-12")
        if not 4 <= self.scene_duration_min <= self.scene_duration_target <= self.scene_duration_max:
            raise ValidationError("Screenplay duration bounds are invalid")
        if self.scene_duration_max != 10:
            raise ValidationError("Screenplay maximum scene duration must be 10 seconds")
        if self.words_per_line != 15 or self.lines_per_turn != 2:
            raise ValidationError("Screenplay dialogue limits are normative")
        if any(
            (
                self.exposition_allowed,
                not self.silence_allowed,
                not self.all_dimensions_checked,
                not self.violation_fails_validation,
                not self.fountain,
                not self.json,
                self.custom_syntax,
            )
        ):
            raise ValidationError("Screenplay configuration weakens a normative invariant")

    def artifact(self, cache_key: str) -> dict[str, Any]:
        return {
            "generation": {
                "scene_count_min": self.scene_count_min,
                "scene_count_max": self.scene_count_max,
                "scene_duration_min": self.scene_duration_min,
                "scene_duration_target": self.scene_duration_target,
                "scene_duration_max": self.scene_duration_max,
                "one_purpose_per_scene": True,
                "one_conflict_per_scene": True,
            },
            "dialogue": {
                "words_per_line": self.words_per_line,
                "lines_per_turn": self.lines_per_turn,
                "exposition_allowed": self.exposition_allowed,
                "silence_allowed": self.silence_allowed,
            },
            "continuity": {
                "all_dimensions_checked": self.all_dimensions_checked,
                "violation_fails_validation": self.violation_fails_validation,
            },
            "export": {
                "fountain": self.fountain,
                "json": self.json,
                "custom_syntax": self.custom_syntax,
            },
            "cache": {"cache_key": cache_key},
            "profile": self.profile,
            "engine_version": SCREENPLAY_ENGINE_VERSION,
            "immutable_at_runtime": True,
        }


class ScreenplayCache:
    """Exact-key cache for complete, already validated Screenplay bundles."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, cache_key: str) -> Path:
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", cache_key):
            raise ValidationError("Invalid screenplay cache key")
        return self.root / f"{cache_key.split(':', 1)[1]}.json"

    def get(self, cache_key: str) -> dict[str, dict[str, Any]] | None:
        path = self._path(cache_key)
        if not path.is_file():
            return None
        document = read_json(path)
        if not isinstance(document, dict) or document.get("cache_key") != cache_key:
            raise ValidationError("Screenplay cache entry is corrupt")
        artifacts = document.get("artifacts")
        if not isinstance(artifacts, dict):
            raise ValidationError("Screenplay cache entry has no artifact bundle")
        if document.get("artifact_bundle_hash") != content_hash(artifacts):
            raise ValidationError("Screenplay cache entry failed its integrity check")
        if artifacts.get("screenplay_config", {}).get("cache", {}).get("cache_key") != cache_key:
            raise ValidationError("Screenplay cache entry is bound to another input")
        return deepcopy(artifacts)

    def put(self, cache_key: str, artifacts: dict[str, dict[str, Any]]) -> None:
        if artifacts.get("screenplay_quality_report", {}).get("passed") is not True:
            raise ValidationError("Only validated screenplays may enter the cache")
        atomic_write_json(
            self._path(cache_key),
            {
                "cache_key": cache_key,
                "artifact_bundle_hash": content_hash(artifacts),
                "artifacts": artifacts,
            },
        )


class DialogueGenerator:
    """Creates and validates bounded tension dialogue, including silence."""

    def validate(
        self, scenes: list[dict[str, Any]], config: ScreenplayConfig
    ) -> list[dict[str, Any]]:
        flattened: list[dict[str, Any]] = []
        for scene in scenes:
            turns: dict[str, int] = {}
            for line in scene.get("dialogue", []):
                character = str(line.get("character", ""))
                text = str(line.get("text", ""))
                category = str(line.get("category", ""))
                silence = line.get("silence") is True
                if not character or category not in ALLOWED_DIALOGUE_CATEGORIES:
                    raise ValidationError("Dialogue line has an invalid speaker or category")
                if silence:
                    if not config.silence_allowed or text:
                        raise ValidationError("Silence must be explicit and text-free")
                elif not text or len(text.split()) > config.words_per_line:
                    raise ValidationError("Dialogue exceeds the 15-word line limit")
                if PROHIBITED_EXPOSITION.search(text):
                    raise ValidationError("Exposition dialogue is prohibited")
                turns[character] = turns.get(character, 0) + 1
                if turns[character] > config.lines_per_turn:
                    raise ValidationError("Dialogue exceeds two lines per turn")
                flattened.append({"scene_id": scene["scene_id"], **line})
        return flattened


class ContinuityValidator:
    """Evaluates all seven normative continuity dimensions."""

    @staticmethod
    def _monotonic_countdown(scenes: list[dict[str, Any]]) -> bool:
        values = [int(scene["countdown_seconds"]) for scene in scenes]
        return values == sorted(values, reverse=True) and len(values) == len(set(values))

    def validate(
        self,
        scenes: list[dict[str, Any]],
        character_bible: dict[str, Any],
        persona_lineage: dict[str, Any] | None,
    ) -> dict[str, Any]:
        known = {
            str(character["character_id"]): str(
                character.get("visual_identity", {}).get("continuity_key", "")
            )
            for character in character_bible["characters"]
        }
        character_ok = all(
            set(scene["characters"]).issubset(known) and bool(scene["characters"])
            for scene in scenes
        )
        wardrobe_ok = all(known.get(character_id) for character_id in known)
        location_ok = all(bool(scene["location"]) for scene in scenes)
        time_ok = all(bool(scene["time_of_day"]) for scene in scenes)
        emotion_ok = all(
            scenes[index - 1]["emotion_end"] == scene["emotion_start"]
            for index, scene in enumerate(scenes)
            if index > 0
        )
        countdown_ok = self._monotonic_countdown(scenes)
        props_ok = all(isinstance(scene.get("props"), list) for scene in scenes)
        checks = {
            "character": character_ok,
            "wardrobe": wardrobe_ok,
            "location": location_ok,
            "time": time_ok,
            "emotion": emotion_ok,
            "countdown": countdown_ok,
            "props": props_ok,
        }
        violations = [
            {
                "scene_id": scenes[0]["scene_id"],
                "dimension": dimension,
                "detail": f"{dimension} continuity failed",
            }
            for dimension, passed in checks.items()
            if not passed
        ]
        persona_ids = {
            scene.get("persona_id") for scene in scenes if scene.get("persona_id")
        }
        persona_ok = persona_lineage is None or persona_ids == {
            persona_lineage["persona_id"]
        }
        return {
            "checks": checks,
            "countdown_monotonic": countdown_ok,
            "emotion_continuous": emotion_ok,
            "persona_lineage_stable": persona_ok,
            "violations": violations,
            "valid": all(checks.values()) and persona_ok,
            "dimensions_checked": list(CONTINUITY_DIMENSIONS),
        }


class ScreenplayExporter:
    """Produces standard Fountain and the canonical machine screenplay."""

    TRANSITIONS = {
        "Hard Cut": "CUT TO:",
        "Fade": "FADE OUT.",
        "Match Cut": "MATCH CUT TO:",
        "L Cut": "L CUT TO:",
        "J Cut": "J CUT TO:",
    }

    def fountain(
        self, screenplay: dict[str, Any], character_bible: dict[str, Any]
    ) -> str:
        names = {
            value["character_id"]: value["name"].upper()
            for value in character_bible["characters"]
        }
        lines = [f"Title: {screenplay['title']}", ""]
        for scene in screenplay["scenes"]:
            lines.extend((f".{scene['slugline']}", ""))
            for action in scene["actions"]:
                lines.extend((action, ""))
            for dialogue in scene["dialogue"]:
                if dialogue["silence"]:
                    lines.extend(("(A deliberate silence.)", ""))
                    continue
                lines.extend(
                    (
                        names.get(dialogue["character"], dialogue["character"].upper()),
                        dialogue["text"],
                        "",
                    )
                )
            lines.extend((f"> {self.TRANSITIONS[scene['transition']]}", ""))
        return "\n".join(lines).rstrip() + "\n"


class ScreenplayQualityGate:
    """Fail-closed evaluator for the normative Part 3 constraints."""

    @staticmethod
    def _observable(scenes: list[dict[str, Any]]) -> bool:
        return all(
            scene.get("actions")
            and all(
                isinstance(action, str)
                and bool(action.strip())
                and PROHIBITED_INTERIOR_ACTION.search(action) is None
                for action in scene["actions"]
            )
            for scene in scenes
        )

    def evaluate(
        self,
        scenes: list[dict[str, Any]],
        continuity: dict[str, Any],
        config: ScreenplayConfig,
        persona_lineage: dict[str, Any] | None,
        creative_scenario: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        dialogue_lines = [line for scene in scenes for line in scene["dialogue"]]
        duration_minimum = (
            AUTHORED_SCENE_DURATION_MIN
            if creative_scenario is not None
            else float(config.scene_duration_min)
        )
        checks = {
            "scene_count_in_range": config.scene_count_min
            <= len(scenes)
            <= config.scene_count_max,
            "scene_order_valid": [scene["order"] for scene in scenes]
            == list(range(1, len(scenes) + 1)),
            "three_acts_present": {scene["act"] for scene in scenes} == {1, 2, 3},
            "one_purpose_per_scene": all(
                scene.get("purpose") in ALLOWED_PURPOSES for scene in scenes
            ),
            "one_conflict_per_scene": all(
                scene.get("conflict") in ALLOWED_CONFLICTS for scene in scenes
            ),
            "heading_grammar_valid": all(
                scene.get("heading", {}).get("interior_exterior")
                in {"INT", "EXT", "INT./EXT."}
                and bool(scene.get("heading", {}).get("location"))
                and bool(scene.get("heading", {}).get("time"))
                for scene in scenes
            ),
            "character_objectives_exist": all(
                set(scene["characters"]) == set(scene["objective"])
                and all(scene["objective"].values())
                for scene in scenes
            ),
            "observable_actions_only": self._observable(scenes),
            "dialogue_under_limit": all(
                line["silence"] or len(line["text"].split()) <= config.words_per_line
                for line in dialogue_lines
            ),
            "tension_dialogue_only": all(
                line["category"] in ALLOWED_DIALOGUE_CATEGORIES
                and PROHIBITED_EXPOSITION.search(line["text"]) is None
                for line in dialogue_lines
            ),
            "silence_represented": any(line["silence"] for line in dialogue_lines),
            "duration_within_bounds": all(
                duration_minimum
                <= float(scene["duration_seconds"])
                <= float(config.scene_duration_max)
                for scene in scenes
            ),
            "cinematic_transitions_only": all(
                scene["transition"] in ALLOWED_TRANSITIONS for scene in scenes
            ),
            "concepts_only_in_act_3": all(
                not scene["concepts"] for scene in scenes if scene["act"] < 3
            ),
            "continuity_valid": continuity.get("valid") is True,
            "persona_lineage_valid": persona_lineage is None
            or continuity.get("persona_lineage_stable") is True,
            "no_invented_biography_or_borrowed_stakes": all(
                PROHIBITED_BIOGRAPHY.search(
                    " ".join(
                        [*scene["actions"], *[line["text"] for line in scene["dialogue"]]]
                    )
                )
                is None
                for scene in scenes
            ),
        }
        if creative_scenario is not None:
            checks.update(
                {
                    "authored_scenario_hash_preserved": creative_scenario.get(
                        "content_hash"
                    )
                    == content_hash(
                        {
                            key: value
                            for key, value in creative_scenario.items()
                            if key != "content_hash"
                        }
                    ),
                    "authored_scenario_timing_exact": abs(
                        sum(float(scene["duration_seconds"]) for scene in scenes)
                        - float(creative_scenario["duration_seconds"])
                    )
                    <= 0.001,
                    "authored_scenario_scene_identity_preserved": [
                        scene["scene_id"] for scene in scenes
                    ]
                    == [scene["scene_id"] for scene in creative_scenario["scenes"]],
                }
            )
        score = sum(checks.values()) / len(checks)
        return {
            "gate_id": "screenplay_quality_gate",
            "passed": all(checks.values()),
            "score": score,
            "threshold": 1.0,
            "checks": checks,
            "blocking": True,
            "fail_closed": True,
        }


class ScreenplayStateMachine:
    """Explicit, forward-only Part 3 lifecycle."""

    LEGAL = {
        "Pending": {"Generating", "Failed"},
        "Generating": {"Generated", "Failed"},
        "Generated": {"Validating", "Failed"},
        "Validating": {"Validated", "Failed"},
        "Validated": {"AwaitingApproval", "Failed"},
        "AwaitingApproval": {"Approved", "Failed"},
        "Approved": {"Exported"},
        "Exported": set(),
        "Failed": set(),
    }

    def transition(self, current: str, requested: str) -> str:
        if requested not in self.LEGAL.get(current, set()):
            raise StateConflictError(
                "Illegal Screenplay state transition",
                details={"current": current, "requested": requested},
            )
        return requested


class SceneGenerator:
    """Builds the minimum complete eight-scene dramatic progression."""

    @staticmethod
    def _dialogue(
        character: str, text: str, category: str, *, silence: bool = False
    ) -> list[dict[str, Any]]:
        return [
            {
                "character": character,
                "text": text,
                "category": category,
                "silence": silence,
            }
        ]

    def generate(
        self,
        *,
        protagonist: dict[str, Any],
        counterpart: dict[str, Any],
        concept: str,
        question: str,
        persona_lineage: dict[str, Any] | None,
        duration: int,
    ) -> list[dict[str, Any]]:
        protagonist_id = protagonist["character_id"]
        counterpart_id = counterpart["character_id"]
        goal = protagonist["objective"]
        counter_goal = counterpart["objective"]
        specifications = [
            (
                1,
                "Introduce protagonist",
                "Human vs Institution",
                "control",
                "concern",
                119,
                f"{protagonist['name']} opens the pending approval record beside a red deadline folder.",
                self._dialogue(protagonist_id, "Who owns the authority behind this approval?", "Question"),
                [protagonist_id, counterpart_id],
                ["approval record", "red deadline folder"],
            ),
            (
                1,
                "Reveal hidden risk",
                "Institution vs Reality",
                "concern",
                "alarm",
                107,
                "The owner field remains blank while the countdown advances.",
                self._dialogue(counterpart_id, "The process already has every required signature.", "Warning"),
                [protagonist_id, counterpart_id],
                ["approval record", "red deadline folder"],
            ),
            (
                2,
                "Increase urgency",
                "Human vs Time",
                "alarm",
                "pressure",
                91,
                "The deadline warning turns red across the review screen.",
                self._dialogue(counterpart_id, "Approve it now or accept the visible delay.", "Demand"),
                [protagonist_id, counterpart_id],
                ["approval record", "red deadline folder"],
            ),
            (
                2,
                "Create reversal",
                "Human vs Institution",
                "pressure",
                "doubt",
                75,
                f"{protagonist['name']} turns the unsigned record toward {counterpart['name']}.",
                self._dialogue(protagonist_id, "Signatures do not identify the person entitled to decide.", "Refusal"),
                [protagonist_id, counterpart_id],
                ["approval record", "red deadline folder"],
            ),
            (
                2,
                "Reveal hidden risk",
                "Human vs Self",
                "doubt",
                "resolve",
                58,
                f"{protagonist['name']} holds one hand above APPROVE, then withdraws it.",
                self._dialogue(protagonist_id, "", "Revelation", silence=True),
                [protagonist_id],
                ["approval record", "red deadline folder"],
            ),
            (
                2,
                "Force decision",
                "Human vs Time",
                "resolve",
                "commitment",
                41,
                f"{counterpart['name']} points at the clock; {protagonist['name']} selects HOLD.",
                self._dialogue(protagonist_id, "Execution waits until authorization has one accountable owner.", "Decision"),
                [protagonist_id, counterpart_id],
                ["approval record", "red deadline folder"],
            ),
            (
                3,
                "Force decision",
                "Human vs Institution",
                "commitment",
                "authority",
                24,
                f"{protagonist['name']} enters Authorization Owner and signs the decision record.",
                self._dialogue(protagonist_id, "I accept this authority on the record.", "Decision"),
                [protagonist_id],
                ["approval record", "red deadline folder", "decision record"],
            ),
            (
                3,
                "Resolve conflict",
                "Institution vs Reality",
                "authority",
                "resolve",
                0,
                f"A title card reads: AUTHORIZATION OWNER RECORDED — {concept.upper()}.",
                self._dialogue(protagonist_id, "Recommendation is not authorization.", "Revelation"),
                [protagonist_id],
                ["decision record"],
            ),
        ]
        scenes: list[dict[str, Any]] = []
        for index, specification in enumerate(specifications, start=1):
            (
                act,
                purpose,
                conflict,
                emotion_start,
                emotion_end,
                countdown,
                action,
                dialogue,
                characters,
                props,
            ) = specification
            time_of_day = "NIGHT" if index <= 2 else "CONTINUOUS"
            heading = {
                "interior_exterior": "INT",
                "location": "Executive Review Room",
                "time": time_of_day,
            }
            objective = {
                character_id: goal if character_id == protagonist_id else counter_goal
                for character_id in characters
            }
            scene = {
                "scene_id": f"scene-{index:03d}",
                "order": index,
                "act": act,
                "heading": heading,
                "slugline": f"INT. EXECUTIVE REVIEW ROOM - {time_of_day}",
                "purpose": purpose,
                "dramatic_purpose": purpose,
                "characters": characters,
                "objective": objective,
                "character_objectives": objective,
                "conflict": conflict,
                "dominant_conflict": conflict,
                "actions": [action],
                "dialogue": dialogue,
                "visual_subtext": question if act == 3 else "Authority remains visible only through human choice.",
                "subtext": question if act == 3 else "Authority remains visible only through human choice.",
                "duration_seconds": duration,
                "transition": "Fade" if index == len(specifications) else "Hard Cut",
                "concepts": [concept] if act == 3 else [],
                "emotion_start": emotion_start,
                "emotion_end": emotion_end,
                "countdown_seconds": countdown,
                "props": props,
                "location": heading["location"],
                "time_of_day": time_of_day,
            }
            if persona_lineage is not None:
                scene["persona_id"] = persona_lineage["persona_id"]
                scene["assumption_lineage"] = list(
                    persona_lineage.get("assumption_lineage", [])
                )
            scenes.append(scene)
        return scenes


class AuthoredSceneGenerator:
    """Maps an approved Creative Scenario into canonical Screenplay scenes."""

    def generate(
        self,
        *,
        scenario: dict[str, Any],
        protagonist: dict[str, Any],
        counterpart: dict[str, Any],
        persona_lineage: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        role_map = {
            "protagonist": protagonist,
            "counterforce": counterpart,
        }
        scenes: list[dict[str, Any]] = []
        for order, authored in enumerate(scenario["scenes"], start=1):
            characters = [
                role_map[role]["character_id"] for role in authored["characters"]
            ]
            objectives = {
                role_map[role]["character_id"]: role_map[role]["objective"]
                for role in authored["characters"]
            }
            speaker = role_map[authored["dialogue"]["speaker"]]["character_id"]
            heading = deepcopy(authored["heading"])
            scene = {
                "scene_id": authored["scene_id"],
                "order": order,
                "act": authored["act"],
                "title": authored["title"],
                "heading": heading,
                "slugline": (
                    f"{heading['interior_exterior']}. {heading['location'].upper()}"
                    f" - {heading['time'].upper()}"
                ),
                "purpose": authored["purpose"],
                "dramatic_purpose": authored["purpose"],
                "characters": characters,
                "objective": objectives,
                "character_objectives": objectives,
                "conflict": authored["conflict"],
                "dominant_conflict": authored["conflict"],
                "actions": [authored["action"]],
                "dialogue": [
                    {
                        "character": speaker,
                        "text": authored["dialogue"]["text"],
                        "category": authored["dialogue"]["category"],
                        "silence": authored["dialogue"]["silence"],
                    }
                ],
                "visual_subtext": authored["title"],
                "subtext": authored["title"],
                "duration_seconds": authored["duration_seconds"],
                "transition": authored["transition"],
                "concepts": deepcopy(authored["concepts"]),
                "emotion_start": authored["emotion_start"],
                "emotion_end": authored["emotion_end"],
                "countdown_seconds": authored["countdown_seconds"],
                "props": deepcopy(authored["props"]),
                "location": heading["location"],
                "time_of_day": heading["time"],
                "shot_design": deepcopy(authored["shot"]),
                "ui_overlays": deepcopy(authored["ui_overlays"]),
                "sound_design": authored["sound"],
                "creative_scenario_hash": scenario["content_hash"],
            }
            if persona_lineage is not None:
                scene["persona_id"] = persona_lineage["persona_id"]
                scene["assumption_lineage"] = list(
                    persona_lineage.get("assumption_lineage", [])
                )
            scenes.append(scene)
        return scenes


class ScreenplayEngine:
    REQUIRED_INPUTS = {
        "dramatic_premise",
        "dramatic_question",
        "character_bible",
        "conflict",
        "stakes",
        "three_act_structure",
        "emotional_arc",
        "concept_placement",
    }

    def __init__(
        self,
        *,
        config: ScreenplayConfig | None = None,
        cache: ScreenplayCache | None = None,
    ) -> None:
        self.config = config or ScreenplayConfig()
        self.cache = cache
        self.last_cache_hit = False
        self.scenes = SceneGenerator()
        self.authored_scenes = AuthoredSceneGenerator()
        self.dialogue = DialogueGenerator()
        self.continuity = ContinuityValidator()
        self.exporter = ScreenplayExporter()
        self.quality = ScreenplayQualityGate()
        self.state = ScreenplayStateMachine()

    @staticmethod
    def _persona_lineage(story: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
        raw = story.get("persona_lineage")
        if raw is None:
            return None
        required = {
            "persona_id",
            "persona_content_hash",
            "persona_approval_binding_hash",
            "assumption_lineage",
        }
        if not isinstance(raw, dict) or required.difference(raw):
            raise ValidationError("Approved Persona lineage is incomplete")
        for field in ("persona_content_hash", "persona_approval_binding_hash"):
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", str(raw[field])):
                raise ValidationError("Approved Persona lineage hash is invalid")
        if not isinstance(raw["assumption_lineage"], list):
            raise ValidationError("Persona assumption lineage must be an array")
        return deepcopy(raw)

    def _cache_identity(self, story: dict[str, dict[str, Any]]) -> tuple[str, str]:
        story_hash = content_hash(
            {name: story[name] for name in sorted(self.REQUIRED_INPUTS)}
            | ({"persona_lineage": story["persona_lineage"]} if "persona_lineage" in story else {})
            | ({"creative_scenario": story["creative_scenario"]} if "creative_scenario" in story else {})
        )
        return story_hash, content_hash(
            {
                "story_hash": story_hash,
                "screenplay_engine_version": SCREENPLAY_ENGINE_VERSION,
                "screenplay_profile": self.config.profile,
                "configuration": asdict(self.config),
            }
        )

    def generate(self, story: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        missing = self.REQUIRED_INPUTS.difference(story)
        if missing:
            raise ValidationError(f"Missing Story artifacts: {sorted(missing)}")
        story_hash, cache_key = self._cache_identity(story)
        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                self.last_cache_hit = True
                return cached
        self.last_cache_hit = False
        lifecycle = "Pending"
        lifecycle = self.state.transition(lifecycle, "Generating")
        protagonist = next(
            value
            for value in story["character_bible"]["characters"]
            if value["role"] == "protagonist"
        )
        counterpart = next(
            value
            for value in story["character_bible"]["characters"]
            if value["role"] == "counterforce"
        )
        persona_lineage = self._persona_lineage(story)
        creative_scenario = story.get("creative_scenario")
        if creative_scenario is not None:
            scenes = self.authored_scenes.generate(
                scenario=creative_scenario,
                protagonist=protagonist,
                counterpart=counterpart,
                persona_lineage=persona_lineage,
            )
        else:
            scenes = self.scenes.generate(
                protagonist=protagonist,
                counterpart=counterpart,
                concept=story["concept_placement"]["concept"],
                question=story["dramatic_question"]["dramatic_question"],
                persona_lineage=persona_lineage,
                duration=self.config.scene_duration_min,
            )
        lifecycle = self.state.transition(lifecycle, "Generated")
        lifecycle = self.state.transition(lifecycle, "Validating")
        dialogue_lines = self.dialogue.validate(scenes, self.config)
        continuity = self.continuity.validate(
            scenes, story["character_bible"], persona_lineage
        )
        report = self.quality.evaluate(
            scenes,
            continuity,
            self.config,
            persona_lineage,
            creative_scenario,
        )
        if not report["passed"]:
            raise QualityGateError("Screenplay Quality Gate failed", details=report)
        lifecycle = self.state.transition(lifecycle, "Validated")
        lifecycle = self.state.transition(lifecycle, "AwaitingApproval")
        screenplay = {
            "title": (
                creative_scenario["title"]
                if creative_scenario is not None
                else "The Empty Approval Field"
            ),
            "format": "cinematic_thought_leadership_short",
            "duration_seconds": sum(scene["duration_seconds"] for scene in scenes),
            "act_count": 3,
            "scene_count": len(scenes),
            "scenes": scenes,
            "source_contract": (
                "story_artifacts_only:authored_creative_scenario"
                if creative_scenario is not None
                else "story_artifacts_only"
            ),
            "story_hash": story_hash,
            "engine_version": SCREENPLAY_ENGINE_VERSION,
        }
        if persona_lineage is not None:
            screenplay["persona_lineage"] = persona_lineage
        if creative_scenario is not None:
            screenplay["creative_scenario_hash"] = creative_scenario["content_hash"]
        action_words = sum(
            len(action.split()) for scene in scenes for action in scene["actions"]
        )
        dialogue_words = sum(
            len(line["text"].split()) for line in dialogue_lines if not line["silence"]
        )
        total_words = action_words + dialogue_words
        continuity_score = sum(continuity["checks"].values()) / len(
            continuity["checks"]
        )
        metrics = {
            "scene_count": len(scenes),
            "dialogue_ratio": round(dialogue_words / total_words, 4),
            "action_ratio": round(action_words / total_words, 4),
            "average_scene_duration": sum(
                scene["duration_seconds"] for scene in scenes
            )
            / len(scenes),
            "continuity_score": continuity_score,
        }
        scene_index = {
            "scenes": [
                {
                    "scene_id": scene["scene_id"],
                    "act": scene["act"],
                    "order": scene["order"],
                    "purpose": scene["purpose"],
                }
                for scene in scenes
            ],
            "ordering": "strict",
        }
        if persona_lineage is not None:
            for artifact in (screenplay, scene_index, continuity):
                artifact["persona_lineage"] = deepcopy(persona_lineage)
        dialogue_artifact: dict[str, Any] = {"lines": dialogue_lines}
        if persona_lineage is not None:
            dialogue_artifact["persona_lineage"] = deepcopy(persona_lineage)
        screenplay_config = self.config.artifact(cache_key)
        screenplay_config.update(
            {
                "active_generation_contract": (
                    "authored_creative_scenario/1"
                    if creative_scenario is not None
                    else "canonical_deterministic/1"
                ),
                "active_scene_duration_min": (
                    AUTHORED_SCENE_DURATION_MIN
                    if creative_scenario is not None
                    else self.config.scene_duration_min
                ),
                "creative_scenario_hash": (
                    creative_scenario["content_hash"]
                    if creative_scenario is not None
                    else None
                ),
            }
        )
        if creative_scenario is not None:
            narration_segments = [
                {"scene_id": line["scene_id"], "text": line["text"]}
                for line in dialogue_lines
                if not line["silence"]
            ]
            narration_language = creative_scenario["language"]
        else:
            narration_segments = [
                {"scene_id": scene["scene_id"], "text": text}
                for scene, text in zip(
                    scenes,
                    (
                        "A consequential approval is already moving.",
                        "Its authority has no named owner.",
                        "The deadline makes delay visible.",
                        "The decision boundary remains hidden.",
                        "Silence exposes the inherited ambiguity.",
                        "One human stops the process.",
                        "Authority is accepted on the record.",
                        "Recommendation is not authorization.",
                    ),
                    strict=True,
                )
            ]
            narration_language = "en"
        artifacts: dict[str, dict[str, Any]] = {
            "screenplay": screenplay,
            "scene_index": scene_index,
            "dialogue": dialogue_artifact,
            "continuity": continuity,
            "screenplay_metrics": metrics,
            "screenplay_config": screenplay_config,
            "screenplay_state": {
                "state": lifecycle,
                "scene_states": [
                    {"scene_id": scene["scene_id"], "state": "Validated"}
                    for scene in scenes
                ],
            },
            "screenplay_quality_report": report,
            "screenplay_fountain": {
                "content": self.exporter.fountain(
                    screenplay, story["character_bible"]
                ),
                "standard_fountain_only": True,
                "approval_state": lifecycle,
            },
            "narration_script": {
                "language": narration_language,
                "segments": narration_segments,
                "throughline": True,
                "final_audio_required": True,
                "delivery": (
                    "character_dialogue"
                    if creative_scenario is not None
                    else "narration"
                ),
            },
        }
        if self.cache is not None:
            self.cache.put(cache_key, artifacts)
        return deepcopy(artifacts)


def part3_coverage_report() -> dict[str, Any]:
    """Return the fixed twenty-cluster Part 3 implementation matrix."""

    full = [
        ("story_only_boundary", "Screenplay consumes the sealed Story bundle only"),
        ("scene_cardinality_and_structure", "eight ordered scenes across exactly three acts"),
        ("purpose_conflict_objectives", "one controlled purpose, conflict, and objective set per scene"),
        ("subtext_and_emotional_progression", "visual subtext and continuous emotional transitions"),
        ("observable_action", "physical-action validator rejects interior thought"),
        ("dialogue_and_silence", "15-word/two-line categories plus explicit silence"),
        ("timing_transitions_concepts", "4-10 seconds, cinematic transitions, Act 3 concepts"),
        ("fountain_and_json", "standard Fountain and machine screenplay artifacts"),
        ("continuity", "seven-dimension fail-closed continuity validator"),
        ("quality_gate", "deterministic mandatory Screenplay Quality Gate"),
        ("computed_metrics", "measured action/dialogue/duration/continuity metrics"),
        ("immutable_configuration", "versioned frozen resolved configuration snapshot"),
        ("cache_and_determinism", "exact Story/version/profile/config key and validated reuse"),
        ("operational_state", "validated lifecycle and per-scene state artifacts"),
        ("public_interfaces", "independently testable generator/dialogue/continuity/export/gate interfaces"),
        ("agent_review_boundary", "read-only post-generation review evidence remains isolated"),
        ("automated_acceptance", "positive, negative, cache, state, Persona, and E2E tests"),
        ("persona_continuity", "approved live Persona lineage is enforced through Story and Screenplay invalidation"),
    ]
    partial = [
        ("human_screenplay_approval", "AwaitingApproval is explicit; approval remains aggregate render approval"),
        (
            "operational_dashboard",
            "longitudinal viewer outcomes and core Screenplay metric trends are deployed; exhaustive lifecycle timing trends remain follow-up",
        ),
    ]
    rows = [
        *({"cluster": cluster, "status": "FULL", "evidence": evidence} for cluster, evidence in full),
        *({"cluster": cluster, "status": "PARTIAL", "evidence": evidence} for cluster, evidence in partial),
    ]
    points = len(full) + len(partial) * 0.5
    return {
        "method": "FULL=1, PARTIAL=0.5, MISSING=0",
        "cluster_count": len(rows),
        "full": len(full),
        "partial": len(partial),
        "missing": 0,
        "points": points,
        "coverage_percent": round(points / len(rows) * 100, 1),
        "clusters": rows,
    }
