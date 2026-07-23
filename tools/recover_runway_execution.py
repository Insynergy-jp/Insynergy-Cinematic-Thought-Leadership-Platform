"""Recover safe Runway idempotency state from one trusted Execute run."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from insynergy_cinematic.errors import AuthenticationError, PlatformError, ValidationError
from insynergy_cinematic.util import atomic_write_json, content_hash, read_json


API_VERSION = "2026-03-10"
MAX_RESPONSE_BYTES = 1_048_576
MAX_STATE_BYTES = 1_048_576
WORKFLOW_NAME = "Execute Approved Plan"
WORKFLOW_PATH = ".github/workflows/execute.yml"
HASH = re.compile(r"sha256:[0-9a-f]{64}")
TASK_ID = re.compile(r"[A-Za-z0-9-]{1,128}")
REQUIRED_JOB_FIELDS = {
    "provider_task_id",
    "payload_hash",
    "attempt",
    "target_width",
    "target_height",
    "target_frame_rate",
    "duration_seconds",
    "native_width",
    "native_height",
}
OPTIONAL_JOB_FIELDS = {
    "provider_duration_seconds",
    "terminal_failure_class",
}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    commands = value.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--repository", required=True)
    inspect.add_argument("--run-id", required=True)
    inspect.add_argument("--github-output", type=Path)
    recover = commands.add_parser("recover")
    recover.add_argument("--source", type=Path, required=True)
    recover.add_argument("--target", type=Path, required=True)
    return value


def _github_run(repository: str, run_id: str, token: str) -> object:
    if not re.fullmatch(r"[0-9]+", run_id):
        raise ValidationError("Runway recovery run ID must be numeric")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/actions/runs/{run_id}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "insynergy-cinematic-runway-recovery",
            "X-GitHub-Api-Version": API_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise ValidationError(
            "Runway recovery metadata request failed",
            details={"status": exc.code},
        ) from exc
    except urllib.error.URLError as exc:
        raise ValidationError("Runway recovery metadata is unavailable") from exc
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ValidationError("Runway recovery metadata is too large")
    try:
        return json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("Runway recovery metadata is not JSON") from exc


def inspect_execution_recovery(
    metadata: object,
    *,
    repository: str,
    run_id: str,
) -> dict:
    if not isinstance(metadata, dict):
        raise ValidationError("Runway recovery metadata must be an object")
    try:
        numeric_run_id = int(run_id)
    except ValueError as exc:
        raise ValidationError("Runway recovery run ID must be numeric") from exc
    source_repository = metadata.get("repository")
    head_repository = metadata.get("head_repository")
    checks = {
        "run_id": metadata.get("id") == numeric_run_id,
        "workflow": metadata.get("name") == WORKFLOW_NAME,
        "workflow_path": metadata.get("path") == WORKFLOW_PATH,
        "event": metadata.get("event") == "workflow_dispatch",
        "status": metadata.get("status") == "completed",
        "conclusion": metadata.get("conclusion") in {"failure", "success"},
        "branch": metadata.get("head_branch") == "main",
        "repository": isinstance(source_repository, dict)
        and source_repository.get("full_name") == repository,
        "head_repository": isinstance(head_repository, dict)
        and head_repository.get("full_name") == repository,
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise ValidationError(
            "Runway recovery source is not a trusted main-branch Execute run",
            details={"failed_checks": failed},
        )
    source_sha = metadata.get("head_sha")
    if not isinstance(source_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValidationError("Runway recovery source SHA is invalid")
    conclusion = str(metadata["conclusion"])
    return {
        "passed": True,
        "repository": repository,
        "run_id": str(numeric_run_id),
        "workflow": WORKFLOW_NAME,
        "workflow_path": WORKFLOW_PATH,
        "source_sha": source_sha,
        "conclusion": conclusion,
        "artifact_name": (
            f"execution-diagnostics-{numeric_run_id}"
            if conclusion == "failure"
            else f"validated-{numeric_run_id}"
        ),
    }


def _positive_integer(value: object, *, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= maximum


def _valid_job(record: object) -> bool:
    if not isinstance(record, dict):
        return False
    fields = set(record)
    if not REQUIRED_JOB_FIELDS.issubset(fields) or not fields.issubset(
        REQUIRED_JOB_FIELDS | OPTIONAL_JOB_FIELDS
    ):
        return False
    duration = record.get("duration_seconds")
    provider_duration = record.get("provider_duration_seconds", duration)
    return all(
        (
            isinstance(record.get("provider_task_id"), str)
            and TASK_ID.fullmatch(record["provider_task_id"]) is not None,
            isinstance(record.get("payload_hash"), str)
            and HASH.fullmatch(record["payload_hash"]) is not None,
            _positive_integer(record.get("attempt"), maximum=10),
            _positive_integer(record.get("target_width"), maximum=8192),
            _positive_integer(record.get("target_height"), maximum=8192),
            _positive_integer(record.get("target_frame_rate"), maximum=120),
            isinstance(duration, (int, float))
            and not isinstance(duration, bool)
            and 2 <= float(duration) <= 10,
            _positive_integer(provider_duration, maximum=10)
            and 2 <= int(provider_duration) <= 10,
            _positive_integer(record.get("native_width"), maximum=8192),
            _positive_integer(record.get("native_height"), maximum=8192),
            record.get("terminal_failure_class") in {None, "transient", "permanent"},
        )
    )


def recover_runway_jobs(source: Path, target: Path) -> dict:
    if source.is_symlink() or not source.is_file():
        raise ValidationError("Runway recovery state is not a regular file")
    source = source.resolve()
    if source.stat().st_size > MAX_STATE_BYTES:
        raise ValidationError("Runway recovery state is too large")
    if target.exists() or target.is_symlink():
        raise ValidationError("Runway idempotency target already exists")
    target = target.resolve(strict=False)
    value = read_json(source)
    jobs = value.get("jobs") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "jobs"}
        or value.get("schema_version") != "1.0"
        or not isinstance(jobs, dict)
        or not 1 <= len(jobs) <= 100
        or not all(
            isinstance(key, str)
            and HASH.fullmatch(key) is not None
            and _valid_job(record)
            for key, record in jobs.items()
        )
    ):
        raise ValidationError("Runway recovery state contract is invalid")
    atomic_write_json(target, value)
    return {
        "passed": True,
        "recovered_jobs": len(jobs),
        "target": target.as_posix(),
        "state_hash": content_hash(value),
    }


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "inspect":
            token = os.environ.get("GITHUB_TOKEN", "")
            if not token:
                raise AuthenticationError("GITHUB_TOKEN is required")
            result = inspect_execution_recovery(
                _github_run(args.repository, args.run_id, token),
                repository=args.repository,
                run_id=args.run_id,
            )
            if args.github_output:
                args.github_output.parent.mkdir(parents=True, exist_ok=True)
                with args.github_output.open("a", encoding="utf-8", newline="\n") as output:
                    output.write(f"artifact_name={result['artifact_name']}\n")
                    output.write(f"source_sha={result['source_sha']}\n")
        else:
            result = recover_runway_jobs(args.source, args.target)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (OSError, json.JSONDecodeError) as exc:
        error = ValidationError("Runway recovery state could not be read")
        print(json.dumps({"error": error.as_dict()}, sort_keys=True, separators=(",", ":")))
        return error.exit_code
    except PlatformError as exc:
        print(json.dumps({"error": exc.as_dict()}, sort_keys=True, separators=(",", ":")))
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
