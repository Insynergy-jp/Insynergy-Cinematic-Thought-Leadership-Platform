"""Typed configuration loading; runtime components never read the environment."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ValidationError


DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": "2.0",
    "profile": "preview",
    "deterministic": True,
    "render": {
        "provider": "local",
        "max_parallel_shots": 4,
        "max_attempts": 3,
        "quality_threshold": 0.9,
        "budget_usd": 20.0,
        "estimate_before_submission": True,
        "preview": {"width": 1280, "height": 720, "frame_rate": 24, "max_duration_seconds": 5},
        "final": {"width": 1920, "height": 1080, "frame_rate": 24, "max_duration_seconds": 10},
    },
    "story": {"concept_ratio_max": 0.2, "supporting_role_max": 3},
    "quality": {"fail_closed": True},
}


@dataclass(frozen=True)
class RenderProfileConfig:
    width: int
    height: int
    frame_rate: int
    max_duration_seconds: int


@dataclass(frozen=True)
class PlatformConfig:
    profile: str
    deterministic: bool
    provider: str
    max_parallel_shots: int
    max_attempts: int
    quality_threshold: float
    budget_usd: float
    estimate_before_submission: bool
    preview: RenderProfileConfig
    final: RenderProfileConfig
    concept_ratio_max: float
    supporting_role_max: int
    fail_closed: bool
    workspace: Path
    runway_base_url: str | None = None
    runway_api_key: str | None = None
    runway_model: str | None = None
    api_token: str | None = None

    def render_profile(self, profile: str | None = None) -> RenderProfileConfig:
        selected = profile or self.profile
        return self.final if selected == "final" else self.preview


def _default_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "default.json"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Unable to load configuration: {path}") from exc
    if not isinstance(value, dict):
        raise ValidationError("Configuration root must be an object")
    return value


def load_config(
    *,
    workspace: Path,
    config_path: Path | None = None,
    profile: str | None = None,
    provider: str | None = None,
    environ: dict[str, str] | None = None,
) -> PlatformConfig:
    """Resolve raw configuration once and return an immutable snapshot."""
    if config_path is not None:
        values = _load_json(config_path)
    else:
        default_path = _default_config_path()
        values = _load_json(default_path) if default_path.is_file() else DEFAULT_CONFIG
    environment = dict(os.environ if environ is None else environ)
    render = values.get("render", {})
    story = values.get("story", {})
    quality = values.get("quality", {})
    selected_profile = profile or values.get("profile", "preview")
    selected_provider = provider or environment.get(
        "INSYNERGY_RENDER_PROVIDER", render.get("provider", "local")
    )
    if selected_profile not in {"draft", "preview", "final"}:
        raise ValidationError(f"Unsupported build profile: {selected_profile}")
    if selected_provider not in {"local", "runway"}:
        raise ValidationError(f"Unsupported render provider: {selected_provider}")

    def profile_config(name: str) -> RenderProfileConfig:
        raw = render.get(name, {})
        result = RenderProfileConfig(
            width=int(raw.get("width", 1280)),
            height=int(raw.get("height", 720)),
            frame_rate=int(raw.get("frame_rate", 24)),
            max_duration_seconds=int(raw.get("max_duration_seconds", 5)),
        )
        if min(result.width, result.height, result.frame_rate, result.max_duration_seconds) < 1:
            raise ValidationError(f"Invalid {name} render profile")
        return result

    threshold = float(render.get("quality_threshold", 0.9))
    if not 0 <= threshold <= 1:
        raise ValidationError("render.quality_threshold must be between 0 and 1")
    parallelism = int(render.get("max_parallel_shots", 4))
    if parallelism < 1:
        raise ValidationError("render.max_parallel_shots must be positive")
    return PlatformConfig(
        profile=selected_profile,
        deterministic=bool(values.get("deterministic", True)),
        provider=selected_provider,
        max_parallel_shots=parallelism,
        max_attempts=int(render.get("max_attempts", 3)),
        quality_threshold=threshold,
        budget_usd=float(render.get("budget_usd", 20.0)),
        estimate_before_submission=bool(render.get("estimate_before_submission", True)),
        preview=profile_config("preview"),
        final=profile_config("final"),
        concept_ratio_max=float(story.get("concept_ratio_max", 0.2)),
        supporting_role_max=int(story.get("supporting_role_max", 3)),
        fail_closed=bool(quality.get("fail_closed", True)),
        workspace=workspace.resolve(),
        runway_base_url=environment.get("RUNWAY_BASE_URL"),
        runway_api_key=environment.get("RUNWAY_API_KEY"),
        runway_model=environment.get("RUNWAY_MODEL_GEN45"),
        api_token=environment.get("INSYNERGY_API_TOKEN"),
    )
