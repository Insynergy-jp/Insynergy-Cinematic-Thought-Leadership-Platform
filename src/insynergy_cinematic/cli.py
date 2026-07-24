"""Canonical command-line adapter."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .api import serve
from .architecture import architecture_audit, part1_coverage_report
from .errors import PlatformError, ValidationError
from .orchestrator import BuildOrchestrator
from .outcomes import OutcomeDashboard, OutcomeThresholds, ViewerOutcomeRepository
from .persona import (
    PERSONA_PREAPPROVAL_ARTIFACTS,
    validate_persona_preapproval_bundle,
)
from .schemas import export_schemas
from .runtime import part6_coverage_report
from .quality import part7_coverage_report
from .github_actions import part8_coverage_report
from .screenplay import part3_coverage_report
from .story import part2_coverage_report
from .schema_validation import (
    PERSONA_NAMES,
    audit_schema_bundle,
    part9_coverage_report,
    validate_persona_bundle,
    validate_schema_document,
)
from .util import read_json


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
    parser.add_argument(
        "--narration-provider", choices=("none", "offline", "openai")
    )
    parser.add_argument("--agent-review-mode", choices=("off", "review"))
    parser.add_argument(
        "--pre-render-preview-mode", choices=("off", "storyboard_animatic")
    )
    parser.add_argument("--persona-mode", choices=("off", "council"))
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Generate and gate all planning artifacts")
    plan.add_argument("article", type=Path)
    plan.add_argument("--creative-brief", type=Path)
    plan.add_argument(
        "--retry-failed-planning",
        action="store_true",
        help="Explicitly retry a previously failed planning stage without discarding approvals",
    )

    review = sub.add_parser(
        "agent-review",
        aliases=("review",),
        help="Run the read-only Agent Review job",
    )
    review.add_argument("build_id")

    previsualize = sub.add_parser(
        "previsualize",
        help="Generate GPT storyboard frames and an FFmpeg review animatic without Runway",
    )
    previsualize.add_argument("build_id")
    preview_preflight = sub.add_parser(
        "preview-preflight",
        help="Validate preview budget and identity without provider credentials",
    )
    preview_preflight.add_argument("build_id")
    recompose = sub.add_parser(
        "recompose-preview",
        help="Recompose and verify the sealed preview in a provider-secret-free process",
    )
    recompose.add_argument("build_id")

    build = sub.add_parser("build", help="Run the complete build pipeline")
    build.add_argument("article", type=Path)
    build.add_argument("--creative-brief", type=Path)
    build.add_argument("--auto-approve", action="store_true")
    build.add_argument("--actor", default="local-operator")

    approve = sub.add_parser("approve", help="Record a scoped human approval")
    approve.add_argument("build_id")
    approve.add_argument(
        "--gate",
        choices=("persona", "storyboard-preview", "execution", "publish"),
        required=True,
    )
    approve.add_argument("--actor", required=True)
    approve.add_argument("--decision", choices=("APPROVED", "REJECTED"), default="APPROVED")
    approve.add_argument("--comment", default="")
    approve.add_argument("--allow-agent-exception", action="store_true")
    approve.add_argument("--agent-exception-reason", default="")
    approve.add_argument("--workflow-initiator")
    approve.add_argument("--environment-reviewer")
    approve.add_argument("--environment-reviewer-id", type=int)
    approve.add_argument("--prevent-self-review", action="store_true")
    approve.add_argument("--environment-review-hash")
    approve.add_argument("--environment-policy-hash")

    for name in (
        "execute",
        "publish",
        "status",
        "pause",
        "resume",
        "cancel",
        "recover",
        "verify",
    ):
        command = sub.add_parser(name)
        command.add_argument("build_id")

    sub.add_parser("list", help="List builds")
    sub.add_parser("health", help="Show dependency readiness")
    sub.add_parser("part1-coverage", help="Show the Part 1 coverage evidence matrix")
    sub.add_parser("part2-coverage", help="Show the Part 2 coverage evidence matrix")
    sub.add_parser("part3-coverage", help="Show the Part 3 coverage evidence matrix")
    sub.add_parser("part6-coverage", help="Show the Part 6 coverage evidence matrix")
    sub.add_parser("part7-coverage", help="Show the Part 7 coverage evidence matrix")
    sub.add_parser("part8-coverage", help="Show the Part 8 coverage evidence matrix")
    sub.add_parser("part9-coverage", help="Show the Part 9 coverage evidence matrix")
    audit_architecture = sub.add_parser(
        "audit-architecture", help="Audit the Part 1 topology and provider isolation"
    )
    audit_architecture.add_argument("--source-root", type=Path)
    audit = sub.add_parser("audit-schemas", help="Audit the complete Part 9 schema bundle")
    audit.add_argument("--schema-root", type=Path)
    validate_schema = sub.add_parser("validate-schema", help="Validate one JSON document")
    validate_schema.add_argument("schema")
    validate_schema.add_argument("document", type=Path)
    validate_schema.add_argument("--schema-root", type=Path)
    validate_persona = sub.add_parser(
        "validate-persona-bundle", help="Validate six cross-bound Persona artifacts"
    )
    validate_persona.add_argument("directory", type=Path)
    validate_persona.add_argument("--schema-root", type=Path)
    validate_persona_preapproval = sub.add_parser(
        "validate-persona-preapproval",
        help="Validate five sealed Persona artifacts before human approval",
    )
    validate_persona_preapproval.add_argument("directory", type=Path)
    outcome = sub.add_parser(
        "record-viewer-outcome",
        help="Append a pseudonymous viewer comprehension and retention measurement",
    )
    outcome.add_argument("build_id")
    viewer = outcome.add_mutually_exclusive_group(required=True)
    viewer.add_argument("--viewer-id")
    viewer.add_argument("--viewer-id-stdin", action="store_true")
    outcome.add_argument("--idea-restatement-accuracy", type=float, required=True)
    outcome.add_argument("--unaided-recall", type=float, required=True)
    outcome.add_argument(
        "--reaction-subject", choices=("IDEA", "MEDIUM", "MIXED"), required=True
    )
    outcome.add_argument(
        "--accuracy-gate-result", choices=("PASS", "FAIL"), required=True
    )
    outcome.add_argument("--retention-hours", type=float, required=True)
    outcome.add_argument("--cohort", default="all")
    outcome.add_argument("--observed-at")
    outcome.add_argument("--idempotency-key", required=True)
    dashboard = sub.add_parser(
        "outcomes-dashboard",
        help="Generate the longitudinal viewer understanding and memory dashboard",
    )
    dashboard.add_argument(
        "--output", type=Path, default=Path(".insynergy/outcomes/dashboard.html")
    )
    dashboard.add_argument(
        "--json-output", type=Path, default=Path(".insynergy/outcomes/dashboard.json")
    )
    dashboard.add_argument("--build-id")
    dashboard.add_argument("--window-days", type=int)
    dashboard.add_argument("--comprehension-threshold", type=float, default=0.80)
    dashboard.add_argument("--recall-threshold", type=float, default=0.70)
    dashboard.add_argument("--minimum-retention-hours", type=float, default=168.0)
    dashboard.add_argument("--minimum-sample-size", type=int, default=5)
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
        if args.command == "audit-schemas":
            _emit(audit_schema_bundle(args.schema_root), args.compact)
            return 0
        if args.command == "audit-architecture":
            _emit(architecture_audit(args.source_root), args.compact)
            return 0
        if args.command == "validate-schema":
            document = read_json(args.document.resolve())
            if not isinstance(document, dict):
                raise ValidationError(
                    "Schema instance must be a JSON object",
                    details={"code": "E-SCHEMA-002"},
                )
            _emit(
                validate_schema_document(
                    args.schema, document, root=args.schema_root
                ),
                args.compact,
            )
            return 0
        if args.command == "validate-persona-bundle":
            directory = args.directory.resolve()
            documents = {
                name: read_json(directory / f"{name}.json") for name in PERSONA_NAMES
            }
            _emit(
                validate_persona_bundle(documents, root=args.schema_root), args.compact
            )
            return 0
        if args.command == "validate-persona-preapproval":
            directory = args.directory.resolve()
            documents = {
                name: read_json(directory / f"{name}.json")
                for name in PERSONA_PREAPPROVAL_ARTIFACTS
            }
            _emit(validate_persona_preapproval_bundle(documents), args.compact)
            return 0
        if args.command == "record-viewer-outcome":
            viewer_id = (
                sys.stdin.readline().rstrip("\r\n")
                if args.viewer_id_stdin
                else args.viewer_id
            )
            _emit(
                ViewerOutcomeRepository(args.workspace).record(
                    build_id=args.build_id,
                    viewer_id=viewer_id,
                    idea_restatement_accuracy=args.idea_restatement_accuracy,
                    unaided_recall=args.unaided_recall,
                    reaction_subject=args.reaction_subject,
                    accuracy_gate_result=args.accuracy_gate_result,
                    retention_interval_hours=args.retention_hours,
                    cohort=args.cohort,
                    observed_at=args.observed_at,
                    idempotency_key=args.idempotency_key,
                ),
                args.compact,
            )
            return 0
        if args.command == "outcomes-dashboard":
            thresholds = OutcomeThresholds(
                comprehension_accuracy=args.comprehension_threshold,
                unaided_recall=args.recall_threshold,
                minimum_retention_hours=args.minimum_retention_hours,
                minimum_sample_size=args.minimum_sample_size,
            )
            output = args.output if args.output.is_absolute() else args.workspace / args.output
            json_output = (
                args.json_output
                if args.json_output.is_absolute()
                else args.workspace / args.json_output
            )
            report = OutcomeDashboard(args.workspace).write(
                output,
                json_output=json_output,
                build_id=args.build_id,
                window_days=args.window_days,
                thresholds=thresholds,
            )
            _emit(
                {
                    "dashboard": str(output.resolve()),
                    "report": str(json_output.resolve()),
                    "verdict": report["aggregate"]["verdict"],
                    "sample_size": report["aggregate"]["sample_size"],
                    "content_hash": report["content_hash"],
                },
                args.compact,
            )
            return 0
        orchestrator = BuildOrchestrator(
            args.workspace,
            config_path=args.config,
            profile=args.profile,
            provider=args.provider,
            runway_scope=args.runway_scope,
            narration_provider=args.narration_provider,
            agent_review_mode=args.agent_review_mode,
            pre_render_preview_mode=args.pre_render_preview_mode,
            persona_mode=args.persona_mode,
        )
        if args.command == "serve":
            serve(orchestrator, args.host, args.port)
            return 0
        if args.command == "part1-coverage":
            result = part1_coverage_report()
        elif args.command == "part2-coverage":
            result = part2_coverage_report()
        elif args.command == "part3-coverage":
            result = part3_coverage_report()
        elif args.command == "part6-coverage":
            result = part6_coverage_report()
        elif args.command == "part7-coverage":
            result = part7_coverage_report()
        elif args.command == "part8-coverage":
            result = part8_coverage_report()
        elif args.command == "part9-coverage":
            result = part9_coverage_report()
        elif args.command == "plan":
            result = orchestrator.plan(
                args.article,
                creative_brief_path=args.creative_brief,
                retry_failed_planning=args.retry_failed_planning,
            )
        elif args.command == "build":
            result = orchestrator.build(
                args.article,
                creative_brief_path=args.creative_brief,
                auto_approve=args.auto_approve,
                actor=args.actor,
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
                workflow_initiator=args.workflow_initiator,
                environment_reviewer=args.environment_reviewer,
                environment_reviewer_id=args.environment_reviewer_id,
                prevent_self_review=args.prevent_self_review,
                environment_review_hash=args.environment_review_hash,
                environment_policy_hash=args.environment_policy_hash,
            )
        elif args.command in {"agent-review", "review"}:
            result = orchestrator.review(args.build_id)
        elif args.command == "previsualize":
            result = orchestrator.previsualize(args.build_id)
        elif args.command == "preview-preflight":
            result = orchestrator.preview_preflight(args.build_id)
        elif args.command == "recompose-preview":
            result = orchestrator.recompose_preview(args.build_id)
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
