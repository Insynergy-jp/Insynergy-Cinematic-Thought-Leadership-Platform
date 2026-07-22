"""OpenAI Responses API adapter for v3.4 storyboard previsualization."""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from ..errors import ValidationError
from ..previsualization import PreviewFrameResult


class OpenAIPreviewProvider:
    def __init__(self, config: Any) -> None:
        if not config.openai_api_key:
            raise ValidationError(
                "OPENAI_API_KEY is required for storyboard previsualization"
            )
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ValidationError(
                "Install the previsualization extra before using storyboard_animatic"
            ) from exc
        self.config = config
        self.client = OpenAI(
            api_key=config.openai_api_key,
            timeout=float(config.preview_timeout_seconds),
            max_retries=0,
        )

    @staticmethod
    def _usage(value: Any) -> dict[str, int]:
        if value is None:
            return {}
        return {
            key: int(getattr(value, key, 0) or 0)
            for key in ("input_tokens", "output_tokens", "total_tokens")
        }

    @staticmethod
    def _output_schema() -> dict[str, Any]:
        scene_properties = {
            "scene_id": {"type": "string"},
            "shot_id": {"type": "string"},
            "order": {"type": "integer", "minimum": 1},
            "duration_seconds": {"type": "number", "exclusiveMinimum": 0},
            "scene_composition": {"type": "string", "minLength": 1},
            "direction": {"type": "string", "minLength": 1},
            "camera_work": {"type": "string", "minLength": 1},
            "narration": {"type": "string", "minLength": 1},
            "tempo": {"type": "string", "minLength": 1},
            "image_prompt": {"type": "string", "minLength": 1},
            "video_prompt": {"type": "string", "minLength": 1},
            "risk_flags": {"type": "array", "items": {"type": "string"}},
        }
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["summary", "scenes"],
            "properties": {
                "summary": {"type": "string", "minLength": 1},
                "scenes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": list(scene_properties),
                        "properties": scene_properties,
                    },
                },
            },
        }

    def create_plan(self, request: dict[str, Any]) -> dict[str, Any]:
        immutable_input = {
            key: request[key]
            for key in ("build_id", "planning_hash", "screenplay", "shot_list", "storyboard")
        }
        response = self.client.responses.create(
            model=request["model"],
            reasoning={"effort": request["reasoning_effort"]},
            max_output_tokens=request["max_output_tokens"],
            input=[
                {
                    "role": "developer",
                    "content": (
                        "Create a production-review previsualization plan. Preserve every sealed "
                        "scene_id, shot_id, order, and duration exactly. Make scene composition, "
                        "direction, camera work, narration, tempo, image prompt, and future video "
                        "prompt explicit. Do not claim to generate MP4 and do not contact Runway."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(immutable_input, ensure_ascii=False, sort_keys=True),
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "previsualization_plan",
                    "strict": True,
                    "schema": self._output_schema(),
                }
            },
        )
        try:
            plan = json.loads(response.output_text)
        except (AttributeError, TypeError, json.JSONDecodeError) as exc:
            raise ValidationError("OpenAI returned an invalid previsualization plan") from exc
        usage = self._usage(response.usage)
        if not isinstance(response.id, str) or not response.id:
            raise ValidationError("OpenAI previsualization response ID is missing")
        if not isinstance(response.model, str) or not response.model:
            raise ValidationError("OpenAI previsualization resolved model is missing")
        return {
            "plan": plan,
            "response_id": response.id,
            "model_resolved": response.model,
            "usage": usage,
        }

    def generate_frame(self, request: dict[str, Any]) -> PreviewFrameResult:
        response = self.client.responses.create(
            model=request["model"],
            input=(
                "Generate one storyboard still only. Preserve institutional realism and human "
                "anatomy; no text, logos, watermarks, UI, or extra panels.\n\n"
                + request["prompt"]
            ),
            tools=[
                {
                    "type": "image_generation",
                    "size": request["size"],
                    "quality": request["quality"],
                    "output_format": request["output_format"],
                }
            ],
            tool_choice={"type": "image_generation"},
        )
        encoded = None
        resolved = response.model
        for item in response.output:
            if getattr(item, "type", "") == "image_generation_call":
                encoded = getattr(item, "result", None)
                resolved = getattr(item, "model", None) or resolved
                break
        if not encoded:
            raise ValidationError("OpenAI image generation returned no frame")
        usage = self._usage(response.usage)
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except (binascii.Error, TypeError, ValueError) as exc:
            raise ValidationError("OpenAI image generation returned invalid bytes") from exc
        if not isinstance(response.id, str) or not response.id:
            raise ValidationError("OpenAI image generation response ID is missing")
        return PreviewFrameResult(
            image_bytes=image_bytes,
            response_id=response.id,
            model_resolved=str(resolved),
            output_format=request["output_format"],
            usage=usage,
        )
