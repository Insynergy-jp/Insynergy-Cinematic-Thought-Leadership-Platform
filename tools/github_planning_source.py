"""Resolve and validate the source revision of an approved planning run."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from insynergy_cinematic.errors import AuthenticationError, PlatformError, ValidationError


API_VERSION = "2026-03-10"
MAX_RESPONSE_BYTES = 1_048_576
WORKFLOW_PATHS = {
    "Plan Article": ".github/workflows/plan.yml",
    "Storyboard Preview": ".github/workflows/preview.yml",
}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--repository", required=True)
    value.add_argument("--run-id", required=True)
    value.add_argument("--workflow", choices=tuple(WORKFLOW_PATHS), required=True)
    value.add_argument("--github-output", type=Path)
    return value


def _github_run(repository: str, run_id: str, token: str) -> object:
    if not re.fullmatch(r"[0-9]+", run_id):
        raise ValidationError("Planning run ID must be numeric")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/actions/runs/{run_id}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "insynergy-cinematic-planning-source",
            "X-GitHub-Api-Version": API_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise ValidationError(
            "Planning run metadata request failed",
            details={"status": exc.code},
        ) from exc
    except urllib.error.URLError as exc:
        raise ValidationError("Planning run metadata is unavailable") from exc
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ValidationError("Planning run metadata is too large")
    try:
        return json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("Planning run metadata is not JSON") from exc


def resolve_planning_source(
    metadata: object,
    *,
    repository: str,
    run_id: str,
    workflow: str,
) -> dict:
    if not isinstance(metadata, dict):
        raise ValidationError("Planning run metadata must be an object")
    if workflow not in WORKFLOW_PATHS:
        raise ValidationError("Planning source workflow is not allowed")
    try:
        numeric_run_id = int(run_id)
    except ValueError as exc:
        raise ValidationError("Planning run ID must be numeric") from exc
    expected_path = WORKFLOW_PATHS[workflow]
    source_repository = metadata.get("repository")
    head_repository = metadata.get("head_repository")
    checks = {
        "run_id": metadata.get("id") == numeric_run_id,
        "workflow": metadata.get("name") == workflow,
        "workflow_path": metadata.get("path") == expected_path,
        "event": metadata.get("event") == "workflow_dispatch",
        "status": metadata.get("status") == "completed",
        "conclusion": metadata.get("conclusion") == "success",
        "branch": metadata.get("head_branch") == "main",
        "repository": isinstance(source_repository, dict)
        and source_repository.get("full_name") == repository,
        "head_repository": isinstance(head_repository, dict)
        and head_repository.get("full_name") == repository,
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise ValidationError(
            "Planning run is not an approved same-repository main-branch source",
            details={"failed_checks": failed},
        )
    source_sha = metadata.get("head_sha")
    if not isinstance(source_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValidationError("Planning source SHA is invalid")
    return {
        "passed": True,
        "repository": repository,
        "run_id": str(numeric_run_id),
        "workflow": workflow,
        "workflow_path": expected_path,
        "source_sha": source_sha,
    }


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            raise AuthenticationError("GITHUB_TOKEN is required")
        result = resolve_planning_source(
            _github_run(args.repository, args.run_id, token),
            repository=args.repository,
            run_id=args.run_id,
            workflow=args.workflow,
        )
        if args.github_output:
            args.github_output.parent.mkdir(parents=True, exist_ok=True)
            with args.github_output.open("a", encoding="utf-8", newline="\n") as output:
                output.write(f"source_sha={result['source_sha']}\n")
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except PlatformError as exc:
        print(json.dumps({"error": exc.as_dict()}, sort_keys=True, separators=(",", ":")))
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
