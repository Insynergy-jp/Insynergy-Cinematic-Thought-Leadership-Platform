"""Reproducible publication package construction."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from .util import file_hash


def create_publish_package(
    *, build_dir: Path, manifest: dict[str, Any], master_video: Path
) -> dict[str, Any]:
    package_dir = build_dir / "package"
    package_dir.mkdir(parents=True, exist_ok=True)
    destination = package_dir / f"{manifest['build_id']}.zip"
    entries: list[tuple[Path, str]] = [(master_video, "media/master.mp4")]
    artifact_dir = build_dir / "artifacts"
    for path in sorted(artifact_dir.glob("*.json")):
        entries.append((path, f"artifacts/{path.name}"))
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo("manifest.json", date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, manifest_bytes)
        for source, name in entries:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, source.read_bytes())
    return {
        "package_uri": str(destination.resolve()),
        "package_hash": file_hash(destination),
        "entry_count": len(entries) + 1,
        "reproducible_archive": True,
    }

