"""Zero-Runway storyboard previsualization, caching, and approval binding."""

from __future__ import annotations

import html
import json
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .errors import QualityGateError, ValidationError
from .util import (
    DETERMINISTIC_TIME,
    atomic_write_json,
    atomic_write_text,
    content_hash,
    file_hash,
    read_json,
    stable_id,
)


PREVIEW_ARTIFACT_TYPES = (
    "previsualization_plan",
    "image_prompt_set",
    "video_prompt_set",
    "storyboard_preview_manifest",
    "storyboard_preview_quality_report",
)


@dataclass(frozen=True)
class PreviewFrameResult:
    image_bytes: bytes
    response_id: str
    model_resolved: str
    output_format: str = "png"
    usage: dict[str, Any] | None = None


class PreviewPlanProvider(Protocol):
    def create_plan(self, request: dict[str, Any]) -> dict[str, Any]: ...


class PreviewImageProvider(Protocol):
    def generate_frame(self, request: dict[str, Any]) -> PreviewFrameResult: ...


class PreviewProvider(PreviewPlanProvider, PreviewImageProvider, Protocol):
    """Combined adapter accepted when one Responses client implements both boundaries."""


def _atomic_write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_provider_plan(
    plan: dict[str, Any], *, shots: list[dict[str, Any]]
) -> dict[str, Any]:
    if not isinstance(plan, dict) or set(plan) != {"summary", "scenes"}:
        raise ValidationError("GPT previsualization plan has an invalid root contract")
    scenes = plan.get("scenes")
    if not isinstance(scenes, list) or len(scenes) != len(shots):
        raise ValidationError("GPT previsualization plan must cover every planned shot")
    expected_fields = {
        "scene_id",
        "shot_id",
        "order",
        "duration_seconds",
        "scene_composition",
        "direction",
        "camera_work",
        "narration",
        "tempo",
        "image_prompt",
        "video_prompt",
        "risk_flags",
    }
    for shot, scene in zip(shots, scenes, strict=True):
        if not isinstance(scene, dict) or set(scene) != expected_fields:
            raise ValidationError("GPT previsualization scene contract is invalid")
        if (
            not isinstance(scene["scene_id"], str)
            or not isinstance(scene["shot_id"], str)
            or not isinstance(scene["order"], int)
            or isinstance(scene["order"], bool)
        ):
            raise ValidationError("GPT previsualization scene identity is invalid")
        if (
            scene["shot_id"] != shot["shot_id"]
            or scene["scene_id"] != shot["scene_id"]
            or scene["order"] != shot["order"]
        ):
            raise ValidationError("GPT previsualization plan changed shot identity or order")
        duration = scene["duration_seconds"]
        if (
            not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or not math.isfinite(float(duration))
            or float(duration) <= 0
            or abs(float(duration) - float(shot["duration_seconds"])) > 0.001
        ):
            raise ValidationError("GPT previsualization plan changed sealed shot timing")
        for field in (
            "scene_composition",
            "direction",
            "camera_work",
            "narration",
            "tempo",
            "image_prompt",
            "video_prompt",
        ):
            if (
                not isinstance(scene[field], str)
                or not scene[field].strip()
                or len(scene[field]) > 20_000
            ):
                raise ValidationError(f"GPT previsualization scene is missing {field}")
        if (
            not isinstance(scene["risk_flags"], list)
            or len(scene["risk_flags"]) > 32
            or not all(
                isinstance(value, str) and bool(value.strip()) and len(value) <= 20_000
                for value in scene["risk_flags"]
            )
        ):
            raise ValidationError("GPT previsualization risk_flags must be strings")
    if not isinstance(plan["summary"], str) or not plan["summary"].strip():
        raise ValidationError("GPT previsualization summary is required")
    return plan


class PreviewAnimaticComposer:
    def __init__(self, *, ffmpeg_binary: str = "ffmpeg", ffprobe_binary: str = "ffprobe"):
        self.ffmpeg_binary = ffmpeg_binary
        self.ffprobe_binary = ffprobe_binary

    def compose(
        self,
        *,
        directory: Path,
        frames: list[dict[str, Any]],
        width: int,
        height: int,
        frame_rate: int,
    ) -> dict[str, Any]:
        if not shutil.which(self.ffmpeg_binary) or not shutil.which(self.ffprobe_binary):
            raise ValidationError("FFmpeg and ffprobe are required for storyboard preview")
        if not frames:
            raise ValidationError("Storyboard preview requires at least one frame")
        version = subprocess.run(
            [self.ffmpeg_binary, "-version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if version.returncode or not version.stdout.strip():
            raise ValidationError("FFmpeg version provenance is unavailable")
        ffmpeg_version = version.stdout.splitlines()[0].strip()
        output = directory / "storyboard-preview.mp4"
        inputs: list[str] = []
        filters: list[str] = []
        labels: list[str] = []
        for index, frame in enumerate(frames):
            overlay_path = directory / f"frame-overlay-{index:03d}.txt"
            atomic_write_text(
                overlay_path,
                (
                    f"Scene {frame['scene_id']} | Shot {frame['shot_id']} | "
                    f"{float(frame['start_seconds']):.3f}s–"
                    f"{float(frame['end_seconds']):.3f}s"
                ),
            )
            inputs.extend(
                [
                    "-loop",
                    "1",
                    "-t",
                    f"{float(frame['duration_seconds']):.6f}",
                    "-i",
                    str(Path(frame["asset_path"])),
                ]
            )
            label = f"v{index}"
            labels.append(f"[{label}]")
            filters.append(
                f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},fps={frame_rate},"
                "drawbox=x=0:y=0:w=iw:h=54:color=black@0.65:t=fill,"
                "drawtext=text='STORYBOARD PREVIEW - NOT FINAL':"
                "fontcolor=white:fontsize=24:x=(w-text_w)/2:y=15,format=yuv420p,"
                "drawbox=x=0:y=h-54:w=iw:h=54:color=black@0.65:t=fill,"
                f"drawtext=textfile='{overlay_path.name}':"
                "fontcolor=white:fontsize=22:x=24:y=h-39,"
                f"setpts=PTS-STARTPTS[{label}]"
            )
        filters.append(
            "".join(labels) + f"concat=n={len(frames)}:v=1:a=0[outv]"
        )
        completed = subprocess.run(
            [
                self.ffmpeg_binary,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                *inputs,
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[outv]",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "20",
                "-movflags",
                "+faststart",
                "-an",
                output.name,
            ],
            cwd=directory,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode or not output.is_file():
            raise ValidationError(
                "FFmpeg storyboard animatic composition failed",
                details={"stderr": completed.stderr[-2000:]},
            )
        probe = subprocess.run(
            [
                self.ffprobe_binary,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,avg_frame_rate,codec_name:"
                "format=duration,format_name",
                "-of",
                "json",
                str(output),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode:
            raise ValidationError("Storyboard animatic is not decodable")
        metadata = json.loads(probe.stdout)
        stream = metadata["streams"][0]
        duration = float(metadata["format"]["duration"])
        expected_duration = sum(float(frame["duration_seconds"]) for frame in frames)
        if (
            int(stream["width"]) != width
            or int(stream["height"]) != height
            or stream.get("codec_name") != "h264"
            or "mp4" not in str(metadata["format"].get("format_name", ""))
            or abs(duration - expected_duration) > max(0.25, 1 / frame_rate)
        ):
            raise ValidationError(
                "Storyboard animatic failed technical validation",
                details={
                    "width": stream.get("width"),
                    "height": stream.get("height"),
                    "duration_seconds": duration,
                    "expected_duration_seconds": expected_duration,
                },
            )
        return {
            "path": str(output),
            "content_hash": file_hash(output),
            "width": width,
            "height": height,
            "frame_rate": frame_rate,
            "duration_seconds": duration,
            "expected_duration_seconds": expected_duration,
            "codec": "h264",
            "container": "mp4",
            "watermark_version": "storyboard-preview-watermark/1",
            "overlay_contract": "preview-shot-identity-timecode/1",
            "ffmpeg_version": ffmpeg_version,
            "ffmpeg_argument_contract": "preview-animatic/1",
        }


class PrevisualizationService:
    def __init__(
        self,
        *,
        config: Any,
        build_root: Path,
        cache_root: Path,
        provider: PreviewProvider,
        composer: PreviewAnimaticComposer | None = None,
    ) -> None:
        self.config = config
        self.build_root = build_root
        self.cache_root = cache_root
        self.provider = provider
        self.composer = composer or PreviewAnimaticComposer()

    def run(
        self,
        *,
        build_id: str,
        planning_hash: str,
        screenplay: dict[str, Any],
        shot_list: dict[str, Any],
        storyboard: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        shots = shot_list["shots"]
        input_bundle = {
            "build_id": build_id,
            "planning_hash": planning_hash,
            "screenplay": screenplay,
            "shot_list": shot_list,
            "storyboard": storyboard,
        }
        plan_key = content_hash(
            {
                "input_hash": content_hash(input_bundle),
                "model": self.config.preview_model,
                "reasoning_effort": self.config.preview_reasoning_effort,
                "prompt_version": self.config.preview_prompt_version,
            }
        )
        plan_cache = self.cache_root / "plans" / f"{plan_key.removeprefix('sha256:')}.json"
        plan_cache_hit = plan_cache.is_file()
        if plan_cache_hit:
            cached_plan = read_json(plan_cache)
            expected_cache_fields = {
                "plan_key",
                "plan",
                "model_resolved",
                "response_id",
                "usage",
                "content_hash",
            }
            if (
                set(cached_plan) != expected_cache_fields
                or cached_plan.get("plan_key") != plan_key
                or cached_plan.get("content_hash")
                != content_hash(
                    {
                        key: value
                        for key, value in cached_plan.items()
                        if key != "content_hash"
                    }
                )
            ):
                raise ValidationError("Storyboard preview plan cache is invalid")
            provider_plan = cached_plan["plan"]
            model_resolved = cached_plan["model_resolved"]
            plan_response_id = cached_plan["response_id"]
            plan_usage = cached_plan.get("usage", {})
        else:
            response = self.provider.create_plan(
                {
                    **input_bundle,
                    "model": self.config.preview_model,
                    "reasoning_effort": self.config.preview_reasoning_effort,
                    "max_output_tokens": self.config.preview_max_output_tokens,
                    "prompt_version": self.config.preview_prompt_version,
                }
            )
            provider_plan = response.get("plan")
            model_resolved = str(response.get("model_resolved", ""))
            plan_response_id = str(response.get("response_id", ""))
            plan_usage = response.get("usage") or {}
            if not model_resolved or not plan_response_id:
                raise ValidationError("GPT previsualization response provenance is incomplete")
            cache_record = {
                "plan_key": plan_key,
                "plan": provider_plan,
                "model_resolved": model_resolved,
                "response_id": plan_response_id,
                "usage": plan_usage,
            }
            cache_record["content_hash"] = content_hash(cache_record)
            atomic_write_json(plan_cache, cache_record)
        validate_provider_plan(provider_plan, shots=shots)
        plan = {
            "schema_version": "3.4.0",
            "contract_version": "previsualization-plan/1",
            "build_id": build_id,
            "planning_hash": planning_hash,
            "plan_key": plan_key,
            "status": "PREVIEW_READY",
            "summary": provider_plan["summary"],
            "scenes": provider_plan["scenes"],
            "review_dimensions": [
                "scene_composition",
                "direction",
                "camera_work",
                "narration",
                "tempo",
            ],
            "model_requested": self.config.preview_model,
            "model_resolved": model_resolved,
            "reasoning_effort": self.config.preview_reasoning_effort,
            "prompt_version": self.config.preview_prompt_version,
            "provider_response_id": plan_response_id,
            "usage": plan_usage,
            "cache_hit": plan_cache_hit,
            "generated_at": DETERMINISTIC_TIME,
        }
        image_prompts = {
            "schema_version": "3.4.0",
            "contract_version": "image-prompt-set/1",
            "build_id": build_id,
            "plan_key": plan_key,
            "image_size": self.config.preview_image_size,
            "image_quality": self.config.preview_image_quality,
            "output_format": self.config.preview_image_output_format,
            "prompts": [
                {
                    "prompt_id": stable_id(
                        "image-prompt",
                        {"shot_id": scene["shot_id"], "prompt": scene["image_prompt"]},
                    ),
                    "shot_id": scene["shot_id"],
                    "order": scene["order"],
                    "prompt": scene["image_prompt"],
                    "negative_constraints": [
                        "text", "logo", "watermark", "extra panel", "cartoon", "anime"
                    ],
                    "safety_constraints": ["institutional realism", "non-deceptive preview"],
                    "aspect_ratio": {
                        "1024x1024": "1:1",
                        "1536x1024": "3:2",
                        "1024x1536": "2:3",
                    }[self.config.preview_image_size],
                }
                for scene in provider_plan["scenes"]
            ],
        }
        video_prompts = {
            "schema_version": "3.4.0",
            "contract_version": "video-prompt-set/1",
            "build_id": build_id,
            "plan_key": plan_key,
            "provider_submission_allowed": False,
            "prompts": [
                {
                    "prompt_id": stable_id(
                        "video-prompt",
                        {"shot_id": scene["shot_id"], "prompt": scene["video_prompt"]},
                    ),
                    "shot_id": scene["shot_id"],
                    "order": scene["order"],
                    "prompt": scene["video_prompt"],
                    "execution_status": "SEALED_NOT_AUTHORIZED",
                }
                for scene in provider_plan["scenes"]
            ],
        }
        preview_directory = self.build_root / "previsualization"
        frame_directory = preview_directory / "frames"
        frames: list[dict[str, Any]] = []
        image_calls = 0
        cursor = 0.0
        usage_totals = {
            key: 0 if plan_cache_hit else int(plan_usage.get(key, 0) or 0)
            for key in ("input_tokens", "output_tokens", "total_tokens")
        }
        for scene, prompt in zip(
            provider_plan["scenes"], image_prompts["prompts"], strict=True
        ):
            frame_key = content_hash(
                {
                    "plan_key": plan_key,
                    "shot_id": scene["shot_id"],
                    "prompt": prompt["prompt"],
                    "image_size": self.config.preview_image_size,
                    "image_quality": self.config.preview_image_quality,
                    "output_format": self.config.preview_image_output_format,
                }
            )
            suffix = ".jpg" if self.config.preview_image_output_format == "jpeg" else f".{self.config.preview_image_output_format}"
            cache_base = self.cache_root / "frames" / frame_key.removeprefix("sha256:")
            cache_image = cache_base.with_suffix(suffix)
            cache_metadata = cache_base.with_suffix(".json")
            if cache_image.is_file() != cache_metadata.is_file():
                raise ValidationError("Storyboard preview frame cache is incomplete")
            cache_hit = cache_image.is_file()
            if cache_hit:
                image_bytes = cache_image.read_bytes()
                metadata = read_json(cache_metadata)
                expected_metadata_fields = {
                    "cache_key",
                    "asset_hash",
                    "response_id",
                    "model_resolved",
                    "output_format",
                    "usage",
                    "content_hash",
                }
                if (
                    set(metadata) != expected_metadata_fields
                    or metadata.get("cache_key") != frame_key
                    or metadata.get("asset_hash") != file_hash(cache_image)
                    or metadata.get("output_format")
                    != self.config.preview_image_output_format
                    or not isinstance(metadata.get("response_id"), str)
                    or not metadata["response_id"]
                    or not isinstance(metadata.get("model_resolved"), str)
                    or not metadata["model_resolved"]
                    or metadata.get("content_hash")
                    != content_hash(
                        {
                            key: value
                            for key, value in metadata.items()
                            if key != "content_hash"
                        }
                    )
                ):
                    raise ValidationError("Storyboard preview frame cache is invalid")
            else:
                frame_result = self.provider.generate_frame(
                    {
                        "build_id": build_id,
                        "shot_id": scene["shot_id"],
                        "prompt": prompt["prompt"],
                        "model": self.config.preview_model,
                        "size": self.config.preview_image_size,
                        "quality": self.config.preview_image_quality,
                        "output_format": self.config.preview_image_output_format,
                    }
                )
                image_calls += 1
                image_bytes = frame_result.image_bytes
                if (
                    not frame_result.response_id
                    or not frame_result.model_resolved
                    or frame_result.output_format
                    != self.config.preview_image_output_format
                ):
                    raise ValidationError(
                        "Image generation response provenance is incomplete"
                    )
                metadata = {
                    "cache_key": frame_key,
                    "asset_hash": "",
                    "response_id": frame_result.response_id,
                    "model_resolved": frame_result.model_resolved,
                    "output_format": frame_result.output_format,
                    "usage": frame_result.usage or {},
                }
                if not image_bytes:
                    raise ValidationError("Image generation returned an empty frame")
                _atomic_write_bytes(cache_image, image_bytes)
                metadata["asset_hash"] = file_hash(cache_image)
                metadata["content_hash"] = content_hash(metadata)
                atomic_write_json(cache_metadata, metadata)
            if not cache_hit:
                for key in usage_totals:
                    usage_totals[key] += int(
                        (metadata.get("usage") or {}).get(key, 0) or 0
                    )
            output_path = frame_directory / f"{int(scene['order']):03d}-preview-frame{suffix}"
            _atomic_write_bytes(output_path, image_bytes)
            end_seconds = cursor + float(scene["duration_seconds"])
            frames.append(
                {
                    "frame_id": f"preview-frame-{int(scene['order']):03d}",
                    "scene_id": scene["scene_id"],
                    "shot_id": scene["shot_id"],
                    "order": scene["order"],
                    "prompt_id": prompt["prompt_id"],
                    "asset_path": str(output_path),
                    "asset_hash": file_hash(output_path),
                    "duration_seconds": scene["duration_seconds"],
                    "start_seconds": cursor,
                    "end_seconds": end_seconds,
                    "transition_seconds": 0.0,
                    "narration": scene["narration"],
                    "tempo": scene["tempo"],
                    "cache_key": frame_key,
                    "cache_hit": cache_hit,
                    "provider_response_id": metadata["response_id"],
                    "model_resolved": metadata["model_resolved"],
                }
            )
            cursor = end_seconds
        profile = self.config.render_profile("preview")
        animatic = self.composer.compose(
            directory=preview_directory,
            frames=frames,
            width=profile.width,
            height=profile.height,
            frame_rate=profile.frame_rate,
        )
        captions_path = preview_directory / "storyboard-review.srt"
        atomic_write_text(captions_path, self._srt(provider_plan["scenes"]))
        review_path = preview_directory / "storyboard-review.html"
        atomic_write_text(
            review_path,
            self._review_html(build_id, animatic, provider_plan["scenes"], frames),
        )
        manifest = {
            "schema_version": "3.4.0",
            "contract_version": "storyboard-preview-manifest/1",
            "build_id": build_id,
            "plan_key": plan_key,
            "status": "PREVIEW_READY",
            "frames": frames,
            "animatic": animatic,
            "captions": {
                "path": str(captions_path),
                "content_hash": file_hash(captions_path),
            },
            "review_html": {
                "path": str(review_path),
                "content_hash": file_hash(review_path),
            },
            "provider_calls": {
                "gpt_plan": 0 if plan_cache_hit else 1,
                "gpt_image": image_calls,
                "runway": 0,
            },
            "usage_summary": {
                **usage_totals,
                "estimated_cost_usd": self.config.preview_preflight_estimated_cost_usd,
                "max_cost_usd": self.config.preview_max_cost_usd,
            },
            "timebase": f"1/{profile.frame_rate}",
            "non_publishable": True,
            "final_cache_eligible": False,
            "limitations": [
                "Still-frame animatic does not prove generated motion fidelity.",
                "It does not prove temporal consistency, lip sync, physics, or final photorealism.",
            ],
            "runway_contacted": False,
        }
        checks = {
            "all_shots_covered": len(frames) == len(shots),
            "shot_order_preserved": [frame["shot_id"] for frame in frames]
            == [shot["shot_id"] for shot in shots],
            "five_review_dimensions_present": all(
                all(scene[field].strip() for field in plan["review_dimensions"])
                for scene in provider_plan["scenes"]
            ),
            "image_prompts_complete": len(image_prompts["prompts"]) == len(shots),
            "video_prompts_complete": len(video_prompts["prompts"]) == len(shots),
            "frames_hash_verified": all(
                Path(frame["asset_path"]).is_file()
                and file_hash(Path(frame["asset_path"])) == frame["asset_hash"]
                for frame in frames
            ),
            "animatic_hash_verified": file_hash(Path(animatic["path"]))
            == animatic["content_hash"],
            "captions_hash_verified": file_hash(captions_path)
            == manifest["captions"]["content_hash"],
            "review_html_hash_verified": file_hash(review_path)
            == manifest["review_html"]["content_hash"],
            "runway_not_contacted": manifest["provider_calls"]["runway"] == 0
            and manifest["runway_contacted"] is False,
            "watermark_present": animatic["watermark_version"]
            == "storyboard-preview-watermark/1",
            "shot_identity_overlay_present": animatic["overlay_contract"]
            == "preview-shot-identity-timecode/1",
            "non_publishable": manifest["non_publishable"] is True
            and manifest["final_cache_eligible"] is False,
        }
        quality_report = {
            "schema_version": "3.4.0",
            "contract_version": "storyboard-preview-quality/1",
            "build_id": build_id,
            "gate_id": "storyboard_preview_quality_gate",
            "decision": "PASS" if all(checks.values()) else "FAIL",
            "passed": all(checks.values()),
            "fail_closed": True,
            "checks": checks,
            "deterministic_disposition": "PASS" if all(checks.values()) else "FAIL",
            "advisory": {"disposition": "NOT_RUN", "findings": []},
            "limitations": manifest["limitations"],
            "openai_usage": manifest["usage_summary"],
            "runway_usage": {
                "request_count": 0,
                "task_count": 0,
                "attempt_count": 0,
                "credit_count": 0,
            },
            "review_dimensions": plan["review_dimensions"],
            "plan_key": plan_key,
        }
        if not quality_report["passed"]:
            raise QualityGateError(
                "Storyboard Preview Quality Gate failed", details=quality_report
            )
        return {
            "previsualization_plan": plan,
            "image_prompt_set": image_prompts,
            "video_prompt_set": video_prompts,
            "storyboard_preview_manifest": manifest,
            "storyboard_preview_quality_report": quality_report,
        }

    @staticmethod
    def _srt(scenes: list[dict[str, Any]]) -> str:
        def timestamp(seconds: float) -> str:
            milliseconds = int(round(seconds * 1000))
            hours, remainder = divmod(milliseconds, 3_600_000)
            minutes, remainder = divmod(remainder, 60_000)
            whole_seconds, millis = divmod(remainder, 1000)
            return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{millis:03d}"

        cursor = 0.0
        blocks = []
        for index, scene in enumerate(scenes, start=1):
            end = cursor + float(scene["duration_seconds"])
            blocks.append(
                f"{index}\n{timestamp(cursor)} --> {timestamp(end)}\n{scene['narration']}\n"
            )
            cursor = end
        return "\n".join(blocks)

    @staticmethod
    def _review_html(
        build_id: str,
        animatic: dict[str, Any],
        scenes: list[dict[str, Any]],
        frames: list[dict[str, Any]],
    ) -> str:
        rows = []
        for scene, frame in zip(scenes, frames, strict=True):
            rows.append(
                "<tr>"
                f"<td>{scene['order']}</td><td>{html.escape(scene['shot_id'])}</td>"
                f"<td>{html.escape(scene['scene_composition'])}</td>"
                f"<td>{html.escape(scene['direction'])}</td>"
                f"<td>{html.escape(scene['camera_work'])}</td>"
                f"<td>{html.escape(scene['narration'])}</td>"
                f"<td>{html.escape(scene['tempo'])}</td>"
                f"<td>{html.escape(Path(frame['asset_path']).name)}</td>"
                "</tr>"
            )
        return """<!doctype html>
<html lang="ja"><meta charset="utf-8"><title>Storyboard Preview</title>
<style>body{font-family:system-ui;margin:2rem;background:#111;color:#eee}video{width:min(100%,960px)}table{border-collapse:collapse;width:100%;margin-top:2rem}th,td{border:1px solid #555;padding:.5rem;vertical-align:top}th{background:#222}</style>
<h1>Storyboard Preview — BUILD_ID</h1>
<video controls src="storyboard-preview.mp4"></video>
<table><thead><tr><th>#</th><th>Shot</th><th>シーン構成</th><th>演出</th><th>カメラワーク</th><th>ナレーション</th><th>テンポ</th><th>Frame</th></tr></thead>
<tbody>ROWS</tbody></table></html>
""".replace("BUILD_ID", html.escape(build_id)).replace("ROWS", "\n".join(rows))


def validate_preview_approval_binding(document: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "contract_version",
        "approval_id",
        "build_id",
        "decision",
        "approver",
        "workflow_initiator",
        "environment_reviewer",
        "prevent_self_review",
        "approved_at",
        "planning_hash",
        "artifact_hashes",
        "content_hash",
    }
    github_fields = {
        "environment_reviewer_id",
        "environment_review_hash",
        "environment_policy_hash",
    }
    if set(document).difference(required | github_fields | {"rationale"}):
        raise ValidationError("Preview Approval Binding has unexpected fields")
    if required.difference(document):
        raise ValidationError("Preview Approval Binding is incomplete")
    if document["schema_version"] != "3.4.0" or document["decision"] != "APPROVED":
        raise ValidationError("Preview Approval Binding version or decision is invalid")
    hashes = document.get("artifact_hashes")
    expected_names = set(PREVIEW_ARTIFACT_TYPES)
    if not isinstance(hashes, dict) or set(hashes) != expected_names:
        raise ValidationError("Preview Approval Binding artifact coverage is invalid")
    if not all(
        isinstance(value, str) and value.startswith("sha256:") and len(value) == 71
        for value in hashes.values()
    ):
        raise ValidationError("Preview Approval Binding contains an invalid hash")
    planning_hash = document.get("planning_hash")
    if (
        not isinstance(planning_hash, str)
        or not planning_hash.startswith("sha256:")
        or len(planning_hash) != 71
        or any(
            character not in "0123456789abcdef"
            for character in planning_hash.removeprefix("sha256:")
        )
    ):
        raise ValidationError("Preview Approval Binding planning hash is invalid")
    present_github_fields = github_fields.intersection(document)
    if present_github_fields and present_github_fields != github_fields:
        raise ValidationError("Preview Approval Binding GitHub evidence is incomplete")
    if present_github_fields:
        reviewer_id = document["environment_reviewer_id"]
        if (
            not isinstance(reviewer_id, int)
            or isinstance(reviewer_id, bool)
            or reviewer_id < 1
        ):
            raise ValidationError("Preview Approval Binding reviewer ID is invalid")
        for field in ("environment_review_hash", "environment_policy_hash"):
            value = document[field]
            if (
                not isinstance(value, str)
                or not value.startswith("sha256:")
                or len(value) != 71
                or any(
                    character not in "0123456789abcdef"
                    for character in value.removeprefix("sha256:")
                )
            ):
                raise ValidationError(
                    f"Preview Approval Binding {field} is invalid"
                )
        if (
            document["approver"].casefold()
            != document["environment_reviewer"].casefold()
        ):
            raise ValidationError(
                "Preview Approval Binding approver must match Environment reviewer"
            )
    expected = content_hash(
        {key: value for key, value in document.items() if key != "content_hash"}
    )
    if document["content_hash"] != expected:
        raise ValidationError("Preview Approval Binding content hash is invalid")
