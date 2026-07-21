"""Provider-independent, cache-first Rendering Platform facade."""

from __future__ import annotations

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
)
from .media import AssetValidator, RenderQualityGate
from .models import RenderRequest, RenderResult, RenderState
from .prompt import PromptAssembler
from .providers import VideoProvider
from .storage import ContentAddressableStore
from .util import atomic_write_json, content_hash, file_hash, read_json, stable_id


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


class RenderingPlatform:
    contract_version = "5.7.2-v1"

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

    def _provider_name(self, frame: dict[str, Any]) -> str:
        strategy_provider = frame["render_strategy"]["provider"]
        if strategy_provider == "runway":
            return self.config.provider
        return "local"

    def _request(self, frame: dict[str, Any], attempt: int = 1) -> RenderRequest:
        assembled = self.assembler.assemble(frame)
        self.assembler.verify(assembled, frame)
        profile = self.config.render_profile()
        provider = self._provider_name(frame)
        provider_version = "local-ffmpeg-v1" if provider == "local" else "gen4.5"
        cache_key = self.cache.key(
            shot_hash=content_hash(frame),
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
            camera_parameters=frame["camera"],
            style_tokens=tuple(frame["style"]),
            negative_style_tokens=tuple(frame["forbidden_style"]),
        )

    def render_shot(self, frame: dict[str, Any]) -> RenderResult:
        request = self._request(frame)
        cached = self.cache.lookup(request.cache_key)
        if cached:
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
        for attempt in range(1, self.config.max_attempts + 1):
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
                download = provider.download(job, asset)
                validation = self.validator.validate(
                    asset,
                    width=attempt_request.width,
                    height=attempt_request.height,
                    frame_rate=attempt_request.frame_rate,
                    duration_seconds=attempt_request.duration_seconds,
                )
                quality = self.quality_gate.evaluate(validation, frame)
                cached_entry = self.cache.store(
                    request.cache_key, asset, validation, quality
                )
                return RenderResult(
                    render_task_id=request.render_task_id,
                    shot_id=request.shot_id,
                    state=RenderState.COMPLETED,
                    asset_uri=cached_entry["asset_uri"],
                    asset_hash=download["asset_hash"],
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
            attempts=self.config.max_attempts,
            error=error.as_dict(),
        )

    def render_build(
        self,
        storyboard: dict[str, Any],
        *,
        approved: bool,
    ) -> dict[str, Any]:
        if not approved:
            raise StoryboardNotApprovedError("Execution approval is required before rendering")
        frames = sorted(storyboard.get("frames", []), key=lambda frame: frame["shot_id"])
        if not frames:
            raise RenderingError("Storyboard contains no frames")
        expensive = sum(
            frame["render_strategy"]["asset_class"] == "runway_video" for frame in frames
        )
        estimate = expensive * (4.0 if self.config.profile == "final" else 1.0)
        if self.config.estimate_before_submission and estimate > self.config.budget_usd:
            raise BudgetExhaustedError(
                "Estimated provider cost exceeds build budget",
                details={"estimated_usd": estimate, "budget_usd": self.config.budget_usd},
            )
        results: list[RenderResult] = []
        with ThreadPoolExecutor(max_workers=self.config.max_parallel_shots) as executor:
            futures = {executor.submit(self.render_shot, frame): frame for frame in frames}
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
        return {
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
            },
        }

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
