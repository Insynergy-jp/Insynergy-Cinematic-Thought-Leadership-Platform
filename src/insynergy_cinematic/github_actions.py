"""Tamper-evident GitHub Actions handoffs and the Part 8 coverage matrix."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from .errors import ValidationError
from .util import atomic_write_json, content_hash, file_hash, read_json


EVIDENCE_CONTRACT_VERSION = "workflow-evidence/1"
EVIDENCE_SCHEMA_VERSION = "1.0.0"
ALLOWED_STAGES = frozenset({"planning", "execution", "publication"})
ALLOWED_PROFILES = frozenset({"draft", "preview", "final"})
BUILD_ID = re.compile(r"^[0-9]{8}-[0-9]{3}$")
RUN_ID = re.compile(r"^[1-9][0-9]*$")
SOURCE_SHA = re.compile(r"^[a-f0-9]{40}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
GITHUB_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
GITHUB_ENVIRONMENT = re.compile(r"^[A-Za-z0-9_.-]{1,255}$")
GITHUB_ENVIRONMENT_REVIEW_CONTRACT_VERSION = "github-environment-review/1"
GITHUB_ENVIRONMENT_POLICY_CONTRACT_VERSION = "github-environment-policy/1"
TEXT_SUFFIXES = frozenset(
    {".csv", ".json", ".md", ".srt", ".txt", ".yaml", ".yml"}
)
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("OPENAI_KEY", re.compile(rb"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("GITHUB_TOKEN", re.compile(rb"\b(?:ghp|github_pat)_[A-Za-z0-9_]{16,}\b")),
    (
        "PRIVATE_KEY",
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "ASSIGNED_SECRET",
        re.compile(
            rb"\b(?:OPENAI_API_KEY|OPENAI_TTS_API_KEY|RUNWAY_API_KEY)\s*[=:]\s*[^\s\"']+"
        ),
    ),
)


def _safe_scalar(name: str, value: str, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value or len(value) > 160:
        raise ValidationError(f"Workflow evidence {name} is invalid")
    if "\n" in value or "\r" in value:
        raise ValidationError(f"Workflow evidence {name} is invalid")
    if pattern is not None and not pattern.fullmatch(value):
        raise ValidationError(f"Workflow evidence {name} is invalid")
    return value


def _validate_metadata(
    *,
    stage: str,
    build_id: str,
    profile: str,
    workflow: str,
    repository: str,
    run_id: str,
    run_attempt: str,
    source_sha: str,
) -> None:
    if stage not in ALLOWED_STAGES:
        raise ValidationError("Workflow evidence stage is invalid")
    _safe_scalar("build_id", build_id, BUILD_ID)
    if profile not in ALLOWED_PROFILES:
        raise ValidationError("Workflow evidence profile is invalid")
    _safe_scalar("workflow", workflow)
    _safe_scalar("repository", repository, REPOSITORY)
    _safe_scalar("run_id", run_id, RUN_ID)
    _safe_scalar("run_attempt", run_attempt, RUN_ID)
    _safe_scalar("source_sha", source_sha, SOURCE_SHA)


def resolve_github_environment_review(
    approvals: object,
    *,
    repository: str,
    run_id: str,
    run_attempt: str,
    environment: str,
    workflow_initiator: str,
    require_distinct_reviewer: bool,
    required_reviewer_ids: frozenset[int] | None = None,
    environment_policy_hash: str | None = None,
) -> dict[str, Any]:
    """Resolve one approved Environment reviewer from GitHub review history.

    The GitHub response is treated as untrusted input. Missing, rejected, or
    ambiguous records fail closed rather than falling back to the workflow
    initiator.
    """

    _safe_scalar("repository", repository, REPOSITORY)
    _safe_scalar("run_id", run_id, RUN_ID)
    _safe_scalar("run_attempt", run_attempt, RUN_ID)
    _safe_scalar("environment", environment, GITHUB_ENVIRONMENT)
    initiator = _safe_scalar(
        "workflow_initiator", workflow_initiator, GITHUB_LOGIN
    )
    if not isinstance(approvals, list):
        raise ValidationError("GitHub Environment review history is invalid")

    matched: list[tuple[str, int, int]] = []
    for approval in approvals:
        if not isinstance(approval, dict):
            continue
        environments = approval.get("environments")
        if not isinstance(environments, list):
            continue
        environment_ids = {
            candidate.get("id")
            for candidate in environments
            if isinstance(candidate, dict)
            and candidate.get("name") == environment
            and isinstance(candidate.get("id"), int)
            and candidate["id"] > 0
        }
        if not environment_ids:
            continue
        if approval.get("state") != "approved":
            raise ValidationError(
                "GitHub Environment review is not approved",
                details={"environment": environment},
            )
        user = approval.get("user")
        login = user.get("login") if isinstance(user, dict) else None
        user_id = user.get("id") if isinstance(user, dict) else None
        if not isinstance(login, str) or not GITHUB_LOGIN.fullmatch(login):
            raise ValidationError("GitHub Environment reviewer identity is invalid")
        if not isinstance(user_id, int) or user_id <= 0:
            raise ValidationError("GitHub Environment reviewer ID is invalid")
        matched.extend((login, user_id, value) for value in environment_ids)

    if not matched:
        raise ValidationError(
            "GitHub Environment reviewer was not found",
            details={"environment": environment, "run_id": run_id},
        )
    identities = {(login.casefold(), user_id) for login, user_id, _ in matched}
    environment_ids = {environment_id for _, _, environment_id in matched}
    if len(identities) != 1 or len(environment_ids) != 1:
        raise ValidationError(
            "GitHub Environment reviewer history is ambiguous",
            details={"environment": environment, "run_id": run_id},
        )
    reviewer, reviewer_id, environment_id = matched[0]
    if required_reviewer_ids is not None and reviewer_id not in required_reviewer_ids:
        raise ValidationError(
            "GitHub Environment approver is not a configured required reviewer",
            details={"environment": environment, "run_id": run_id},
        )
    if require_distinct_reviewer and reviewer.casefold() == initiator.casefold():
        raise ValidationError(
            "GitHub Environment self-review is prohibited",
            details={"environment": environment, "run_id": run_id},
        )

    record: dict[str, Any] = {
        "schema_version": "1.0.0",
        "contract_version": GITHUB_ENVIRONMENT_REVIEW_CONTRACT_VERSION,
        "repository": repository,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "environment": environment,
        "environment_id": environment_id,
        "decision": "APPROVED",
        "workflow_initiator": initiator,
        "environment_reviewer": reviewer,
        "environment_reviewer_id": reviewer_id,
        "prevent_self_review": require_distinct_reviewer,
    }
    if environment_policy_hash:
        record["environment_policy_hash"] = environment_policy_hash
    record["content_hash"] = content_hash(record)
    return record


def resolve_github_environment_policy(
    configuration: object,
    *,
    environment: str,
    branch_policies: object,
    required_branch: str = "main",
) -> dict[str, Any]:
    """Validate live reviewers, self-review, and exact deployment branch policy."""

    _safe_scalar("environment", environment, GITHUB_ENVIRONMENT)
    _safe_scalar("required branch", required_branch, GITHUB_ENVIRONMENT)
    if not isinstance(configuration, dict) or configuration.get("name") != environment:
        raise ValidationError("GitHub Environment configuration is invalid")
    environment_id = configuration.get("id")
    rules = configuration.get("protection_rules")
    if not isinstance(environment_id, int) or environment_id <= 0:
        raise ValidationError("GitHub Environment ID is invalid")
    if not isinstance(rules, list):
        raise ValidationError("GitHub Environment protection rules are invalid")
    reviewer_rules = [
        rule
        for rule in rules
        if isinstance(rule, dict) and rule.get("type") == "required_reviewers"
    ]
    if len(reviewer_rules) != 1:
        raise ValidationError(
            "GitHub Environment must have exactly one Required reviewers rule"
        )
    rule = reviewer_rules[0]
    prevent_self_review = rule.get("prevent_self_review")
    reviewers = rule.get("reviewers")
    if not isinstance(prevent_self_review, bool) or not isinstance(reviewers, list):
        raise ValidationError("GitHub Environment Required reviewers rule is invalid")
    resolved_reviewers: list[dict[str, Any]] = []
    for entry in reviewers:
        if not isinstance(entry, dict) or entry.get("type") != "User":
            raise ValidationError(
                "Environment approval requires direct GitHub user reviewers"
            )
        reviewer = entry.get("reviewer")
        login = reviewer.get("login") if isinstance(reviewer, dict) else None
        reviewer_id = reviewer.get("id") if isinstance(reviewer, dict) else None
        if not isinstance(login, str) or not GITHUB_LOGIN.fullmatch(login):
            raise ValidationError("GitHub required reviewer login is invalid")
        if not isinstance(reviewer_id, int) or reviewer_id <= 0:
            raise ValidationError("GitHub required reviewer ID is invalid")
        resolved_reviewers.append({"login": login, "id": reviewer_id})
    if not resolved_reviewers or len(resolved_reviewers) > 6:
        raise ValidationError("GitHub Required reviewers list is invalid")
    deployment_policy = configuration.get("deployment_branch_policy")
    if not isinstance(deployment_policy, dict) or deployment_policy != {
        "protected_branches": False,
        "custom_branch_policies": True,
    }:
        raise ValidationError(
            "GitHub Environment must use an exact custom deployment branch policy"
        )
    if not isinstance(branch_policies, dict):
        raise ValidationError("GitHub deployment branch policy response is invalid")
    total_count = branch_policies.get("total_count")
    entries = branch_policies.get("branch_policies")
    if total_count != 1 or not isinstance(entries, list) or len(entries) != 1:
        raise ValidationError(
            "GitHub Environment must allow exactly one deployment branch"
        )
    branch_policy = entries[0]
    if (
        not isinstance(branch_policy, dict)
        or branch_policy.get("name") != required_branch
        or branch_policy.get("type", "branch") != "branch"
        or not isinstance(branch_policy.get("id"), int)
        or branch_policy["id"] <= 0
    ):
        raise ValidationError(
            f"GitHub Environment deployment branch must be exactly {required_branch}"
        )
    policy: dict[str, Any] = {
        "schema_version": "1.0.0",
        "contract_version": GITHUB_ENVIRONMENT_POLICY_CONTRACT_VERSION,
        "environment": environment,
        "environment_id": environment_id,
        "prevent_self_review": prevent_self_review,
        "required_reviewers": resolved_reviewers,
        "deployment_branch": required_branch,
        "deployment_branch_policy_id": branch_policy["id"],
    }
    policy["content_hash"] = content_hash(policy)
    return policy


def _inside(root: Path, path: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError as exc:
        raise ValidationError("Workflow evidence path escapes its root") from exc


def _files(root: Path, paths: Iterable[Path], output: Path) -> list[Path]:
    selected: set[Path] = set()
    for requested in paths:
        candidate = requested if requested.is_absolute() else root / requested
        if not candidate.exists():
            raise ValidationError(
                "Workflow evidence input is missing",
                details={"path": str(requested)},
            )
        if candidate.is_symlink():
            raise ValidationError("Workflow evidence rejects symbolic links")
        _inside(root, candidate.resolve())
        values = [candidate]
        if candidate.is_dir():
            values = sorted(candidate.rglob("*"))
        for value in values:
            if value.is_symlink():
                raise ValidationError("Workflow evidence rejects symbolic links")
            if value.is_dir():
                continue
            if not value.is_file():
                raise ValidationError("Workflow evidence accepts regular files only")
            resolved = value.resolve()
            _inside(root, resolved)
            if resolved != output:
                selected.add(resolved)
    if not selected:
        raise ValidationError("Workflow evidence bundle has no files")
    return sorted(selected, key=lambda value: _inside(root, value).as_posix())


def _scan_file(path: Path) -> None:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return
    value = path.read_bytes()
    for code, pattern in SECRET_PATTERNS:
        if pattern.search(value):
            raise ValidationError(
                "Workflow evidence secret scan failed",
                details={"path": path.name, "finding_code": code},
            )


def create_workflow_evidence(
    *,
    root: Path,
    paths: Iterable[Path],
    output: Path,
    stage: str,
    build_id: str,
    profile: str,
    workflow: str,
    repository: str,
    run_id: str,
    run_attempt: str,
    source_sha: str,
) -> dict[str, Any]:
    """Create a deterministic, secret-scanned transport manifest."""
    _validate_metadata(
        stage=stage,
        build_id=build_id,
        profile=profile,
        workflow=workflow,
        repository=repository,
        run_id=run_id,
        run_attempt=run_attempt,
        source_sha=source_sha,
    )
    root = root.resolve()
    output = output if output.is_absolute() else root / output
    output = output.resolve()
    _inside(root, output)
    files = _files(root, paths, output)
    entries = []
    for path in files:
        _scan_file(path)
        entries.append(
            {
                "path": _inside(root, path).as_posix(),
                "size": path.stat().st_size,
                "sha256": file_hash(path),
            }
        )
    evidence: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "contract_version": EVIDENCE_CONTRACT_VERSION,
        "stage": stage,
        "build_id": build_id,
        "profile": profile,
        "source": {
            "workflow": workflow,
            "repository": repository,
            "run_id": run_id,
            "run_attempt": run_attempt,
            "source_sha": source_sha,
        },
        "secret_scan": {"status": "PASS", "policy": "artifact-patterns/1"},
        "files": entries,
        "bundle_hash": content_hash(entries),
    }
    evidence["evidence_hash"] = content_hash(evidence)
    atomic_write_json(output, evidence)
    return evidence


def verify_workflow_evidence(
    evidence_path: Path,
    *,
    root: Path,
    expected_stage: str,
    expected_build_id: str,
    expected_profile: str,
    expected_workflow: str,
    expected_repository: str,
    expected_run_id: str,
    expected_source_sha: str,
) -> dict[str, Any]:
    """Verify a downloaded handoff before an approval or external effect."""
    root = root.resolve()
    evidence_path = evidence_path if evidence_path.is_absolute() else root / evidence_path
    _inside(root, evidence_path.resolve())
    evidence = read_json(evidence_path)
    required = {
        "schema_version",
        "contract_version",
        "stage",
        "build_id",
        "profile",
        "source",
        "secret_scan",
        "files",
        "bundle_hash",
        "evidence_hash",
    }
    if not isinstance(evidence, dict) or set(evidence) != required:
        raise ValidationError("Workflow evidence fields do not match the contract")
    expected_hash = content_hash(
        {key: value for key, value in evidence.items() if key != "evidence_hash"}
    )
    if evidence["evidence_hash"] != expected_hash:
        raise ValidationError("Workflow evidence integrity failure")
    source = evidence.get("source")
    if not isinstance(source, dict) or set(source) != {
        "workflow",
        "repository",
        "run_id",
        "run_attempt",
        "source_sha",
    }:
        raise ValidationError("Workflow evidence source is invalid")
    _validate_metadata(
        stage=str(evidence.get("stage", "")),
        build_id=str(evidence.get("build_id", "")),
        profile=str(evidence.get("profile", "")),
        workflow=str(source.get("workflow", "")),
        repository=str(source.get("repository", "")),
        run_id=str(source.get("run_id", "")),
        run_attempt=str(source.get("run_attempt", "")),
        source_sha=str(source.get("source_sha", "")),
    )
    expected = {
        "stage": expected_stage,
        "build_id": expected_build_id,
        "profile": expected_profile,
    }
    actual = {key: evidence[key] for key in expected}
    expected_source = {
        "workflow": expected_workflow,
        "repository": expected_repository,
        "run_id": expected_run_id,
        "source_sha": expected_source_sha,
    }
    actual_source = {key: source[key] for key in expected_source}
    if actual != expected or actual_source != expected_source:
        raise ValidationError(
            "Workflow evidence approval binding mismatch",
            details={"expected": {**expected, **expected_source}},
        )
    if evidence.get("secret_scan") != {
        "status": "PASS",
        "policy": "artifact-patterns/1",
    }:
        raise ValidationError("Workflow evidence secret scan is absent")
    entries = evidence.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValidationError("Workflow evidence file list is invalid")
    if evidence.get("bundle_hash") != content_hash(entries):
        raise ValidationError("Workflow evidence bundle hash is invalid")
    observed_paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "size", "sha256"}:
            raise ValidationError("Workflow evidence file entry is invalid")
        relative = Path(str(entry["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValidationError("Workflow evidence file path is invalid")
        relative_text = relative.as_posix()
        if relative_text in observed_paths:
            raise ValidationError("Workflow evidence file path is duplicated")
        observed_paths.add(relative_text)
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ValidationError(
                "Workflow evidence file is missing",
                details={"path": relative_text},
            )
        _inside(root, path.resolve())
        if path.stat().st_size != entry["size"] or file_hash(path) != entry["sha256"]:
            raise ValidationError(
                "Workflow evidence file integrity failure",
                details={"path": relative_text},
            )
        _scan_file(path)
    return {
        "passed": True,
        "stage": evidence["stage"],
        "build_id": evidence["build_id"],
        "profile": evidence["profile"],
        "bundle_hash": evidence["bundle_hash"],
        "evidence_hash": evidence["evidence_hash"],
        "file_count": len(entries),
    }


def workflow_summary(
    evidence: dict[str, Any], *, result: dict[str, Any] | None = None
) -> str:
    """Render only allow-listed, non-payload metadata for a job summary."""
    state = "NOT_APPLICABLE"
    if isinstance(result, dict):
        candidate = result.get("state")
        if isinstance(candidate, str) and re.fullmatch(r"[A-Z_]+", candidate):
            state = candidate
    source = evidence["source"]
    return "\n".join(
        (
            f"## {evidence['stage'].title()} evidence",
            "",
            f"- Build: `{evidence['build_id']}`",
            f"- Profile: `{evidence['profile']}`",
            f"- State: `{state}`",
            f"- Bundle hash: `{evidence['bundle_hash']}`",
            f"- Evidence hash: `{evidence['evidence_hash']}`",
            f"- Files: `{len(evidence['files'])}`",
            f"- Source run: `{source['run_id']}` (attempt `{source['run_attempt']}`)",
            f"- Source commit: `{source['source_sha']}`",
            "",
        )
    )


def part8_coverage_report() -> dict[str, Any]:
    """Return the fixed twenty-cluster Part 8 implementation matrix."""
    full = [
        ("host_domain_boundary", "workflows invoke host-agnostic orchestrator verbs"),
        ("trigger_and_input_contracts", "typed dispatch inputs and fail-closed validation"),
        ("deterministic_planning", "secret-free planning with immutable handoff"),
        ("agent_review_isolation", "optional review is isolated in planning-ai"),
        ("independent_approvals", "render and publication use separate environments"),
        ("execution_preflight", "identity, configuration, budget, and approval checks"),
        ("quality_gated_delivery", "quality verification blocks publication"),
        ("concurrency_and_idempotency", "build-scoped single-flight and domain replay guards"),
        ("manifest_resume_projection", "portable manifest, checkpoints, and recovery plans"),
        ("backpressure_and_cost", "bounded queue, provider limits, and pre-spend admission"),
        ("secret_scoping", "provider credentials are job and Environment scoped"),
        ("token_least_privilege", "read-only workflow token permissions"),
        ("action_supply_chain", "40-hex pins, reviewed allowlist, and local actions"),
        ("untrusted_input_protection", "secret-free PR CI and no shell expression injection"),
        ("artifact_integrity", "file hashes, source binding, secret scan, and retention"),
        ("observability_and_diagnostics", "safe summaries and bounded failure evidence"),
        ("workflow_testing_and_runbooks", "policy, contract, E2E tests, and operator procedures"),
        (
            "persona_council_workflow",
            "planning-ai deliberation, secretless quality, protected Persona approval, and deterministic Story handoff",
        ),
    ]
    partial = [
        (
            "runner_oidc_and_telemetry",
            "ephemeral hosted runners are bounded; self-hosted fleet, OIDC, and export remain external",
        ),
        (
            "live_protection_acceptance",
            "repository contracts exist; live branch/environment protection evidence is external",
        ),
    ]
    missing: list[tuple[str, str]] = []
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
