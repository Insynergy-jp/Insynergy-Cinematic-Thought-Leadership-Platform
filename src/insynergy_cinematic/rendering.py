"""Provider-independent, cache-first Rendering Platform facade."""

from __future__ import annotations

import base64
import math
import os
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .config import PlatformConfig
from .errors import (
    BudgetExhaustedError,
    ProviderTimeoutError,
    RenderingError,
    StoryboardNotApprovedError,
    ValidationError,
)
from .media import AssetValidator, RenderQualityGate
from .models import RenderRequest, RenderResult, RenderState
from .prompt import PromptAssembler
from .providers import VideoProvider
from .runtime import DurableTaskQueue
from .storage import ContentAddressableStore
from .util import (
    atomic_write_json,
    atomic_write_text,
    content_hash,
    file_hash,
    read_json,
    stable_id,
)


RUNWAY_GEN45_CREDITS_PER_SECOND = 12
RUNWAY_CREDIT_USD = 0.01
RUNWAY_RECOVERY_SHOTS_ENV = "INSYNERGY_RUNWAY_RECOVERY_SHOTS"
RUNWAY_RECOVERY_REASON_ENV = "INSYNERGY_RUNWAY_RECOVERY_REASON"
RUNWAY_STORYBOARD_REFERENCES_ENV = "INSYNERGY_RUNWAY_STORYBOARD_REFERENCES"
SHOT_ID = re.compile(r"scene-[0-9]{3}-shot-[0-9]{2}")
FULL_AUTO_V11_REFERENCES = {
    "scene-001-shot-01": "creative/full-auto-30s/storyboard-shot-01-identity-v11.png",
    "scene-002-shot-01": "creative/full-auto-30s/storyboard-shot-02-desktop-v11.png",
    "scene-004-shot-01": "creative/full-auto-30s/storyboard-shot-04-desktop-v11.png",
    "scene-005-shot-01": "creative/full-auto-30s/storyboard-shot-05-desktop-v11.png",
    "scene-007-shot-01": "creative/full-auto-30s/storyboard-shot-07-identity-v11.png",
}


def runway_recovery_shots(config: PlatformConfig) -> frozenset[str]:
    raw = os.environ.get(RUNWAY_RECOVERY_SHOTS_ENV, "").strip()
    if not raw:
        return frozenset()
    if config.provider != "runway" or config.runway_scope != "hybrid":
        raise ValidationError(
            "Runway fidelity recovery requires a planned hybrid Runway build"
        )
    reason = os.environ.get(RUNWAY_RECOVERY_REASON_ENV, "").strip()
    if not reason or len(reason) > 500:
        raise ValidationError("Runway fidelity recovery requires a bounded reason")
    shots = frozenset(item.strip() for item in raw.split(",") if item.strip())
    if not shots or len(shots) > 12 or any(SHOT_ID.fullmatch(item) is None for item in shots):
        raise ValidationError("Runway fidelity recovery shot IDs are invalid")
    return shots


def uses_runway(config: PlatformConfig, frame: dict[str, Any]) -> bool:
    if config.provider != "runway":
        return False
    return (
        config.runway_scope == "all_shots"
        or frame["render_strategy"]["asset_class"] == "runway_video"
        or frame["shot_id"] in runway_recovery_shots(config)
    )


def runway_credit_estimate(
    config: PlatformConfig, frames: list[dict[str, Any]]
) -> int:
    profile = config.render_profile()
    return sum(
        math.ceil(
            min(float(frame["duration_seconds"]), profile.max_duration_seconds)
        )
        * RUNWAY_GEN45_CREDITS_PER_SECOND
        for frame in frames
        if uses_runway(config, frame)
    )


class RenderCache:
    """Exact cache only; near matches are misses by construction."""

    def __init__(self, root: Path, cas: ContentAddressableStore) -> None:
        self.root = root
        self.cas = cas
        self._lock = threading.Lock()

    @staticmethod
    def key(
        *, shot_hash: str, prompt_hash: str, provider: str, provider_version: str, profile: str
    ) -> str:
        return content_hash(
            {
                "shot_hash": shot_hash,
                "prompt_hash": prompt_hash,
                "provider": provider,
                "provider_version": provider_version,
                "render_profile": profile,
            }
        )

    def _entry(self, key: str) -> Path:
        return self.root / f"{key.split(':', 1)[1]}.json"

    def lookup(self, key: str) -> dict[str, Any] | None:
        path = self._entry(key)
        if not path.exists():
            return None
        entry = read_json(path)
        if entry.get("cache_key") != key:
            return None
        asset = self.cas.resolve(entry.get("asset_hash", ""), ".mp4")
        if not asset or file_hash(asset) != entry.get("asset_hash"):
            return None
        entry["asset_uri"] = str(asset.resolve())
        return entry

    def store(
        self, key: str, asset: Path, validation: dict[str, Any], quality: dict[str, Any]
    ) -> dict[str, Any]:
        asset_hash, cas_path = self.cas.put_file(asset)
        entry = {
            "cache_key": key,
            "asset_hash": asset_hash,
            "asset_uri": str(cas_path.resolve()),
            "validation": validation,
            "quality": quality,
            "validated": True,
            "quality_passed": quality.get("passed") is True,
        }
        with self._lock:
            atomic_write_json(self._entry(key), entry)
        return entry


class StoryboardPostProcessor:
    """Deterministically composite authored UI and exact motion-graphics beats."""

    def __init__(self, ffmpeg_binary: str = "ffmpeg") -> None:
        self.ffmpeg_binary = ffmpeg_binary

    @staticmethod
    def _font_file() -> str:
        for candidate in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
        ):
            if Path(candidate).is_file():
                return candidate
        if shutil.which("fc-match"):
            matched = subprocess.run(
                ["fc-match", "-f", "%{file}", "DejaVu Sans"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            if matched and Path(matched).is_file():
                return matched
        raise RenderingError("A TrueType font is required for storyboard post-production")

    @staticmethod
    def _symbol_font_file() -> str:
        for candidate in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Apple Symbols.ttf",
        ):
            if Path(candidate).is_file():
                return candidate
        return StoryboardPostProcessor._font_file()

    @staticmethod
    def _filter_path(value: Path | str) -> str:
        return str(value).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")

    def apply(
        self,
        asset: Path,
        frame: dict[str, Any],
        *,
        width: int,
        height: int,
        frame_rate: int,
        duration_seconds: float,
    ) -> dict[str, Any]:
        overlays = [str(item) for item in frame.get("ui_overlays", [])]
        shot_id = str(frame["shot_id"])
        if not overlays and shot_id not in {"scene-003-shot-01", "scene-008-shot-01"}:
            return {"applied": False, "mode": "none", "exact_strings": []}
        if not shutil.which(self.ffmpeg_binary):
            raise RenderingError("FFmpeg is required for storyboard post-production")

        temporary = asset.with_suffix(".post-production.mp4")
        temporary.unlink(missing_ok=True)
        text_paths: list[Path] = []
        font_file = self._filter_path(self._font_file())
        symbol_font_file = self._filter_path(self._symbol_font_file())
        sx = width / 1920
        sy = height / 1080

        def px(value: int) -> int:
            return max(1, round(value * sx))

        def py(value: int) -> int:
            return max(1, round(value * sy))

        def text_path(value: str) -> str:
            path = asset.with_suffix(f".post-{len(text_paths):03d}.txt")
            atomic_write_text(path, value + "\n")
            text_paths.append(path)
            return self._filter_path(path)

        filters: list[str] = []

        def box(
            x: int,
            y: int,
            w: int,
            h: int,
            color: str,
            *,
            thickness: str = "fill",
            enable: str | None = None,
        ) -> None:
            value = (
                f"drawbox=x={px(x)}:y={py(y)}:w={px(w)}:h={py(h)}:"
                f"color={color}:t={thickness}"
            )
            if enable:
                value += f":enable='{enable}'"
            filters.append(value)

        def label(
            value: str,
            x: int | str,
            y: int | str,
            size: int,
            *,
            color: str = "white",
            enable: str | None = None,
            align: str | None = None,
            font: str | None = None,
        ) -> None:
            x_value = px(x) if isinstance(x, int) else x
            y_value = py(y) if isinstance(y, int) else y
            item = (
                f"drawtext=fontfile='{font or font_file}':textfile='{text_path(value)}':reload=0:"
                f"fontcolor={color}:fontsize={px(size)}:x={x_value}:y={y_value}"
            )
            if align:
                item += f":text_align={align}"
            if enable:
                item += f":enable='{enable}'"
            filters.append(item)

        mode = "ui_overlay"
        if shot_id == "scene-001-shot-01":
            box(1010, 90, 820, 880, "0x07111d@0.88")
            box(1010, 90, 820, 4, "0x58b7ff@0.90")
            label("00:18", 1060, 125, 30, color="0xaedcff")
            label("EXECUTION MODE", 1060, 190, 34)
            for index, value in enumerate(
                (
                    "FULL AUTO",
                    "PARALLEL RUNS",
                    "AUTO RETRY",
                    "CONTINUE UNTIL COMPLETE",
                )
            ):
                y = 270 + index * 82
                box(1080, y + 5, 30, 30, "0x9bd8ff@0.95", thickness="2")
                label("X", 1086, y + 1, 23, color="0xdff4ff")
                label(value, 1140, y, 31, color="0xeaf5ff")
            box(1060, 620, 720, 1, "0x7ebde8@0.55")
            label("SPENDING LIMIT", 1060, 660, 29)
            label("OFF", 1660, 660, 31, color="0xff7d7d")
            box(1410, 800, 270, 92, "0x183b58@0.96")
            label("RUN", 1500, 822, 34)
            label(
                "▶",
                "'max(0,min(w-40,w*0.88-(t/1.2)*w*0.08))'",
                842,
                38,
                enable="between(t,0.25,1.25)",
                font=symbol_font_file,
            )
            box(1410, 800, 270, 92, "0x5aaeff@0.28", enable="between(t,1.15,1.32)")
        elif shot_id == "scene-002-shot-01":
            box(715, 370, 500, 190, "0x06111d@0.82")
            box(715, 370, 500, 3, "0x57b8ff@0.90")
            label("RUN #001 STARTED", 785, 435, 34, color="0xeaf6ff")
        elif shot_id == "scene-003-shot-01":
            mode = "exact_agent_multiplication"
            filters.clear()
            box(0, 0, 1920, 1080, "0x02060b@1.0")
            for row in range(10):
                for column in range(16):
                    index = row * 16 + column
                    threshold = min(3.45, 0.18 + index * 0.0205)
                    x = 18 + column * 119
                    y = 18 + row * 105
                    box(x, y, 104, 86, "0x14314a@0.72", enable=f"gte(t,{threshold:.3f})")
                    box(x, y, 104, 86, "0x69c6ff@0.55", thickness="1", enable=f"gte(t,{threshold:.3f})")
                    box(x + 14, y + 14, 10, 10, "0x8ed8ff@0.85", enable=f"gte(t,{threshold:.3f})")
            timings = (
                ("Creating Agent...", 0.00, 0.40),
                ("Searching...", 0.40, 0.80),
                ("Generating...", 0.80, 1.25),
                ("Retry...", 1.25, 1.65),
                ("Launching Parallel Worker...", 1.65, 2.15),
                ("Expanding Context...", 2.15, 2.60),
                ("Thinking...", 2.60, 3.35),
            )
            for value, start, end in timings:
                label(value, 74, 70, 42, enable=f"between(t,{start:.2f},{end:.2f})")
            for value, start, end in (
                ("Run #18", 0.80, 1.25),
                ("Run #37", 1.25, 2.15),
                ("Run #96", 2.15, 3.35),
                ("Run #184", 3.35, 4.00),
            ):
                label(value, 1600, 72, 38, color="0xdff4ff", enable=f"between(t,{start:.2f},{end:.2f})")
            box(0, 0, 1920, 1080, "0xc8323c@0.13", enable="between(t,1.25,1.45)")
        elif shot_id == "scene-004-shot-01":
            box(1370, 805, 390, 160, "0x07111d@0.88")
            box(1370, 805, 5, 160, "0xd9545d@0.92")
            label("USAGE ALERT", 1410, 835, 26, color="0xd7e7f5")
            label("$512.43", 1410, 885, 38, color="0xff8c91")
        elif shot_id == "scene-005-shot-01":
            box(110, 90, 1700, 900, "0x06101a@0.64")
            box(110, 90, 1700, 3, "0x63bfff@0.75")
            label("Completed", 190, 250, 40, color="0xcfe9fa")
            label("184 Tasks", 190, 330, 68)
            label("Current Usage", 1280, 170, 34, color="0xcfe9fa")
            for value, start, end in (
                ("$731.88", 0.95, 1.55),
                ("$734", 1.55, 2.20),
                ("$739", 2.20, 3.00),
                ("$744", 3.00, 4.00),
            ):
                label(value, 1280, 245, 70, color="0xff8088", enable=f"between(t,{start:.2f},{end:.2f})")
        elif shot_id == "scene-006-shot-01":
            box(520, 90, 1290, 850, "0x06101a@0.76")
            box(520, 90, 1290, 3, "0x63bfff@0.72")
            box(630, 610, 260, 100, "0xa92531@0.96")
            label("STOP", 705, 634, 38)
            label(
                "▶",
                "'max(0,min(w-40,w*0.80-(t/0.30)*w*0.39))'",
                648,
                42,
                enable="between(t,0.00,0.55)",
                font=symbol_font_file,
            )
            box(630, 610, 260, 100, "white@0.18", enable="between(t,0.30,0.55)")
            label("Stopping...", 650, 220, 40, enable="between(t,0.55,1.15)")
            label("Waiting for active workers...", 650, 220, 38, enable="gte(t,1.15)")
            label("12 Active Agents", 1120, 320, 34, color="0xff7b84", enable="gte(t,1.85)")
            for index in range(12):
                box(650 + index * 88, 430, 56, 56, "0xd9434e@0.88", enable=f"gte(t,{1.85 + (index % 3) * 0.05:.2f})")
            label("$744", 1510, 150, 38, color="0xff8990", enable="between(t,0.00,2.45)")
            label("$746", 1510, 150, 38, color="0xff8990", enable="between(t,2.45,3.15)")
            label("$748", 1510, 150, 38, color="0xff8990", enable="gte(t,3.15)")
        elif shot_id == "scene-007-shot-01":
            box(925, 80, 900, 920, "0x05101a@0.52")
            label("TASK EXECUTED AS CONFIGURED.", 1000, 125, 34, color="0xeaf5ff")
            box(990, 245, 700, 3, "0x5dbbff@0.85")
            label("APPROVAL", 990, 285, 28, color="0xbfe5ff")
            label("ESCALATION", 1460, 285, 28, color="0xbfe5ff")
            box(1050, 350, 3, 180, "0x5dbbff@0.75")
            box(1580, 350, 3, 180, "0x5dbbff@0.75")
            box(1050, 530, 180, 3, "0x5dbbff@0.75")
            box(1400, 530, 180, 3, "0x5dbbff@0.75")
            box(1230, 520, 170, 22, "0xff6c75@0.28")
            label("[ MISSING ]", 1238, 475, 25, color="0xff969c")
            label("SPENDING LIMIT", 1190, 575, 28, color="0xff969c")
            box(990, 720, 700, 3, "0x5dbbff@0.85")
            label("DECISION BOUNDARY", 1130, 760, 34, color="0xd7efff")
        elif shot_id == "scene-008-shot-01":
            mode = "exact_timed_title_card"
            filters.clear()
            box(0, 0, 1920, 1080, "black@1.0")
            label("THE AI DID EXACTLY WHAT IT WAS TOLD.", "(w-text_w)/2", "(h-text_h)/2", 48, enable="between(t,0.00,1.00)")
            label("NO ONE DESIGNED WHEN IT SHOULD STOP.", "(w-text_w)/2", "(h-text_h)/2", 48, enable="between(t,1.00,2.60)")
            label("DECISION DESIGN", "(w-text_w)/2", 440, 66, enable="gte(t,2.60)")
            box(710, 540, 500, 3, "0x58b9ff@0.90", enable="gte(t,2.60)")
            label(
                "DESIGN JUDGMENT BEFORE AUTOMATION.",
                "(w-text_w)/2",
                600,
                30,
                color="0xc9d8e3",
                enable="gte(t,2.60)",
            )
        else:
            for index, value in enumerate(overlays):
                label(value, 100, 100 + index * 60, 30)

        custom_background = shot_id in {"scene-003-shot-01", "scene-008-shot-01"}
        if custom_background:
            inputs = [
                "-f",
                "lavfi",
                "-i",
                f"color=c=black:s={width}x{height}:r={frame_rate}:d={duration_seconds}",
            ]
        else:
            inputs = ["-i", str(asset)]
        command = [
            self.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *inputs,
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r=48000:cl=stereo:d={duration_seconds}",
            "-vf",
            ",".join(filters),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-map_metadata",
            "-1",
            "-metadata",
            "creation_time=1970-01-01T00:00:00Z",
            "-t",
            str(duration_seconds),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(temporary),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        for path in text_paths:
            path.unlink(missing_ok=True)
        if completed.returncode:
            temporary.unlink(missing_ok=True)
            raise RenderingError(
                "Storyboard post-production failed",
                details={"shot_id": shot_id, "stderr": completed.stderr[-2000:]},
            )
        os.replace(temporary, asset)
        result = {
            "applied": True,
            "mode": mode,
            "exact_strings": overlays,
            "overlay_count": len(overlays),
            "asset_hash": file_hash(asset),
        }
        result["binding_hash"] = content_hash(
            {"shot_id": shot_id, "mode": mode, "exact_strings": overlays}
        )
        return result

class RenderingPlatform:
    contract_version = "5.7.2-v2"

    def __init__(
        self,
        *,
        config: PlatformConfig,
        build_root: Path,
        provider_registry: dict[str, VideoProvider],
        cache: RenderCache,
        assembler: PromptAssembler | None = None,
        validator: AssetValidator | None = None,
        quality_gate: RenderQualityGate | None = None,
    ) -> None:
        if not provider_registry:
            raise ValueError("Provider registry must not be empty")
        self.config = config
        self.build_root = build_root
        self.provider_registry = provider_registry
        self.cache = cache
        self.assembler = assembler or PromptAssembler()
        self.validator = validator or AssetValidator()
        self.quality_gate = quality_gate or RenderQualityGate(config.quality_threshold)
        self.postprocessor = StoryboardPostProcessor()
        self._conditioning_cache: dict[str, tuple[str, str]] = {}

    def _provider_name(self, frame: dict[str, Any]) -> str:
        return "runway" if uses_runway(self.config, frame) else "local"

    def _conditioning_reference(
        self, frame: dict[str, Any], provider: str
    ) -> tuple[str | None, str | None]:
        reference_set = os.environ.get(RUNWAY_STORYBOARD_REFERENCES_ENV, "").strip()
        if not reference_set or provider != "runway":
            return None, None
        if reference_set != "full-auto-v11":
            raise ValidationError("Unsupported Runway storyboard reference set")
        shot_id = str(frame["shot_id"])
        relative = FULL_AUTO_V11_REFERENCES.get(shot_id)
        if relative is None:
            return None, None
        recovery = runway_recovery_shots(self.config)
        if shot_id not in recovery:
            raise ValidationError(
                "Storyboard conditioning is only permitted for authorized recovery shots"
            )
        if shot_id in self._conditioning_cache:
            return self._conditioning_cache[shot_id]
        workspace = self.build_root.parents[2]
        source = workspace / relative
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 5_000_000:
            raise ValidationError("Storyboard conditioning image is missing or unsafe")
        raw = source.read_bytes()
        reference = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
        value = (reference, file_hash(source))
        self._conditioning_cache[shot_id] = value
        return value

    def _request(self, frame: dict[str, Any], attempt: int = 1) -> RenderRequest:
        provider = self._provider_name(frame)
        conditioning_image_ref, conditioning_image_hash = self._conditioning_reference(
            frame, provider
        )
        assembled = self.assembler.assemble(
            frame,
            max_utf16_units=1000 if provider == "runway" else None,
        )
        self.assembler.verify(assembled, frame)
        profile = self.config.render_profile()
        provider_version = (
            "local-ffmpeg-v2"
            if provider == "local"
            else "gen4.5-utf16-bounded-prompt-v1"
        )
        cache_key = self.cache.key(
            shot_hash=content_hash(
                {
                    "frame": frame,
                    "conditioning_image_hash": conditioning_image_hash,
                }
                if conditioning_image_hash
                else frame
            ),
            prompt_hash=assembled["prompt_hash"],
            provider=provider,
            provider_version=provider_version,
            profile=self.config.profile,
        )
        return RenderRequest(
            render_task_id=stable_id(
                "render-task", {"build": self.build_root.name, "shot": frame["shot_id"]}
            ),
            shot_id=frame["shot_id"],
            build_id=self.build_root.name,
            cache_key=cache_key,
            attempt=attempt,
            render_profile=self.config.profile,
            assembled_prompt=assembled["prompt"],
            prompt_provenance=assembled["storyboard_hash"],
            duration_seconds=min(
                float(frame["duration_seconds"]), profile.max_duration_seconds
            ),
            width=profile.width,
            height=profile.height,
            frame_rate=profile.frame_rate,
            provider=provider,
            strategy=frame["render_strategy"]["asset_class"],
            visible_action=str(frame.get("visible_action", "")),
            camera_parameters=frame["camera"],
            style_tokens=tuple(frame["style"]),
            negative_style_tokens=tuple(frame["forbidden_style"]),
            conditioning_image_ref=conditioning_image_ref,
        )

    def render_shot(self, frame: dict[str, Any]) -> RenderResult:
        request = self._request(frame)
        cached = self.cache.lookup(request.cache_key)
        cached_post = (cached or {}).get("validation", {}).get(
            "storyboard_postproduction", {}
        )
        expected_overlays = [str(item) for item in frame.get("ui_overlays", [])]
        if cached and cached_post.get("exact_strings") == expected_overlays:
            return RenderResult(
                render_task_id=request.render_task_id,
                shot_id=request.shot_id,
                state=RenderState.CACHED,
                asset_uri=cached["asset_uri"],
                asset_hash=cached["asset_hash"],
                cache_key=request.cache_key,
                provider=request.provider,
                from_cache=True,
                quality_score=float(cached["quality"]["score"]),
                validation=cached["validation"],
                attempts=0,
            )
        provider = self.provider_registry.get(request.provider)
        if provider is None:
            raise RenderingError(
                f"No provider registered for {request.provider}",
                render_task_id=request.render_task_id,
            )
        last_error: RenderingError | None = None
        attempt_limit = 1 if request.provider == "runway" else self.config.max_attempts
        for attempt in range(1, attempt_limit + 1):
            attempt_request = self._request(frame, attempt=attempt)
            try:
                job = provider.submit(attempt_request)
                status = provider.get_status(job)
                state = RenderState(status["state"])
                deadline = time.monotonic() + 45 * 60
                while state in {
                    RenderState.CREATED,
                    RenderState.PLANNED,
                    RenderState.READY,
                    RenderState.QUEUED,
                    RenderState.SUBMITTED,
                    RenderState.RUNNING,
                }:
                    if time.monotonic() >= deadline:
                        raise ProviderTimeoutError(
                            "Provider render exceeded the 45 minute deadline",
                            render_task_id=request.render_task_id,
                        )
                    time.sleep(20 if request.provider == "runway" else 0.05)
                    status = provider.get_status(job)
                    state = RenderState(status["state"])
                if state != RenderState.COMPLETED:
                    terminal_error = RenderingError(
                        f"Provider entered terminal state {state.value}",
                        render_task_id=request.render_task_id,
                        details={
                            key: status[key]
                            for key in ("failure_code", "provider_task_id")
                            if key in status
                        },
                    )
                    terminal_error.failure_class = str(
                        status.get("failure_class", "permanent")
                    )
                    raise terminal_error
                asset = self.build_root / "renders" / f"{request.shot_id}.mp4"
                provider.download(job, asset)
                postproduction = self.postprocessor.apply(
                    asset,
                    frame,
                    width=attempt_request.width,
                    height=attempt_request.height,
                    frame_rate=attempt_request.frame_rate,
                    duration_seconds=attempt_request.duration_seconds,
                )
                validation = self.validator.validate(
                    asset,
                    width=attempt_request.width,
                    height=attempt_request.height,
                    frame_rate=attempt_request.frame_rate,
                    duration_seconds=attempt_request.duration_seconds,
                )
                validation["storyboard_postproduction"] = postproduction
                quality = self.quality_gate.evaluate(validation, frame)
                cached_entry = self.cache.store(
                    request.cache_key, asset, validation, quality
                )
                return RenderResult(
                    render_task_id=request.render_task_id,
                    shot_id=request.shot_id,
                    state=RenderState.COMPLETED,
                    asset_uri=cached_entry["asset_uri"],
                    asset_hash=cached_entry["asset_hash"],
                    cache_key=request.cache_key,
                    provider=request.provider,
                    from_cache=False,
                    quality_score=float(quality["score"]),
                    validation=validation,
                    attempts=attempt,
                )
            except RenderingError as exc:
                last_error = exc
                if exc.failure_class in {"permanent", "budget"}:
                    break
        error = last_error or RenderingError(
            "Unknown rendering failure", render_task_id=request.render_task_id
        )
        return RenderResult(
            render_task_id=request.render_task_id,
            shot_id=request.shot_id,
            state=RenderState.MANUAL_REVIEW,
            asset_uri=None,
            asset_hash=None,
            cache_key=request.cache_key,
            provider=request.provider,
            from_cache=False,
            quality_score=0.0,
            validation={"passed": False},
            attempts=attempt_limit,
            error=error.as_dict(),
        )

    def render_build(
        self,
        storyboard: dict[str, Any],
        *,
        approved: bool,
        runtime_queue: DurableTaskQueue | None = None,
        execution_generation: int = 1,
    ) -> dict[str, Any]:
        if not approved:
            raise StoryboardNotApprovedError("Execution approval is required before rendering")
        frames = sorted(storyboard.get("frames", []), key=lambda frame: frame["shot_id"])
        if not frames:
            raise RenderingError("Storyboard contains no frames")
        recovery_shots = runway_recovery_shots(self.config)
        frame_by_id = {str(frame["shot_id"]): frame for frame in frames}
        unknown_recovery_shots = sorted(recovery_shots.difference(frame_by_id))
        if unknown_recovery_shots:
            raise ValidationError(
                "Runway fidelity recovery contains shots outside the approved storyboard",
                details={"unknown_shots": unknown_recovery_shots},
            )
        invalid_recovery_shots = sorted(
            shot_id
            for shot_id in recovery_shots
            if frame_by_id[shot_id]["render_strategy"]["asset_class"] == "title_card"
        )
        if invalid_recovery_shots:
            raise ValidationError(
                "Deterministic title cards cannot be expanded to Runway recovery",
                details={"invalid_shots": invalid_recovery_shots},
            )
        reference_set = os.environ.get(RUNWAY_STORYBOARD_REFERENCES_ENV, "").strip()
        if reference_set == "full-auto-v11" and recovery_shots != frozenset(
            FULL_AUTO_V11_REFERENCES
        ):
            raise ValidationError(
                "Full Auto v11 recovery must bind the complete approved reference set"
            )
        estimated_runway_credits = runway_credit_estimate(self.config, frames)
        estimate = round(estimated_runway_credits * RUNWAY_CREDIT_USD, 2)
        if estimated_runway_credits > self.config.max_runway_credits:
            raise BudgetExhaustedError(
                "Estimated Runway credits exceed the configured credit limit",
                details={
                    "estimated_runway_credits": estimated_runway_credits,
                    "max_runway_credits": self.config.max_runway_credits,
                },
            )
        if self.config.estimate_before_submission and estimate > self.config.budget_usd:
            raise BudgetExhaustedError(
                "Estimated provider cost exceeds build budget",
                details={"estimated_usd": estimate, "budget_usd": self.config.budget_usd},
            )
        requests = {frame["shot_id"]: self._request(frame) for frame in frames}
        if runtime_queue is not None:
            runtime_queue.initialize(
                [
                    {
                        "render_task_id": request.render_task_id,
                        "shot_id": request.shot_id,
                        "provider": request.provider,
                        "cache_key": request.cache_key,
                        "estimated_cost_usd": (
                            math.ceil(request.duration_seconds)
                            * RUNWAY_GEN45_CREDITS_PER_SECOND
                            * RUNWAY_CREDIT_USD
                            if request.provider == "runway"
                            else 0.0
                        ),
                    }
                    for request in requests.values()
                ],
                generation=execution_generation,
            )

        def execute_frame(frame: dict[str, Any]) -> RenderResult:
            request = requests[frame["shot_id"]]
            claim: dict[str, Any] | None = None
            if runtime_queue is not None:
                claim = runtime_queue.claim(
                    request.render_task_id,
                    worker_id=threading.current_thread().name,
                )
                if claim["outcome"] == "DEFERRED":
                    error = RenderingError(
                        f"Runtime dispatch deferred: {claim['reason']}",
                        render_task_id=request.render_task_id,
                    )
                    error.failure_class = "capacity"
                    raise error
            try:
                result = self.render_shot(frame)
            except Exception as exc:
                if (
                    runtime_queue is not None
                    and claim is not None
                    and claim["outcome"] == "CLAIMED"
                ):
                    runtime_queue.complete(
                        request.render_task_id,
                        lease_id=str(claim["lease_id"]),
                        result={
                            "render_task_id": request.render_task_id,
                            "shot_id": request.shot_id,
                            "state": "FAILED",
                            "error": {
                                "code": getattr(exc, "code", "UNEXPECTED_RENDER_ERROR"),
                                "message": str(exc),
                            },
                        },
                    )
                raise
            if (
                runtime_queue is not None
                and claim is not None
                and claim["outcome"] == "CLAIMED"
            ):
                runtime_queue.complete(
                    request.render_task_id,
                    lease_id=str(claim["lease_id"]),
                    result=result.as_dict(),
                )
            return result

        results: list[RenderResult] = []
        provider_names = {request.provider for request in requests.values()}
        provider_worker_limit = min(
            self.config.provider_parallel_limits.get(
                provider, self.config.max_in_flight_tasks
            )
            for provider in provider_names
        )
        worker_limit = min(
            self.config.max_parallel_shots,
            self.config.max_in_flight_tasks,
            provider_worker_limit,
        )
        with ThreadPoolExecutor(max_workers=worker_limit) as executor:
            futures = {executor.submit(execute_frame, frame): frame for frame in frames}
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except RenderingError as exc:
                    frame = futures[future]
                    request = self._request(frame)
                    results.append(
                        RenderResult(
                            render_task_id=request.render_task_id,
                            shot_id=request.shot_id,
                            state=RenderState.MANUAL_REVIEW,
                            asset_uri=None,
                            asset_hash=None,
                            cache_key=request.cache_key,
                            provider=request.provider,
                            from_cache=False,
                            quality_score=0.0,
                            validation={"passed": False},
                            error=exc.as_dict(),
                        )
                    )
        results.sort(key=lambda result: result.shot_id)
        all_ready = all(
            result.state in {RenderState.COMPLETED, RenderState.CACHED} for result in results
        )
        cached_count = sum(result.from_cache for result in results)
        value = {
            "schema_version": "2.0",
            "contract_version": self.contract_version,
            "build_id": self.build_root.name,
            "profile": self.config.profile,
            "all_ready": all_ready,
            "state": "READY" if all_ready else "MANUAL_REVIEW",
            "results": [result.as_dict() for result in results],
            "metrics": {
                "shots_total": len(results),
                "shots_ready": sum(
                    result.state in {RenderState.COMPLETED, RenderState.CACHED}
                    for result in results
                ),
                "shots_cached": cached_count,
                "shots_manual_review": sum(
                    result.state == RenderState.MANUAL_REVIEW for result in results
                ),
                "cache_hit_rate": cached_count / len(results),
                "quality_pass_rate": sum(
                    result.quality_score >= self.config.quality_threshold for result in results
                )
                / len(results),
                "estimated_provider_cost_usd": estimate,
                "estimated_runway_credits": estimated_runway_credits,
                "runway_credit_limit": self.config.max_runway_credits,
                "planned_runway_scope": self.config.runway_scope,
                "runway_recovery_shots": sorted(recovery_shots),
                "runway_recovery_reason": (
                    os.environ.get(RUNWAY_RECOVERY_REASON_ENV, "").strip()
                    if recovery_shots
                    else None
                ),
                "storyboard_reference_set": reference_set or None,
                "runtime_worker_limit": worker_limit,
            },
        }
        if runtime_queue is not None:
            value["runtime_queue"] = runtime_queue.snapshot()
        return value

    def cancel_build(self, build_id: str, scope: str = "all") -> dict[str, Any]:
        return {"build_id": build_id, "scope": scope, "accepted": True}

    def get_build_status(self, build_id: str) -> dict[str, Any]:
        manifest = self.build_root / "render-manifest.json"
        return read_json(manifest) if manifest.exists() else {"build_id": build_id, "state": "UNKNOWN"}

    def health_check(self) -> dict[str, Any]:
        return {
            name: provider.health_check()
            for name, provider in sorted(self.provider_registry.items())
        }
