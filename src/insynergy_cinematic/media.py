"""Technical validation and deterministic FFmpeg composition."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .errors import AssetValidationError, QualityBelowThresholdError, ValidationError
from .util import atomic_write_text, file_hash


class AssetValidator:
    def __init__(self, ffprobe_binary: str = "ffprobe") -> None:
        self.ffprobe_binary = ffprobe_binary

    def validate(
        self,
        asset: Path,
        *,
        width: int,
        height: int,
        frame_rate: int,
        duration_seconds: float,
        require_audio: bool = False,
    ) -> dict[str, Any]:
        if not asset.is_file() or asset.stat().st_size == 0:
            raise AssetValidationError("Rendered asset is missing or empty")
        if not shutil.which(self.ffprobe_binary):
            raise AssetValidationError("ffprobe is required for technical validation")
        command = [
            self.ffprobe_binary,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(asset),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode:
            raise AssetValidationError(
                "Asset is not decodable", details={"stderr": completed.stderr[-1000:]}
            )
        probe = json.loads(completed.stdout)
        video = next(
            (stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"),
            None,
        )
        if not video:
            raise AssetValidationError("Asset contains no video stream")
        audio = next(
            (stream for stream in probe.get("streams", []) if stream.get("codec_type") == "audio"),
            None,
        )
        actual_duration = float(probe.get("format", {}).get("duration", 0))
        rate_text = str(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1")
        numerator, _, denominator = rate_text.partition("/")
        actual_rate = float(numerator or 0) / float(denominator or 1)
        checks = {
            "decodable": True,
            "width": int(video.get("width", 0)) == width,
            "height": int(video.get("height", 0)) == height,
            "frame_rate": abs(actual_rate - frame_rate) < 0.01,
            "duration": abs(actual_duration - duration_seconds) <= max(0.25, 1 / frame_rate),
            "codec": video.get("codec_name") in {"h264", "hevc", "av1"},
            "nonempty": asset.stat().st_size > 0,
            "audio": audio is not None if require_audio else True,
        }
        if not all(checks.values()):
            raise AssetValidationError(
                "Asset failed technical validation",
                details={"checks": checks, "probe": probe},
            )
        return {
            "passed": True,
            "checks": checks,
            "width": int(video["width"]),
            "height": int(video["height"]),
            "duration_seconds": actual_duration,
            "codec": video["codec_name"],
            "frame_rate": actual_rate,
            "asset_hash": file_hash(asset),
            "audio_stream_present": audio is not None,
        }


class RenderQualityGate:
    def __init__(self, threshold: float = 0.90) -> None:
        self.threshold = threshold

    def evaluate(self, validation: dict[str, Any], frame: dict[str, Any]) -> dict[str, Any]:
        technical = 1.0 if validation.get("passed") else 0.0
        continuity = 1.0 if frame.get("character_continuity") else 0.0
        intent = 1.0 if frame.get("visible_action") and frame.get("camera") else 0.0
        style = 1.0 if frame.get("style") and frame.get("forbidden_style") else 0.0
        score = round(technical * 0.40 + continuity * 0.20 + intent * 0.25 + style * 0.15, 4)
        result = {
            "gate_id": "render_quality_gate",
            "passed": score >= self.threshold,
            "score": score,
            "threshold": self.threshold,
            "dimensions": {
                "technical": technical,
                "continuity": continuity,
                "intent": intent,
                "style": style,
            },
            "fail_closed": True,
        }
        if not result["passed"]:
            raise QualityBelowThresholdError("Rendered asset is below the quality threshold")
        return result


class FFmpegComposer:
    def __init__(self, ffmpeg_binary: str = "ffmpeg") -> None:
        self.ffmpeg_binary = ffmpeg_binary

    def compose(self, assets: list[Path], destination: Path) -> dict[str, Any]:
        if not assets:
            raise ValidationError("Composition requires at least one asset")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".partial.mp4")
        temporary.unlink(missing_ok=True)
        list_file = destination.with_suffix(".concat.txt")
        entries = []
        for asset in assets:
            safe = str(asset.resolve()).replace("'", "'\\''")
            entries.append(f"file '{safe}'")
        atomic_write_text(list_file, "\n".join(entries) + "\n")
        command = [
            self.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-map_metadata",
            "-1",
            "-metadata",
            "creation_time=1970-01-01T00:00:00Z",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(temporary),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode:
            temporary.unlink(missing_ok=True)
            raise ValidationError(
                "FFmpeg composition failed", details={"stderr": completed.stderr[-2000:]}
            )
        os.replace(temporary, destination)
        list_file.unlink(missing_ok=True)
        return {
            "asset_uri": str(destination.resolve()),
            "asset_hash": file_hash(destination),
            "input_count": len(assets),
            "ffmpeg_copy_concat": True,
        }
