"""Resolve the actual GitHub Environment reviewer for a workflow run."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from insynergy_cinematic.errors import AuthenticationError, PlatformError, ValidationError
from insynergy_cinematic.github_actions import (
    resolve_github_environment_policy,
    resolve_github_environment_review,
)
from insynergy_cinematic.util import atomic_write_json


API_VERSION = "2026-03-10"
MAX_RESPONSE_BYTES = 1_048_576


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--repository", required=True)
    value.add_argument("--run-id", required=True)
    value.add_argument("--run-attempt", required=True)
    value.add_argument("--environment", required=True)
    value.add_argument("--workflow-initiator", required=True)
    value.add_argument("--output", type=Path, required=True)
    value.add_argument("--github-output", type=Path)
    return value


def _github_json(path: str, token: str) -> object:
    url = f"https://api.github.com/{path}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "insynergy-cinematic-persona-approval",
            "X-GitHub-Api-Version": API_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise ValidationError(
            "GitHub approval metadata request failed",
            details={"status": exc.code},
        ) from exc
    except urllib.error.URLError as exc:
        raise ValidationError("GitHub approval metadata is unavailable") from exc
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ValidationError("GitHub approval metadata is too large")
    try:
        return json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("GitHub approval metadata is not JSON") from exc


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            raise AuthenticationError("GITHUB_TOKEN is required")
        environment_path = urllib.parse.quote(args.environment, safe="")
        configuration = _github_json(
            f"repos/{args.repository}/environments/{environment_path}", token
        )
        policy = resolve_github_environment_policy(
            configuration, environment=args.environment
        )
        approvals = _github_json(
            f"repos/{args.repository}/actions/runs/{args.run_id}/approvals", token
        )
        record = resolve_github_environment_review(
            approvals,
            repository=args.repository,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            environment=args.environment,
            workflow_initiator=args.workflow_initiator,
            require_distinct_reviewer=policy["prevent_self_review"],
            required_reviewer_ids=frozenset(
                reviewer["id"] for reviewer in policy["required_reviewers"]
            ),
            environment_policy_hash=policy["content_hash"],
        )
        atomic_write_json(args.output, record)
        if args.github_output:
            args.github_output.parent.mkdir(parents=True, exist_ok=True)
            with args.github_output.open("a", encoding="utf-8", newline="\n") as output:
                output.write(
                    f"environment_reviewer={record['environment_reviewer']}\n"
                )
                output.write(f"environment_review_hash={record['content_hash']}\n")
                output.write(
                    "prevent_self_review="
                    f"{'true' if record['prevent_self_review'] else 'false'}\n"
                )
        print(
            json.dumps(
                {
                    "passed": True,
                    "environment": record["environment"],
                    "environment_reviewer": record["environment_reviewer"],
                    "workflow_initiator": record["workflow_initiator"],
                    "content_hash": record["content_hash"],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except PlatformError as exc:
        print(json.dumps({"error": exc.as_dict()}, sort_keys=True, separators=(",", ":")))
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
