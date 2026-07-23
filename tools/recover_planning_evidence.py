"""Recover one hash-bound Persona approval file from its planning base artifact."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path, PurePosixPath

from insynergy_cinematic.errors import PlatformError, ValidationError
from insynergy_cinematic.util import file_hash, read_json


RECOVERABLE_PATH = "persona-approval-result.json"


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--root", type=Path, default=Path.cwd())
    value.add_argument("--evidence", type=Path, default=Path("workflow-evidence.json"))
    value.add_argument("--github-output", type=Path)
    commands = value.add_subparsers(dest="command", required=True)
    commands.add_parser("inspect")
    recover = commands.add_parser("recover")
    recover.add_argument("--source-root", type=Path, required=True)
    return value


def _safe_path(root: Path, raw_path: object) -> Path:
    if not isinstance(raw_path, str):
        raise ValidationError("Workflow evidence path must be a string")
    portable = PurePosixPath(raw_path)
    if portable.is_absolute() or ".." in portable.parts or raw_path != portable.as_posix():
        raise ValidationError(
            "Workflow evidence path is unsafe",
            details={"path": raw_path},
        )
    candidate = root.joinpath(*portable.parts)
    if not candidate.resolve(strict=False).is_relative_to(root.resolve()):
        raise ValidationError(
            "Workflow evidence path escapes its root",
            details={"path": raw_path},
        )
    return candidate


def _entries(root: Path, evidence_path: Path) -> list[dict]:
    evidence = read_json(_safe_path(root, evidence_path.as_posix()))
    if not isinstance(evidence, dict) or evidence.get("contract_version") != "workflow-evidence/1":
        raise ValidationError("Workflow evidence contract is invalid")
    entries = evidence.get("files")
    if not isinstance(entries, list):
        raise ValidationError("Workflow evidence files are invalid")
    normalized: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "size", "sha256"}:
            raise ValidationError("Workflow evidence file entry is invalid")
        _safe_path(root, entry["path"])
        if not isinstance(entry["size"], int) or entry["size"] < 0:
            raise ValidationError("Workflow evidence file size is invalid")
        if not isinstance(entry["sha256"], str) or not entry["sha256"].startswith("sha256:"):
            raise ValidationError("Workflow evidence file hash is invalid")
        normalized.append(entry)
    return normalized


def inspect_recovery(root: Path, evidence_path: Path) -> dict:
    root = root.resolve()
    entries = _entries(root, evidence_path)
    missing = sorted(
        entry["path"]
        for entry in entries
        if not _safe_path(root, entry["path"]).is_file()
    )
    if not missing:
        return {"passed": True, "recovery_required": False, "missing": []}
    if missing != [RECOVERABLE_PATH]:
        raise ValidationError(
            "Planning evidence has non-recoverable missing files",
            details={"missing": missing},
        )
    return {
        "passed": True,
        "recovery_required": True,
        "missing": missing,
    }


def recover(root: Path, evidence_path: Path, source_root: Path) -> dict:
    root = root.resolve()
    source_root = source_root.resolve()
    inspection = inspect_recovery(root, evidence_path)
    if inspection["recovery_required"] is not True:
        raise ValidationError("Planning evidence does not require recovery")
    entry = next(
        entry for entry in _entries(root, evidence_path) if entry["path"] == RECOVERABLE_PATH
    )
    source = _safe_path(source_root, RECOVERABLE_PATH)
    target = _safe_path(root, RECOVERABLE_PATH)
    if source.is_symlink() or not source.is_file():
        raise ValidationError("Recoverable planning evidence source is not a regular file")
    if target.exists() or target.is_symlink():
        raise ValidationError("Recoverable planning evidence target already exists")
    if source.stat().st_size != entry["size"] or file_hash(source) != entry["sha256"]:
        raise ValidationError(
            "Recoverable planning evidence does not match its sealed hash",
            details={"path": RECOVERABLE_PATH},
        )
    payload = source.read_bytes()
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", dir=target.parent
    )
    try:
        with os.fdopen(file_descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, target)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    if target.stat().st_size != entry["size"] or file_hash(target) != entry["sha256"]:
        raise ValidationError("Recovered planning evidence failed post-write verification")
    return {
        "passed": True,
        "recovered": RECOVERABLE_PATH,
        "sha256": entry["sha256"],
        "size": entry["size"],
    }


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect_recovery(args.root, args.evidence)
            if args.github_output:
                args.github_output.parent.mkdir(parents=True, exist_ok=True)
                with args.github_output.open("a", encoding="utf-8", newline="\n") as output:
                    required = "true" if result["recovery_required"] else "false"
                    output.write(f"recovery_required={required}\n")
        else:
            result = recover(args.root, args.evidence, args.source_root)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except PlatformError as exc:
        print(json.dumps({"error": exc.as_dict()}, sort_keys=True, separators=(",", ":")))
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
