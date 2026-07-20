"""The sole adapter containing Runway-specific HTTP semantics."""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ..errors import ProviderSubmissionError, ProviderTimeoutError, ValidationError
from ..models import ProviderJobRef, RenderRequest, RenderState
from ..util import canonical_json, file_hash, stable_id


STATUS_MAP = {
    "PENDING": RenderState.SUBMITTED,
    "QUEUED": RenderState.QUEUED,
    "RUNNING": RenderState.RUNNING,
    "PROCESSING": RenderState.RUNNING,
    "SUCCEEDED": RenderState.COMPLETED,
    "COMPLETED": RenderState.COMPLETED,
    "FAILED": RenderState.FAILED,
    "CANCELLED": RenderState.CANCELLED,
}


class RunwayProvider:
    provider_id = "runway"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_id: str,
        timeout_seconds: int = 30,
    ) -> None:
        if not base_url or not api_key or not model_id:
            raise ValidationError("Runway adapter configuration is incomplete")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_id = model_id
        self.timeout_seconds = timeout_seconds

    def _request(
        self, method: str, path: str, payload: dict | None = None, timeout: int | None = None
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
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout_seconds) as response:
                return response.read(), dict(response.headers)
        except TimeoutError as exc:
            raise ProviderTimeoutError("Runway operation timed out") from exc
        except urllib.error.HTTPError as exc:
            detail = exc.read(1024).decode("utf-8", errors="replace")
            failure = "permanent" if exc.code in {400, 401, 403, 404} else "transient"
            error = ProviderSubmissionError(
                f"Runway HTTP error {exc.code}", details={"status": exc.code, "detail": detail}
            )
            error.failure_class = failure
            raise error from exc

    def map_request(self, request: RenderRequest) -> dict[str, Any]:
        if not request.prompt_provenance.startswith("sha256:"):
            raise ValidationError("Assembled prompt provenance is required")
        max_duration = 10 if request.render_profile == "final" else 5
        seed = int(hashlib.sha256(request.cache_key.encode()).hexdigest()[:8], 16)
        payload = {
            "model": self.model_id,
            "prompt_text": request.assembled_prompt,
            "seed": seed,
            "duration": min(request.duration_seconds, max_duration),
            "resolution": f"{request.width}x{request.height}",
            "fps": request.frame_rate,
            "quality": "high" if request.render_profile == "final" else "draft",
            "negative_prompt": ", ".join(request.negative_style_tokens),
            "idempotency_key": stable_id(
                "idem", {"cache_key": request.cache_key, "attempt": request.attempt}
            ),
        }
        if request.conditioning_image_ref is not None:
            payload["init_image"] = request.conditioning_image_ref
        return payload

    def submit(self, request: RenderRequest) -> ProviderJobRef:
        payload = self.map_request(request)
        raw, _headers = self._request("POST", "/v1/jobs", payload)
        value = json.loads(raw)
        task_id = str(value.get("id") or value.get("job_id") or "")
        if not task_id:
            raise ProviderSubmissionError("Runway response contained no job id")
        return ProviderJobRef(
            provider=self.provider_id,
            provider_task_id=task_id,
            idempotency_key=payload["idempotency_key"],
            state=RenderState.SUBMITTED,
        )

    def get_status(self, job_ref: ProviderJobRef) -> dict:
        raw, _headers = self._request("GET", f"/v1/jobs/{job_ref.provider_task_id}")
        value = json.loads(raw)
        raw_state = str(value.get("status", "RUNNING")).upper()
        return {
            "state": STATUS_MAP.get(raw_state, RenderState.RUNNING).value,
            "provider_task_id": job_ref.provider_task_id,
            "asset_url": value.get("asset_url") or value.get("output_url"),
        }

    def download(self, job_ref: ProviderJobRef, destination: Path) -> dict:
        raw, headers = self._request(
            "GET", f"/v1/jobs/{job_ref.provider_task_id}/asset", timeout=120
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".partial.mp4")
        temporary.write_bytes(raw)
        claimed = headers.get("X-Checksum-Sha256") or headers.get("x-checksum-sha256")
        actual = file_hash(temporary)
        if claimed and actual != f"sha256:{claimed}":
            temporary.unlink(missing_ok=True)
            raise ProviderSubmissionError("Runway download checksum mismatch")
        os.replace(temporary, destination)
        return {
            "asset_uri": str(destination.resolve()),
            "asset_hash": actual,
            "size_bytes": len(raw),
        }

    def cancel(self, job_ref: ProviderJobRef) -> dict:
        raw, _headers = self._request(
            "POST", f"/v1/jobs/{job_ref.provider_task_id}/cancel", {}
        )
        value = json.loads(raw or b"{}")
        return {
            "outcome": value.get("outcome", "CANCELLED"),
            "observed_state": value.get("status", "CANCELLED"),
        }

    def health_check(self) -> dict:
        start = time.monotonic()
        try:
            self._request("GET", "/v1/health", timeout=5)
        except Exception as exc:  # health checks return a status rather than propagating
            return {"status": "UNAVAILABLE", "detail": type(exc).__name__}
        return {
            "status": "HEALTHY",
            "latency_seconds": round(time.monotonic() - start, 3),
        }
