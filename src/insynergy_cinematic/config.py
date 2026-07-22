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
    "platform_version": "3.4.0",
    "profile": "preview",
    "deterministic": True,
    "render": {
        "provider": "local",
        "runway_scope": "hybrid",
        "max_runway_credits": 480,
        "max_parallel_shots": 4,
        "max_attempts": 3,
        "quality_threshold": 0.9,
        "budget_usd": 20.0,
        "estimate_before_submission": True,
        "preview": {"width": 1280, "height": 720, "frame_rate": 24, "max_duration_seconds": 5},
        "final": {"width": 1920, "height": 1080, "frame_rate": 24, "max_duration_seconds": 10},
    },
    "story": {
        "concept_ratio_max": 0.2,
        "supporting_role_max": 3,
        "canonical_duration_seconds": 28,
        "draft_duration_seconds": 12,
        "genre": "cinematic_thought_leadership",
        "audience": "executive",
        "author_style": [
            "human decision first",
            "institutional accuracy",
            "restrained executive tone",
        ],
        "persona_mode": "off",
        "thresholds": {
            "dramatic_score": 0.85,
            "conflict_score": 0.80,
            "stakes_score": 0.85,
            "emotional_progression": 0.85,
        },
    },
    "screenplay": {
        "generation": {
            "scene_count_min": 8,
            "scene_count_max": 12,
            "scene_duration_min": 4,
            "scene_duration_target": 7,
            "scene_duration_max": 10,
        },
        "dialogue": {
            "words_per_line": 15,
            "lines_per_turn": 2,
            "exposition_allowed": False,
            "silence_allowed": True,
        },
        "continuity": {
            "all_dimensions_checked": True,
            "violation_fails_validation": True,
        },
        "export": {"fountain": True, "json": True, "custom_syntax": False},
    },
    "quality": {"fail_closed": True},
    "performance": {
        "max_in_flight_tasks": 4,
        "provider_parallel_limits": {"local": 4, "runway": 4},
        "checkpoint_enabled": True,
        "event_hash_chain_enabled": True,
    },
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
    "pre_render_preview": {
        "mode": "off",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "medium",
        "image_size": "1536x1024",
        "image_quality": "medium",
        "image_output_format": "png",
        "timeout_seconds": 300,
        "max_output_tokens": 24000,
        "max_images": 12,
        "preflight_estimated_cost_usd": 5.0,
        "max_cost_usd": 10.0,
        "prompt_version": "storyboard-preview-v1",
        "allowed_models": ["gpt-5.6-sol"],
    },
    "persona_council": {
        "model": "gpt-5.6-sol",
        "reasoning_effort": "medium",
        "trace_mode": "disabled",
        "timeout_seconds": 180,
        "max_input_bytes": 524288,
        "max_output_tokens": 20000,
        "preflight_estimated_cost_usd": 1.0,
        "max_cost_usd": 5.0,
        "manager_agent_version": "persona-manager-v1",
        "prompt_version": "persona-council-v1",
        "policy_version": "persona-policy/1",
        "allowed_models": ["gpt-5.6-sol"],
    },
}


@dataclass(frozen=True)
class RenderProfileConfig:
    width: int
    height: int
    frame_rate: int
    max_duration_seconds: int


@dataclass(frozen=True)
class StorySettings:
    canonical_duration_seconds: int
    draft_duration_seconds: int
    genre: str
    audience: str
    author_style: tuple[str, ...]
    persona_mode: str
    dramatic_score_min: float
    conflict_score_min: float
    stakes_score_min: float
    emotional_progression_min: float


@dataclass(frozen=True)
class ScreenplaySettings:
    scene_count_min: int
    scene_count_max: int
    scene_duration_min: int
    scene_duration_target: int
    scene_duration_max: int
    words_per_line: int
    lines_per_turn: int
    exposition_allowed: bool
    silence_allowed: bool
    all_dimensions_checked: bool
    violation_fails_validation: bool
    fountain: bool
    json: bool
    custom_syntax: bool


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
    story: StorySettings
    screenplay: ScreenplaySettings
    fail_closed: bool
    max_in_flight_tasks: int
    provider_parallel_limits: dict[str, int]
    checkpoint_enabled: bool
    event_hash_chain_enabled: bool
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
    pre_render_preview_mode: str
    preview_model: str
    preview_reasoning_effort: str
    preview_image_size: str
    preview_image_quality: str
    preview_image_output_format: str
    preview_timeout_seconds: int
    preview_max_output_tokens: int
    preview_max_images: int
    preview_preflight_estimated_cost_usd: float
    preview_max_cost_usd: float
    preview_prompt_version: str
    preview_allowed_models: tuple[str, ...]
    persona_model: str
    persona_reasoning_effort: str
    persona_trace_mode: str
    persona_timeout_seconds: int
    persona_max_input_bytes: int
    persona_max_output_tokens: int
    persona_preflight_estimated_cost_usd: float
    persona_max_cost_usd: float
    persona_manager_agent_version: str
    persona_prompt_version: str
    persona_policy_version: str
    persona_allowed_models: tuple[str, ...]
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
    pre_render_preview_mode: str | None = None,
    persona_mode: str | None = None,
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
    screenplay = values.get("screenplay", {})
    quality = values.get("quality", {})
    performance = values.get("performance", {})
    agent_review = values.get("agent_review", {})
    pre_render_preview = values.get("pre_render_preview", {})
    persona_council = values.get("persona_council", {})
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
    selected_preview_mode = pre_render_preview_mode or environment.get(
        "INSYNERGY_PRE_RENDER_PREVIEW_MODE",
        pre_render_preview.get("mode", "off"),
    )
    selected_persona_mode = persona_mode or environment.get(
        "INSYNERGY_PERSONA_MODE", story.get("persona_mode", "off")
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
    if selected_preview_mode not in {"off", "storyboard_animatic"}:
        raise ValidationError(
            f"Unsupported pre-render preview mode: {selected_preview_mode}"
        )
    if selected_persona_mode not in {"off", "council"}:
        raise ValidationError(
            f"Unsupported Persona Council mode: {selected_persona_mode}"
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

    generation = screenplay.get("generation", {})
    dialogue = screenplay.get("dialogue", {})
    continuity = screenplay.get("continuity", {})
    export = screenplay.get("export", {})
    screenplay_settings = ScreenplaySettings(
        scene_count_min=int(generation.get("scene_count_min", 8)),
        scene_count_max=int(generation.get("scene_count_max", 12)),
        scene_duration_min=int(generation.get("scene_duration_min", 4)),
        scene_duration_target=int(generation.get("scene_duration_target", 7)),
        scene_duration_max=int(generation.get("scene_duration_max", 10)),
        words_per_line=int(dialogue.get("words_per_line", 15)),
        lines_per_turn=int(dialogue.get("lines_per_turn", 2)),
        exposition_allowed=bool(dialogue.get("exposition_allowed", False)),
        silence_allowed=bool(dialogue.get("silence_allowed", True)),
        all_dimensions_checked=bool(
            continuity.get("all_dimensions_checked", True)
        ),
        violation_fails_validation=bool(
            continuity.get("violation_fails_validation", True)
        ),
        fountain=bool(export.get("fountain", True)),
        json=bool(export.get("json", True)),
        custom_syntax=bool(export.get("custom_syntax", False)),
    )
    if not (
        8
        <= screenplay_settings.scene_count_min
        <= screenplay_settings.scene_count_max
        <= 12
    ):
        raise ValidationError("screenplay scene count must remain within 8-12")
    if not (
        4
        <= screenplay_settings.scene_duration_min
        <= screenplay_settings.scene_duration_target
        <= screenplay_settings.scene_duration_max
        == 10
    ):
        raise ValidationError("screenplay duration bounds are invalid")
    if (
        screenplay_settings.words_per_line != 15
        or screenplay_settings.lines_per_turn != 2
        or screenplay_settings.exposition_allowed
        or not screenplay_settings.silence_allowed
        or not screenplay_settings.all_dimensions_checked
        or not screenplay_settings.violation_fails_validation
        or not screenplay_settings.fountain
        or not screenplay_settings.json
        or screenplay_settings.custom_syntax
    ):
        raise ValidationError("screenplay configuration weakens a normative invariant")
    raw_author_style = story.get(
        "author_style",
        [
            "human decision first",
            "institutional accuracy",
            "restrained executive tone",
        ],
    )
    if not isinstance(raw_author_style, list):
        raise ValidationError("story.author_style must be a list")
    story_thresholds = story.get("thresholds", {})
    story_settings = StorySettings(
        canonical_duration_seconds=int(story.get("canonical_duration_seconds", 28)),
        draft_duration_seconds=int(story.get("draft_duration_seconds", 12)),
        genre=str(story.get("genre", "cinematic_thought_leadership")),
        audience=str(story.get("audience", "executive")),
        author_style=tuple(str(value) for value in raw_author_style),
        persona_mode=selected_persona_mode,
        dramatic_score_min=float(story_thresholds.get("dramatic_score", 0.85)),
        conflict_score_min=float(story_thresholds.get("conflict_score", 0.80)),
        stakes_score_min=float(story_thresholds.get("stakes_score", 0.85)),
        emotional_progression_min=float(
            story_thresholds.get("emotional_progression", 0.85)
        ),
    )
    if not 15 <= story_settings.canonical_duration_seconds <= 30:
        raise ValidationError("story canonical duration must be within 15-30 seconds")
    if not 5 <= story_settings.draft_duration_seconds <= 15:
        raise ValidationError("story draft duration must be within 5-15 seconds")
    if (
        not story_settings.genre
        or not story_settings.audience
        or not story_settings.author_style
        or any(not value.strip() for value in story_settings.author_style)
    ):
        raise ValidationError("story profile and author style must be non-empty")
    if story_settings.persona_mode not in {"off", "council"}:
        raise ValidationError("story.persona_mode must be off or council")
    if (
        story_settings.dramatic_score_min != 0.85
        or story_settings.conflict_score_min != 0.80
        or story_settings.stakes_score_min != 0.85
        or story_settings.emotional_progression_min != 0.85
    ):
        raise ValidationError("story quality thresholds are normative")

    threshold = float(render.get("quality_threshold", 0.9))
    if not 0 <= threshold <= 1:
        raise ValidationError("render.quality_threshold must be between 0 and 1")
    parallelism = int(render.get("max_parallel_shots", 4))
    if parallelism < 1:
        raise ValidationError("render.max_parallel_shots must be positive")
    max_in_flight = int(performance.get("max_in_flight_tasks", parallelism))
    if max_in_flight < 1:
        raise ValidationError("performance.max_in_flight_tasks must be positive")
    raw_provider_limits = performance.get(
        "provider_parallel_limits", {"local": parallelism, "runway": parallelism}
    )
    if not isinstance(raw_provider_limits, dict):
        raise ValidationError("performance.provider_parallel_limits must be an object")
    provider_limits = {
        str(key): int(value) for key, value in raw_provider_limits.items()
    }
    if set(provider_limits) != {"local", "runway"} or any(
        value < 1 for value in provider_limits.values()
    ):
        raise ValidationError(
            "performance.provider_parallel_limits must define positive local and runway limits"
        )
    max_runway_credits = int(render.get("max_runway_credits", 480))
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
    preview_reasoning = environment.get(
        "OPENAI_PREVIEW_REASONING_EFFORT",
        str(pre_render_preview.get("reasoning_effort", "medium")),
    )
    if preview_reasoning not in {"none", "low", "medium", "high", "xhigh", "max"}:
        raise ValidationError("OPENAI_PREVIEW_REASONING_EFFORT is not allow-listed")
    preview_model = environment.get(
        "OPENAI_MODEL_PREVIEW",
        str(pre_render_preview.get("model", "gpt-5.6-sol")),
    )
    raw_preview_models = pre_render_preview.get("allowed_models", ["gpt-5.6-sol"])
    if not isinstance(raw_preview_models, list):
        raise ValidationError("pre_render_preview.allowed_models must be a list")
    preview_allowed_models = tuple(str(value) for value in raw_preview_models)
    if not preview_model or preview_model not in preview_allowed_models:
        raise ValidationError("OPENAI_MODEL_PREVIEW is not allow-listed")
    preview_image_size = str(pre_render_preview.get("image_size", "1536x1024"))
    if preview_image_size not in {"1024x1024", "1536x1024", "1024x1536"}:
        raise ValidationError("pre_render_preview.image_size is not supported")
    preview_image_quality = str(pre_render_preview.get("image_quality", "medium"))
    if preview_image_quality not in {"low", "medium", "high"}:
        raise ValidationError("pre_render_preview.image_quality is not supported")
    preview_output_format = str(
        pre_render_preview.get("image_output_format", "png")
    )
    if preview_output_format not in {"png", "jpeg", "webp"}:
        raise ValidationError("pre_render_preview.image_output_format is not supported")
    preview_timeout = int(pre_render_preview.get("timeout_seconds", 300))
    preview_output_tokens = int(pre_render_preview.get("max_output_tokens", 24000))
    preview_max_images = int(pre_render_preview.get("max_images", 12))
    preview_preflight_cost = float(
        pre_render_preview.get("preflight_estimated_cost_usd", 5.0)
    )
    preview_max_cost = float(pre_render_preview.get("max_cost_usd", 10.0))
    preview_prompt_version = str(
        pre_render_preview.get("prompt_version", "storyboard-preview-v1")
    )
    if (
        min(preview_timeout, preview_output_tokens, preview_max_images) < 1
        or preview_preflight_cost <= 0
        or preview_max_cost <= 0
        or preview_preflight_cost > preview_max_cost
        or not preview_prompt_version
    ):
        raise ValidationError("Pre-render preview limits and prompt version are required")
    persona_reasoning = environment.get(
        "OPENAI_PERSONA_REASONING_EFFORT",
        str(persona_council.get("reasoning_effort", "medium")),
    )
    if persona_reasoning not in {"none", "low", "medium", "high", "xhigh", "max"}:
        raise ValidationError("OPENAI_PERSONA_REASONING_EFFORT is not allow-listed")
    persona_trace = environment.get(
        "OPENAI_PERSONA_TRACE_MODE",
        str(persona_council.get("trace_mode", "disabled")),
    )
    if persona_trace not in {"disabled", "metadata"}:
        raise ValidationError("OPENAI_PERSONA_TRACE_MODE must be disabled or metadata")
    persona_timeout = int(
        environment.get(
            "PERSONA_COUNCIL_TIMEOUT_SECONDS",
            persona_council.get("timeout_seconds", 180),
        )
    )
    persona_input_limit = int(
        environment.get(
            "PERSONA_COUNCIL_MAX_INPUT_BYTES",
            persona_council.get("max_input_bytes", 524288),
        )
    )
    persona_output_limit = int(
        environment.get(
            "PERSONA_COUNCIL_MAX_OUTPUT_TOKENS",
            persona_council.get("max_output_tokens", 20000),
        )
    )
    persona_max_cost = float(
        environment.get(
            "PERSONA_COUNCIL_MAX_COST_USD",
            persona_council.get("max_cost_usd", 5.0),
        )
    )
    persona_preflight_cost = float(
        environment.get(
            "PERSONA_COUNCIL_PREFLIGHT_ESTIMATED_COST_USD",
            persona_council.get("preflight_estimated_cost_usd", 1.0),
        )
    )
    if (
        min(persona_timeout, persona_input_limit, persona_output_limit) < 1
        or persona_max_cost <= 0
        or persona_preflight_cost <= 0
    ):
        raise ValidationError("Persona Council limits and budget must be positive")
    persona_model = environment.get(
        "OPENAI_MODEL_PERSONA",
        str(persona_council.get("model", "gpt-5.6-sol")),
    )
    raw_persona_models = persona_council.get("allowed_models", ["gpt-5.6-sol"])
    if not isinstance(raw_persona_models, list):
        raise ValidationError("persona_council.allowed_models must be a list")
    persona_allowed_models = tuple(str(value) for value in raw_persona_models)
    if not persona_model or persona_model not in persona_allowed_models:
        raise ValidationError("OPENAI_MODEL_PERSONA is not allow-listed")
    persona_manager_version = str(
        persona_council.get("manager_agent_version", "persona-manager-v1")
    )
    persona_prompt_version = str(
        persona_council.get("prompt_version", "persona-council-v1")
    )
    persona_policy_version = str(
        persona_council.get("policy_version", "persona-policy/1")
    )
    if not all((persona_manager_version, persona_prompt_version, persona_policy_version)):
        raise ValidationError("Persona Council version identifiers are required")
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
        story=story_settings,
        screenplay=screenplay_settings,
        fail_closed=bool(quality.get("fail_closed", True)),
        max_in_flight_tasks=max_in_flight,
        provider_parallel_limits=provider_limits,
        checkpoint_enabled=bool(performance.get("checkpoint_enabled", True)),
        event_hash_chain_enabled=bool(
            performance.get("event_hash_chain_enabled", True)
        ),
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
        pre_render_preview_mode=selected_preview_mode,
        preview_model=preview_model,
        preview_reasoning_effort=preview_reasoning,
        preview_image_size=preview_image_size,
        preview_image_quality=preview_image_quality,
        preview_image_output_format=preview_output_format,
        preview_timeout_seconds=preview_timeout,
        preview_max_output_tokens=preview_output_tokens,
        preview_max_images=preview_max_images,
        preview_preflight_estimated_cost_usd=preview_preflight_cost,
        preview_max_cost_usd=preview_max_cost,
        preview_prompt_version=preview_prompt_version,
        preview_allowed_models=preview_allowed_models,
        persona_model=persona_model,
        persona_reasoning_effort=persona_reasoning,
        persona_trace_mode=persona_trace,
        persona_timeout_seconds=persona_timeout,
        persona_max_input_bytes=persona_input_limit,
        persona_max_output_tokens=persona_output_limit,
        persona_preflight_estimated_cost_usd=persona_preflight_cost,
        persona_max_cost_usd=persona_max_cost,
        persona_manager_agent_version=persona_manager_version,
        persona_prompt_version=persona_prompt_version,
        persona_policy_version=persona_policy_version,
        persona_allowed_models=persona_allowed_models,
        workspace=workspace.resolve(),
        runway_base_url=environment.get("RUNWAY_BASE_URL"),
        runway_api_key=environment.get("RUNWAY_API_KEY"),
        runway_model=environment.get("RUNWAY_MODEL_GEN45"),
        api_token=environment.get("INSYNERGY_API_TOKEN"),
        openai_api_key=environment.get("OPENAI_API_KEY"),
        openai_tts_api_key=environment.get("OPENAI_TTS_API_KEY"),
    )
