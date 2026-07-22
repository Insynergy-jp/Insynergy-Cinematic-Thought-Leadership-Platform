"""Refresh generated Part 9 registry/package data and initialize a release baseline."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from insynergy_cinematic.schemas import registry
from insynergy_cinematic.util import atomic_write_json, content_hash, file_hash


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
PACKAGED = ROOT / "src" / "insynergy_cinematic" / "schema_data"


def refresh(*, initialize_baseline: bool = False) -> dict[str, int | bool]:
    baseline_path = SCHEMAS / "compatibility-baseline.json"
    if initialize_baseline:
        if baseline_path.exists():
            raise ValueError("compatibility baseline already exists and is immutable")
        files: dict[str, str] = {}
        for path in sorted(SCHEMAS.rglob("*.schema.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            schema_id = str(document.get("$id", ""))
            if "/v2.0/" in schema_id or "/v2.1/" in schema_id:
                files[path.relative_to(SCHEMAS).as_posix()] = file_hash(path)
        baseline = {
            "schema_version": "1.0.0",
            "contract_version": "schema-compatibility-baseline/1",
            "release": "3.2.0",
            "files": files,
            "content_hash": content_hash(files),
        }
        atomic_write_json(baseline_path, baseline)
    if not baseline_path.is_file():
        raise ValueError("initialize the compatibility baseline before refreshing")
    atomic_write_json(SCHEMAS / "schema-registry.json", registry())
    copied = 0
    for source in sorted(SCHEMAS.rglob("*.json")):
        relative = source.relative_to(SCHEMAS)
        target = PACKAGED / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        copied += 1
    return {"initialized_baseline": initialize_baseline, "copied": copied}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--initialize-compatibility-baseline", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            refresh(initialize_baseline=args.initialize_compatibility_baseline),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
