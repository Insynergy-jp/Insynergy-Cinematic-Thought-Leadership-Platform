"""Deterministic local provider used for offline builds and contract tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import textwrap
from dataclasses import asdict
from pathlib import Path

from ..errors import ProviderSubmissionError
from ..models import ProviderJobRef, RenderRequest, RenderState
from ..util import atomic_write_json, atomic_write_text, file_hash, stable_id


class LocalVideoProvider:
    provider_id = "local"

    def __init__(self, root: Path, *, ffmpeg_binary: str = "ffmpeg") -> None:
        self.root = root
        self.ffmpeg_binary = ffmpeg_binary
        self._lock = threading.Lock()

    def _job_path(self, task_id: str) -> Path:
        return self.root / "jobs" / f"{task_id}.json"

    def submit(self, request: RenderRequest) -> ProviderJobRef:
        if not shutil.which(self.ffmpeg_binary):
            raise ProviderSubmissionError("ffmpeg is required by the local provider")
        provider_task_id = stable_id(
            "local-job", {"cache_key": request.cache_key, "attempt": request.attempt}
        )
        path = self._job_path(provider_task_id)
        with self._lock:
            if not path.exists():
                atomic_write_json(
                    path,
                    {
                        "provider_task_id": provider_task_id,
                        "state": RenderState.SUBMITTED.value,
                        "request": asdict(request),
                    },
                )
        return ProviderJobRef(
            provider=self.provider_id,
            provider_task_id=provider_task_id,
            idempotency_key=stable_id(
                "idem", {"cache_key": request.cache_key, "attempt": request.attempt}
            ),
            state=RenderState.SUBMITTED,
        )

    def get_status(self, job_ref: ProviderJobRef) -> dict:
        path = self._job_path(job_ref.provider_task_id)
        if not path.exists():
            return {"state": RenderState.FAILED.value, "detail": "job_not_found"}
        with path.open(encoding="utf-8") as handle:
            job = json.load(handle)
        state = job["state"]
        if state == RenderState.SUBMITTED.value:
            state = RenderState.COMPLETED.value
        return {"state": state, "provider_task_id": job_ref.provider_task_id}

    @staticmethod
    def _font_file() -> str:
        if shutil.which("fc-match"):
            matched = subprocess.run(
                ["fc-match", "-f", "%{file}", "DejaVu Sans"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            if matched and Path(matched).is_file():
                return matched
        for candidate in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
        ):
            if Path(candidate).is_file():
                return candidate
        raise ProviderSubmissionError("A TrueType font is required by the local provider")

    @staticmethod
    def _filter_path(path: Path | str) -> str:
        return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")

    @staticmethod
    def _display_lines(request: dict) -> list[str]:
        value = str(request.get("visible_action") or "Decision authority becomes visible.").strip()
        marker = "title card reads:"
        if marker in value.casefold():
            value = value[value.casefold().index(marker) + len(marker) :].strip()
        return textwrap.wrap(value, width=44, break_long_words=False, break_on_hyphens=False)[:4]

    def download(self, job_ref: ProviderJobRef, destination: Path) -> dict:
        path = self._job_path(job_ref.provider_task_id)
        with path.open(encoding="utf-8") as handle:
            job = json.load(handle)
        request = job["request"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".partial.mp4")
        temporary.unlink(missing_ok=True)
        display_lines = self._display_lines(request)
        text_paths = [
            destination.with_suffix(f".display-{index:02d}.txt")
            for index in range(1, len(display_lines) + 1)
        ]
        kicker_path = destination.with_suffix(".kicker.txt")
        for text_path, line in zip(text_paths, display_lines):
            atomic_write_text(text_path, line)
        atomic_write_text(
            kicker_path,
            "INSYNERGY  /  " + str(request["strategy"]).replace("_", " ").upper() + "\n",
        )
        colors = {
            "runway_video": "0x263547",
            "animated_still": "0x34495e",
            "motion_graphics": "0x1f4f5f",
            "title_card": "0x151b24",
            "narration": "0x202020",
        }
        color = colors.get(request["strategy"], "0x263547")
        duration = max(0.5, float(request["duration_seconds"]))
        font_file = self._filter_path(self._font_file())
        kicker_file = self._filter_path(kicker_path)
        fade_out_start = max(0.1, duration - 0.45)
        video_filters = [
            "drawgrid=width=96:height=96:thickness=1:color=white@0.045",
            "drawbox=x=72:y=70:w=12:h=ih-140:color=0x26d9c7@0.92:t=fill",
            "drawbox=x=104:y=70:w=iw-176:h=2:color=white@0.22:t=fill",
            "drawbox=x=104:y=ih-102:w=iw-176:h=2:color=white@0.12:t=fill",
            (
                f"drawtext=fontfile='{font_file}':textfile='{kicker_file}':reload=0:"
                "fontcolor=0x70f2e3:fontsize=24:x=112:y=100"
            ),
        ]
        line_height = 56
        line_count = len(text_paths)
        for index, text_path in enumerate(text_paths):
            display_file = self._filter_path(text_path)
            y_offset = index * line_height - ((line_count - 1) * line_height // 2)
            video_filters.append(
                f"drawtext=fontfile='{font_file}':textfile='{display_file}':reload=0:"
                f"fontcolor=white:fontsize=38:x=112:y=(h-text_h)/2+{y_offset}:"
                "shadowcolor=black@0.65:shadowx=2:shadowy=2"
            )
        video_filters.extend(
            (
                (
                    f"drawtext=fontfile='{font_file}':text='DECISION DESIGN':"
                    "fontcolor=white@0.52:fontsize=18:x=112:y=h-74"
                ),
                "fade=t=in:st=0:d=0.45",
                f"fade=t=out:st={fade_out_start}:d=0.45",
            )
        )
        video_filter = ",".join(video_filters)
        command = [
            self.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s={request['width']}x{request['height']}:r={request['frame_rate']}:d={duration}",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r=48000:cl=stereo:d={duration}",
            "-vf",
            video_filter,
            "-map_metadata",
            "-1",
            "-metadata",
            "creation_time=1970-01-01T00:00:00Z",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            str(temporary),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        for text_path in text_paths:
            text_path.unlink(missing_ok=True)
        kicker_path.unlink(missing_ok=True)
        if completed.returncode:
            temporary.unlink(missing_ok=True)
            raise ProviderSubmissionError(
                "Local render failed",
                render_task_id=request["render_task_id"],
                details={"stderr": completed.stderr[-2000:]},
            )
        os.replace(temporary, destination)
        job["state"] = RenderState.COMPLETED.value
        atomic_write_json(path, job)
        return {
            "asset_uri": str(destination.resolve()),
            "asset_hash": file_hash(destination),
            "size_bytes": destination.stat().st_size,
        }

    def cancel(self, job_ref: ProviderJobRef) -> dict:
        path = self._job_path(job_ref.provider_task_id)
        if not path.exists():
            return {"outcome": "ALREADY_TERMINAL", "observed_state": "NOT_FOUND"}
        with path.open(encoding="utf-8") as handle:
            job = json.load(handle)
        if job["state"] == RenderState.COMPLETED.value:
            return {"outcome": "ALREADY_TERMINAL", "observed_state": job["state"]}
        job["state"] = RenderState.CANCELLED.value
        atomic_write_json(path, job)
        return {"outcome": "CANCELLED", "observed_state": job["state"]}

    def health_check(self) -> dict:
        return {
            "status": "HEALTHY" if shutil.which(self.ffmpeg_binary) else "UNAVAILABLE",
            "detail": "ffmpeg_available" if shutil.which(self.ffmpeg_binary) else "ffmpeg_missing",
        }
