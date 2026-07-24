"""Technical validation and deterministic FFmpeg composition."""

from __future__ import annotations

import array
import json
import math
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
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

    def _loudness_metrics(self, asset: Path) -> dict[str, Any]:
        completed = subprocess.run(
            [
                self.ffmpeg_binary,
                "-hide_banner",
                "-nostats",
                "-i",
                str(asset),
                "-map",
                "0:a:0",
                "-af",
                "loudnorm=I=-14:TP=-1:LRA=7:print_format=json",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        start = completed.stderr.rfind("{")
        end = completed.stderr.rfind("}")
        if completed.returncode or start < 0 or end <= start:
            return {
                "integrated_loudness_lufs": -120.0,
                "true_peak_db": -120.0,
                "loudness_target_met": False,
            }
        try:
            report = json.loads(completed.stderr[start : end + 1])
            integrated = float(report["input_i"])
            true_peak = float(report["input_tp"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return {
                "integrated_loudness_lufs": -120.0,
                "true_peak_db": -120.0,
                "loudness_target_met": False,
            }
        return {
            "integrated_loudness_lufs": integrated,
            "true_peak_db": true_peak,
            "loudness_target_met": -16.0 <= integrated <= -12.0 and true_peak <= -0.5,
        }

    @staticmethod
    def _faststart(asset: Path) -> bool:
        with asset.open("rb") as handle:
            header = handle.read(4 * 1024 * 1024)
        moov = header.find(b"moov")
        mdat = header.find(b"mdat")
        return moov >= 0 and (mdat < 0 or moov < mdat)

    def validate(
        self,
        asset: Path,
        *,
        width: int,
        height: int,
        frame_rate: int,
        duration_seconds: float,
        require_audio: bool = False,
        require_youtube_ready: bool = False,
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
        youtube_checks = {
            "h264_high_profile": video.get("codec_name") == "h264"
            and str(video.get("profile", "")).lower() == "high",
            "progressive": str(video.get("field_order", "progressive"))
            in {"progressive", "unknown"},
            "yuv420p": video.get("pix_fmt") == "yuv420p",
            "bt709": all(
                video.get(field) == "bt709"
                for field in ("color_space", "color_transfer", "color_primaries")
            ),
            "aac_stereo_48khz": bool(audio)
            and audio.get("codec_name") == "aac"
            and int(audio.get("sample_rate", 0)) == 48000
            and int(audio.get("channels", 0)) == 2,
            "faststart": self._faststart(asset),
        }
        loudness_metrics = (
            self._loudness_metrics(asset)
            if require_youtube_ready and audio
            else {
                "integrated_loudness_lufs": -120.0,
                "true_peak_db": -120.0,
                "loudness_target_met": not require_youtube_ready,
            }
        )
        youtube_checks["loudness"] = loudness_metrics["loudness_target_met"]
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
            "youtube_delivery": all(youtube_checks.values())
            if require_youtube_ready
            else True,
        }
        if not all(checks.values()):
            raise AssetValidationError(
                "Asset failed technical validation",
                details={
                    "checks": checks,
                    "youtube_checks": youtube_checks,
                    "loudness": loudness_metrics,
                    "probe": probe,
                },
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
            "youtube_ready": all(youtube_checks.values()),
            "youtube_checks": youtube_checks,
            **loudness_metrics,
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


class _NarrationMixer:
    def __init__(self, *, ffmpeg_binary: str = "ffmpeg") -> None:
        self.ffmpeg_binary = ffmpeg_binary

    def _mix_wavs(
        self,
        master: Path,
        timeline: list[dict[str, Any]],
        wav_paths: list[Path],
        *,
        duration_seconds: float,
        integrated_loudness_lufs: float,
        true_peak_db: float,
        audio_bitrate: str,
    ) -> None:
        temporary_master = master.with_suffix(".narrated.mp4")
        temporary_master.unlink(missing_ok=True)
        command = [
            self.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(master),
        ]
        for wav_path in wav_paths:
            command.extend(("-i", str(wav_path)))
        filters: list[str] = []
        labels: list[str] = []
        for index, segment in enumerate(timeline, start=1):
            start = max(0.0, float(segment["start_seconds"]))
            end = min(duration_seconds, float(segment.get("end_seconds", duration_seconds)))
            available = max(0.25, end - start)
            fade_start = max(0.0, available - 0.12)
            delay_ms = round(start * 1000)
            label = f"narration{index}"
            labels.append(f"[{label}]")
            filters.append(
                f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo,"
                f"atrim=duration={available},afade=t=out:st={fade_start}:d=0.12,"
                f"adelay={delay_ms}:all=1,volume=1.0[{label}]"
            )
        filters.append(
            "".join(labels)
            + f"amix=inputs={len(labels)}:duration=longest:dropout_transition=0,"
            + f"loudnorm=I={integrated_loudness_lufs}:TP={true_peak_db}:LRA=7,"
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
                audio_bitrate,
                "-ar",
                "48000",
                "-ac",
                "2",
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


class OfflineNarrator(_NarrationMixer):
    """Generate deterministic, zero-API-cost English narration and bind it to the Master."""

    def __init__(
        self,
        *,
        ffmpeg_binary: str = "ffmpeg",
        speech_binary: str = "espeak-ng",
    ) -> None:
        super().__init__(ffmpeg_binary=ffmpeg_binary)
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
            self._mix_wavs(
                master,
                timeline,
                wav_paths,
                duration_seconds=duration_seconds,
                integrated_loudness_lufs=-16.0,
                true_peak_db=-1.5,
                audio_bitrate="192k",
            )
        return {
            "asset_hash": file_hash(master),
            "narration_engine": "espeak-ng-offline",
            "narration_segment_count": len(timeline),
            "narration_api_cost_usd": 0.0,
        }


class OpenAITTSNarrator(_NarrationMixer):
    """Create production narration with the OpenAI Speech API without retrying billable calls."""

    API_URL = "https://api.openai.com/v1/audio/speech"
    FULL_AUTO_SHOUT_RECOVERY = "full-auto-shot7-shout-v1"
    FULL_AUTO_MORNING_LINE = "It'll be done by morning."
    FULL_AUTO_SHOUT_LINE = "I'm such a fucking idiot!"
    FULL_AUTO_MORNING_INSTRUCTIONS = (
        "Perform only the supplied line in natural American English as the same "
        "middle-aged male developer. Speak quietly with ordinary confidence and slight "
        "satisfaction, as an offhand remark before leaving the room. Do not shout, add "
        "words, narration, laughter, vocal effects, or trailing speech."
    )
    FULL_AUTO_SHOUT_INSTRUCTIONS = (
        "Perform only the supplied line as a raw, explosive, self-directed yell in "
        "natural American English by the same middle-aged male developer. Start at full "
        "shouting intensity: anger, shock, and immediate regret collide at once. Drive "
        "the line from the chest with hard breath pressure and let the voice strain or "
        "crack slightly without becoming theatrical. Make 'fucking idiot' land louder "
        "and sharper than 'I'm such a'. This is not narration, a calm read, sarcasm, or "
        "a whisper. Do not add words, a separate scream, growls, laughter, effects, or "
        "trailing speech. End abruptly into dead air."
    )

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o-mini-tts",
        voice: str = "marin",
        instructions: str,
        performance_recovery: str | None = None,
        ffmpeg_binary: str = "ffmpeg",
        timeout_seconds: int = 120,
    ) -> None:
        super().__init__(ffmpeg_binary=ffmpeg_binary)
        if not api_key:
            raise ValidationError("OPENAI_TTS_API_KEY is required for OpenAI narration")
        if model != "gpt-4o-mini-tts":
            raise ValidationError("OpenAI narration model is not allow-listed")
        if performance_recovery not in {None, self.FULL_AUTO_SHOUT_RECOVERY}:
            raise ValidationError("OpenAI narration performance recovery is not allow-listed")
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.instructions = instructions
        self.performance_recovery = performance_recovery
        self.timeout_seconds = timeout_seconds

    def _instructions_for(self, text: str) -> str:
        if self.performance_recovery != self.FULL_AUTO_SHOUT_RECOVERY:
            return self.instructions
        if text == self.FULL_AUTO_MORNING_LINE:
            return self.FULL_AUTO_MORNING_INSTRUCTIONS
        if text == self.FULL_AUTO_SHOUT_LINE:
            return self.FULL_AUTO_SHOUT_INSTRUCTIONS
        raise ValidationError(
            "Full Auto narration performance recovery received unexpected dialogue",
            details={"dialogue": text},
        )

    def _synthesize(self, text: str, destination: Path, *, instructions: str) -> None:
        payload = json.dumps(
            {
                "model": self.model,
                "voice": self.voice,
                "input": text,
                "instructions": instructions,
                "response_format": "wav",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.API_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                audio = response.read()
        except urllib.error.HTTPError as exc:
            raise ValidationError(
                "OpenAI narration request failed", details={"http_status": exc.code}
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ValidationError(
                "OpenAI narration request outcome is unknown; automatic retry is disabled"
            ) from exc
        if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
            raise ValidationError("OpenAI narration response is not a valid WAV file")
        destination.write_bytes(audio)

    def mix(
        self,
        master: Path,
        timeline: list[dict[str, Any]],
        *,
        duration_seconds: float,
        integrated_loudness_lufs: float = -14.0,
        true_peak_db: float = -1.0,
        audio_bitrate: str = "384k",
    ) -> dict[str, Any]:
        if not timeline:
            raise ValidationError("Narration timeline must contain at least one segment")
        if not shutil.which(self.ffmpeg_binary):
            raise ValidationError("ffmpeg is required for narration mixing")
        with tempfile.TemporaryDirectory(prefix="insynergy-openai-narration-") as temporary:
            root = Path(temporary)
            wav_paths: list[Path] = []
            for index, segment in enumerate(timeline, start=1):
                wav_path = root / f"segment-{index:02d}.wav"
                text = str(segment["text"])
                self._synthesize(
                    text,
                    wav_path,
                    instructions=self._instructions_for(text),
                )
                wav_paths.append(wav_path)
            self._mix_wavs(
                master,
                timeline,
                wav_paths,
                duration_seconds=duration_seconds,
                integrated_loudness_lufs=integrated_loudness_lufs,
                true_peak_db=true_peak_db,
                audio_bitrate=audio_bitrate,
            )
        return {
            "asset_hash": file_hash(master),
            "narration_engine": "openai-speech-api",
            "narration_model": self.model,
            "narration_voice": self.voice,
            "narration_segment_count": len(timeline),
            "narration_billing": "metered",
            "ai_generated_voice": True,
            "narration_performance_recovery": self.performance_recovery,
        }


class SoundtrackMixer:
    """Mix an approval-bound soundtrack beneath dialogue and trim it to the Master."""

    def __init__(self, ffmpeg_binary: str = "ffmpeg") -> None:
        self.ffmpeg_binary = ffmpeg_binary

    def mix(
        self,
        master: Path,
        soundtrack: Path,
        *,
        duration_seconds: float,
        gain_db: float,
        expected_hash: str,
    ) -> dict[str, Any]:
        if not shutil.which(self.ffmpeg_binary):
            raise ValidationError("ffmpeg is required for soundtrack mixing")
        if not soundtrack.is_file() or file_hash(soundtrack) != expected_hash:
            raise ValidationError("Soundtrack integrity check failed")
        if not -36.0 <= gain_db <= -6.0:
            raise ValidationError("Soundtrack gain is out of range")
        fade_duration = min(0.4, max(0.1, duration_seconds / 10))
        fade_start = max(0.0, duration_seconds - 0.8)
        soundtrack_end = max(fade_start + fade_duration, duration_seconds - 0.4)
        temporary_master = master.with_suffix(".soundtrack.mp4")
        temporary_master.unlink(missing_ok=True)
        filters = (
            f"[1:a]aresample=48000,aformat=channel_layouts=stereo,"
            f"atrim=duration={soundtrack_end},volume={gain_db}dB,"
            f"afade=t=out:st={fade_start}:d={fade_duration},"
            f"apad,atrim=duration={duration_seconds}[soundtrack];"
            f"[0:a][soundtrack]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
            f"alimiter=limit=0.891251,apad,atrim=duration={duration_seconds}[mixed]"
        )
        command = [
            self.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(master),
            "-stream_loop",
            "-1",
            "-i",
            str(soundtrack),
            "-filter_complex",
            filters,
            "-map",
            "0:v:0",
            "-map",
            "[mixed]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "384k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            "-t",
            str(duration_seconds),
            str(temporary_master),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode:
            temporary_master.unlink(missing_ok=True)
            raise ValidationError(
                "Soundtrack mix failed", details={"stderr": completed.stderr[-2000:]}
            )
        os.replace(temporary_master, master)
        return {
            "asset_hash": file_hash(master),
            "soundtrack_uri": str(soundtrack.resolve()),
            "soundtrack_hash": expected_hash,
            "soundtrack_gain_db": gain_db,
            "soundtrack_duration_seconds": duration_seconds,
            "soundtrack_final_silence_seconds": 0.4,
        }


class YouTubeMastering:
    """Encode a final SDR master using YouTube's recommended delivery characteristics."""

    def __init__(self, ffmpeg_binary: str = "ffmpeg") -> None:
        self.ffmpeg_binary = ffmpeg_binary

    def _loudness_report(
        self,
        source: Path,
        *,
        integrated_loudness_lufs: float,
        true_peak_db: float,
    ) -> dict[str, float]:
        completed = subprocess.run(
            [
                self.ffmpeg_binary,
                "-hide_banner",
                "-nostats",
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-af",
                (
                    f"loudnorm=I={integrated_loudness_lufs}:TP={true_peak_db}:"
                    "LRA=7:print_format=json"
                ),
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        start = completed.stderr.rfind("{")
        end = completed.stderr.rfind("}")
        if completed.returncode or start < 0 or end <= start:
            raise ValidationError("YouTube loudness analysis failed")
        try:
            report = json.loads(completed.stderr[start : end + 1])
            measured = {
                key: float(report[key])
                for key in (
                    "input_i",
                    "input_tp",
                    "input_lra",
                    "input_thresh",
                    "target_offset",
                )
            }
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValidationError("YouTube loudness analysis is invalid") from exc
        if not all(math.isfinite(value) for value in measured.values()):
            raise ValidationError("YouTube loudness analysis is non-finite")
        return measured

    def _loudnorm_filter(
        self,
        source: Path,
        *,
        integrated_loudness_lufs: float,
        true_peak_db: float,
    ) -> str:
        measured = self._loudness_report(
            source,
            integrated_loudness_lufs=integrated_loudness_lufs,
            true_peak_db=true_peak_db,
        )
        return (
            f"loudnorm=I={integrated_loudness_lufs}:TP={true_peak_db}:LRA=7:"
            f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
            f"measured_LRA={measured['input_lra']}:"
            f"measured_thresh={measured['input_thresh']}:"
            f"offset={measured['target_offset']}:linear=true:print_format=summary"
        )

    def master(
        self,
        source: Path,
        *,
        width: int,
        height: int,
        frame_rate: int,
        video_bitrate: str = "8M",
        audio_bitrate: str = "384k",
        audio_sample_rate: int = 48000,
        integrated_loudness_lufs: float = -14.0,
        true_peak_db: float = -1.0,
    ) -> dict[str, Any]:
        if not shutil.which(self.ffmpeg_binary):
            raise ValidationError("ffmpeg is required for YouTube mastering")
        destination = source.with_suffix(".youtube.mp4")
        destination.unlink(missing_ok=True)
        gop = max(1, frame_rate // 2)
        loudnorm_filter = self._loudnorm_filter(
            source,
            integrated_loudness_lufs=integrated_loudness_lufs,
            true_peak_db=true_peak_db,
        )
        command = [
            self.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-vf",
            (
                f"scale={width}:{height}:flags=lanczos,setsar=1,format=yuv420p,"
                "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709"
            ),
            "-af",
            loudnorm_filter,
            "-map_metadata",
            "-1",
            "-metadata",
            "creation_time=1970-01-01T00:00:00Z",
            "-metadata",
            "comment=This video contains an AI-generated narration voice.",
            "-c:v",
            "libx264",
            "-profile:v",
            "high",
            "-level:v",
            "4.0",
            "-preset",
            "slow",
            "-b:v",
            video_bitrate,
            "-maxrate",
            video_bitrate,
            "-bufsize",
            "16M",
            "-g",
            str(gop),
            "-keyint_min",
            str(gop),
            "-sc_threshold",
            "0",
            "-bf",
            "2",
            "-flags",
            "+cgop",
            "-pix_fmt",
            "yuv420p",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-colorspace",
            "bt709",
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            "-ar",
            str(audio_sample_rate),
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(destination),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode:
            destination.unlink(missing_ok=True)
            raise ValidationError(
                "YouTube mastering failed", details={"stderr": completed.stderr[-2000:]}
            )
        loudness = self._loudness_report(
            destination,
            integrated_loudness_lufs=integrated_loudness_lufs,
            true_peak_db=true_peak_db,
        )
        correction_attempts = 0
        while not (
            -16.0 <= loudness["input_i"] <= -12.0
            and loudness["input_tp"] <= -0.5
        ) and correction_attempts < 2:
            correction_attempts += 1
            gain_db = integrated_loudness_lufs - loudness["input_i"]
            # AAC encoding can create inter-sample peaks above the filter's ceiling.
            # Keep one additional decibel of headroom so the encoded measurement,
            # rather than only the pre-encode PCM signal, remains inside the gate.
            limiter_target_db = min(true_peak_db - 1.0, -1.5)
            limiter_level = 10 ** (limiter_target_db / 20)
            correction = source.with_suffix(
                f".youtube-audio-correction-{correction_attempts}.mp4"
            )
            correction.unlink(missing_ok=True)
            correction_filter = (
                f"volume={gain_db:.4f}dB,"
                f"alimiter=limit={limiter_level:.8f}:attack=5:release=50:"
                "level=false:latency=true"
            )
            correction_command = [
                self.ffmpeg_binary,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(destination),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0",
                "-c:v",
                "copy",
                "-af",
                correction_filter,
                "-c:a",
                "aac",
                "-b:a",
                audio_bitrate,
                "-ar",
                str(audio_sample_rate),
                "-ac",
                "2",
                "-map_metadata",
                "0",
                "-movflags",
                "+faststart",
                str(correction),
            ]
            corrected = subprocess.run(
                correction_command,
                capture_output=True,
                text=True,
                check=False,
            )
            if corrected.returncode:
                correction.unlink(missing_ok=True)
                destination.unlink(missing_ok=True)
                raise ValidationError(
                    "YouTube loudness correction failed",
                    details={"stderr": corrected.stderr[-2000:]},
                )
            os.replace(correction, destination)
            loudness = self._loudness_report(
                destination,
                integrated_loudness_lufs=integrated_loudness_lufs,
                true_peak_db=true_peak_db,
            )
        if not (
            -16.0 <= loudness["input_i"] <= -12.0
            and loudness["input_tp"] <= -0.5
        ):
            destination.unlink(missing_ok=True)
            raise ValidationError(
                "YouTube mastering could not satisfy the loudness envelope",
                details={
                    "integrated_loudness_lufs": loudness["input_i"],
                    "true_peak_db": loudness["input_tp"],
                    "correction_attempts": correction_attempts,
                },
            )
        os.replace(destination, source)
        return {
            "asset_hash": file_hash(source),
            "delivery_profile": "youtube-1080p-sdr-v1",
            "container": "mp4",
            "video_codec": "h264-high",
            "video_bitrate": video_bitrate,
            "pixel_format": "yuv420p",
            "color_space": "bt709",
            "audio_codec": "aac-lc",
            "audio_bitrate": audio_bitrate,
            "audio_sample_rate": audio_sample_rate,
            "integrated_loudness_lufs": loudness["input_i"],
            "true_peak_db": loudness["input_tp"],
            "loudness_correction_attempts": correction_attempts,
            "encoded_true_peak_safety_margin_db": 1.0,
            "faststart": True,
        }


def _srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(
    destination: Path,
    timeline: list[dict[str, Any]],
    *,
    duration_seconds: float,
    language: str = "en",
) -> dict[str, Any]:
    normalized_language = language.strip().casefold()
    if normalized_language not in {"en", "ja"}:
        raise ValidationError("Caption language is not supported")
    blocks: list[str] = []
    for index, segment in enumerate(timeline, start=1):
        start = max(0.0, float(segment["start_seconds"]))
        end = min(duration_seconds, float(segment.get("end_seconds", duration_seconds)))
        if end <= start:
            raise ValidationError("Caption segment has an invalid time range")
        text = str(segment["text"]).strip().replace("\r", " ").replace("\n", " ")
        blocks.append(
            f"{index}\n{_srt_timestamp(start)} --> {_srt_timestamp(end)}\n{text}\n"
        )
    atomic_write_text(destination, "\n".join(blocks))
    return {
        "caption_uri": str(destination.resolve()),
        "caption_hash": file_hash(destination),
        "caption_format": "srt",
        "caption_language": normalized_language,
        "caption_segment_count": len(timeline),
    }
