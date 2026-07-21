"""Runway API adapter; all provider-specific HTTP semantics live here."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ..errors import ProviderSubmissionError, ProviderTimeoutError, ValidationError
from ..models import ProviderJobRef, RenderRequest, RenderState
from ..util import atomic_write_json, canonical_json, content_hash, file_hash, read_json


RUNWAY_API_VERSION = "2024-11-06"
RUNWAY_MODEL = "gen4.5"
RUNWAY_NATIVE_RATIOS = {
    "landscape": ("1280:720", 1280, 720),
    "portrait": ("720:1280", 720, 1280),
}

STATUS_MAP = {
    "PENDING": RenderState.SUBMITTED,
    "QUEUED": RenderState.QUEUED,
    "THROTTLED": RenderState.QUEUED,
    "RUNNING": RenderState.RUNNING,
    "PROCESSING": RenderState.RUNNING,
    "SUCCEEDED": RenderState.COMPLETED,
    "COMPLETE": RenderState.COMPLETED,
    "COMPLETED": RenderState.COMPLETED,
    "FAILED": RenderState.FAILED,
    "CANCELED": RenderState.CANCELLED,
    "CANCELLED": RenderState.CANCELLED,
}

RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}
PERMANENT_FAILURE_PREFIXES = (
    "SAFETY.",
    "INPUT_PREPROCESSING.SAFETY.",
    "ASSET.INVALID",
)
RETRYABLE_FAILURE_PREFIXES = (
    "INTERNAL",
    "INPUT_PREPROCESSING.INTERNAL",
    "THIRD_PARTY.UNAVAILABLE",
)


class RunwayProvider:
    provider_id = "runway"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_id: str,
        timeout_seconds: int = 30,
        state_path: Path | None = None,
        opener: Callable[..., Any] | None = None,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
    ) -> None:
        if not base_url or not api_key or not model_id:
            raise ValidationError("Runway adapter configuration is incomplete")
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValidationError("RUNWAY_BASE_URL must be an HTTPS origin")
        if model_id != RUNWAY_MODEL:
            raise ValidationError(
                f"RUNWAY_MODEL_GEN45 must be {RUNWAY_MODEL!r} for this adapter contract"
            )
        if timeout_seconds < 1:
            raise ValidationError("Runway timeout must be positive")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_id = model_id
        self.timeout_seconds = timeout_seconds
        self.state_path = state_path
        self.ffmpeg_binary = ffmpeg_binary
        self.ffprobe_binary = ffprobe_binary
        self._opener = opener or urllib.request.urlopen
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._load_state()

    def _load_state(self) -> None:
        if self.state_path is None or not self.state_path.exists():
            return
        try:
            value = read_json(self.state_path)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError("Unable to read Runway idempotency state") from exc
        jobs = value.get("jobs") if isinstance(value, dict) else None
        if not isinstance(jobs, dict) or not all(
            isinstance(key, str) and isinstance(record, dict)
            for key, record in jobs.items()
        ):
            raise ValidationError("Runway idempotency state is invalid")
        self._jobs = jobs

    def _persist_state(self) -> None:
        if self.state_path is not None:
            atomic_write_json(
                self.state_path,
                {"schema_version": "1.0", "jobs": self._jobs},
            )

    @staticmethod
    def _idempotency_key(request: RenderRequest) -> str:
        return request.cache_key

    @staticmethod
    def _prompt_utf16_length(prompt: str) -> int:
        return len(prompt.encode("utf-16-le")) // 2

    @staticmethod
    def _ratio(width: int, height: int) -> tuple[str, int, int]:
        if width * 9 == height * 16:
            return RUNWAY_NATIVE_RATIOS["landscape"]
        if height * 9 == width * 16:
            return RUNWAY_NATIVE_RATIOS["portrait"]
        raise ValidationError("Gen-4.5 requires a 16:9 or 9:16 render profile")

    @staticmethod
    def _conditioning_image(value: str) -> str:
        if value.startswith("data:image/"):
            return value
        parsed = urlsplit(value)
        if parsed.scheme == "https" and parsed.netloc:
            return value
        raise ValidationError(
            "Runway conditioning images must use an HTTPS URL or image data URI"
        )

    def _duration(self, request: RenderRequest) -> int:
        requested = float(request.duration_seconds)
        if not requested.is_integer():
            raise ValidationError("Gen-4.5 duration must be a whole number of seconds")
        profile_max = 10 if request.render_profile == "final" else 5
        duration = min(int(requested), profile_max)
        if not 2 <= duration <= 10:
            raise ValidationError("Gen-4.5 duration must be between 2 and 10 seconds")
        return duration

    def map_request(self, request: RenderRequest) -> dict[str, Any]:
        """Map without mutating the approved prompt or adding unsupported fields."""
        if not request.prompt_provenance.startswith("sha256:"):
            raise ValidationError("Assembled prompt provenance is required")
        if not request.assembled_prompt:
            raise ValidationError("Assembled prompt must not be empty")
        if self._prompt_utf16_length(request.assembled_prompt) > 1000:
            raise ValidationError("Assembled prompt exceeds Runway's 1000 character limit")
        ratio, _native_width, _native_height = self._ratio(
            request.width, request.height
        )
        payload: dict[str, Any] = {
            "model": self.model_id,
            "promptText": request.assembled_prompt,
            "ratio": ratio,
            "duration": self._duration(request),
            "seed": int(hashlib.sha256(request.cache_key.encode()).hexdigest()[:8], 16),
        }
        if request.conditioning_image_ref is not None:
            payload["promptImage"] = self._conditioning_image(
                request.conditioning_image_ref
            )
        return payload

    @staticmethod
    def submission_path(_request: RenderRequest) -> str:
        # Gen-4.5 uses the image-to-video operation for both modes. Text-only
        # generation omits promptImage rather than changing the endpoint.
        return "/v1/image_to_video"

    @staticmethod
    def _http_failure(
        status: int,
        message: str,
        *,
        provider_error: str | None = None,
    ) -> ProviderSubmissionError:
        details: dict[str, Any] = {
            "status": status,
            "retryable": status in RETRYABLE_HTTP_STATUSES,
        }
        if provider_error:
            details["provider_error"] = provider_error
        error = ProviderSubmissionError(
            message,
            details=details,
        )
        error.failure_class = (
            "transient" if status in RETRYABLE_HTTP_STATUSES else "permanent"
        )
        return error

    @staticmethod
    def _safe_provider_error(body: bytes) -> str | None:
        """Return only Runway's documented human-readable error member."""
        try:
            value = json.loads(body[:16_384])
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        provider_error = value.get("error") if isinstance(value, dict) else None
        if isinstance(provider_error, str) and provider_error.strip():
            return provider_error.strip()[:500]
        return None

    def _api_request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: int | None = None,
        ambiguous_write: bool = False,
    ) -> tuple[bytes, dict[str, str]]:
        body = canonical_json(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Runway-Version": RUNWAY_API_VERSION,
                "User-Agent": "insynergy-cinematic/2.0",
            },
        )
        try:
            with self._opener(
                request, timeout=timeout or self.timeout_seconds
            ) as response:
                return response.read(), dict(response.headers)
        except urllib.error.HTTPError as exc:
            provider_error = self._safe_provider_error(exc.read(16_384))
            failure = self._http_failure(
                exc.code,
                f"Runway HTTP error {exc.code}",
                provider_error=provider_error,
            )
            exc.close()
            raise failure from exc
        except (TimeoutError, socket.timeout) as exc:
            error = ProviderTimeoutError(
                "Runway operation timed out",
                details={"submission_outcome_unknown": ambiguous_write},
            )
            if ambiguous_write:
                error.failure_class = "permanent"
            raise error from exc
        except urllib.error.URLError as exc:
            is_timeout = isinstance(exc.reason, (TimeoutError, socket.timeout))
            error: ProviderSubmissionError | ProviderTimeoutError
            if is_timeout:
                error = ProviderTimeoutError(
                    "Runway operation timed out",
                    details={"submission_outcome_unknown": ambiguous_write},
                )
            else:
                error = ProviderSubmissionError(
                    "Runway connection failed",
                    details={"submission_outcome_unknown": ambiguous_write},
                )
            if ambiguous_write:
                error.failure_class = "permanent"
            raise error from exc

    @staticmethod
    def _json_object(raw: bytes, operation: str) -> dict[str, Any]:
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ProviderSubmissionError(
                f"Runway returned invalid JSON for {operation}"
            ) from exc
        if not isinstance(value, dict):
            raise ProviderSubmissionError(
                f"Runway returned an invalid response for {operation}"
            )
        return value

    def _record_for_task(self, task_id: str) -> dict[str, Any] | None:
        return next(
            (
                record
                for record in self._jobs.values()
                if record.get("provider_task_id") == task_id
            ),
            None,
        )

    def submit(self, request: RenderRequest) -> ProviderJobRef:
        payload = self.map_request(request)
        payload_hash = content_hash(payload)
        idempotency_key = self._idempotency_key(request)
        with self._lock:
            existing = self._jobs.get(idempotency_key)
            if existing is not None:
                if existing.get("payload_hash") != payload_hash:
                    raise ValidationError(
                        "Runway idempotency key resolved to a different payload"
                    )
                previous_attempt = int(existing.get("attempt", 1))
                retryable_failure = (
                    existing.get("terminal_failure_class") == "transient"
                )
                if not (retryable_failure and request.attempt > previous_attempt):
                    return ProviderJobRef(
                        provider=self.provider_id,
                        provider_task_id=str(existing["provider_task_id"]),
                        idempotency_key=idempotency_key,
                        state=RenderState.SUBMITTED,
                    )
            raw, _headers = self._api_request(
                "POST",
                self.submission_path(request),
                payload,
                ambiguous_write=True,
            )
            value = self._json_object(raw, "submission")
            task_id = str(value.get("id") or "")
            if not task_id:
                raise ProviderSubmissionError("Runway response contained no task id")
            _ratio, native_width, native_height = self._ratio(
                request.width, request.height
            )
            self._jobs[idempotency_key] = {
                "provider_task_id": task_id,
                "payload_hash": payload_hash,
                "attempt": request.attempt,
                "target_width": request.width,
                "target_height": request.height,
                "target_frame_rate": request.frame_rate,
                "duration_seconds": self._duration(request),
                "native_width": native_width,
                "native_height": native_height,
            }
            try:
                self._persist_state()
            except OSError as exc:
                error = ProviderSubmissionError(
                    "Runway task was accepted but idempotency state could not be persisted",
                    details={"submission_outcome_unknown": False},
                )
                error.failure_class = "permanent"
                raise error from exc
        return ProviderJobRef(
            provider=self.provider_id,
            provider_task_id=task_id,
            idempotency_key=idempotency_key,
            state=RenderState.SUBMITTED,
        )

    @staticmethod
    def _task_failure_class(failure_code: Any) -> str:
        code = str(failure_code or "").upper()
        if any(code.startswith(prefix) for prefix in PERMANENT_FAILURE_PREFIXES):
            return "permanent"
        if not code or any(
            code.startswith(prefix) for prefix in RETRYABLE_FAILURE_PREFIXES
        ):
            return "transient"
        return "permanent"

    def get_status(self, job_ref: ProviderJobRef) -> dict[str, Any]:
        raw, _headers = self._api_request(
            "GET", f"/v1/tasks/{job_ref.provider_task_id}"
        )
        value = self._json_object(raw, "task status")
        returned_id = str(value.get("id") or "")
        if returned_id and returned_id != job_ref.provider_task_id:
            error = ProviderSubmissionError("Runway returned a mismatched task id")
            error.failure_class = "permanent"
            raise error
        raw_state = str(value.get("status") or "").upper()
        if raw_state not in STATUS_MAP:
            error = ProviderSubmissionError(
                "Runway returned an unknown task status",
                details={"status": raw_state or "MISSING"},
            )
            error.failure_class = "permanent"
            raise error
        result: dict[str, Any] = {
            "state": STATUS_MAP.get(raw_state, RenderState.RUNNING).value,
            "provider_task_id": job_ref.provider_task_id,
        }
        if isinstance(value.get("progress"), (int, float)):
            result["progress"] = float(value["progress"])
        output = value.get("output")
        if isinstance(output, list) and output and isinstance(output[0], str):
            result["asset_url"] = output[0]
        if raw_state == "FAILED":
            failure_code = value.get("failureCode")
            result["failure_code"] = str(failure_code or "INTERNAL")
            result["failure_class"] = self._task_failure_class(failure_code)
            with self._lock:
                record = self._record_for_task(job_ref.provider_task_id)
                if record is not None and record.get(
                    "terminal_failure_class"
                ) != result["failure_class"]:
                    record["terminal_failure_class"] = result["failure_class"]
                    try:
                        self._persist_state()
                    except OSError as exc:
                        error = ProviderSubmissionError(
                            "Runway failure state could not be persisted",
                            details={
                                "provider_task_id": job_ref.provider_task_id,
                            },
                        )
                        error.failure_class = "permanent"
                        raise error from exc
        return result

    def _download_provider_asset(
        self, url: str, destination: Path, *, timeout: int = 120
    ) -> dict[str, Any]:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.netloc:
            error = ProviderSubmissionError("Runway returned an unsafe asset URL")
            error.failure_class = "permanent"
            raise error
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "video/mp4,application/octet-stream",
                "User-Agent": "insynergy-cinematic/2.0",
            },
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.unlink(missing_ok=True)
        digest = hashlib.sha256()
        size = 0
        try:
            with self._opener(request, timeout=timeout) as response:
                headers = dict(response.headers)
                with destination.open("wb") as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
        except urllib.error.HTTPError as exc:
            destination.unlink(missing_ok=True)
            failure = self._http_failure(
                exc.code, f"Runway asset HTTP error {exc.code}"
            )
            exc.close()
            raise failure from exc
        except (TimeoutError, socket.timeout) as exc:
            destination.unlink(missing_ok=True)
            raise ProviderTimeoutError("Runway asset download timed out") from exc
        except urllib.error.URLError as exc:
            destination.unlink(missing_ok=True)
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise ProviderTimeoutError(
                    "Runway asset download timed out"
                ) from exc
            raise ProviderSubmissionError(
                "Runway asset connection failed"
            ) from exc
        if size == 0:
            destination.unlink(missing_ok=True)
            raise ProviderSubmissionError("Runway asset download was empty")
        reported_size = headers.get("Content-Length") or headers.get("content-length")
        if reported_size is not None:
            try:
                expected_size = int(reported_size)
            except ValueError as exc:
                destination.unlink(missing_ok=True)
                raise ProviderSubmissionError(
                    "Runway asset returned an invalid Content-Length"
                ) from exc
            if expected_size != size:
                destination.unlink(missing_ok=True)
                raise ProviderSubmissionError("Runway asset size mismatch")
        actual_hash = "sha256:" + digest.hexdigest()
        claimed = headers.get("X-Checksum-Sha256") or headers.get(
            "x-checksum-sha256"
        )
        if claimed:
            expected_hash = claimed.lower()
            if not expected_hash.startswith("sha256:"):
                expected_hash = f"sha256:{expected_hash}"
            if actual_hash != expected_hash:
                destination.unlink(missing_ok=True)
                raise ProviderSubmissionError("Runway asset checksum mismatch")
        return {
            "provider_asset_hash": actual_hash,
            "provider_size_bytes": size,
        }

    def _probe_asset(self, asset: Path) -> dict[str, Any]:
        if not shutil.which(self.ffprobe_binary):
            error = ProviderSubmissionError(
                "ffprobe is required to normalize Runway output"
            )
            error.failure_class = "permanent"
            raise error
        completed = subprocess.run(
            [
                self.ffprobe_binary,
                "-v",
                "error",
                "-show_streams",
                "-of",
                "json",
                str(asset),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode:
            raise ProviderSubmissionError("Downloaded Runway asset is not decodable")
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ProviderSubmissionError("ffprobe returned invalid JSON") from exc
        streams = value.get("streams", [])
        video = next(
            (
                stream
                for stream in streams
                if stream.get("codec_type") == "video"
            ),
            None,
        )
        if not isinstance(video, dict):
            raise ProviderSubmissionError("Downloaded Runway asset contains no video")
        rate_text = str(
            video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"
        )
        numerator, separator, denominator = rate_text.partition("/")
        try:
            rate_denominator = float(denominator or 1) if separator else 1.0
            rate = float(numerator or 0) / rate_denominator
        except (ValueError, ZeroDivisionError) as exc:
            raise ProviderSubmissionError(
                "Downloaded Runway asset has an invalid frame rate"
            ) from exc
        return {
            "width": int(video.get("width", 0)),
            "height": int(video.get("height", 0)),
            "frame_rate": rate,
            "has_audio": any(
                stream.get("codec_type") == "audio" for stream in streams
            ),
        }

    def _normalize_asset(
        self, source: Path, destination: Path, record: dict[str, Any]
    ) -> None:
        probe = self._probe_asset(source)
        target_width = int(record["target_width"])
        target_height = int(record["target_height"])
        target_rate = int(record["target_frame_rate"])
        if (
            probe["width"] == target_width
            and probe["height"] == target_height
            and abs(probe["frame_rate"] - target_rate) < 0.01
            and probe["has_audio"]
        ):
            os.replace(source, destination)
            return
        if not shutil.which(self.ffmpeg_binary):
            error = ProviderSubmissionError(
                "ffmpeg is required to normalize Runway output"
            )
            error.failure_class = "permanent"
            raise error
        temporary = destination.with_suffix(".normalizing.mp4")
        temporary.unlink(missing_ok=True)
        command = [
            self.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
        ]
        if not probe["has_audio"]:
            command.extend(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    f"anullsrc=r=48000:cl=stereo:d={record['duration_seconds']}",
                ]
            )
        command.extend(
            [
                "-map",
                "0:v:0",
                "-map",
                "0:a:0" if probe["has_audio"] else "1:a:0",
                "-vf",
                f"scale={target_width}:{target_height}:flags=lanczos,fps={target_rate}",
                "-map_metadata",
                "-1",
                "-metadata",
                "creation_time=1970-01-01T00:00:00Z",
                "-c:v",
                "libx264",
                "-preset",
                "slow",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-movflags",
                "+faststart",
            ]
        )
        if not probe["has_audio"]:
            command.append("-shortest")
        command.append(str(temporary))
        completed = subprocess.run(
            command, capture_output=True, text=True, check=False
        )
        if completed.returncode:
            temporary.unlink(missing_ok=True)
            error = ProviderSubmissionError(
                "Runway output normalization failed",
                details={"stderr": completed.stderr[-1000:]},
            )
            error.failure_class = "permanent"
            raise error
        normalized = self._probe_asset(temporary)
        if (
            normalized["width"] != target_width
            or normalized["height"] != target_height
            or abs(normalized["frame_rate"] - target_rate) >= 0.01
            or not normalized["has_audio"]
        ):
            temporary.unlink(missing_ok=True)
            error = ProviderSubmissionError(
                "Normalized Runway output does not match the render profile"
            )
            error.failure_class = "permanent"
            raise error
        os.replace(temporary, destination)
        source.unlink(missing_ok=True)

    def download(self, job_ref: ProviderJobRef, destination: Path) -> dict[str, Any]:
        if destination.is_file() and destination.stat().st_size > 0:
            return {
                "asset_uri": str(destination.resolve()),
                "asset_hash": file_hash(destination),
                "size_bytes": destination.stat().st_size,
                "idempotent_replay": True,
            }
        status = self.get_status(job_ref)
        if status["state"] != RenderState.COMPLETED.value:
            error = ProviderSubmissionError(
                "Runway task is not complete and cannot be downloaded",
                details={"state": status["state"]},
            )
            error.failure_class = "permanent"
            raise error
        asset_url = status.get("asset_url")
        if not isinstance(asset_url, str) or not asset_url:
            raise ProviderSubmissionError("Completed Runway task contained no output URL")
        record = self._record_for_task(job_ref.provider_task_id)
        if record is None:
            error = ProviderSubmissionError(
                "Runway task metadata is unavailable; refusing unsafe download replay"
            )
            error.failure_class = "permanent"
            raise error
        source = destination.with_suffix(".provider.partial.mp4")
        transport = self._download_provider_asset(asset_url, source)
        try:
            self._normalize_asset(source, destination, record)
        finally:
            source.unlink(missing_ok=True)
        return {
            "asset_uri": str(destination.resolve()),
            "asset_hash": file_hash(destination),
            "size_bytes": destination.stat().st_size,
            **transport,
        }

    def cancel(self, job_ref: ProviderJobRef) -> dict[str, Any]:
        status = self.get_status(job_ref)
        if status["state"] in {
            RenderState.COMPLETED.value,
            RenderState.FAILED.value,
            RenderState.CANCELLED.value,
        }:
            return {
                "outcome": "ALREADY_TERMINAL",
                "observed_state": status["state"],
            }
        try:
            self._api_request(
                "DELETE",
                f"/v1/tasks/{job_ref.provider_task_id}",
                ambiguous_write=True,
            )
        except ProviderSubmissionError as exc:
            if exc.details.get("status") == 404:
                return {
                    "outcome": "ALREADY_TERMINAL",
                    "observed_state": "NOT_FOUND",
                }
            raise
        return {"outcome": "CANCELLED", "observed_state": "CANCELLED"}

    def health_check(self) -> dict[str, Any]:
        start = time.monotonic()
        try:
            raw, _headers = self._api_request(
                "GET", "/v1/organization", timeout=5
            )
            self._json_object(raw, "organization health check")
        except (ProviderSubmissionError, ProviderTimeoutError) as exc:
            status = exc.details.get("status")
            detail = "auth_failed" if status in {401, 403} else exc.code.lower()
            return {"status": "UNAVAILABLE", "detail": detail}
        return {
            "status": "HEALTHY",
            "latency_seconds": round(time.monotonic() - start, 3),
        }
