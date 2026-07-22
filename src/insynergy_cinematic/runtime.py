"""Durable runtime control primitives for Part 6 orchestration.

The queue is deliberately non-authoritative: it records delivery and lease reality,
while the Build Manifest remains the source of execution intent.  A new execution
generation fences leases from an interrupted runner and preserves terminal work.
"""

from __future__ import annotations

import fcntl
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .errors import StateConflictError, ValidationError
from .util import atomic_write_json, content_hash, now_iso, read_json, stable_id


TERMINAL_TASK_STATES = {"COMPLETED", "CACHED", "FAILED", "CANCELLED"}


def part6_coverage_report() -> dict[str, Any]:
    """Return the normalized Part 6 implementation-coverage evidence matrix."""
    full = [
        ("performance_budgets", "sealed performance-budget artifact and budget preflight"),
        ("profiles_and_config", "immutable performance-config and build-profile artifacts"),
        ("plan_and_dependencies", "execution-plan plus acyclic dependency-graph artifacts"),
        ("cas_and_incremental", "content-addressed artifacts and exact render/review reuse"),
        ("manifest_and_state", "single-writer Manifest CAS and guarded state transitions"),
        ("durable_queue", "file-backed task intent with at-least-once delivery semantics"),
        ("worker_fencing", "execution generations and lease-token completion guards"),
        ("provider_idempotency", "durable provider task identity and replay protection"),
        ("checkpoint_and_recovery", "content-addressed checkpoints and recovery plans"),
        ("backpressure", "global/provider concurrency and budget admission limits"),
        ("event_model", "ordered, deduplicated, hash-chained runtime events"),
        ("observability", "queue, Manifest, checkpoint, operation, and recovery views"),
        ("security_boundaries", "secret-free snapshots and provider/job credential isolation"),
        ("public_interfaces", "CLI/API inspect, verify, recover, pause, resume, and cancel"),
        ("automated_invariants", "runtime concurrency, tamper, recovery, and E2E tests"),
    ]
    partial = [
        ("retry_and_failure", "classified provider retry exists; orchestration-wide policy is incomplete"),
        ("graceful_shutdown", "pause/cancel checkpoints exist; process signal draining is incomplete"),
        ("acceptance_evidence", "machine verification exists; live load/security evidence remains external"),
        ("cross_runner_compatibility", "portable files and fencing exist; distributed soak proof is absent"),
    ]
    missing = [
        ("compensation_and_rollback", "no general compensating-action engine"),
        ("production_transition", "no staged shadow/pilot/general-production handover engine"),
    ]
    rows = [
        *(
            {"cluster": cluster, "status": "FULL", "evidence": evidence}
            for cluster, evidence in full
        ),
        *(
            {"cluster": cluster, "status": "PARTIAL", "evidence": evidence}
            for cluster, evidence in partial
        ),
        *(
            {"cluster": cluster, "status": "MISSING", "evidence": evidence}
            for cluster, evidence in missing
        ),
    ]
    points = len(full) + len(partial) * 0.5
    return {
        "method": "FULL=1, PARTIAL=0.5, MISSING=0",
        "cluster_count": len(rows),
        "full": len(full),
        "partial": len(partial),
        "missing": len(missing),
        "points": points,
        "coverage_percent": round(points / len(rows) * 100, 1),
        "clusters": rows,
    }


class DurableTaskQueue:
    """File-backed at-least-once queue with fenced, idempotent completion."""

    def __init__(
        self,
        path: Path,
        *,
        build_id: str,
        max_in_flight: int,
        provider_limits: dict[str, int],
        budget_usd: float,
    ) -> None:
        if max_in_flight < 1 or budget_usd < 0:
            raise ValidationError("Runtime queue limits are invalid")
        if not provider_limits or any(value < 1 for value in provider_limits.values()):
            raise ValidationError("Every runtime provider limit must be positive")
        self.path = path
        self.build_id = build_id
        self.max_in_flight = max_in_flight
        self.provider_limits = dict(sorted(provider_limits.items()))
        self.budget_usd = budget_usd
        self._thread_lock = threading.RLock()

    @property
    def lock_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".lock")

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._thread_lock:
            with self.lock_path.open("a+", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _empty(self) -> dict[str, Any]:
        return {
            "schema_version": "2.0",
            "contract_version": "durable-task-queue/1",
            "build_id": self.build_id,
            "generation": 0,
            "accepting_dispatch": True,
            "limits": {
                "max_in_flight": self.max_in_flight,
                "provider_limits": self.provider_limits,
                "budget_usd": self.budget_usd,
            },
            "tasks": {},
            "metrics": {
                "recoveries": 0,
                "backpressure_deferrals": 0,
                "duplicate_completions": 0,
            },
            "events": [],
            "updated_at": now_iso(),
        }

    def _load_unlocked(self) -> dict[str, Any]:
        document = read_json(self.path) if self.path.exists() else self._empty()
        self._verify(document)
        return document

    def _write_unlocked(self, document: dict[str, Any]) -> None:
        document["updated_at"] = now_iso()
        document["content_hash"] = content_hash(
            {key: value for key, value in document.items() if key != "content_hash"}
        )
        atomic_write_json(self.path, document)

    @staticmethod
    def _event(document: dict[str, Any], event_type: str, payload: dict[str, Any]) -> None:
        previous = (
            document["events"][-1]["event_hash"] if document["events"] else None
        )
        event = {
            "sequence": len(document["events"]) + 1,
            "event_type": event_type,
            "occurred_at": now_iso(),
            "previous_event_hash": previous,
            "payload": payload,
        }
        event["event_id"] = stable_id(
            "queue-event", {"previous": previous, "event": event}
        )
        event["event_hash"] = content_hash(event)
        document["events"].append(event)

    def initialize(
        self,
        requests: list[dict[str, Any]],
        *,
        generation: int,
    ) -> dict[str, Any]:
        """Register immutable task intent and fence unfinished prior leases."""
        if generation < 1:
            raise ValidationError("Execution generation must be positive")
        request_ids = {str(value["render_task_id"]) for value in requests}
        if len(request_ids) != len(requests):
            raise ValidationError("Runtime queue contains duplicate task identities")
        with self._locked():
            document = self._load_unlocked()
            existing_ids = set(document["tasks"])
            if existing_ids and existing_ids != request_ids:
                raise StateConflictError(
                    "Runtime task intent changed for an existing build",
                    details={
                        "existing": sorted(existing_ids),
                        "requested": sorted(request_ids),
                    },
                )
            if generation < int(document["generation"]):
                raise StateConflictError("Execution generation is stale")
            if generation > int(document["generation"]):
                recovered = 0
                for task in document["tasks"].values():
                    if task["state"] not in TERMINAL_TASK_STATES:
                        task["state"] = "READY"
                        task["lease"] = None
                        task["last_deferred_reason"] = None
                        recovered += 1
                if document["generation"]:
                    document["metrics"]["recoveries"] += 1
                document["generation"] = generation
                document["accepting_dispatch"] = True
                self._event(
                    document,
                    "GENERATION_STARTED",
                    {"generation": generation, "recovered_tasks": recovered},
                )
            for request in requests:
                task_id = str(request["render_task_id"])
                identity = {
                    "render_task_id": task_id,
                    "shot_id": str(request["shot_id"]),
                    "provider": str(request["provider"]),
                    "cache_key": str(request["cache_key"]),
                }
                existing = document["tasks"].get(task_id)
                if existing:
                    if any(existing[key] != value for key, value in identity.items()):
                        raise StateConflictError(
                            f"Runtime task identity changed: {task_id}"
                        )
                    continue
                document["tasks"][task_id] = {
                    **identity,
                    "state": "READY",
                    "generation": generation,
                    "lease": None,
                    "claim_count": 0,
                    "delivery_count": 0,
                    "estimated_cost_usd": float(
                        request.get("estimated_cost_usd", 0.0)
                    ),
                    "result_hash": None,
                    "last_error": None,
                    "last_deferred_reason": None,
                }
                self._event(document, "TASK_REGISTERED", identity)
            estimated = sum(
                float(task["estimated_cost_usd"])
                for task in document["tasks"].values()
            )
            if estimated > self.budget_usd:
                raise ValidationError(
                    "Runtime queue budget reservation exceeds the build budget"
                )
            self._write_unlocked(document)
            return self._snapshot(document)

    def claim(self, task_id: str, *, worker_id: str) -> dict[str, Any]:
        """Claim one task or return an explicit replay/backpressure outcome."""
        with self._locked():
            document = self._load_unlocked()
            task = document["tasks"].get(task_id)
            if not task:
                raise ValidationError(f"Unknown runtime task: {task_id}")
            task["delivery_count"] += 1
            if task["state"] in TERMINAL_TASK_STATES:
                outcome = {
                    "outcome": "ALREADY_TERMINAL",
                    "state": task["state"],
                    "result_hash": task["result_hash"],
                }
                self._write_unlocked(document)
                return outcome
            if not document["accepting_dispatch"]:
                return self._defer(document, task, "QUEUE_PAUSED")
            if task["state"] == "LEASED":
                return self._defer(document, task, "TASK_ALREADY_LEASED")
            leased = [
                value for value in document["tasks"].values()
                if value["state"] == "LEASED"
            ]
            if len(leased) >= self.max_in_flight:
                return self._defer(document, task, "GLOBAL_CAPACITY")
            provider_in_flight = sum(
                value["state"] == "LEASED"
                and value["provider"] == task["provider"]
                for value in document["tasks"].values()
            )
            provider_limit = self.provider_limits.get(
                task["provider"], self.max_in_flight
            )
            if provider_in_flight >= provider_limit:
                return self._defer(document, task, "PROVIDER_CAPACITY")
            task["claim_count"] += 1
            lease_id = stable_id(
                "lease",
                {
                    "task_id": task_id,
                    "generation": document["generation"],
                    "claim_count": task["claim_count"],
                    "worker_id": worker_id,
                },
            )
            task["state"] = "LEASED"
            task["generation"] = document["generation"]
            task["lease"] = {
                "lease_id": lease_id,
                "worker_id": worker_id,
                "generation": document["generation"],
                "claimed_at": now_iso(),
            }
            task["last_deferred_reason"] = None
            self._event(
                document,
                "TASK_CLAIMED",
                {"task_id": task_id, "lease_id": lease_id, "worker_id": worker_id},
            )
            self._write_unlocked(document)
            return {"outcome": "CLAIMED", **task["lease"]}

    def _defer(
        self, document: dict[str, Any], task: dict[str, Any], reason: str
    ) -> dict[str, Any]:
        document["metrics"]["backpressure_deferrals"] += 1
        task["last_deferred_reason"] = reason
        self._event(
            document,
            "TASK_DEFERRED",
            {"task_id": task["render_task_id"], "reason": reason},
        )
        self._write_unlocked(document)
        return {"outcome": "DEFERRED", "reason": reason}

    def complete(
        self,
        task_id: str,
        *,
        lease_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        result_hash = content_hash(result)
        with self._locked():
            document = self._load_unlocked()
            task = document["tasks"].get(task_id)
            if not task:
                raise ValidationError(f"Unknown runtime task: {task_id}")
            if task["state"] in TERMINAL_TASK_STATES:
                if task["result_hash"] != result_hash:
                    raise StateConflictError(
                        f"Conflicting duplicate completion: {task_id}"
                    )
                document["metrics"]["duplicate_completions"] += 1
                self._write_unlocked(document)
                return {"outcome": "ALREADY_RECORDED", "state": task["state"]}
            lease = task.get("lease") or {}
            if (
                task["state"] != "LEASED"
                or lease.get("lease_id") != lease_id
                or lease.get("generation") != document["generation"]
            ):
                raise StateConflictError(
                    f"Runtime completion has a stale or invalid lease: {task_id}"
                )
            result_state = str(result.get("state", "FAILED"))
            task["state"] = (
                result_state
                if result_state in {"COMPLETED", "CACHED"}
                else "FAILED"
            )
            task["result_hash"] = result_hash
            task["last_error"] = result.get("error")
            task["lease"] = None
            self._event(
                document,
                "TASK_COMPLETED" if task["state"] != "FAILED" else "TASK_FAILED",
                {
                    "task_id": task_id,
                    "state": task["state"],
                    "result_hash": result_hash,
                },
            )
            self._write_unlocked(document)
            return {"outcome": "RECORDED", "state": task["state"]}

    def pause(self) -> dict[str, Any]:
        with self._locked():
            document = self._load_unlocked()
            document["accepting_dispatch"] = False
            self._event(document, "QUEUE_PAUSED", {})
            self._write_unlocked(document)
            return self._snapshot(document)

    def cancel_pending(self) -> dict[str, Any]:
        with self._locked():
            document = self._load_unlocked()
            document["accepting_dispatch"] = False
            cancelled = 0
            for task in document["tasks"].values():
                if task["state"] not in TERMINAL_TASK_STATES:
                    task["state"] = "CANCELLED"
                    task["lease"] = None
                    cancelled += 1
            self._event(document, "QUEUE_CANCELLED", {"cancelled": cancelled})
            self._write_unlocked(document)
            return self._snapshot(document)

    def snapshot(self) -> dict[str, Any]:
        with self._locked():
            return self._snapshot(self._load_unlocked())

    @staticmethod
    def _snapshot(document: dict[str, Any]) -> dict[str, Any]:
        counts: dict[str, int] = {}
        providers: dict[str, dict[str, int]] = {}
        for task in document["tasks"].values():
            counts[task["state"]] = counts.get(task["state"], 0) + 1
            provider_counts = providers.setdefault(task["provider"], {})
            provider_counts[task["state"]] = provider_counts.get(task["state"], 0) + 1
        value = {
            "schema_version": document["schema_version"],
            "contract_version": document["contract_version"],
            "build_id": document["build_id"],
            "generation": document["generation"],
            "accepting_dispatch": document["accepting_dispatch"],
            "limits": document["limits"],
            "task_count": len(document["tasks"]),
            "state_counts": dict(sorted(counts.items())),
            "provider_state_counts": {
                key: dict(sorted(value.items()))
                for key, value in sorted(providers.items())
            },
            "metrics": document["metrics"],
            "event_count": len(document["events"]),
            "updated_at": document["updated_at"],
        }
        value["content_hash"] = content_hash(value)
        return value

    def verify(self) -> dict[str, Any]:
        with self._locked():
            document = self._load_unlocked()
            return {
                "valid": True,
                "content_hash": document.get("content_hash"),
                "snapshot": self._snapshot(document),
            }

    def _verify(self, document: dict[str, Any]) -> None:
        if document.get("build_id") != self.build_id:
            raise ValidationError("Runtime queue belongs to another build")
        if document.get("contract_version") != "durable-task-queue/1":
            raise ValidationError("Unsupported runtime queue contract")
        expected_limits = {
            "max_in_flight": self.max_in_flight,
            "provider_limits": self.provider_limits,
            "budget_usd": self.budget_usd,
        }
        if document.get("limits") != expected_limits:
            raise ValidationError("Runtime queue limits differ from the sealed configuration")
        expected = document.get("content_hash")
        if expected and expected != content_hash(
            {key: value for key, value in document.items() if key != "content_hash"}
        ):
            raise ValidationError("Runtime queue integrity failure")
        previous: str | None = None
        for sequence, event in enumerate(document.get("events", []), start=1):
            if event.get("sequence") != sequence:
                raise ValidationError("Runtime queue event sequence is invalid")
            if event.get("previous_event_hash") != previous:
                raise ValidationError("Runtime queue event chain is invalid")
            event_hash = event.get("event_hash")
            if event_hash != content_hash(
                {key: value for key, value in event.items() if key != "event_hash"}
            ):
                raise ValidationError("Runtime queue event integrity failure")
            previous = event_hash
