"""Fail-closed structural and supply-chain policy for GitHub Actions."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
USES = re.compile(r"^\s*uses:\s*([^\s#]+)", flags=re.MULTILINE)
PINNED = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[a-f0-9]{40}$")
JOB = re.compile(r"^  ([a-z][a-z0-9-]*):\s*$")
SECRET = re.compile(r"\$\{\{\s*secrets\.([A-Za-z0-9_]+)\s*\}\}")
FORBIDDEN_EVENTS = ("pull_request_target:", "repository_dispatch:")
ALLOWED_PERMISSIONS = {"actions": "read", "contents": "read"}
EXPECTED_ENVIRONMENTS = {
    ("plan.yml", "agent-review"): "planning-ai",
    ("plan.yml", "persona-deliberation"): "planning-ai",
    ("plan.yml", "persona-approval"): "persona-approval",
    ("preview.yml", "preview"): "planning-ai",
    ("preview.yml", "approval"): "storyboard-preview-approval",
    ("execute.yml", "execute"): "render-approval",
    ("publish.yml", "publish"): "publication-approval",
}
ALLOWED_SECRETS = {
    ("plan.yml", "agent-review"): {"OPENAI_API_KEY"},
    ("plan.yml", "persona-deliberation"): {"OPENAI_API_KEY"},
    ("plan.yml", "persona-approval"): {"GITHUB_TOKEN"},
    ("preview.yml", "preview"): {"GITHUB_TOKEN", "OPENAI_API_KEY"},
    ("preview.yml", "preflight"): {"GITHUB_TOKEN"},
    ("preview.yml", "compose"): {"GITHUB_TOKEN"},
    ("preview.yml", "approval"): {"GITHUB_TOKEN"},
    ("execute.yml", "execute"): {
        "GITHUB_TOKEN",
        "OPENAI_TTS_API_KEY",
        "RUNWAY_API_KEY",
    },
    ("publish.yml", "publish"): {"GITHUB_TOKEN"},
}


def _section(lines: list[str], name: str, indent: int = 0) -> list[str]:
    prefix = " " * indent + name + ":"
    for index, line in enumerate(lines):
        if line == prefix:
            values = []
            for candidate in lines[index + 1 :]:
                if candidate and len(candidate) - len(candidate.lstrip()) <= indent:
                    break
                values.append(candidate)
            return values
    return []


def _jobs(text: str) -> dict[str, str]:
    lines = text.splitlines()
    jobs_start = next((index for index, line in enumerate(lines) if line == "jobs:"), None)
    if jobs_start is None:
        return {}
    starts = [
        (index, match.group(1))
        for index, line in enumerate(lines[jobs_start + 1 :], jobs_start + 1)
        if (match := JOB.fullmatch(line))
    ]
    jobs: dict[str, str] = {}
    for offset, (start, name) in enumerate(starts):
        end = starts[offset + 1][0] if offset + 1 < len(starts) else len(lines)
        jobs[name] = "\n".join(lines[start:end])
    return jobs


def _run_blocks(path: Path, text: str) -> list[str]:
    errors: list[str] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)run:\s*(.*)$", line)
        if not match:
            continue
        indent = len(match.group(1))
        marker = match.group(2).strip()
        if marker not in {"|", "|-", "|+"}:
            errors.append(f"{path}:{index + 1}: run command must use a strict shell block")
            continue
        body: list[str] = []
        for candidate in lines[index + 1 :]:
            if candidate.strip() and len(candidate) - len(candidate.lstrip()) <= indent:
                break
            body.append(candidate)
        content = [value.strip() for value in body if value.strip()]
        if not content or content[0] != "set -euo pipefail":
            errors.append(f"{path}:{index + 1}: run block must start with set -euo pipefail")
        if any("${{" in value for value in body):
            errors.append(f"{path}:{index + 1}: expressions must reach shell only through env")
    return errors


def _validate_workflow(path: Path, text: str) -> list[str]:
    errors: list[str] = []
    lines = text.splitlines()
    if any(event in text for event in FORBIDDEN_EVENTS):
        errors.append(f"{path}: forbidden privileged or unvalidated event")
    permissions = _section(lines, "permissions")
    if not permissions:
        errors.append(f"{path}: top-level permissions are required")
    else:
        observed: dict[str, str] = {}
        for line in permissions:
            match = re.fullmatch(r"  ([a-z-]+):\s*(\S+)", line)
            if match:
                observed[match.group(1)] = match.group(2)
        for scope, value in observed.items():
            if ALLOWED_PERMISSIONS.get(scope) != value:
                errors.append(f"{path}: permission {scope}: {value} is not allowed")
        if observed.get("contents") != "read":
            errors.append(f"{path}: contents permission must be read")
    concurrency = _section(lines, "concurrency")
    if not concurrency or not any("cancel-in-progress:" in line for line in concurrency):
        errors.append(f"{path}: explicit concurrency cancellation policy is required")
    if path.name != "ci.yml":
        on = _section(lines, "on")
        if not any(line.strip() == "workflow_dispatch:" for line in on):
            errors.append(f"{path}: operational workflows must use workflow_dispatch")
        if any(line.strip().startswith(("pull_request:", "push:", "schedule:")) for line in on):
            errors.append(f"{path}: privileged workflows cannot use automatic untrusted triggers")
    jobs = _jobs(text)
    if not jobs:
        errors.append(f"{path}: workflow must define jobs")
    for name, job in jobs.items():
        if "\n    runs-on: " not in job and "\n    uses: " not in job:
            errors.append(f"{path}: job {name} has no runner or reusable workflow")
        if "\n    runs-on: " in job and "\n    timeout-minutes: " not in job:
            errors.append(f"{path}: job {name} has no timeout-minutes")
        expected_environment = EXPECTED_ENVIRONMENTS.get((path.name, name))
        environment = re.search(r"^    environment:\s*([^\s#]+)", job, re.MULTILINE)
        if expected_environment and (
            environment is None or environment.group(1) != expected_environment
        ):
            errors.append(
                f"{path}: job {name} must use environment {expected_environment}"
            )
        if not expected_environment and environment:
            errors.append(f"{path}: job {name} has an unexpected protected environment")
        if "\n    permissions:" in job:
            for scope, value in re.findall(
                r"^      ([a-z-]+):\s*(\S+)", job, re.MULTILINE
            ):
                if ALLOWED_PERMISSIONS.get(scope) != value:
                    errors.append(
                        f"{path}: job {name} permission {scope}: {value} is not allowed"
                    )
        secrets = set(SECRET.findall(job))
        allowed = ALLOWED_SECRETS.get((path.name, name), set())
        unexpected = secrets.difference(allowed)
        if unexpected:
            errors.append(
                f"{path}: job {name} uses disallowed secrets: {', '.join(sorted(unexpected))}"
            )
    for match in re.finditer(r"uses:\s*actions/checkout@[a-f0-9]{40}[^\n]*", text):
        step = text[match.start() :]
        next_step = re.search(r"\n\s+- name:", step[1:])
        if next_step:
            step = step[: next_step.start() + 1]
        if "persist-credentials: false" not in step:
            errors.append(f"{path}: checkout must disable credential persistence")
    for match in re.finditer(r"uses:\s*actions/upload-artifact@[a-f0-9]{40}[^\n]*", text):
        step = text[match.start() :]
        next_step = re.search(r"\n\s+- name:", step[1:])
        if next_step:
            step = step[: next_step.start() + 1]
        if "if-no-files-found:" not in step or "retention-days:" not in step:
            errors.append(f"{path}: artifact uploads need missing-file and retention policy")
    errors.extend(_run_blocks(path, text))
    return errors


def validate(root: Path = ROOT) -> list[str]:
    allowlist_path = root / ".github" / "policy" / "action-allowlist.txt"
    allowlist = {
        line.strip()
        for line in allowlist_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    errors: list[str] = []
    observed: set[str] = set()
    for path in sorted((root / ".github").rglob("*.yml")):
        text = path.read_text(encoding="utf-8")
        for use in USES.findall(text):
            if use.startswith("./"):
                target = root / use
                if target.is_dir():
                    target = target / "action.yml"
                if not target.exists():
                    errors.append(f"{path}: missing local action {use}")
                continue
            observed.add(use)
            if not PINNED.fullmatch(use):
                errors.append(f"{path}: external action is not pinned by SHA: {use}")
            elif use not in allowlist:
                errors.append(f"{path}: external action is not allowlisted: {use}")
        if path.parent == root / ".github" / "workflows":
            errors.extend(_validate_workflow(path, text))
        else:
            errors.extend(_run_blocks(path, text))
    unused = allowlist.difference(observed)
    errors.extend(f"allowlist entry is unused: {entry}" for entry in sorted(unused))
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("\n".join(errors))
        return 1
    print("workflow policy: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
