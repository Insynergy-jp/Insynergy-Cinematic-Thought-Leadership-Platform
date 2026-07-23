"""Attest that a newer execution runtime does not change approved creative inputs."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from insynergy_cinematic.errors import PlatformError, ValidationError
from insynergy_cinematic.util import content_hash


COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
ALLOWED_RUNTIME_CHANGES = frozenset(
    {
        ".github/workflows/execute.yml",
        ".github/workflows/plan.yml",
        "src/insynergy_cinematic/prompt.py",
        "src/insynergy_cinematic/rendering.py",
        "tests/test_prompt_transport.py",
        "tests/test_runtime_compatibility.py",
        "tests/test_workflow_recovery.py",
        "tools/github_planning_source.py",
        "tools/recover_planning_evidence.py",
        "tools/verify_runtime_compatibility.py",
    }
)
ALLOWED_STATUSES = frozenset({"A", "M"})
REQUIRED_RUNTIME_CHANGES = {
    ".github/workflows/execute.yml": "M",
    "src/insynergy_cinematic/prompt.py": "M",
    "src/insynergy_cinematic/rendering.py": "M",
}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--root", type=Path, default=Path.cwd())
    value.add_argument("--planning-source-sha", required=True)
    value.add_argument("--execution-source-sha", required=True)
    return value


def _git(
    root: Path, *arguments: str, check: bool = True
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=check,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        stderr = ""
        if isinstance(exc, subprocess.CalledProcessError):
            stderr = exc.stderr.decode("utf-8", errors="replace").strip()
        raise ValidationError(
            "Runtime compatibility Git inspection failed",
            details={"operation": " ".join(arguments), "stderr": stderr},
        ) from exc


def _verified_commit(root: Path, name: str, value: str) -> str:
    if not COMMIT_SHA.fullmatch(value):
        raise ValidationError(f"{name} must be a full lowercase commit SHA")
    result = _git(root, "rev-parse", "--verify", f"{value}^{{commit}}")
    resolved = result.stdout.decode("ascii").strip()
    if resolved != value:
        raise ValidationError(
            f"{name} does not resolve exactly",
            details={"expected": value, "actual": resolved},
        )
    return resolved


def _changes(root: Path, planning_sha: str, execution_sha: str) -> list[dict[str, str]]:
    result = _git(
        root,
        "diff",
        "--name-status",
        "-z",
        "--no-renames",
        planning_sha,
        execution_sha,
        "--",
    )
    fields = result.stdout.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    if len(fields) % 2:
        raise ValidationError("Runtime compatibility Git diff is malformed")
    changes: list[dict[str, str]] = []
    for index in range(0, len(fields), 2):
        try:
            status = fields[index].decode("ascii")
            path = fields[index + 1].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError("Runtime compatibility Git diff is not UTF-8") from exc
        changes.append({"status": status, "path": path})
    return changes


def verify_runtime_compatibility(
    *,
    root: Path,
    planning_source_sha: str,
    execution_source_sha: str,
) -> dict:
    root = root.resolve()
    if not (root / ".git").exists():
        raise ValidationError("Runtime compatibility root is not a Git checkout")
    planning_sha = _verified_commit(root, "planning_source_sha", planning_source_sha)
    execution_sha = _verified_commit(root, "execution_source_sha", execution_source_sha)
    ancestry = _git(
        root,
        "merge-base",
        "--is-ancestor",
        planning_sha,
        execution_sha,
        check=False,
    )
    if ancestry.returncode != 0:
        raise ValidationError(
            "Execution source does not descend from the approved planning source",
            details={
                "planning_source_sha": planning_sha,
                "execution_source_sha": execution_sha,
            },
        )

    changes = _changes(root, planning_sha, execution_sha)
    invalid = [
        change
        for change in changes
        if change["status"] not in ALLOWED_STATUSES
        or change["path"] not in ALLOWED_RUNTIME_CHANGES
    ]
    if invalid:
        raise ValidationError(
            "Execution source contains changes outside the approved recovery runtime",
            details={"invalid_changes": invalid},
        )
    observed = {change["path"]: change["status"] for change in changes}
    missing_required = [
        {"status": status, "path": path}
        for path, status in sorted(REQUIRED_RUNTIME_CHANGES.items())
        if observed.get(path) != status
    ]
    if missing_required:
        raise ValidationError(
            "Execution source is missing required recovery runtime changes",
            details={"missing_required_changes": missing_required},
        )

    result = {
        "contract_version": "planning-runtime-compatibility/1",
        "passed": True,
        "planning_source_sha": planning_sha,
        "execution_source_sha": execution_sha,
        "changes": changes,
    }
    result["diff_hash"] = content_hash(result)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = verify_runtime_compatibility(
            root=args.root,
            planning_source_sha=args.planning_source_sha,
            execution_source_sha=args.execution_source_sha,
        )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except PlatformError as exc:
        print(json.dumps({"error": exc.as_dict()}, sort_keys=True, separators=(",", ":")))
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
