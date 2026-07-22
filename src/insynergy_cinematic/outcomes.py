"""Privacy-preserving longitudinal viewer outcomes and operational dashboard."""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import html
import math
import os
import re
import secrets
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from .errors import StateConflictError, ValidationError
from .storage import BuildRepository
from .util import atomic_write_json, atomic_write_text, canonical_json, content_hash, now_iso, read_json, stable_id


OUTCOME_CONTRACT_VERSION = "viewer-outcome/1"
DASHBOARD_CONTRACT_VERSION = "viewer-outcomes-dashboard/1"
REACTION_SUBJECTS = frozenset({"IDEA", "MEDIUM", "MIXED"})
ACCURACY_RESULTS = frozenset({"PASS", "FAIL"})
COHORT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
BUILD_ID = re.compile(r"^[0-9]{8}-[0-9]{3}$")


@dataclass(frozen=True)
class OutcomeThresholds:
    comprehension_accuracy: float = 0.80
    unaided_recall: float = 0.70
    minimum_retention_hours: float = 168.0
    minimum_sample_size: int = 5

    def validate(self) -> None:
        if not 0 <= self.comprehension_accuracy <= 1:
            raise ValidationError("Comprehension threshold must be between 0 and 1")
        if not 0 <= self.unaided_recall <= 1:
            raise ValidationError("Recall threshold must be between 0 and 1")
        if self.minimum_retention_hours < 1:
            raise ValidationError("Minimum retention interval must be positive")
        if self.minimum_sample_size < 1:
            raise ValidationError("Minimum sample size must be positive")


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValidationError("observed_at must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValidationError("observed_at must include a timezone")
    return parsed.astimezone(UTC)


def _ratio(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValidationError(f"{name} must be a number between 0 and 1")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be a number between 0 and 1") from exc
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValidationError(f"{name} must be a number between 0 and 1")
    return result


def _hours(value: Any) -> float:
    if isinstance(value, bool):
        raise ValidationError("retention_interval_hours must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("retention_interval_hours must be a finite number") from exc
    if not math.isfinite(result) or not 0 <= result <= 87_600:
        raise ValidationError("retention_interval_hours must be between 0 and 87600")
    return result


class ViewerOutcomeRepository:
    """Append immutable pseudonymous measurements to a hash-chained ledger."""

    def __init__(self, workspace: Path | str) -> None:
        self.workspace = Path(workspace).resolve()
        self.root = self.workspace / ".insynergy" / "outcomes"
        self.evaluations = self.root / "evaluations"
        self.ledger_path = self.root / "ledger.json"
        self.salt_path = self.root / ".viewer-token-key"
        self.lock_path = self.root / ".ledger.lock"
        self.builds = BuildRepository(self.workspace)
        self._thread_lock = threading.RLock()

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        with self._thread_lock:
            with self.lock_path.open("a+", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _token_key(self) -> bytes:
        if not self.salt_path.is_file():
            atomic_write_text(self.salt_path, secrets.token_hex(32) + "\n")
            os.chmod(self.salt_path, 0o600)
        try:
            return bytes.fromhex(self.salt_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError) as exc:
            raise ValidationError("Viewer token key is invalid") from exc

    def _viewer_token(self, viewer_id: str) -> str:
        normalized = viewer_id.strip()
        if not normalized or len(normalized.encode("utf-8")) > 256:
            raise ValidationError("viewer_id must be 1-256 UTF-8 bytes")
        digest = hmac.new(
            self._token_key(), normalized.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return f"viewer-hmac:{digest}"

    @staticmethod
    def _empty_ledger() -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": "1.0.0",
            "contract_version": "viewer-outcome-ledger/1",
            "version": 0,
            "entries": [],
        }
        value["content_hash"] = content_hash(value)
        return value

    @staticmethod
    def _validate_event(event: dict[str, Any]) -> None:
        required = {
            "schema_version",
            "contract_version",
            "evaluation_id",
            "build_id",
            "viewer_token",
            "cohort",
            "observed_at",
            "retention_interval_hours",
            "idea_restatement_accuracy",
            "unaided_recall",
            "reaction_subject",
            "accuracy_gate_result",
            "recorded_at",
            "content_hash",
        }
        if not isinstance(event, dict) or set(event) != required:
            raise ValidationError("Viewer outcome fields do not match the contract")
        if event["contract_version"] != OUTCOME_CONTRACT_VERSION:
            raise ValidationError("Viewer outcome contract version is unsupported")
        if not BUILD_ID.fullmatch(str(event["build_id"])):
            raise ValidationError("Viewer outcome build identity is invalid")
        if not str(event["viewer_token"]).startswith("viewer-hmac:"):
            raise ValidationError("Viewer outcome pseudonym is invalid")
        if not COHORT.fullmatch(str(event["cohort"])):
            raise ValidationError("Viewer outcome cohort is invalid")
        _parse_time(event["observed_at"])
        _parse_time(event["recorded_at"])
        _hours(event["retention_interval_hours"])
        _ratio(event["idea_restatement_accuracy"], "idea_restatement_accuracy")
        _ratio(event["unaided_recall"], "unaided_recall")
        if event["reaction_subject"] not in REACTION_SUBJECTS:
            raise ValidationError("reaction_subject is invalid")
        if event["accuracy_gate_result"] not in ACCURACY_RESULTS:
            raise ValidationError("accuracy_gate_result is invalid")
        expected = content_hash(
            {key: value for key, value in event.items() if key != "content_hash"}
        )
        if event["content_hash"] != expected:
            raise ValidationError("Viewer outcome integrity failure")

    def _load_ledger(self, *, verify_files: bool = True) -> dict[str, Any]:
        ledger = read_json(self.ledger_path) if self.ledger_path.is_file() else self._empty_ledger()
        if not isinstance(ledger, dict) or set(ledger) != {
            "schema_version",
            "contract_version",
            "version",
            "entries",
            "content_hash",
        }:
            raise ValidationError("Viewer outcome ledger fields are invalid")
        expected = content_hash(
            {key: value for key, value in ledger.items() if key != "content_hash"}
        )
        if ledger["content_hash"] != expected:
            raise ValidationError("Viewer outcome ledger integrity failure")
        entries = ledger["entries"]
        if not isinstance(entries, list) or ledger["version"] != len(entries):
            raise ValidationError("Viewer outcome ledger sequence is invalid")
        previous: str | None = None
        identities: set[str] = set()
        for sequence, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict) or set(entry) != {
                "sequence",
                "evaluation_id",
                "event_content_hash",
                "previous_entry_hash",
                "entry_hash",
            }:
                raise ValidationError("Viewer outcome ledger entry is invalid")
            expected_entry_hash = content_hash(
                {key: value for key, value in entry.items() if key != "entry_hash"}
            )
            if (
                entry["sequence"] != sequence
                or entry["previous_entry_hash"] != previous
                or entry["entry_hash"] != expected_entry_hash
                or entry["evaluation_id"] in identities
            ):
                raise ValidationError("Viewer outcome ledger chain is invalid")
            identities.add(entry["evaluation_id"])
            previous = entry["entry_hash"]
            if verify_files:
                path = self.evaluations / f"{entry['evaluation_id']}.json"
                if not path.is_file():
                    raise ValidationError("Viewer outcome ledger references a missing event")
                event = read_json(path)
                self._validate_event(event)
                if event["content_hash"] != entry["event_content_hash"]:
                    raise ValidationError("Viewer outcome ledger event hash mismatch")
        if verify_files and self.evaluations.exists():
            observed = {path.stem for path in self.evaluations.glob("*.json")}
            if observed != identities:
                raise ValidationError("Viewer outcome store contains unledgered events")
        return ledger

    def _append_entry(self, ledger: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        entries = list(ledger["entries"])
        previous = entries[-1]["entry_hash"] if entries else None
        entry = {
            "sequence": len(entries) + 1,
            "evaluation_id": event["evaluation_id"],
            "event_content_hash": event["content_hash"],
            "previous_entry_hash": previous,
        }
        entry["entry_hash"] = content_hash(entry)
        entries.append(entry)
        updated = {
            "schema_version": "1.0.0",
            "contract_version": "viewer-outcome-ledger/1",
            "version": len(entries),
            "entries": entries,
        }
        updated["content_hash"] = content_hash(updated)
        return updated

    def record(
        self,
        *,
        build_id: str,
        viewer_id: str,
        idea_restatement_accuracy: Any,
        unaided_recall: Any,
        reaction_subject: str,
        accuracy_gate_result: str,
        retention_interval_hours: Any,
        cohort: str = "all",
        observed_at: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if not BUILD_ID.fullmatch(build_id):
            raise ValidationError("build_id is invalid")
        self.builds.load(build_id)
        cohort = cohort.strip()
        if not COHORT.fullmatch(cohort):
            raise ValidationError("cohort must be a safe 1-64 character identifier")
        reaction = reaction_subject.strip().upper()
        accuracy = accuracy_gate_result.strip().upper()
        if reaction not in REACTION_SUBJECTS:
            raise ValidationError("reaction_subject must be IDEA, MEDIUM, or MIXED")
        if accuracy not in ACCURACY_RESULTS:
            raise ValidationError("accuracy_gate_result must be PASS or FAIL")
        observed = observed_at or now_iso()
        if _parse_time(observed) > datetime.now(UTC) + timedelta(minutes=5):
            raise ValidationError("observed_at cannot be in the future")
        restatement = _ratio(idea_restatement_accuracy, "idea_restatement_accuracy")
        recall = _ratio(unaided_recall, "unaided_recall")
        interval = _hours(retention_interval_hours)
        key = (idempotency_key or "").strip()
        if key and len(key.encode("utf-8")) > 256:
            raise ValidationError("idempotency key exceeds 256 UTF-8 bytes")

        with self._lock():
            viewer_token = self._viewer_token(viewer_id)
            identity = (
                {"idempotency_key": key, "build_id": build_id}
                if key
                else {
                    "build_id": build_id,
                    "viewer_token": viewer_token,
                    "observed_at": observed,
                    "retention_interval_hours": interval,
                }
            )
            evaluation_id = stable_id("VOE", identity, length=24)
            self.evaluations.mkdir(parents=True, exist_ok=True)
            path = self.evaluations / f"{evaluation_id}.json"
            if path.is_file() and observed_at is None:
                prior = read_json(path)
                self._validate_event(prior)
                observed = prior["observed_at"]
            event: dict[str, Any] = {
                "schema_version": "1.0.0",
                "contract_version": OUTCOME_CONTRACT_VERSION,
                "evaluation_id": evaluation_id,
                "build_id": build_id,
                "viewer_token": viewer_token,
                "cohort": cohort,
                "observed_at": observed,
                "retention_interval_hours": interval,
                "idea_restatement_accuracy": restatement,
                "unaided_recall": recall,
                "reaction_subject": reaction,
                "accuracy_gate_result": accuracy,
                "recorded_at": now_iso(),
            }
            event["content_hash"] = content_hash(event)
            ledger = self._load_ledger(verify_files=not path.exists())
            existing_ids = {entry["evaluation_id"] for entry in ledger["entries"]}
            created = True
            if path.is_file():
                existing = read_json(path)
                self._validate_event(existing)
                comparable = {
                    key: value for key, value in event.items() if key != "recorded_at"
                }
                existing_comparable = {
                    key: value for key, value in existing.items() if key != "recorded_at"
                }
                comparable["content_hash"] = None
                existing_comparable["content_hash"] = None
                if comparable != existing_comparable:
                    raise StateConflictError("Viewer outcome idempotency collision")
                event = existing
                created = False
            else:
                atomic_write_json(path, event)
            if evaluation_id not in existing_ids:
                ledger = self._append_entry(ledger, event)
                atomic_write_json(self.ledger_path, ledger)
            self._load_ledger(verify_files=True)
        return {
            "created": created,
            "evaluation_id": evaluation_id,
            "build_id": build_id,
            "content_hash": event["content_hash"],
            "privacy": "viewer_id_hmac_pseudonymized_and_not_returned",
        }

    def events(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        with self._lock():
            ledger = self._load_ledger(verify_files=True)
            values = [
                read_json(self.evaluations / f"{entry['evaluation_id']}.json")
                for entry in ledger["entries"]
            ]
        return values, ledger


def _wilson(successes: int, total: int) -> list[float] | None:
    if total == 0:
        return None
    z = 1.959963984540054
    ratio = successes / total
    denominator = 1 + z * z / total
    centre = (ratio + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((ratio * (1 - ratio) + z * z / (4 * total)) / total) / denominator
    return [round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4)]


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _classify(event: dict[str, Any], thresholds: OutcomeThresholds) -> str:
    comprehension = event["idea_restatement_accuracy"] >= thresholds.comprehension_accuracy
    eligible = event["retention_interval_hours"] >= thresholds.minimum_retention_hours
    retention = event["unaided_recall"] >= thresholds.unaided_recall
    decisive_failure = (
        not comprehension
        or event["reaction_subject"] != "IDEA"
        or event["accuracy_gate_result"] != "PASS"
        or (eligible and not retention)
    )
    if decisive_failure:
        return "FAIL"
    return "SUCCESS" if eligible else "PENDING_RETENTION"


def _aggregate(events: list[dict[str, Any]], thresholds: OutcomeThresholds) -> dict[str, Any]:
    comprehension = [
        event["idea_restatement_accuracy"] >= thresholds.comprehension_accuracy
        for event in events
    ]
    eligible = [
        event for event in events
        if event["retention_interval_hours"] >= thresholds.minimum_retention_hours
    ]
    retention = [event["unaided_recall"] >= thresholds.unaided_recall for event in eligible]
    medium_failures = sum(event["reaction_subject"] != "IDEA" for event in events)
    accuracy_failures = sum(event["accuracy_gate_result"] != "PASS" for event in events)
    outcomes = [_classify(event, thresholds) for event in events]
    failure_count = outcomes.count("FAIL")
    if failure_count:
        verdict = "FAIL"
    elif len(events) < thresholds.minimum_sample_size or len(eligible) < thresholds.minimum_sample_size:
        verdict = "INSUFFICIENT_EVIDENCE"
    else:
        verdict = "SUCCESS"
    comprehension_passes = sum(comprehension)
    retention_passes = sum(retention)
    return {
        "sample_size": len(events),
        "retention_eligible_sample_size": len(eligible),
        "verdict": verdict,
        "outcome_counts": {
            "success": outcomes.count("SUCCESS"),
            "pending_retention": outcomes.count("PENDING_RETENTION"),
            "fail": failure_count,
        },
        "idea_restatement_accuracy_mean": _average(
            [event["idea_restatement_accuracy"] for event in events]
        ),
        "comprehension_pass_rate": round(comprehension_passes / len(events), 4) if events else None,
        "comprehension_pass_rate_95ci": _wilson(comprehension_passes, len(events)),
        "unaided_recall_mean_long_term": _average(
            [event["unaided_recall"] for event in eligible]
        ),
        "retention_pass_rate": round(retention_passes / len(eligible), 4) if eligible else None,
        "retention_pass_rate_95ci": _wilson(retention_passes, len(eligible)),
        "medium_foregrounding_count": medium_failures,
        "medium_foregrounding_rate": round(medium_failures / len(events), 4) if events else None,
        "accuracy_gate_failure_count": accuracy_failures,
        "accuracy_gate_pass_rate": round((len(events) - accuracy_failures) / len(events), 4) if events else None,
    }


def _group(events: list[dict[str, Any]], field: str, thresholds: OutcomeThresholds) -> list[dict[str, Any]]:
    values: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        values.setdefault(str(event[field]), []).append(event)
    return [
        {field: name, **_aggregate(group, thresholds)}
        for name, group in sorted(values.items())
    ]


def _retention_buckets(events: list[dict[str, Any]], thresholds: OutcomeThresholds) -> list[dict[str, Any]]:
    definitions = (
        ("under_24h", 0, 24),
        ("1_to_6_days", 24, 168),
        ("7_to_29_days", 168, 720),
        ("30_days_plus", 720, float("inf")),
    )
    rows = []
    for name, lower, upper in definitions:
        group = [
            event for event in events
            if lower <= event["retention_interval_hours"] < upper
        ]
        passes = sum(event["unaided_recall"] >= thresholds.unaided_recall for event in group)
        rows.append(
            {
                "bucket": name,
                "sample_size": len(group),
                "unaided_recall_mean": _average([event["unaided_recall"] for event in group]),
                "recall_pass_rate": round(passes / len(group), 4) if group else None,
            }
        )
    return rows


class OutcomeDashboard:
    def __init__(self, workspace: Path | str) -> None:
        self.workspace = Path(workspace).resolve()
        self.repository = ViewerOutcomeRepository(self.workspace)

    def _engine_metrics(self, *, build_id: str | None = None) -> dict[str, Any]:
        repository = self.repository.builds
        listed = repository.list_builds()
        if build_id:
            listed = [item for item in listed if item["build_id"] == build_id]
        story_rows: list[dict[str, Any]] = []
        screenplay_rows: list[dict[str, Any]] = []
        for item in listed:
            manifest = repository.load(item["build_id"])
            repository.verify_artifacts(manifest)
            if "story_metrics" in manifest.get("artifacts", {}):
                document = repository.load_artifact(manifest, "story_metrics")
                story_rows.append(document.get("data", document))
            if "screenplay_metrics" in manifest.get("artifacts", {}):
                document = repository.load_artifact(manifest, "screenplay_metrics")
                screenplay_rows.append(document.get("data", document))

        def means(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> dict[str, Any]:
            return {
                field: _average(
                    [float(row[field]) for row in rows if isinstance(row.get(field), (int, float))]
                )
                for field in fields
            }

        return {
            "build_count": len(listed),
            "story": {
                "sample_size": len(story_rows),
                "means": means(
                    story_rows,
                    (
                        "dramatic_score",
                        "conflict_score",
                        "stakes_score",
                        "emotional_progression",
                        "concept_ratio",
                    ),
                ),
            },
            "screenplay": {
                "sample_size": len(screenplay_rows),
                "means": means(
                    screenplay_rows,
                    (
                        "scene_count",
                        "dialogue_ratio",
                        "action_ratio",
                        "average_scene_duration",
                        "continuity_score",
                    ),
                ),
            },
        }

    def report(
        self,
        *,
        build_id: str | None = None,
        window_days: int | None = None,
        thresholds: OutcomeThresholds | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        thresholds = thresholds or OutcomeThresholds()
        thresholds.validate()
        if build_id and not BUILD_ID.fullmatch(build_id):
            raise ValidationError("build_id filter is invalid")
        if window_days is not None and not 1 <= window_days <= 3650:
            raise ValidationError("window_days must be between 1 and 3650")
        now_value = _parse_time(generated_at or now_iso())
        events, ledger = self.repository.events()
        if build_id:
            events = [event for event in events if event["build_id"] == build_id]
        if window_days is not None:
            start = now_value - timedelta(days=window_days)
            events = [event for event in events if _parse_time(event["observed_at"]) >= start]
        by_month: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            month = _parse_time(event["observed_at"]).strftime("%Y-%m")
            by_month.setdefault(month, []).append(event)
        report: dict[str, Any] = {
            "schema_version": "1.0.0",
            "contract_version": DASHBOARD_CONTRACT_VERSION,
            "generated_at": now_value.isoformat().replace("+00:00", "Z"),
            "filters": {"build_id": build_id, "window_days": window_days},
            "thresholds": {
                "idea_restatement_accuracy": thresholds.comprehension_accuracy,
                "unaided_recall": thresholds.unaided_recall,
                "minimum_retention_hours": thresholds.minimum_retention_hours,
                "minimum_sample_size": thresholds.minimum_sample_size,
                "failure_policy": "any_decisive_failure_fails; success_requires_comprehension_and_long_term_retention",
            },
            "aggregate": _aggregate(events, thresholds),
            "by_build": _group(events, "build_id", thresholds),
            "by_cohort": _group(events, "cohort", thresholds),
            "by_month": [
                {"month": month, **_aggregate(group, thresholds)}
                for month, group in sorted(by_month.items())
            ],
            "retention_buckets": _retention_buckets(events, thresholds),
            "engine_metrics": self._engine_metrics(build_id=build_id),
            "integrity": {
                "ledger_version": ledger["version"],
                "ledger_content_hash": ledger["content_hash"],
                "verified": True,
            },
            "privacy": {
                "raw_viewer_identifiers_stored": False,
                "viewer_tokens_in_dashboard": False,
                "free_text_responses_stored": False,
                "aggregation_only": True,
            },
        }
        report["content_hash"] = content_hash(report)
        return report

    def render_html(self, report: dict[str, Any]) -> str:
        aggregate = report["aggregate"]

        def percentage(value: float | None) -> str:
            return "—" if value is None else f"{value * 100:.1f}%"

        def value_or_dash(value: Any) -> str:
            return "—" if value is None else html.escape(str(value))

        def bar(label: str, value: float | None, failure: bool = False) -> str:
            width = 0 if value is None else round(value * 100, 1)
            display = percentage(value)
            css = "failure" if failure else "success"
            return (
                f'<div class="metric"><div><span>{html.escape(label)}</span><strong>{display}</strong></div>'
                f'<div class="track"><i class="{css}" style="width:{width}%"></i></div></div>'
            )

        build_rows = "".join(
            "<tr>"
            f"<td>{html.escape(row['build_id'])}</td>"
            f"<td><span class=\"status {row['verdict'].lower()}\">{html.escape(row['verdict'])}</span></td>"
            f"<td>{row['sample_size']}</td>"
            f"<td>{percentage(row['comprehension_pass_rate'])}</td>"
            f"<td>{percentage(row['retention_pass_rate'])}</td>"
            f"<td>{percentage(row['medium_foregrounding_rate'])}</td>"
            "</tr>"
            for row in report["by_build"]
        ) or '<tr><td colspan="6" class="empty">No viewer outcomes in this window.</td></tr>'
        retention_rows = "".join(
            "<tr>"
            f"<td>{html.escape(row['bucket'].replace('_', ' '))}</td>"
            f"<td>{row['sample_size']}</td>"
            f"<td>{value_or_dash(row['unaided_recall_mean'])}</td>"
            f"<td>{percentage(row['recall_pass_rate'])}</td>"
            "</tr>"
            for row in report["retention_buckets"]
        )
        month_rows = "".join(
            "<tr>"
            f"<td>{html.escape(row['month'])}</td>"
            f"<td>{row['sample_size']}</td>"
            f"<td>{percentage(row['comprehension_pass_rate'])}</td>"
            f"<td>{percentage(row['retention_pass_rate'])}</td>"
            f"<td>{html.escape(row['verdict'])}</td>"
            "</tr>"
            for row in report["by_month"]
        ) or '<tr><td colspan="5" class="empty">No trend points yet.</td></tr>'
        engine = report["engine_metrics"]
        safe_json = canonical_json(report).replace("</", "<\\/")
        return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Insynergy Viewer Outcomes</title>
<style>
:root{{--ink:#121826;--muted:#667085;--paper:#f4f1ea;--card:#fff;--line:#ddd8cd;--teal:#177e89;--red:#b42318;--gold:#b7791f}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 Inter,ui-sans-serif,system-ui,sans-serif}}
main{{max-width:1180px;margin:auto;padding:42px 24px 72px}}header{{display:flex;justify-content:space-between;gap:24px;align-items:end;margin-bottom:26px}}
h1{{font:700 36px/1.05 Georgia,serif;margin:0 0 8px}}h2{{font:700 21px Georgia,serif;margin:0 0 16px}}p{{margin:0;color:var(--muted)}}
.verdict{{padding:11px 16px;border:1px solid var(--line);background:var(--card);font-weight:800;letter-spacing:.08em}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:20px 0}}.card,.panel{{background:var(--card);border:1px solid var(--line);box-shadow:0 5px 20px #1d293908}}
.card{{padding:18px}}.card small{{display:block;color:var(--muted)}}.card strong{{display:block;font:700 30px Georgia,serif;margin-top:6px}}
.columns{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:16px 0}}.panel{{padding:22px;overflow:auto}}
.metric{{margin:14px 0}}.metric>div:first-child{{display:flex;justify-content:space-between}}.track{{height:8px;background:#e8e5df;margin-top:7px}}.track i{{display:block;height:100%}}.success{{background:var(--teal)}}.failure{{background:var(--red)}}
table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}th,td{{padding:10px 9px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}th:first-child,td:first-child{{text-align:left}}th{{font-size:12px;text-transform:uppercase;color:var(--muted)}}
.status{{font-size:11px;font-weight:800;padding:4px 7px;background:#edf7f6;color:#0f646c}}.status.fail{{background:#fef3f2;color:var(--red)}}.status.insufficient_evidence{{background:#fffaeb;color:var(--gold)}}
.foot{{margin-top:18px;font-size:13px}}.empty{{text-align:center!important;color:var(--muted)}}code{{font-size:12px}}
@media(max-width:800px){{header{{display:block}}.verdict{{display:inline-block;margin-top:16px}}.grid,.columns{{grid-template-columns:1fr 1fr}}}}@media(max-width:520px){{.grid,.columns{{grid-template-columns:1fr}}}}
</style></head><body><main>
<header><div><p>INSYNERGY / OPERATIONAL EVIDENCE</p><h1>Viewer understanding & memory</h1><p>Longitudinal comprehension, unaided recall, reaction subject, and rigor.</p></div><div class="verdict">{html.escape(aggregate['verdict'])}</div></header>
<section class="grid">
<div class="card"><small>Viewer outcomes</small><strong>{aggregate['sample_size']}</strong></div>
<div class="card"><small>Long-term samples</small><strong>{aggregate['retention_eligible_sample_size']}</strong></div>
<div class="card"><small>Medium foregrounded</small><strong>{aggregate['medium_foregrounding_count']}</strong></div>
<div class="card"><small>Evaluated builds</small><strong>{len(report['by_build'])}</strong></div>
</section>
<section class="columns"><div class="panel"><h2>Success signals</h2>
{bar('Idea comprehension', aggregate['comprehension_pass_rate'])}
{bar('Long-term unaided recall', aggregate['retention_pass_rate'])}
{bar('Accuracy gate pass', aggregate['accuracy_gate_pass_rate'])}
{bar('Medium foregrounding', aggregate['medium_foregrounding_rate'], True)}
</div><div class="panel"><h2>Evidence sufficiency</h2><p>Success requires both comprehension and retention at or beyond {report['thresholds']['minimum_retention_hours']:.0f} hours, with at least {report['thresholds']['minimum_sample_size']} eligible measurements. Any misunderstanding, medium foregrounding, rigor loss, or eligible recall failure is decisive.</p><p class="foot">Ledger v{report['integrity']['ledger_version']} · <code>{html.escape(report['integrity']['ledger_content_hash'])}</code></p></div></section>
<section class="panel"><h2>Build outcomes</h2><table><thead><tr><th>Build</th><th>Verdict</th><th>n</th><th>Comprehension</th><th>Retention</th><th>Medium</th></tr></thead><tbody>{build_rows}</tbody></table></section>
<section class="columns"><div class="panel"><h2>Memory by interval</h2><table><thead><tr><th>Interval</th><th>n</th><th>Mean recall</th><th>Pass</th></tr></thead><tbody>{retention_rows}</tbody></table></div>
<div class="panel"><h2>Monthly trend</h2><table><thead><tr><th>Month</th><th>n</th><th>Comprehension</th><th>Retention</th><th>Verdict</th></tr></thead><tbody>{month_rows}</tbody></table></div></section>
<section class="panel"><h2>Production context</h2><p>{engine['build_count']} builds · Story metrics n={engine['story']['sample_size']} · Screenplay metrics n={engine['screenplay']['sample_size']}. Viewer outcomes govern success; production metrics remain diagnostic context.</p></section>
<p class="foot">Privacy: raw viewer identifiers and free-text responses are not stored. Dashboard data is aggregate-only. Generated {html.escape(report['generated_at'])}.</p>
<script type="application/json" id="dashboard-data">{safe_json}</script>
</main></body></html>"""

    def write(
        self,
        output: Path,
        *,
        json_output: Path | None = None,
        build_id: str | None = None,
        window_days: int | None = None,
        thresholds: OutcomeThresholds | None = None,
    ) -> dict[str, Any]:
        report = self.report(
            build_id=build_id,
            window_days=window_days,
            thresholds=thresholds,
        )
        output = output.resolve()
        atomic_write_text(output, self.render_html(report))
        if json_output is not None:
            atomic_write_json(json_output.resolve(), report)
        return report
