"""Validate a failed Storyboard Preview run before secretless recovery."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from insynergy_cinematic.errors import AuthenticationError, PlatformError, ValidationError
from insynergy_cinematic.github_actions import (
    validate_storyboard_preview_recovery_bundle,
)
from insynergy_cinematic.util import atomic_write_json


API_VERSION = "2026-03-10"
MAX_RESPONSE_BYTES = 1_048_576


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--repository", required=True)
    value.add_argument("--provider-run-id", required=True)
    value.add_argument("--planning-run-id", required=True)
    value.add_argument("--build-id", required=True)
    value.add_argument("--profile", required=True)
    value.add_argument("--root", type=Path, default=Path.cwd())
    value.add_argument("--output", type=Path, required=True)
    return value


def _github_json(path: str, token: str) -> object:
    request = urllib.request.Request(
        f"https://api.github.com/{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "insynergy-cinematic-preview-recovery",
            "X-GitHub-Api-Version": API_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise ValidationError(
            "GitHub Storyboard Preview recovery metadata request failed",
            details={"status": exc.code},
        ) from exc
    except urllib.error.URLError as exc:
        raise ValidationError(
            "GitHub Storyboard Preview recovery metadata is unavailable"
        ) from exc
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ValidationError("GitHub Storyboard Preview recovery metadata is too large")
    try:
        return json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "GitHub Storyboard Preview recovery metadata is not JSON"
        ) from exc


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            raise AuthenticationError("GITHUB_TOKEN is required")
        provider_run = _github_json(
            f"repos/{args.repository}/actions/runs/{args.provider_run_id}", token
        )
        planning_run = _github_json(
            f"repos/{args.repository}/actions/runs/{args.planning_run_id}", token
        )
        result = validate_storyboard_preview_recovery_bundle(
            root=args.root,
            repository=args.repository,
            provider_run_id=args.provider_run_id,
            planning_run_id=args.planning_run_id,
            build_id=args.build_id,
            profile=args.profile,
            provider_run=provider_run,
            planning_run=planning_run,
        )
        atomic_write_json(args.output, result)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except PlatformError as exc:
        print(json.dumps({"error": exc.as_dict()}, sort_keys=True, separators=(",", ":")))
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
