"""Canonical command-line adapter."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .api import serve
from .errors import PlatformError
from .orchestrator import BuildOrchestrator
from .schemas import export_schemas


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="insynergy-cinematic",
        description="Insynergy Cinematic Thought Leadership Platform v3",
    )
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path)
    parser.add_argument("--profile", choices=("draft", "preview", "final"))
    parser.add_argument("--provider", choices=("local", "runway"))
    parser.add_argument("--runway-scope", choices=("hybrid", "all_shots"))
    parser.add_argument("--narration-provider", choices=("offline", "openai"))
    parser.add_argument("--agent-review-mode", choices=("off", "review"))
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Generate and gate all planning artifacts")
    plan.add_argument("article", type=Path)

    review = sub.add_parser(
        "agent-review",
        aliases=("review",),
        help="Run the read-only Agent Review job",
    )
    review.add_argument("build_id")

    build = sub.add_parser("build", help="Run the complete build pipeline")
    build.add_argument("article", type=Path)
    build.add_argument("--auto-approve", action="store_true")
    build.add_argument("--actor", default="local-operator")

    approve = sub.add_parser("approve", help="Record a scoped human approval")
    approve.add_argument("build_id")
    approve.add_argument("--gate", choices=("execution", "publish"), required=True)
    approve.add_argument("--actor", required=True)
    approve.add_argument("--decision", choices=("APPROVED", "REJECTED"), default="APPROVED")
    approve.add_argument("--comment", default="")
    approve.add_argument("--allow-agent-exception", action="store_true")
    approve.add_argument("--agent-exception-reason", default="")

    for name in ("execute", "publish", "status", "pause", "resume", "cancel"):
        command = sub.add_parser(name)
        command.add_argument("build_id")

    sub.add_parser("list", help="List builds")
    sub.add_parser("health", help="Show dependency readiness")
    schema = sub.add_parser("export-schemas", help="Export Part 9 JSON Schemas")
    schema.add_argument("destination", type=Path, nargs="?", default=Path("schemas"))
    server = sub.add_parser("serve", help="Serve the /api/v2 HTTP JSON API")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8080)
    return parser


def _emit(value: Any, compact: bool) -> None:
    print(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=None if compact else 2,
            separators=(",", ":") if compact else None,
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "export-schemas":
            count = export_schemas(args.destination.resolve())
            _emit({"exported": count, "destination": str(args.destination.resolve())}, args.compact)
            return 0
        orchestrator = BuildOrchestrator(
            args.workspace,
            config_path=args.config,
            profile=args.profile,
            provider=args.provider,
            runway_scope=args.runway_scope,
            narration_provider=args.narration_provider,
            agent_review_mode=args.agent_review_mode,
        )
        if args.command == "serve":
            serve(orchestrator, args.host, args.port)
            return 0
        if args.command == "plan":
            result = orchestrator.plan(args.article)
        elif args.command == "build":
            result = orchestrator.build(
                args.article, auto_approve=args.auto_approve, actor=args.actor
            )
        elif args.command == "approve":
            result = orchestrator.approve(
                args.build_id,
                gate=args.gate,
                actor=args.actor,
                decision=args.decision,
                comment=args.comment,
                allow_agent_exception=args.allow_agent_exception,
                agent_exception_reason=args.agent_exception_reason,
            )
        elif args.command in {"agent-review", "review"}:
            result = orchestrator.review(args.build_id)
        elif args.command == "status":
            result = orchestrator.inspect(args.build_id)
        elif args.command == "list":
            result = orchestrator.list_builds()
        elif args.command == "health":
            result = orchestrator.health()
        else:
            result = getattr(orchestrator, args.command)(args.build_id)
        _emit(result, args.compact)
        return 0
    except PlatformError as exc:
        _emit({"error": exc.as_dict()}, args.compact)
        return exc.exit_code
    except KeyboardInterrupt:
        return 9


if __name__ == "__main__":
    sys.exit(main())
