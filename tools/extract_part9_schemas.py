"""Extract the 58 normative JSON Schema documents from Part 9.

This is a maintainer tool. Runtime code consumes the checked-in schemas.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse


def extract(source: Path, destination: Path) -> list[Path]:
    text = source.read_text(encoding="utf-8")
    pattern = re.compile(
        r"^(?:# Canonical Schema|## Agent Review Report schema|## Review Approval Binding schema)\s*$.*?^```json\s*$\n(.*?)^```\s*$",
        flags=re.MULTILINE | re.DOTALL,
    )
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for match in pattern.finditer(text):
        document = json.loads(match.group(1))
        schema_id = document.get("$id")
        if not schema_id:
            raise ValueError("Canonical schema has no $id")
        filename = Path(urlparse(schema_id).path).name
        if not filename.endswith(".schema.json"):
            raise ValueError(f"Unexpected canonical schema id: {schema_id}")
        path = destination / filename
        if path.exists():
            raise ValueError(f"Duplicate canonical schema filename: {filename}")
        path.write_text(
            json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    if len(written) != 58:
        raise ValueError(f"Expected 58 canonical schemas, extracted {len(written)}")
    return written


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    written = extract(args.source, args.destination)
    print(json.dumps({"extracted": len(written), "destination": str(args.destination)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
