"""Create, verify, and summarize GitHub Actions transport evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from insynergy_cinematic.errors import PlatformError
from insynergy_cinematic.github_actions import (
    create_workflow_evidence,
    verify_workflow_evidence,
    workflow_summary,
)
from insynergy_cinematic.util import read_json


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--root", type=Path, default=Path.cwd())
    commands = value.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--stage", required=True)
    create.add_argument("--build-id", required=True)
    create.add_argument("--profile", required=True)
    create.add_argument("--workflow", required=True)
    create.add_argument("--repository", required=True)
    create.add_argument("--run-id", required=True)
    create.add_argument("--run-attempt", required=True)
    create.add_argument("--source-sha", required=True)
    create.add_argument("paths", type=Path, nargs="+")

    verify = commands.add_parser("verify")
    verify.add_argument("--evidence", type=Path, required=True)
    verify.add_argument("--stage", required=True)
    verify.add_argument("--build-id", required=True)
    verify.add_argument("--profile", required=True)
    verify.add_argument("--workflow", required=True)
    verify.add_argument("--repository", required=True)
    verify.add_argument("--run-id", required=True)
    verify.add_argument("--source-sha", required=True)

    summary = commands.add_parser("summary")
    summary.add_argument("--evidence", type=Path, required=True)
    summary.add_argument("--result", type=Path)
    summary.add_argument("--output", type=Path)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "create":
            result = create_workflow_evidence(
                root=root,
                paths=args.paths,
                output=args.output,
                stage=args.stage,
                build_id=args.build_id,
                profile=args.profile,
                workflow=args.workflow,
                repository=args.repository,
                run_id=args.run_id,
                run_attempt=args.run_attempt,
                source_sha=args.source_sha,
            )
            output: object = {
                "passed": True,
                "bundle_hash": result["bundle_hash"],
                "evidence_hash": result["evidence_hash"],
                "file_count": len(result["files"]),
            }
        elif args.command == "verify":
            output = verify_workflow_evidence(
                args.evidence,
                root=root,
                expected_stage=args.stage,
                expected_build_id=args.build_id,
                expected_profile=args.profile,
                expected_workflow=args.workflow,
                expected_repository=args.repository,
                expected_run_id=args.run_id,
                expected_source_sha=args.source_sha,
            )
        else:
            evidence = read_json(root / args.evidence)
            result = read_json(root / args.result) if args.result else None
            markdown = workflow_summary(evidence, result=result)
            destination = args.output or (
                Path(os.environ["GITHUB_STEP_SUMMARY"])
                if os.environ.get("GITHUB_STEP_SUMMARY")
                else None
            )
            if destination:
                with destination.open("a", encoding="utf-8") as handle:
                    handle.write(markdown)
            output = {"passed": True, "summary": markdown}
        print(json.dumps(output, sort_keys=True, separators=(",", ":")))
        return 0
    except PlatformError as exc:
        print(json.dumps({"error": exc.as_dict()}, sort_keys=True, separators=(",", ":")))
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
