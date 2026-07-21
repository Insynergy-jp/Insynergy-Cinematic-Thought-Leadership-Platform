"""Content-addressable artifact storage and authoritative build manifests."""

from __future__ import annotations

import shutil
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import NotFoundError, StateConflictError, ValidationError
from .agent_review import (
    build_report_validation_request,
    validate_agent_review_report,
    validate_review_approval_binding,
)
from .models import ArtifactEnvelope, BuildState
from .schemas import validate_envelope
from .util import atomic_write_json, canonical_json, content_hash, now_iso, read_json


class ContentAddressableStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()

    def put_bytes(self, value: bytes, suffix: str = ".bin") -> tuple[str, Path]:
        import hashlib

        digest = hashlib.sha256(value).hexdigest()
        key = f"sha256:{digest}"
        path = self.root / digest[:2] / f"{digest}{suffix}"
        with self._lock:
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(prefix=f".{digest}.", dir=path.parent)
                try:
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(value)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, path)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
        return key, path

    def put_file(self, source: Path) -> tuple[str, Path]:
        import hashlib

        digest = hashlib.sha256()
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        hex_digest = digest.hexdigest()
        key = f"sha256:{hex_digest}"
        path = self.root / hex_digest[:2] / f"{hex_digest}{source.suffix}"
        with self._lock:
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(prefix=f".{hex_digest}.", dir=path.parent)
                os.close(fd)
                try:
                    shutil.copyfile(source, temporary)
                    os.replace(temporary, path)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
        return key, path

    def put_json(self, value: Any) -> tuple[str, Path]:
        encoded = (canonical_json(value) + "\n").encode("utf-8")
        return self.put_bytes(encoded, ".json")

    def resolve(self, key: str, suffix: str | None = None) -> Path | None:
        if not key.startswith("sha256:"):
            return None
        digest = key.split(":", 1)[1]
        parent = self.root / digest[:2]
        if suffix:
            candidate = parent / f"{digest}{suffix}"
            return candidate if candidate.exists() else None
        matches = list(parent.glob(f"{digest}.*")) if parent.exists() else []
        return matches[0] if matches else None


class BuildRepository:
    LEGAL_TRANSITIONS: dict[BuildState, set[BuildState]] = {
        BuildState.CREATED: {BuildState.PLANNING, BuildState.CANCELLED},
        BuildState.PLANNING: {BuildState.PLANNED, BuildState.FAILED, BuildState.CANCELLED},
        BuildState.PLANNED: {BuildState.AWAITING_EXECUTION_APPROVAL, BuildState.CANCELLED},
        BuildState.AWAITING_EXECUTION_APPROVAL: {
            BuildState.EXECUTING,
            BuildState.CANCELLED,
        },
        BuildState.EXECUTING: {
            BuildState.COMPOSING,
            BuildState.PAUSED,
            BuildState.FAILED,
            BuildState.CANCELLED,
        },
        BuildState.PAUSED: {BuildState.EXECUTING, BuildState.CANCELLED},
        BuildState.COMPOSING: {
            BuildState.VALIDATING,
            BuildState.FAILED,
            BuildState.CANCELLED,
        },
        BuildState.VALIDATING: {BuildState.READY, BuildState.FAILED},
        BuildState.READY: {BuildState.AWAITING_PUBLISH_APPROVAL, BuildState.CANCELLED},
        BuildState.AWAITING_PUBLISH_APPROVAL: {
            BuildState.PUBLISHED,
            BuildState.CANCELLED,
        },
        BuildState.PUBLISHED: set(),
        BuildState.CANCELLED: set(),
        BuildState.FAILED: set(),
    }

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.root = workspace / ".insynergy"
        self.builds = self.root / "builds"
        self.cas = ContentAddressableStore(self.root / "cas")

    def build_dir(self, build_id: str) -> Path:
        return self.builds / build_id

    def find_by_identity(self, build_identity: str) -> dict | None:
        if not self.builds.exists():
            return None
        for path in sorted(self.builds.glob("*/manifest.json")):
            manifest = read_json(path)
            if manifest.get("source", {}).get("build_identity") == build_identity:
                return manifest
        return None

    def next_build_id(self) -> str:
        date_prefix = datetime.now().strftime("%Y%m%d")
        sequences = []
        if self.builds.exists():
            for path in self.builds.glob(f"{date_prefix}-[0-9][0-9][0-9]"):
                try:
                    sequences.append(int(path.name.rsplit("-", 1)[1]))
                except ValueError:
                    continue
        sequence = max(sequences, default=0) + 1
        if sequence > 999:
            raise ValidationError("Daily build identity space exhausted")
        return f"{date_prefix}-{sequence:03d}"

    def manifest_path(self, build_id: str) -> Path:
        return self.build_dir(build_id) / "manifest.json"

    def create(self, build_id: str, source: dict[str, Any], profile: str, config: dict) -> dict:
        path = self.manifest_path(build_id)
        if path.exists():
            existing = read_json(path)
            if existing.get("source", {}).get("content_hash") != source.get("content_hash"):
                raise StateConflictError("Build identity collision")
            return existing
        manifest = {
            "schema_version": "2.0",
            "build_id": build_id,
            "state": BuildState.CREATED.value,
            "version": 1,
            "profile": profile,
            "source": source,
            "configuration": config,
            "artifacts": {},
            "gates": {},
            "approvals": {},
            "render_tasks": {},
            "metrics": {},
            "agent_review": {
                "mode": "off",
                "status": "DISABLED",
                "review_key": None,
                "report_ref": None,
                "report_content_hash": None,
            },
            "transitions": [
                {
                    "previous_state": None,
                    "new_state": BuildState.CREATED.value,
                    "timestamp": now_iso(),
                    "reason": "build_created",
                }
            ],
            "events": [],
        }
        atomic_write_json(path, manifest)
        return manifest

    def load(self, build_id: str) -> dict:
        path = self.manifest_path(build_id)
        if not path.exists():
            raise NotFoundError(f"Build not found: {build_id}")
        return read_json(path)

    def save(self, manifest: dict, *, expected_version: int | None = None) -> dict:
        build_id = manifest["build_id"]
        if expected_version is not None and self.manifest_path(build_id).exists():
            current = self.load(build_id)
            if current["version"] != expected_version:
                raise StateConflictError(
                    "Manifest version conflict",
                    details={"expected": expected_version, "actual": current["version"]},
                )
        manifest["version"] = int(manifest.get("version", 0)) + 1
        atomic_write_json(self.manifest_path(build_id), manifest)
        return manifest

    def transition(self, manifest: dict, new_state: BuildState, reason: str) -> dict:
        current = BuildState(manifest["state"])
        if new_state == current:
            return manifest
        if new_state not in self.LEGAL_TRANSITIONS[current]:
            raise StateConflictError(
                f"Illegal build transition: {current.value} -> {new_state.value}"
            )
        manifest["state"] = new_state.value
        manifest["transitions"].append(
            {
                "previous_state": current.value,
                "new_state": new_state.value,
                "timestamp": now_iso(),
                "reason": reason,
            }
        )
        return self.save(manifest)

    def record_event(self, manifest: dict, event_type: str, payload: dict | None = None) -> None:
        manifest["events"].append(
            {
                "sequence": len(manifest["events"]) + 1,
                "event_type": event_type,
                "build_id": manifest["build_id"],
                "occurred_at": now_iso(),
                "payload": payload or {},
            }
        )

    def store_artifact(self, manifest: dict, envelope: ArtifactEnvelope) -> dict:
        document = envelope.as_dict()
        validate_envelope(document, expected_type=envelope.artifact_type)
        key, _cas_path = self.cas.put_json(document)
        artifact_dir = self.build_dir(manifest["build_id"]) / "artifacts"
        artifact_path = artifact_dir / f"{envelope.artifact_type}.json"
        atomic_write_json(artifact_path, document)
        manifest["artifacts"][envelope.artifact_type] = {
            "artifact_id": envelope.artifact_id,
            "content_hash": envelope.content_hash,
            "cas_ref": key,
            "path": str(artifact_path),
            "immutable": True,
        }
        return document

    def load_artifact(self, manifest: dict, artifact_type: str) -> dict:
        reference = manifest.get("artifacts", {}).get(artifact_type)
        if not reference:
            raise NotFoundError(f"Artifact not found: {artifact_type}")
        return read_json(Path(reference["path"]))

    def store_sealed_document(
        self,
        manifest: dict,
        *,
        artifact_type: str,
        document: dict[str, Any],
        artifact_id: str,
    ) -> dict[str, Any]:
        """Store a Part 9 sealed document that is not wrapped in ArtifactEnvelope."""
        if artifact_type == "agent_review_report":
            validate_agent_review_report(document)
        elif artifact_type == "review_approval_binding":
            validate_review_approval_binding(document)
        else:
            raise ValidationError(f"Unsupported sealed document: {artifact_type}")
        existing = manifest.get("artifacts", {}).get(artifact_type)
        if existing:
            if existing.get("content_hash") != document["content_hash"]:
                raise StateConflictError(
                    f"Sealed document is immutable: {artifact_type}"
                )
            return self.load_artifact(manifest, artifact_type)
        key, _cas_path = self.cas.put_json(document)
        artifact_dir = self.build_dir(manifest["build_id"]) / "artifacts"
        artifact_path = artifact_dir / f"{artifact_type}.json"
        atomic_write_json(artifact_path, document)
        manifest["artifacts"][artifact_type] = {
            "artifact_id": artifact_id,
            "content_hash": document["content_hash"],
            "cas_ref": key,
            "path": str(artifact_path),
            "immutable": True,
            "sealed_document": True,
        }
        return document

    def verify_artifacts(self, manifest: dict) -> None:
        for artifact_type, reference in manifest.get("artifacts", {}).items():
            path = Path(reference["path"])
            if not path.exists():
                raise ValidationError(f"Missing artifact: {artifact_type}")
            document = read_json(path)
            if reference.get("sealed_document") is True:
                if artifact_type == "agent_review_report":
                    request = build_report_validation_request(
                        manifest, self, document.get("review_key", "")
                    )
                    validate_agent_review_report(document, request)
                elif artifact_type == "review_approval_binding":
                    validate_review_approval_binding(document)
                else:
                    raise ValidationError(
                        f"Unknown sealed document artifact: {artifact_type}"
                    )
                if document.get("content_hash") != reference["content_hash"]:
                    raise ValidationError(f"Artifact integrity failure: {artifact_type}")
                continue
            validate_envelope(document, expected_type=artifact_type)
            actual = content_hash(document["data"])
            if actual != reference["content_hash"]:
                raise ValidationError(f"Artifact integrity failure: {artifact_type}")

    def list_builds(self) -> list[dict]:
        if not self.builds.exists():
            return []
        values = []
        for path in sorted(self.builds.glob("*/manifest.json")):
            manifest = read_json(path)
            values.append(
                {
                    "build_id": manifest["build_id"],
                    "state": manifest["state"],
                    "profile": manifest["profile"],
                    "version": manifest["version"],
                }
            )
        return values
