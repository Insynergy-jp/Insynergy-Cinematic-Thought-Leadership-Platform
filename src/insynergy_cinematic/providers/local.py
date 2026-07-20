"""Deterministic local provider used for offline builds and contract tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from dataclasses import asdict
from pathlib import Path

from ..errors import ProviderSubmissionError
from ..models import ProviderJobRef, RenderRequest, RenderState
from ..util import atomic_write_json, file_hash, stable_id


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

    def download(self, job_ref: ProviderJobRef, destination: Path) -> dict:
        path = self._job_path(job_ref.provider_task_id)
        with path.open(encoding="utf-8") as handle:
            job = json.load(handle)
        request = job["request"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".partial.mp4")
        temporary.unlink(missing_ok=True)
        colors = {
            "runway_video": "0x263547",
            "animated_still": "0x34495e",
            "motion_graphics": "0x1f4f5f",
            "title_card": "0x151b24",
            "narration": "0x202020",
        }
        color = colors.get(request["strategy"], "0x263547")
        duration = max(0.5, float(request["duration_seconds"]))
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
