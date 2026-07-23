"""Storyboard-only deterministic prompt assembly."""

from __future__ import annotations

import re
from typing import Any

from .errors import ValidationError
from .util import content_hash


class PromptAssembler:
    _preferred_caps = {
        "composition": 240,
        "visible_action": 360,
        "identity": 120,
        "location": 60,
        "camera": 100,
        "lighting": 90,
        "emotion": 40,
        "style": 100,
        "excluded": 140,
        "cues": 220,
    }
    _minimum_caps = {
        "composition": 110,
        "visible_action": 260,
        "identity": 70,
        "location": 25,
        "camera": 50,
        "lighting": 60,
        "emotion": 20,
        "style": 70,
        "excluded": 90,
        "cues": 60,
    }
    _reduction_order = (
        "composition",
        "visible_action",
        "lighting",
        "style",
        "excluded",
        "camera",
        "identity",
        "location",
        "emotion",
        "cues",
    )
    _number_words = (
        "zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
    )
    _cue_pattern = re.compile(
        rf"\$\d+(?:\.\d+)?|\b\d{{1,2}}:\d{{2}}\b|"
        rf"\b[A-Z][A-Z0-9_-]{{1,}}\b|"
        rf"\b(?:{_number_words})\s+[a-z-]+(?:\s+[a-z-]+){{0,2}}\b"
    )
    _interface_state_pattern = re.compile(
        r"\b(?:changes to|reads|displays)\s+([^,.;]+)",
        flags=re.IGNORECASE,
    )
    _interaction_cue_pattern = re.compile(
        r"\bleft mouse button once\b",
        flags=re.IGNORECASE,
    )

    @staticmethod
    def utf16_length(value: str) -> int:
        return len(value.encode("utf-16-le")) // 2

    @classmethod
    def _prefix(cls, value: str, limit: int) -> str:
        if limit <= 0:
            return ""
        used = 0
        characters: list[str] = []
        for character in value:
            width = cls.utf16_length(character)
            if used + width > limit:
                break
            characters.append(character)
            used += width
        candidate = "".join(characters).rstrip()
        if len(candidate) < len(value) and " " in candidate:
            candidate = candidate.rsplit(" ", 1)[0].rstrip(" ,;:.")
        return candidate

    @classmethod
    def _suffix(cls, value: str, limit: int) -> str:
        if limit <= 0:
            return ""
        used = 0
        characters: list[str] = []
        for character in reversed(value):
            width = cls.utf16_length(character)
            if used + width > limit:
                break
            characters.append(character)
            used += width
        candidate = "".join(reversed(characters)).lstrip()
        if len(candidate) < len(value) and " " in candidate:
            candidate = candidate.split(" ", 1)[1].lstrip(" ,;:.")
        return candidate

    @classmethod
    def _clip_balanced(cls, value: str, limit: int) -> str:
        value = " ".join(value.split())
        if cls.utf16_length(value) <= limit:
            return value.rstrip(".")
        separator = " … "
        separator_units = cls.utf16_length(separator) * 2
        available = max(3, limit - separator_units)
        prefix_units = max(1, available * 45 // 100)
        middle_units = max(1, available * 30 // 100)
        suffix_units = max(1, available - prefix_units - middle_units)
        prefix = cls._prefix(value, prefix_units)
        suffix = cls._suffix(value, suffix_units)
        midpoint = len(value) // 2
        middle_start = max(0, midpoint - middle_units // 2)
        middle_source = value[middle_start:].lstrip()
        if middle_start > 0 and " " in middle_source:
            middle_source = middle_source.split(" ", 1)[1]
        middle = cls._prefix(middle_source, middle_units)
        candidate = separator.join(part for part in (prefix, middle, suffix) if part)
        while cls.utf16_length(candidate) > limit and middle:
            middle = cls._prefix(middle, max(1, cls.utf16_length(middle) - 1))
            candidate = separator.join(part for part in (prefix, middle, suffix) if part)
        if cls.utf16_length(candidate) > limit:
            candidate = cls._prefix(candidate, limit)
        return candidate.rstrip(".")

    @classmethod
    def _clip_list(cls, value: str, limit: int) -> str:
        parts = [part.strip() for part in re.split(r"[,;]", value) if part.strip()]
        full = "; ".join(parts)
        if cls.utf16_length(full) <= limit:
            return full
        if len(parts) < 2:
            return cls._clip_balanced(value, limit)

        priority: list[int] = []
        left, right = 0, len(parts) - 1
        while left <= right:
            priority.append(left)
            if right != left:
                priority.append(right)
            left += 1
            right -= 1

        selected: set[int] = set()

        def build() -> str:
            output: list[str] = []
            previous: int | None = None
            for index in sorted(selected):
                if previous is not None and index != previous + 1:
                    output.append("…")
                output.append(parts[index])
                previous = index
            return "; ".join(output)

        for index in priority:
            selected.add(index)
            if cls.utf16_length(build()) > limit:
                selected.remove(index)
        candidate = build()
        return candidate or cls._clip_balanced(value, limit)

    @classmethod
    def _exact_cues(cls, composition: str, visible_action: str) -> str:
        cues: list[str] = []
        observed: set[str] = set()
        for match in cls._cue_pattern.finditer(f"{composition} {visible_action}"):
            cue = match.group(0).strip()
            while cue.rsplit(" ", 1)[-1].casefold() in {
                "and",
                "but",
                "sit",
                "sits",
                "while",
                "with",
            }:
                cue = cue.rsplit(" ", 1)[0]
            folded = cue.casefold()
            if folded not in observed:
                observed.add(folded)
                cues.append(cue)
        for match in cls._interface_state_pattern.finditer(visible_action):
            cue = " ".join(match.group(1).split())
            folded = cue.casefold()
            if folded not in observed:
                observed.add(folded)
                cues.append(cue)
        for match in cls._interaction_cue_pattern.finditer(visible_action):
            cue = " ".join(match.group(0).split())
            folded = cue.casefold()
            if folded not in observed:
                observed.add(folded)
                cues.append(cue)
        return "; ".join(cues)

    @classmethod
    def _bounded_prompt(
        cls,
        *,
        values: dict[str, str],
        limit: int,
    ) -> str:
        labels = {
            "composition": "Frame",
            "visible_action": "Action",
            "identity": "Identity",
            "location": "Place",
            "camera": "Camera",
            "lighting": "Light",
            "emotion": "Mood",
            "style": "Style",
            "excluded": "Avoid",
            "cues": "Exact cues",
        }
        order = tuple(labels)
        caps = {
            key: min(cls.utf16_length(values[key]), cls._preferred_caps[key])
            for key in order
            if values.get(key)
        }

        def build() -> str:
            return ". ".join(
                f"{labels[key]}: "
                + (
                    cls._clip_list(values[key], caps[key])
                    if key in {"style", "excluded", "cues"}
                    else cls._clip_balanced(values[key], caps[key])
                )
                for key in order
                if key in caps
            ) + "."

        prompt = build()
        while cls.utf16_length(prompt) > limit:
            overage = cls.utf16_length(prompt) - limit
            changed = False
            for key in cls._reduction_order:
                if key not in caps:
                    continue
                floor = min(
                    caps[key],
                    cls._minimum_caps[key],
                    cls.utf16_length(values[key]),
                )
                available = caps[key] - floor
                if available <= 0:
                    continue
                caps[key] -= min(available, overage + 4)
                changed = True
                break
            if not changed:
                raise ValidationError("Storyboard prompt cannot fit the provider limit")
            prompt = build()
        return prompt

    def assemble(
        self,
        frame: dict[str, Any],
        *,
        max_utf16_units: int | None = None,
    ) -> dict[str, Any]:
        required = {
            "frame_id",
            "shot_id",
            "composition",
            "visible_action",
            "camera",
            "character_continuity",
            "location",
            "lighting",
            "emotion",
            "style",
            "forbidden_style",
        }
        missing = required.difference(frame)
        if missing:
            raise ValidationError(f"Storyboard frame is incomplete: {sorted(missing)}")
        camera = frame["camera"]
        identity = ", ".join(
            f"{character_id}={key}"
            for character_id, key in sorted(frame["character_continuity"].items())
        )
        component_values = {
            "composition": str(frame["composition"]),
            "visible_action": str(frame["visible_action"]),
            "identity": identity,
            "location": str(frame["location"]),
            "camera": (
                f"{camera['framing']}, {camera['lens']}, "
                f"{camera['movement']}, {camera['angle']}"
            ),
            "lighting": str(frame["lighting"]),
            "emotion": str(frame["emotion"]),
            "style": ", ".join(frame["style"]),
            "excluded": ", ".join(frame["forbidden_style"]),
        }
        component_values["cues"] = self._exact_cues(
            component_values["composition"], component_values["visible_action"]
        )
        components = [
            f"Composition: {frame['composition']}",
            f"Visible action: {frame['visible_action']}",
            f"Character identity: {identity}",
            f"Location: {frame['location']}",
            f"Camera: {component_values['camera']}",
            f"Lighting: {frame['lighting']}",
            f"Emotion: {frame['emotion']}",
            "Style: " + ", ".join(frame["style"]),
            "Excluded visual styles: " + ", ".join(frame["forbidden_style"]),
        ]
        source_prompt = ". ".join(
            component.rstrip(".") for component in components
        ) + "."
        prompt = source_prompt
        compacted = False
        if max_utf16_units is not None:
            if max_utf16_units < 1:
                raise ValidationError("Provider prompt limit must be positive")
            if self.utf16_length(source_prompt) > max_utf16_units:
                prompt = self._bounded_prompt(
                    values=component_values,
                    limit=max_utf16_units,
                )
                compacted = True
        provenance = content_hash(frame)
        result = {
            "shot_id": frame["shot_id"],
            "prompt": prompt,
            "negative_prompt": ", ".join(frame["forbidden_style"]),
            "storyboard_hash": provenance,
            "source_contract": "storyboard_only",
            "deterministic": True,
        }
        if max_utf16_units is not None:
            result["transport"] = {
                "contract_version": "utf16-bounded-prompt/1",
                "max_utf16_units": max_utf16_units,
                "source_prompt_hash": content_hash(source_prompt),
                "compacted": compacted,
            }
        result["prompt_hash"] = content_hash(result)
        return result

    @staticmethod
    def verify(prompt: dict[str, Any], frame: dict[str, Any]) -> None:
        if prompt.get("source_contract") != "storyboard_only":
            raise ValidationError("Prompt provenance is not storyboard-only")
        if prompt.get("storyboard_hash") != content_hash(frame):
            raise ValidationError("Prompt provenance does not match storyboard")
        comparable = dict(prompt)
        claimed = comparable.pop("prompt_hash", None)
        if claimed != content_hash(comparable):
            raise ValidationError("Prompt hash mismatch")
