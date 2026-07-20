"""Provider-neutral video boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..models import ProviderJobRef, RenderRequest


class VideoProvider(Protocol):
    provider_id: str

    def submit(self, request: RenderRequest) -> ProviderJobRef: ...

    def get_status(self, job_ref: ProviderJobRef) -> dict: ...

    def download(self, job_ref: ProviderJobRef, destination: Path) -> dict: ...

    def cancel(self, job_ref: ProviderJobRef) -> dict: ...

    def health_check(self) -> dict: ...


__all__ = ["VideoProvider"]

