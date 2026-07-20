"""Fail closed when a workflow uses an unpinned or unapproved Action."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
USES = re.compile(r"^\s*uses:\s*([^\s#]+)", flags=re.MULTILINE)
PINNED = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[a-f0-9]{40}$")


def validate() -> list[str]:
    allowlist_path = ROOT / ".github" / "policy" / "action-allowlist.txt"
    allowlist = {
        line.strip()
        for line in allowlist_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    errors: list[str] = []
    observed: set[str] = set()
    for path in sorted((ROOT / ".github").rglob("*.yml")):
        text = path.read_text(encoding="utf-8")
        for use in USES.findall(text):
            if use.startswith("./"):
                target = ROOT / use
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

