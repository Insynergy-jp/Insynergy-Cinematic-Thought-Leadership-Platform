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
    "platform_version": "3.2.0",
    "profile": "preview",
    "deterministic": True,
    "render": {
        "provider": "local",
        "runway_scope": "hybrid",
        "max_runway_credits": 360,
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
    "narration": {
        "provider": "offline",
        "openai_model": "gpt-4o-mini-tts",
        "openai_voice": "marin",
        "openai_instructions": (
            "Speak in a calm, authoritative, natural executive documentary style. "
            "Use measured pacing, precise diction, restrained emotion, and brief pauses."
        ),
    },
    "youtube": {
        "video_bitrate": "8M",
        "audio_bitrate": "384k",
        "audio_sample_rate": 48000,
        "integrated_loudness_lufs": -14.0,
        "true_peak_db": -1.0,
    },
    "agent_review": {
        "mode": "off",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "medium",
        "trace_mode": "disabled",
        "timeout_seconds": 120,
        "max_input_bytes": 524288,
        "max_output_tokens": 16000,
        "agent_version": "3.0.2",
        "prompt_version": "agent-review-v2",
        "allowed_models": ["gpt-5.6-sol"],
        "policy_version": "agent-review-policy/1",
    },
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
    runway_scope: str
    max_runway_credits: int
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
    narration_provider: str
    narration_openai_model: str
    narration_openai_voice: str
    narration_openai_instructions: str
    youtube_video_bitrate: str
    youtube_audio_bitrate: str
    youtube_audio_sample_rate: int
    youtube_integrated_loudness_lufs: float
    youtube_true_peak_db: float
    agent_review_mode: str
    agent_review_model: str
    agent_review_reasoning_effort: str
    agent_review_trace_mode: str
    agent_review_timeout_seconds: int
    agent_review_max_input_bytes: int
    agent_review_max_output_tokens: int
    agent_review_agent_version: str
    agent_review_prompt_version: str
    agent_review_allowed_models: tuple[str, ...]
    agent_review_policy_version: str
    workspace: Path
    runway_base_url: str | None = None
    runway_api_key: str | None = None
    runway_model: str | None = None
    api_token: str | None = None
    openai_api_key: str | None = None
    openai_tts_api_key: str | None = None

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
    runway_scope: str | None = None,
    narration_provider: str | None = None,
    agent_review_mode: str | None = None,
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
    agent_review = values.get("agent_review", {})
    narration = values.get("narration", {})
    youtube = values.get("youtube", {})
    selected_profile = profile or values.get("profile", "preview")
    selected_provider = provider or environment.get(
        "INSYNERGY_RENDER_PROVIDER", render.get("provider", "local")
    )
    selected_runway_scope = runway_scope or environment.get(
        "INSYNERGY_RUNWAY_SCOPE", render.get("runway_scope", "hybrid")
    )
    selected_agent_review_mode = agent_review_mode or environment.get(
        "INSYNERGY_AGENT_REVIEW_MODE", agent_review.get("mode", "off")
    )
    selected_narration_provider = narration_provider or environment.get(
        "INSYNERGY_NARRATION_PROVIDER", narration.get("provider", "offline")
    )
    if selected_profile not in {"draft", "preview", "final"}:
        raise ValidationError(f"Unsupported build profile: {selected_profile}")
    if selected_provider not in {"local", "runway"}:
        raise ValidationError(f"Unsupported render provider: {selected_provider}")
    if selected_runway_scope not in {"hybrid", "all_shots"}:
        raise ValidationError(f"Unsupported Runway scope: {selected_runway_scope}")
    if selected_runway_scope == "all_shots" and selected_provider != "runway":
        raise ValidationError("all_shots Runway scope requires provider=runway")
    if selected_agent_review_mode not in {"off", "review"}:
        raise ValidationError(
            f"Unsupported Agent Review mode: {selected_agent_review_mode}"
        )
    if selected_narration_provider not in {"offline", "openai"}:
        raise ValidationError(
            f"Unsupported narration provider: {selected_narration_provider}"
        )
    narration_model = str(narration.get("openai_model", "gpt-4o-mini-tts"))
    if narration_model != "gpt-4o-mini-tts":
        raise ValidationError("narration.openai_model is not allow-listed")
    narration_voice = str(narration.get("openai_voice", "marin"))
    if narration_voice not in {
        "alloy", "ash", "ballad", "coral", "echo", "fable", "nova",
        "onyx", "sage", "shimmer", "verse", "marin", "cedar",
    }:
        raise ValidationError("narration.openai_voice is not allow-listed")
    narration_instructions = str(narration.get("openai_instructions", "")).strip()
    if not narration_instructions or len(narration_instructions.encode("utf-8")) > 2048:
        raise ValidationError("narration.openai_instructions must be 1-2048 bytes")
    youtube_sample_rate = int(youtube.get("audio_sample_rate", 48000))
    if youtube_sample_rate != 48000:
        raise ValidationError("youtube.audio_sample_rate must be 48000")
    youtube_loudness = float(youtube.get("integrated_loudness_lufs", -14.0))
    youtube_true_peak = float(youtube.get("true_peak_db", -1.0))
    if not -24.0 <= youtube_loudness <= -12.0:
        raise ValidationError("youtube.integrated_loudness_lufs is out of range")
    if not -3.0 <= youtube_true_peak <= -0.5:
        raise ValidationError("youtube.true_peak_db is out of range")

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
    max_runway_credits = int(render.get("max_runway_credits", 360))
    if max_runway_credits < 1:
        raise ValidationError("render.max_runway_credits must be positive")
    reasoning_effort = environment.get(
        "OPENAI_REASONING_EFFORT",
        str(agent_review.get("reasoning_effort", "medium")),
    )
    if reasoning_effort not in {"none", "low", "medium", "high", "xhigh", "max"}:
        raise ValidationError("OPENAI_REASONING_EFFORT is not allow-listed")
    trace_mode = environment.get(
        "OPENAI_TRACE_MODE", str(agent_review.get("trace_mode", "disabled"))
    )
    if trace_mode not in {"disabled", "metadata"}:
        raise ValidationError("OPENAI_TRACE_MODE must be disabled or metadata")
    review_timeout = int(
        environment.get(
            "AGENT_REVIEW_TIMEOUT_SECONDS",
            agent_review.get("timeout_seconds", 120),
        )
    )
    review_input_limit = int(
        environment.get(
            "AGENT_REVIEW_MAX_INPUT_BYTES",
            agent_review.get("max_input_bytes", 524288),
        )
    )
    review_output_limit = int(
        environment.get(
            "AGENT_REVIEW_MAX_OUTPUT_TOKENS",
            agent_review.get("max_output_tokens", 16000),
        )
    )
    if min(review_timeout, review_input_limit, review_output_limit) < 1:
        raise ValidationError("Agent Review limits must be positive")
    review_model = environment.get(
        "OPENAI_MODEL_REVIEW", str(agent_review.get("model", "gpt-5.6-sol"))
    )
    raw_allowed_models = agent_review.get("allowed_models", ["gpt-5.6-sol"])
    if not isinstance(raw_allowed_models, list):
        raise ValidationError("agent_review.allowed_models must be a list")
    allowed_models = tuple(str(value) for value in raw_allowed_models)
    if not review_model or not allowed_models or review_model not in allowed_models:
        raise ValidationError("OPENAI_MODEL_REVIEW is not allow-listed")
    agent_version = str(agent_review.get("agent_version", "3.0.2"))
    prompt_version = str(agent_review.get("prompt_version", "agent-review-v2"))
    policy_version = str(
        agent_review.get("policy_version", "agent-review-policy/1")
    )
    if not all((agent_version, prompt_version, policy_version)):
        raise ValidationError("Agent Review version identifiers are required")
    return PlatformConfig(
        profile=selected_profile,
        deterministic=bool(values.get("deterministic", True)),
        provider=selected_provider,
        runway_scope=selected_runway_scope,
        max_runway_credits=max_runway_credits,
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
        narration_provider=selected_narration_provider,
        narration_openai_model=narration_model,
        narration_openai_voice=narration_voice,
        narration_openai_instructions=narration_instructions,
        youtube_video_bitrate=str(youtube.get("video_bitrate", "8M")),
        youtube_audio_bitrate=str(youtube.get("audio_bitrate", "384k")),
        youtube_audio_sample_rate=youtube_sample_rate,
        youtube_integrated_loudness_lufs=youtube_loudness,
        youtube_true_peak_db=youtube_true_peak,
        agent_review_mode=selected_agent_review_mode,
        agent_review_model=review_model,
        agent_review_reasoning_effort=reasoning_effort,
        agent_review_trace_mode=trace_mode,
        agent_review_timeout_seconds=review_timeout,
        agent_review_max_input_bytes=review_input_limit,
        agent_review_max_output_tokens=review_output_limit,
        agent_review_agent_version=agent_version,
        agent_review_prompt_version=prompt_version,
        agent_review_allowed_models=allowed_models,
        agent_review_policy_version=policy_version,
        workspace=workspace.resolve(),
        runway_base_url=environment.get("RUNWAY_BASE_URL"),
        runway_api_key=environment.get("RUNWAY_API_KEY"),
        runway_model=environment.get("RUNWAY_MODEL_GEN45"),
        api_token=environment.get("INSYNERGY_API_TOKEN"),
        openai_api_key=environment.get("OPENAI_API_KEY"),
        openai_tts_api_key=environment.get("OPENAI_TTS_API_KEY"),
    )
