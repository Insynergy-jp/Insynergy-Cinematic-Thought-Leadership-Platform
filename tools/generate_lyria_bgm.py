from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path

from google import genai


MODEL = "lyria-3-clip-preview"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate one 30-second Lyria 3 Clip music preview."
    )
    parser.add_argument("--prompt-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is required")

    prompt = args.prompt_file.read_text(encoding="utf-8").strip()
    if not prompt:
        raise SystemExit("prompt file is empty")

    client = genai.Client(api_key=api_key)
    interaction = client.interactions.create(model=MODEL, input=prompt)
    audio = interaction.output_audio
    if audio is None or not audio.data:
        raise RuntimeError("Lyria response did not contain output audio")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(base64.b64decode(audio.data))

    metadata = {
        "model": MODEL,
        "prompt_file": str(args.prompt_file),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "output_file": str(args.output),
    }
    args.output.with_suffix(".json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(metadata, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
