"""Markdown article loading at the knowledge-layer boundary."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .models import Article


def _scalar(value: str) -> Any:
    value = value.strip().strip('"').strip("'")
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return value


def _frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    closing = text.find("\n---\n", 4)
    if closing < 0:
        return {}, text
    metadata: dict[str, Any] = {}
    for line in text[4:closing].splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = _scalar(value)
    return metadata, text[closing + 5 :]


def load_article(path: Path) -> Article:
    if not path.is_file():
        raise ValidationError(f"Article does not exist: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError("Article must be UTF-8") from exc
    metadata, body = _frontmatter(raw.replace("\r\n", "\n"))
    headings = re.findall(r"^#\s+(.+?)\s*$", body, flags=re.MULTILINE)
    title = str(metadata.get("title") or (headings[0] if headings else path.stem)).strip()
    subtitle = str(metadata.get("subtitle", "")).strip()
    body = re.sub(r"^#\s+.+?\s*$", "", body, count=1, flags=re.MULTILINE).strip()
    meaningful = re.sub(r"[`*_>#\[\]()-]", " ", body)
    if len(re.findall(r"\w+", meaningful, flags=re.UNICODE)) < 20:
        raise ValidationError("Article must contain at least 20 meaningful words")
    references = tuple(re.findall(r"https?://[^\s)>]+", body))
    return Article(
        title=title,
        subtitle=subtitle,
        body=body,
        source_path=str(path.resolve()),
        metadata=metadata,
        references=references,
    )

