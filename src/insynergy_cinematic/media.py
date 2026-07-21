"""Technical validation and deterministic FFmpeg composition."""

from __future__ import annotations

import array
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .errors import AssetValidationError, QualityBelowThresholdError, ValidationError
from .util import atomic_write_text, file_hash


class AssetValidator:
    def __init__(self, ffprobe_binary: str = "ffprobe", ffmpeg_binary: str = "ffmpeg") -> None:
        self.ffprobe_binary = ffprobe_binary
        self.ffmpeg_binary = ffmpeg_binary

    def _visual_metrics(self, asset: Path) -> dict[str, Any]:
        if not shutil.which(self.ffmpeg_binary):
            raise AssetValidationError("ffmpeg is required for visual content validation")
        width, height = 32, 18
        completed = subprocess.run(
            [
                self.ffmpeg_binary,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(asset),
                "-vf",
                f"fps=1,scale={width}:{height}",
                "-pix_fmt",
                "rgb24",
                "-f",
                "rawvideo",
                "pipe:1",
            ],
            capture_output=True,
            check=False,
        )
        if completed.returncode:
            raise AssetValidationError(
                "Visual content analysis failed",
                details={"stderr": completed.stderr.decode("utf-8", errors="replace")[-1000:]},
            )
        frame_size = width * height * 3
        frames = [
            completed.stdout[index : index + frame_size]
            for index in range(0, len(completed.stdout), frame_size)
            if len(completed.stdout[index : index + frame_size]) == frame_size
        ]
        if not frames:
            return {"visual_content_present": False, "spatial_stddev": 0.0, "temporal_delta": 0.0}
        spatial_values: list[float] = []
        for frame in frames:
            channel_stddev: list[float] = []
            for channel in range(3):
                values = frame[channel::3]
                mean = sum(values) / len(values)
                variance = sum((value - mean) ** 2 for value in values) / len(values)
                channel_stddev.append(math.sqrt(variance))
            spatial_values.append(sum(channel_stddev) / len(channel_stddev))
        temporal_values = [
            sum(abs(left - right) for left, right in zip(previous, current)) / frame_size
            for previous, current in zip(frames, frames[1:])
        ]
        spatial = max(spatial_values)
        temporal = max(temporal_values, default=0.0)
        return {
            "visual_content_present": spatial >= 4.0,
            "spatial_stddev": round(spatial, 4),
            "temporal_delta": round(temporal, 4),
        }

    def _audio_metrics(self, asset: Path) -> dict[str, Any]:
        if not shutil.which(self.ffmpeg_binary):
            raise AssetValidationError("ffmpeg is required for audio content validation")
        completed = subprocess.run(
            [
                self.ffmpeg_binary,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(asset),
                "-map",
                "0:a:0",
                "-ac",
                "1",
                "-ar",
                "8000",
                "-f",
                "s16le",
                "pipe:1",
            ],
            capture_output=True,
            check=False,
        )
        if completed.returncode or not completed.stdout:
            return {
                "audio_non_silent": False,
                "audio_rms_dbfs": -120.0,
                "audio_peak_dbfs": -120.0,
                "active_sample_ratio": 0.0,
            }
        samples = array.array("h")
        samples.frombytes(completed.stdout)
        if not samples:
            return {
                "audio_non_silent": False,
                "audio_rms_dbfs": -120.0,
                "audio_peak_dbfs": -120.0,
                "active_sample_ratio": 0.0,
            }
        normalized = [sample / 32768.0 for sample in samples]
        rms = math.sqrt(sum(sample * sample for sample in normalized) / len(normalized))
        peak = max(abs(sample) for sample in normalized)
        active_ratio = sum(abs(sample) >= 0.005 for sample in normalized) / len(normalized)
        rms_db = 20 * math.log10(rms) if rms > 0 else float("-inf")
        peak_db = 20 * math.log10(peak) if peak > 0 else float("-inf")
        return {
            "audio_non_silent": rms_db >= -45.0 and peak_db >= -30.0 and active_ratio >= 0.005,
            "audio_rms_dbfs": round(rms_db, 4),
            "audio_peak_dbfs": round(peak_db, 4),
            "active_sample_ratio": round(active_ratio, 6),
        }

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
        visual_metrics = self._visual_metrics(asset)
        audio_metrics = self._audio_metrics(asset) if require_audio and audio else {
            "audio_non_silent": False,
            "audio_rms_dbfs": -120.0,
            "audio_peak_dbfs": -120.0,
            "active_sample_ratio": 0.0,
        }
        checks = {
            "decodable": True,
            "width": int(video.get("width", 0)) == width,
            "height": int(video.get("height", 0)) == height,
            "frame_rate": abs(actual_rate - frame_rate) < 0.01,
            "duration": abs(actual_duration - duration_seconds) <= max(0.25, 1 / frame_rate),
            "codec": video.get("codec_name") in {"h264", "hevc", "av1"},
            "nonempty": asset.stat().st_size > 0,
            "audio": audio is not None if require_audio else True,
            "audio_signal": audio_metrics["audio_non_silent"] if require_audio else True,
            "visual_content": visual_metrics["visual_content_present"],
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
            **visual_metrics,
            **audio_metrics,
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


class OfflineNarrator:
    """Generate deterministic, zero-API-cost English narration and bind it to the Master."""

    def __init__(
        self,
        *,
        ffmpeg_binary: str = "ffmpeg",
        speech_binary: str = "espeak-ng",
    ) -> None:
        self.ffmpeg_binary = ffmpeg_binary
        self.speech_binary = speech_binary

    def mix(
        self,
        master: Path,
        timeline: list[dict[str, Any]],
        *,
        duration_seconds: float,
    ) -> dict[str, Any]:
        if not timeline:
            raise ValidationError("Narration timeline must contain at least one segment")
        if not shutil.which(self.ffmpeg_binary):
            raise ValidationError("ffmpeg is required for narration mixing")
        if not shutil.which(self.speech_binary):
            raise ValidationError("espeak-ng is required for zero-cost narration")
        temporary_master = master.with_suffix(".narrated.mp4")
        temporary_master.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory(prefix="insynergy-narration-") as temporary:
            root = Path(temporary)
            wav_paths: list[Path] = []
            for index, segment in enumerate(timeline, start=1):
                wav_path = root / f"segment-{index:02d}.wav"
                completed = subprocess.run(
                    [
                        self.speech_binary,
                        "-v",
                        "en-us",
                        "-s",
                        "150",
                        "-p",
                        "42",
                        "-a",
                        "165",
                        "-w",
                        str(wav_path),
                        str(segment["text"]),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if completed.returncode or not wav_path.is_file() or wav_path.stat().st_size == 0:
                    raise ValidationError(
                        "Offline narration synthesis failed",
                        details={"stderr": completed.stderr[-1000:]},
                    )
                wav_paths.append(wav_path)
            command = [self.ffmpeg_binary, "-hide_banner", "-loglevel", "error", "-y", "-i", str(master)]
            for wav_path in wav_paths:
                command.extend(("-i", str(wav_path)))
            filters: list[str] = []
            labels: list[str] = []
            for index, segment in enumerate(timeline, start=1):
                delay_ms = max(0, round(float(segment["start_seconds"]) * 1000))
                label = f"narration{index}"
                labels.append(f"[{label}]")
                filters.append(
                    f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo,"
                    f"adelay={delay_ms}:all=1,volume=1.0[{label}]"
                )
            filters.append(
                "".join(labels)
                + f"amix=inputs={len(labels)}:duration=longest:dropout_transition=0,"
                + "loudnorm=I=-16:TP=-1.5:LRA=11,"
                + f"apad,atrim=duration={duration_seconds}[narration]"
            )
            command.extend(
                (
                    "-filter_complex",
                    ";".join(filters),
                    "-map",
                    "0:v:0",
                    "-map",
                    "[narration]",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-movflags",
                    "+faststart",
                    "-t",
                    str(duration_seconds),
                    str(temporary_master),
                )
            )
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            if completed.returncode:
                temporary_master.unlink(missing_ok=True)
                raise ValidationError(
                    "Narration mix failed", details={"stderr": completed.stderr[-2000:]}
                )
        os.replace(temporary_master, master)
        return {
            "asset_hash": file_hash(master),
            "narration_engine": "espeak-ng-offline",
            "narration_segment_count": len(timeline),
            "narration_api_cost_usd": 0.0,
        }
