"""Storyboard-only deterministic prompt assembly."""

from __future__ import annotations

from typing import Any

from .errors import ValidationError
from .util import canonical_json, content_hash


class PromptAssembler:
    def assemble(self, frame: dict[str, Any]) -> dict[str, Any]:
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
        components = [
            f"Composition: {frame['composition']}",
            f"Visible action: {frame['visible_action']}",
            f"Character identity: {identity}",
            f"Location: {frame['location']}",
            f"Camera: {camera['framing']}, {camera['lens']}, {camera['movement']}, {camera['angle']}",
            f"Lighting: {frame['lighting']}",
            f"Emotion: {frame['emotion']}",
            "Style: " + ", ".join(frame["style"]),
            "Excluded visual styles: " + ", ".join(frame["forbidden_style"]),
        ]
        prompt = ". ".join(component.rstrip(".") for component in components) + "."
        provenance = content_hash(frame)
        result = {
            "shot_id": frame["shot_id"],
            "prompt": prompt,
            "negative_prompt": ", ".join(frame["forbidden_style"]),
            "storyboard_hash": provenance,
            "source_contract": "storyboard_only",
            "deterministic": True,
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
