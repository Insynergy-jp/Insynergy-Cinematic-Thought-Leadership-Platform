"""Content-addressable artifact storage and authoritative build manifests."""

from __future__ import annotations

import shutil
import os
import fcntl
import tempfile
import threading
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .errors import NotFoundError, StateConflictError, ValidationError
from .agent_review import (
    build_report_validation_request,
    validate_agent_review_report,
    validate_review_approval_binding,
)
from .models import ArtifactEnvelope, BuildState
from .schemas import validate_envelope
from .schema_validation import PERSONA_NAMES, validate_persona_bundle, validate_schema_document
from .util import (
    atomic_write_json,
    canonical_json,
    content_hash,
    now_iso,
    read_json,
    stable_id,
)


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
        BuildState.CREATED: {
            BuildState.PERSONA_PLANNING,
            BuildState.PLANNING,
            BuildState.CANCELLED,
        },
        BuildState.PERSONA_PLANNING: {
            BuildState.AWAITING_PERSONA_APPROVAL,
            BuildState.FAILED,
            BuildState.CANCELLED,
        },
        BuildState.AWAITING_PERSONA_APPROVAL: {
            BuildState.PLANNING,
            BuildState.FAILED,
            BuildState.CANCELLED,
        },
        BuildState.PLANNING: {BuildState.PLANNED, BuildState.FAILED, BuildState.CANCELLED},
        BuildState.PLANNED: {
            BuildState.AWAITING_STORYBOARD_PREVIEW_APPROVAL,
            BuildState.AWAITING_EXECUTION_APPROVAL,
            BuildState.CANCELLED,
        },
        BuildState.AWAITING_STORYBOARD_PREVIEW_APPROVAL: {
            BuildState.AWAITING_EXECUTION_APPROVAL,
            BuildState.CANCELLED,
        },
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
        # FAILED remains closed by default. The orchestrator exposes one explicit,
        # guarded retry path for a failure that occurred during deterministic planning.
        BuildState.FAILED: {BuildState.PLANNING},
    }

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.root = workspace / ".insynergy"
        self.builds = self.root / "builds"
        self.cas = ContentAddressableStore(self.root / "cas")
        self.operations = self.root / "operations"
        self._thread_lock = threading.RLock()

    @contextmanager
    def _file_lock(self, path: Path) -> Iterator[None]:
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._thread_lock:
            with path.open("a+", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _manifest_lock_path(self, build_id: str) -> Path:
        return self.build_dir(build_id) / ".manifest.lock"

    @staticmethod
    def _manifest_hash(manifest: dict[str, Any]) -> str:
        value = deepcopy(manifest)
        value.setdefault("integrity", {}).pop("manifest_hash", None)
        return content_hash(value)

    def _seal_manifest(
        self, manifest: dict[str, Any], *, previous_manifest_hash: str | None
    ) -> None:
        manifest["integrity"] = {
            "algorithm": "sha256-canonical-json",
            "previous_manifest_hash": previous_manifest_hash,
            "manifest_hash": None,
        }
        manifest["integrity"]["manifest_hash"] = self._manifest_hash(manifest)

    def _verify_manifest(self, manifest: dict[str, Any]) -> None:
        integrity = manifest.get("integrity")
        if not integrity:
            return
        if integrity.get("algorithm") != "sha256-canonical-json":
            raise ValidationError("Unsupported Manifest integrity algorithm")
        if integrity.get("manifest_hash") != self._manifest_hash(manifest):
            raise ValidationError("Runtime Manifest integrity failure")
        self.verify_event_chain(manifest)

    def verify_manifest_history(self, manifest: dict[str, Any]) -> int:
        previous_hash: str | None = None
        count = 0
        history_root = self.build_dir(manifest["build_id"]) / "history"
        for path in sorted(history_root.glob("manifest-v*.json")):
            historical = read_json(path)
            self._verify_manifest(historical)
            if (
                historical.get("integrity", {}).get("previous_manifest_hash")
                != previous_hash
            ):
                raise ValidationError("Runtime Manifest history chain is invalid")
            previous_hash = historical.get("integrity", {}).get("manifest_hash")
            count += 1
        if count and (
            manifest.get("integrity", {}).get("previous_manifest_hash")
            != previous_hash
        ):
            raise ValidationError("Current Manifest is detached from its history")
        return count

    def build_dir(self, build_id: str) -> Path:
        return self.builds / build_id

    def find_by_identity(self, build_identity: str) -> dict | None:
        if not self.builds.exists():
            return None
        for path in sorted(self.builds.glob("*/manifest.json")):
            manifest = self.load(path.parent.name)
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
        with self._file_lock(self._manifest_lock_path(build_id)):
            if path.exists():
                existing = read_json(path)
                self._verify_manifest(existing)
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
                "runtime": {
                    "execution_generation": 0,
                    "queue_ref": None,
                    "queue_snapshot": None,
                    "recovery_attempts": [],
                },
                "checkpoints": [],
                "quality": {
                    "reports": [],
                    "chain": None,
                    "approval_audit": [],
                },
                "agent_review": {
                    "mode": "off",
                    "status": "DISABLED",
                    "review_key": None,
                    "report_ref": None,
                    "report_content_hash": None,
                },
                "persona_council": {
                    "mode": "off",
                    "status": "DISABLED",
                    "deliberation_key": None,
                    "persona_content_hash": None,
                    "quality_report_content_hash": None,
                    "approval_binding_content_hash": None,
                },
                "previsualization": {
                    "mode": "off",
                    "status": "DISABLED",
                    "plan_key": None,
                    "preview_manifest_content_hash": None,
                    "quality_report_content_hash": None,
                    "approval_binding_content_hash": None,
                    "runway_api_calls": 0,
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
            self.record_event(
                manifest,
                "build_state_transitioned",
                {
                    "previous_state": None,
                    "new_state": BuildState.CREATED.value,
                    "reason": "build_created",
                },
                dedup_key="transition:1:CREATED",
            )
            self._seal_manifest(manifest, previous_manifest_hash=None)
            atomic_write_json(path, manifest)
            return manifest

    def load(self, build_id: str) -> dict:
        path = self.manifest_path(build_id)
        if not path.exists():
            raise NotFoundError(f"Build not found: {build_id}")
        manifest = read_json(path)
        self._verify_manifest(manifest)
        return manifest

    def save(self, manifest: dict, *, expected_version: int | None = None) -> dict:
        build_id = manifest["build_id"]
        path = self.manifest_path(build_id)
        with self._file_lock(self._manifest_lock_path(build_id)):
            if not path.exists():
                raise NotFoundError(f"Build not found: {build_id}")
            current = read_json(path)
            self._verify_manifest(current)
            effective_expected = (
                int(manifest.get("version", 0))
                if expected_version is None
                else expected_version
            )
            if current["version"] != effective_expected:
                raise StateConflictError(
                    "Manifest version conflict",
                    details={"expected": effective_expected, "actual": current["version"]},
                )
            history = self.build_dir(build_id) / "history" / (
                f"manifest-v{int(current['version']):06d}.json"
            )
            if not history.exists():
                atomic_write_json(history, current)
            previous_hash = (
                current.get("integrity", {}).get("manifest_hash")
                or self._manifest_hash(current)
            )
            manifest["version"] = int(current["version"]) + 1
            self._seal_manifest(
                manifest, previous_manifest_hash=str(previous_hash)
            )
            atomic_write_json(path, manifest)
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
        self.record_event(
            manifest,
            "build_state_transitioned",
            {
                "previous_state": current.value,
                "new_state": new_state.value,
                "reason": reason,
            },
            dedup_key=(
                f"transition:{len(manifest['transitions'])}:{current.value}:"
                f"{new_state.value}:{reason}"
            ),
        )
        return self.save(manifest)

    def record_event(
        self,
        manifest: dict,
        event_type: str,
        payload: dict | None = None,
        *,
        dedup_key: str | None = None,
    ) -> dict[str, Any]:
        identity = dedup_key or content_hash(
            {"event_type": event_type, "payload": payload or {}}
        )
        for existing in manifest["events"]:
            if existing.get("dedup_key") == identity:
                return existing
        previous = None
        if manifest["events"]:
            last = manifest["events"][-1]
            previous = last.get("event_hash") or content_hash(last)
        event = {
            "sequence": len(manifest["events"]) + 1,
            "event_type": event_type,
            "build_id": manifest["build_id"],
            "occurred_at": now_iso(),
            "dedup_key": identity,
            "previous_event_hash": previous,
            "payload": payload or {},
        }
        event["event_id"] = stable_id(
            "event", {"build_id": manifest["build_id"], "event": event}
        )
        event["event_hash"] = content_hash(event)
        manifest["events"].append(event)
        return event

    @staticmethod
    def verify_event_chain(manifest: dict[str, Any]) -> None:
        previous: str | None = None
        for sequence, event in enumerate(manifest.get("events", []), start=1):
            if event.get("sequence") != sequence:
                raise ValidationError("Build event sequence is invalid")
            if "event_hash" not in event:
                previous = content_hash(event)
                continue
            if event.get("previous_event_hash") != previous:
                raise ValidationError("Build event chain is invalid")
            expected = content_hash(
                {key: value for key, value in event.items() if key != "event_hash"}
            )
            if event.get("event_hash") != expected:
                raise ValidationError("Build event integrity failure")
            previous = expected

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
        elif artifact_type in PERSONA_NAMES:
            validate_schema_document(artifact_type, document)
            expected = content_hash(
                {key: value for key, value in document.items() if key != "content_hash"}
            )
            if document.get("content_hash") != expected:
                raise ValidationError(
                    f"Persona sealed document hash is invalid: {artifact_type}"
                )
        elif artifact_type == "storyboard_preview_approval_binding":
            from .previsualization import validate_preview_approval_binding

            validate_preview_approval_binding(document)
            validate_schema_document("storyboard-preview-approval-binding", document)
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
                elif artifact_type in PERSONA_NAMES:
                    validate_schema_document(artifact_type, document)
                    expected = content_hash(
                        {
                            key: value
                            for key, value in document.items()
                            if key != "content_hash"
                        }
                    )
                    if document.get("content_hash") != expected:
                        raise ValidationError(
                            f"Persona artifact integrity failure: {artifact_type}"
                        )
                elif artifact_type == "storyboard_preview_approval_binding":
                    from .previsualization import validate_preview_approval_binding

                    validate_preview_approval_binding(document)
                    validate_schema_document(
                        "storyboard-preview-approval-binding", document
                    )
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
        if set(PERSONA_NAMES).issubset(manifest.get("artifacts", {})):
            validate_persona_bundle(
                {
                    name: self.load_artifact(manifest, name)
                    for name in PERSONA_NAMES
                }
            )

    def record_quality_report(
        self, manifest: dict[str, Any], report: dict[str, Any]
    ) -> dict[str, Any]:
        """Persist one immutable Quality Gate report and advance its chain."""
        from .quality import quality_chain_report, verify_quality_gate_report

        verify_quality_gate_report(report)
        quality = manifest.setdefault(
            "quality", {"reports": [], "chain": None, "approval_audit": []}
        )
        for reference in quality.setdefault("reports", []):
            if reference.get("report_id") == report["report_id"]:
                self.verify_quality_report(reference)
                return manifest
        envelope = ArtifactEnvelope(
            artifact_type="quality_gate_report",
            build_id=manifest["build_id"],
            data=report,
            input_hashes=tuple(
                sorted(
                    {
                        reference["content_hash"]
                        for reference in report["artifact_refs"]
                    }
                )
            ),
            generator="quality-gate-engine",
        ).as_dict()
        validate_envelope(envelope, expected_type="quality_gate_report")
        cas_ref, _ = self.cas.put_json(envelope)
        path = (
            self.build_dir(manifest["build_id"])
            / "quality"
            / "reports"
            / f"{len(quality['reports']) + 1:03d}-{report['gate_id']}-{report['report_id']}.json"
        )
        atomic_write_json(path, envelope)
        reference = {
            "report_id": report["report_id"],
            "gate_id": report["gate_id"],
            "decision": report["decision"],
            "report_content_hash": report["content_hash"],
            "envelope_content_hash": envelope["content_hash"],
            "cas_ref": cas_ref,
            "path": str(path),
        }
        quality["reports"].append(reference)
        reports = self.load_quality_reports(manifest)
        quality["chain"] = quality_chain_report(reports)
        self.record_event(
            manifest,
            "quality_gate_reported",
            {
                "gate_id": report["gate_id"],
                "report_id": report["report_id"],
                "decision": report["decision"],
                "content_hash": report["content_hash"],
            },
            dedup_key=f"quality-report:{report['report_id']}",
        )
        return self.save(manifest)

    def verify_quality_report(
        self, reference: dict[str, Any]
    ) -> dict[str, Any]:
        from .quality import verify_quality_gate_report

        path = Path(str(reference.get("path", "")))
        if not path.is_file():
            raise ValidationError("Quality Gate report file is missing")
        envelope = read_json(path)
        validate_envelope(envelope, expected_type="quality_gate_report")
        if envelope["content_hash"] != reference.get("envelope_content_hash"):
            raise ValidationError("Quality Gate report envelope integrity failure")
        report = envelope["data"]
        verify_quality_gate_report(report)
        if (
            report["report_id"] != reference.get("report_id")
            or report["content_hash"] != reference.get("report_content_hash")
            or report["gate_id"] != reference.get("gate_id")
            or report["decision"] != reference.get("decision")
        ):
            raise ValidationError("Quality Gate report reference is inconsistent")
        cas_path = self.cas.resolve(str(reference.get("cas_ref", "")), ".json")
        if not cas_path or read_json(cas_path) != envelope:
            raise ValidationError("Quality Gate report CAS evidence is inconsistent")
        return report

    def load_quality_reports(
        self, manifest: dict[str, Any]
    ) -> list[dict[str, Any]]:
        return [
            self.verify_quality_report(reference)
            for reference in manifest.get("quality", {}).get("reports", [])
        ]

    def verify_quality(self, manifest: dict[str, Any]) -> dict[str, Any]:
        from .quality import quality_chain_report

        reports = self.load_quality_reports(manifest)
        expected_chain = quality_chain_report(reports)
        recorded_chain = manifest.get("quality", {}).get("chain")
        if reports and recorded_chain != expected_chain:
            raise ValidationError("Quality Gate chain integrity failure")
        previous_audit_hash: str | None = None
        for sequence, entry in enumerate(
            manifest.get("quality", {}).get("approval_audit", []), start=1
        ):
            expected = content_hash(
                {key: value for key, value in entry.items() if key != "content_hash"}
            )
            if (
                entry.get("sequence") != sequence
                or entry.get("previous_entry_hash") != previous_audit_hash
                or entry.get("content_hash") != expected
            ):
                raise ValidationError("Approval audit integrity failure")
            previous_audit_hash = expected
        return {
            "valid": True,
            "report_count": len(reports),
            "passed_report_count": sum(report["passed"] for report in reports),
            "chain": expected_chain,
            "approval_audit_count": len(
                manifest.get("quality", {}).get("approval_audit", [])
            ),
        }

    def quality_baseline(
        self, *, profile: str, exclude_build_id: str
    ) -> dict[str, float]:
        """Return the latest verified local Build Quality score baseline."""
        if not self.builds.exists():
            return {}
        for path in sorted(self.builds.glob("*/manifest.json"), reverse=True):
            if path.parent.name == exclude_build_id:
                continue
            candidate = self.load(path.parent.name)
            if candidate.get("profile") != profile:
                continue
            artifact_type = next(
                (
                    value
                    for value in (
                        "published_build_quality_report",
                        "build_quality_report",
                    )
                    if value in candidate.get("artifacts", {})
                ),
                None,
            )
            if not artifact_type:
                continue
            document = self.load_artifact(candidate, artifact_type)["data"]
            return {
                key: float(value)
                for key, value in document.get("gate_scores", {}).items()
            }
        return {}

    def record_approval_audit(
        self,
        manifest: dict[str, Any],
        *,
        gate: str,
        state: str,
        actor: str,
        approval_ref: str | None,
        artifact_hash: str,
        rationale: str,
    ) -> None:
        quality = manifest.setdefault(
            "quality", {"reports": [], "chain": None, "approval_audit": []}
        )
        audit = quality.setdefault("approval_audit", [])
        previous = audit[-1]["content_hash"] if audit else None
        entry = {
            "sequence": len(audit) + 1,
            "gate": gate,
            "state": state,
            "actor": actor,
            "approval_ref": approval_ref,
            "artifact_hash": artifact_hash,
            "rationale": rationale,
            "previous_entry_hash": previous,
            "recorded_at": now_iso(),
        }
        entry["content_hash"] = content_hash(entry)
        audit.append(entry)

    def publish_checkpoint(
        self,
        manifest: dict[str, Any],
        stage: str,
        *,
        queue_snapshot: dict[str, Any] | None = None,
        clean: bool = False,
    ) -> dict[str, Any]:
        """Seal a safe resume anchor without treating Queue state as authority."""
        if not stage or len(stage) > 128:
            raise ValidationError("Checkpoint stage is invalid")
        self._verify_manifest(manifest)
        self.verify_artifacts(manifest)
        checkpoint_identity = {
            "build_id": manifest["build_id"],
            "stage": stage,
            "manifest_version": manifest["version"],
            "manifest_hash": manifest.get("integrity", {}).get("manifest_hash"),
        }
        checkpoint_id = stable_id("checkpoint", checkpoint_identity)
        for reference in manifest.get("checkpoints", []):
            if reference.get("checkpoint_id") == checkpoint_id:
                self.verify_checkpoint(reference)
                return manifest
        previous = (
            manifest.get("checkpoints", [])[-1].get("content_hash")
            if manifest.get("checkpoints")
            else None
        )
        document = {
            "schema_version": "2.0",
            "contract_version": "runtime-checkpoint/1",
            "checkpoint_id": checkpoint_id,
            "build_id": manifest["build_id"],
            "stage": stage,
            "build_state": manifest["state"],
            "manifest_version": manifest["version"],
            "manifest_hash": checkpoint_identity["manifest_hash"],
            "previous_checkpoint_hash": previous,
            "artifact_hashes": {
                key: value["content_hash"]
                for key, value in sorted(manifest.get("artifacts", {}).items())
            },
            "gate_hash": content_hash(manifest.get("gates", {})),
            "approval_hash": content_hash(manifest.get("approvals", {})),
            "render_task_hash": content_hash(manifest.get("render_tasks", {})),
            "queue_snapshot": queue_snapshot,
            "clean": clean,
            "created_at": now_iso(),
        }
        document["content_hash"] = content_hash(document)
        cas_ref, _ = self.cas.put_json(document)
        path = (
            self.build_dir(manifest["build_id"])
            / "checkpoints"
            / f"{len(manifest.get('checkpoints', [])) + 1:03d}-{stage}.json"
        )
        atomic_write_json(path, document)
        manifest.setdefault("checkpoints", []).append(
            {
                "checkpoint_id": checkpoint_id,
                "stage": stage,
                "content_hash": document["content_hash"],
                "cas_ref": cas_ref,
                "path": str(path),
                "clean": clean,
            }
        )
        self.record_event(
            manifest,
            "checkpoint_published",
            {
                "checkpoint_id": checkpoint_id,
                "stage": stage,
                "content_hash": document["content_hash"],
                "clean": clean,
            },
            dedup_key=f"checkpoint:{checkpoint_id}",
        )
        return self.save(manifest)

    def verify_checkpoint(self, reference: dict[str, Any]) -> dict[str, Any]:
        path = Path(str(reference.get("path", "")))
        if not path.is_file():
            raise ValidationError("Checkpoint file is missing")
        document = read_json(path)
        expected = content_hash(
            {key: value for key, value in document.items() if key != "content_hash"}
        )
        if (
            document.get("content_hash") != expected
            or reference.get("content_hash") != expected
        ):
            raise ValidationError("Checkpoint integrity failure")
        cas_path = self.cas.resolve(str(reference.get("cas_ref", "")), ".json")
        if not cas_path or read_json(cas_path) != document:
            raise ValidationError("Checkpoint CAS evidence is missing or inconsistent")
        return document

    def recovery_plan(self, manifest: dict[str, Any]) -> dict[str, Any]:
        """Derive an immutable, side-effect-free recovery decision."""
        self._verify_manifest(manifest)
        self.verify_artifacts(manifest)
        latest = None
        if manifest.get("checkpoints"):
            latest = self.verify_checkpoint(manifest["checkpoints"][-1])
        state = BuildState(manifest["state"])
        if state in {BuildState.PUBLISHED, BuildState.READY}:
            outcome = "COMPLETED"
        elif state in {BuildState.CANCELLED, BuildState.FAILED}:
            outcome = "DENIED"
        elif state == BuildState.PAUSED:
            outcome = "RESUME" if latest and latest.get("clean") else "RECONCILE"
        elif state in {
            BuildState.AWAITING_STORYBOARD_PREVIEW_APPROVAL,
            BuildState.AWAITING_EXECUTION_APPROVAL,
            BuildState.AWAITING_PUBLISH_APPROVAL,
        }:
            outcome = "WAIT_FOR_APPROVAL"
        elif state in {
            BuildState.EXECUTING,
            BuildState.COMPOSING,
            BuildState.VALIDATING,
        }:
            outcome = "RECONCILE"
        else:
            outcome = "RESTART_STAGE"
        queue_snapshot = manifest.get("runtime", {}).get("queue_snapshot")
        terminal = {"COMPLETED", "CACHED", "FAILED", "CANCELLED"}
        task_states = (queue_snapshot or {}).get("state_counts", {})
        reusable = sum(
            count for name, count in task_states.items() if name in terminal
        )
        requeue = sum(
            count for name, count in task_states.items() if name not in terminal
        )
        plan = {
            "schema_version": "2.0",
            "contract_version": "recovery-plan/1",
            "build_id": manifest["build_id"],
            "build_state": state.value,
            "outcome": outcome,
            "checkpoint_id": latest.get("checkpoint_id") if latest else None,
            "checkpoint_hash": latest.get("content_hash") if latest else None,
            "manifest_hash": manifest.get("integrity", {}).get("manifest_hash"),
            "execution_generation": manifest.get("runtime", {}).get(
                "execution_generation", 0
            ),
            "tasks_reusable": reusable,
            "tasks_to_requeue": requeue,
            "provider_redispatch": "RECONCILE_BEFORE_EFFECT",
            "generated_at": (
                latest.get("created_at")
                if latest
                else manifest.get("transitions", [{}])[-1].get("timestamp")
            ),
        }
        plan["recovery_plan_id"] = stable_id("recovery-plan", plan)
        plan["content_hash"] = content_hash(plan)
        return plan

    def prepare_recovery(
        self, manifest: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Persist the immutable Recovery Plan before a resume side effect."""
        plan = self.recovery_plan(manifest)
        runtime = manifest.setdefault("runtime", {})
        attempts = runtime.setdefault("recovery_attempts", [])
        for reference in attempts:
            if reference.get("content_hash") == plan["content_hash"]:
                return self.verify_recovery_plan(reference), manifest
        cas_ref, _ = self.cas.put_json(plan)
        path = (
            self.build_dir(manifest["build_id"])
            / "recovery"
            / f"{len(attempts) + 1:03d}-{plan['recovery_plan_id']}.json"
        )
        atomic_write_json(path, plan)
        reference = {
            "recovery_plan_id": plan["recovery_plan_id"],
            "content_hash": plan["content_hash"],
            "cas_ref": cas_ref,
            "path": str(path),
            "outcome": plan["outcome"],
        }
        attempts.append(reference)
        self.record_event(
            manifest,
            "recovery_plan_persisted",
            {
                "recovery_plan_id": plan["recovery_plan_id"],
                "content_hash": plan["content_hash"],
                "outcome": plan["outcome"],
            },
            dedup_key=f"recovery-plan:{plan['content_hash']}",
        )
        return plan, self.save(manifest)

    def verify_recovery_plan(
        self, reference: dict[str, Any]
    ) -> dict[str, Any]:
        path = Path(str(reference.get("path", "")))
        if not path.is_file():
            raise ValidationError("Recovery Plan file is missing")
        plan = read_json(path)
        expected = content_hash(
            {key: value for key, value in plan.items() if key != "content_hash"}
        )
        if (
            plan.get("content_hash") != expected
            or reference.get("content_hash") != expected
            or plan.get("recovery_plan_id") != reference.get("recovery_plan_id")
        ):
            raise ValidationError("Recovery Plan integrity failure")
        cas_path = self.cas.resolve(str(reference.get("cas_ref", "")), ".json")
        if not cas_path or read_json(cas_path) != plan:
            raise ValidationError("Recovery Plan CAS evidence is missing or inconsistent")
        return plan

    def verify_runtime(self, manifest: dict[str, Any]) -> dict[str, Any]:
        self._verify_manifest(manifest)
        history_count = self.verify_manifest_history(manifest)
        self.verify_artifacts(manifest)
        quality = self.verify_quality(manifest)
        checkpoints = []
        previous_checkpoint_hash: str | None = None
        for reference in manifest.get("checkpoints", []):
            checkpoint = self.verify_checkpoint(reference)
            if checkpoint.get("previous_checkpoint_hash") != previous_checkpoint_hash:
                raise ValidationError("Checkpoint history chain is invalid")
            previous_checkpoint_hash = checkpoint["content_hash"]
            checkpoints.append(checkpoint)
        recovery_plans = [
            self.verify_recovery_plan(reference)
            for reference in manifest.get("runtime", {}).get(
                "recovery_attempts", []
            )
        ]
        queue_ref = manifest.get("runtime", {}).get("queue_ref")
        queue_valid = True
        if queue_ref:
            from .runtime import DurableTaskQueue

            performance = manifest.get("configuration", {}).get("performance", {})
            queue = DurableTaskQueue(
                Path(queue_ref),
                build_id=manifest["build_id"],
                max_in_flight=int(performance.get("max_in_flight_tasks", 1)),
                provider_limits={
                    key: int(value)
                    for key, value in performance.get(
                        "provider_parallel_limits", {"local": 1, "runway": 1}
                    ).items()
                },
                budget_usd=float(
                    manifest.get("configuration", {})
                    .get("render", {})
                    .get("budget_usd", 0.0)
                ),
            )
            queue_valid = queue.verify()["valid"]
        recovery = self.recovery_plan(manifest)
        from .runtime import part6_coverage_report
        from .quality import part7_coverage_report

        return {
            "passed": queue_valid,
            "manifest_integrity": True,
            "event_chain_integrity": True,
            "artifact_integrity": True,
            "quality_integrity": quality["valid"],
            "checkpoint_integrity": True,
            "queue_integrity": queue_valid,
            "manifest_version": manifest["version"],
            "manifest_history_count": history_count,
            "event_count": len(manifest.get("events", [])),
            "checkpoint_count": len(checkpoints),
            "recovery_plan_count": len(recovery_plans),
            "recovery": recovery,
            "quality": quality,
            "part6_coverage": part6_coverage_report(),
            "part7_coverage": part7_coverage_report(),
        }

    def _operation_path(self, idempotency_key: str) -> Path:
        key_hash = content_hash(idempotency_key).split(":", 1)[1]
        return self.operations / f"{key_hash}.json"

    def begin_operation(
        self,
        *,
        idempotency_key: str,
        operation_type: str,
        request: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        if not idempotency_key.strip() or len(idempotency_key) > 256:
            raise ValidationError("Idempotency key is invalid")
        request_hash = content_hash(request)
        path = self._operation_path(idempotency_key)
        with self._file_lock(path.with_suffix(".lock")):
            if path.exists():
                existing = read_json(path)
                self._verify_operation(existing)
                if (
                    existing.get("operation_type") != operation_type
                    or existing.get("request_hash") != request_hash
                ):
                    raise StateConflictError(
                        "Idempotency key was already used for a different request"
                    )
                if existing["state"] == "SUCCEEDED":
                    return existing, False
                if existing["state"] == "RUNNING":
                    raise StateConflictError("Operation is already in progress")
                attempt = int(existing.get("attempt", 1)) + 1
            else:
                attempt = 1
            record = {
                "schema_version": "2.0",
                "contract_version": "durable-operation/1",
                "operation_id": stable_id(
                    "operation",
                    {
                        "idempotency_key_hash": content_hash(idempotency_key),
                        "operation_type": operation_type,
                        "request_hash": request_hash,
                    },
                ),
                "idempotency_key_hash": content_hash(idempotency_key),
                "operation_type": operation_type,
                "request_hash": request_hash,
                "state": "RUNNING",
                "attempt": attempt,
                "build_id": request.get("build_id"),
                "result": None,
                "error": None,
                "started_at": now_iso(),
                "completed_at": None,
            }
            record["content_hash"] = content_hash(record)
            atomic_write_json(path, record)
            return record, True

    @staticmethod
    def _verify_operation(operation: dict[str, Any]) -> None:
        expected = content_hash(
            {key: value for key, value in operation.items() if key != "content_hash"}
        )
        if operation.get("content_hash") != expected:
            raise ValidationError("Durable operation integrity failure")

    def finish_operation(
        self,
        operation: dict[str, Any],
        *,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        path = self.operations / (
            operation["idempotency_key_hash"].split(":", 1)[1] + ".json"
        )
        with self._file_lock(path.with_suffix(".lock")):
            current = read_json(path)
            self._verify_operation(current)
            if current.get("operation_id") != operation.get("operation_id"):
                raise StateConflictError("Durable operation identity changed")
            if current["state"] == "SUCCEEDED":
                return current
            current["state"] = "SUCCEEDED" if error is None else "FAILED"
            current["result"] = result
            current["error"] = error
            current["build_id"] = (
                (result or {}).get("build_id") or current.get("build_id")
            )
            current["completed_at"] = now_iso()
            current["content_hash"] = content_hash(
                {key: value for key, value in current.items() if key != "content_hash"}
            )
            atomic_write_json(path, current)
            return current

    def list_operations(self, build_id: str) -> list[dict[str, Any]]:
        if not self.operations.exists():
            return []
        values = []
        for path in sorted(self.operations.glob("*.json")):
            value = read_json(path)
            self._verify_operation(value)
            if value.get("build_id") == build_id:
                values.append(value)
        return values

    def list_builds(self) -> list[dict]:
        if not self.builds.exists():
            return []
        values = []
        for path in sorted(self.builds.glob("*/manifest.json")):
            manifest = self.load(path.parent.name)
            values.append(
                {
                    "build_id": manifest["build_id"],
                    "state": manifest["state"],
                    "profile": manifest["profile"],
                    "version": manifest["version"],
                }
            )
        return values
