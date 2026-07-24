"""Recover validated render assets when an approved revision changes audio only."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from insynergy_cinematic.config import load_config
from insynergy_cinematic.errors import PlatformError, ValidationError
from insynergy_cinematic.prompt import PromptAssembler
from insynergy_cinematic.rendering import RenderCache, RenderingPlatform
from insynergy_cinematic.storage import ContentAddressableStore
from insynergy_cinematic.util import atomic_write_json, content_hash


FULL_AUTO_EN_TRANSLATION = "full-auto-v11-en-translation-v1"
FULL_AUTO_V13_JA_RAGE = "full-auto-v13-ja-rage-v1"
RECOVERY_PROFILES = {
    FULL_AUTO_EN_TRANSLATION: {
        "source_language": "ja",
        "target_language": "en",
        "source_lines": (
            "朝には終わってるだろ。",
            "なんて俺はクソなんだ！",
        ),
        "target_lines": (
            "It'll be done by morning.",
            "I'm such a fucking idiot!",
        ),
    },
    FULL_AUTO_V13_JA_RAGE: {
        "source_language": "ja",
        "target_language": "ja",
        "source_lines": (
            "全部任せよう。",
            "……全部？",
            "誰が承認した？",
        ),
        "target_lines": (
            "全部任せよう。",
            "……全部？",
            "誰が承認した？",
        ),
    },
}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--source-root", type=Path, required=True)
    value.add_argument("--target-root", type=Path, default=Path.cwd())
    value.add_argument("--build-id", required=True)
    value.add_argument("--config", type=Path, required=True)
    value.add_argument("--profile", required=True)
    value.add_argument("--provider", required=True)
    value.add_argument("--runway-scope", required=True)
    value.add_argument(
        "--revision",
        choices=tuple(RECOVERY_PROFILES),
        default=FULL_AUTO_EN_TRANSLATION,
    )
    value.add_argument("--output", type=Path)
    return value


def _document(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValidationError("Audio-only recovery input is missing or unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("Audio-only recovery input is invalid") from exc
    if not isinstance(value, dict) or not isinstance(value.get("data"), dict):
        raise ValidationError("Audio-only recovery artifact envelope is invalid")
    return value["data"]


def _artifact(root: Path, build_id: str, name: str) -> dict[str, Any]:
    return _document(
        root / ".insynergy" / "builds" / build_id / "artifacts" / f"{name}.json"
    )


def _lines(narration: dict[str, Any]) -> tuple[str, ...]:
    segments = narration.get("segments")
    if not isinstance(segments, list):
        raise ValidationError("Narration segments are invalid")
    return tuple(str(item.get("text", "")) for item in segments)


def _visual_frame(frame: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in frame.items() if key != "sound_design"}


def _frames(storyboard: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values = storyboard.get("frames")
    if not isinstance(values, list) or len(values) != 8:
        raise ValidationError("Audio-only recovery requires the eight-shot storyboard")
    result: dict[str, dict[str, Any]] = {}
    for frame in values:
        if not isinstance(frame, dict):
            raise ValidationError("Storyboard frame is invalid")
        shot_id = str(frame.get("shot_id", ""))
        if not shot_id or shot_id in result:
            raise ValidationError("Storyboard shot identity is invalid")
        result[shot_id] = frame
    return result


def recover_audio_only_cache(
    *,
    source_root: Path,
    target_root: Path,
    build_id: str,
    config_path: Path,
    profile: str,
    provider: str,
    runway_scope: str,
    revision: str = FULL_AUTO_EN_TRANSLATION,
) -> dict[str, Any]:
    source_root = source_root.resolve()
    target_root = target_root.resolve()
    if source_root == target_root:
        raise ValidationError("Audio-only recovery source and target must differ")

    source_storyboard = _artifact(source_root, build_id, "storyboard")
    target_storyboard = _artifact(target_root, build_id, "storyboard")
    source_narration = _artifact(source_root, build_id, "narration_script")
    target_narration = _artifact(target_root, build_id, "narration_script")
    recovery_profile = RECOVERY_PROFILES.get(revision)
    if recovery_profile is None:
        raise ValidationError("Audio-only recovery revision is not allow-listed")
    if (
        source_narration.get("language") != recovery_profile["source_language"]
        or target_narration.get("language") != recovery_profile["target_language"]
        or _lines(source_narration) != recovery_profile["source_lines"]
        or _lines(target_narration) != recovery_profile["target_lines"]
    ):
        raise ValidationError("Audio-only recovery narration boundary does not match Full Auto")

    source_frames = _frames(source_storyboard)
    target_frames = _frames(target_storyboard)
    if source_frames.keys() != target_frames.keys():
        raise ValidationError("Audio-only recovery shot sets differ")

    assembler = PromptAssembler()
    prompt_hashes: dict[str, str] = {}
    for shot_id in source_frames:
        source_frame = source_frames[shot_id]
        target_frame = target_frames[shot_id]
        if _visual_frame(source_frame) != _visual_frame(target_frame):
            raise ValidationError(
                "Audio-only recovery detected a visual storyboard change",
                details={"shot_id": shot_id},
            )
        source_prompt = assembler.assemble(source_frame, max_utf16_units=1000)
        target_prompt = assembler.assemble(target_frame, max_utf16_units=1000)
        if source_prompt["prompt"] != target_prompt["prompt"]:
            raise ValidationError(
                "Audio-only recovery detected a visual prompt change",
                details={"shot_id": shot_id},
            )
        prompt_hashes[shot_id] = content_hash(target_prompt["prompt"])

    render_manifest = _artifact(source_root, build_id, "render_manifest")
    if render_manifest.get("all_ready") is not True:
        raise ValidationError("Audio-only recovery source render is not ready")
    results = render_manifest.get("results")
    if not isinstance(results, list) or len(results) != len(source_frames):
        raise ValidationError("Audio-only recovery source render manifest is incomplete")
    results_by_shot = {str(item.get("shot_id", "")): item for item in results}
    if results_by_shot.keys() != source_frames.keys():
        raise ValidationError("Audio-only recovery render identities differ")

    config = load_config(
        workspace=target_root,
        config_path=config_path,
        profile=profile,
        provider=provider,
        runway_scope=runway_scope,
        narration_provider="openai",
    )
    target_cache = RenderCache(
        target_root / ".insynergy" / "render-cache",
        ContentAddressableStore(target_root / ".insynergy" / "cas"),
    )
    source_cache = RenderCache(
        source_root / ".insynergy" / "render-cache",
        ContentAddressableStore(source_root / ".insynergy" / "cas"),
    )
    platform = RenderingPlatform(
        config=config,
        build_root=target_root / ".insynergy" / "builds" / build_id,
        provider_registry={"local": object(), "runway": object()},
        cache=target_cache,
    )

    recovered: list[dict[str, Any]] = []
    for shot_id, target_frame in target_frames.items():
        result = results_by_shot[shot_id]
        if (
            result.get("state") not in {"COMPLETED", "CACHED"}
            or result.get("asset_hash") is None
            or float(result.get("quality_score", 0.0)) < config.quality_threshold
            or not isinstance(result.get("validation"), dict)
            or result["validation"].get("passed") is not True
        ):
            raise ValidationError(
                "Audio-only recovery source shot is not validated",
                details={"shot_id": shot_id},
            )
        source_entry = source_cache.lookup(str(result.get("cache_key", "")))
        if source_entry is None or source_entry.get("asset_hash") != result["asset_hash"]:
            raise ValidationError(
                "Audio-only recovery source cache is incomplete",
                details={"shot_id": shot_id},
            )
        expected_overlays = [str(item) for item in target_frame.get("ui_overlays", [])]
        postproduction = source_entry["validation"].get(
            "storyboard_postproduction", {}
        )
        if postproduction.get("exact_strings") != expected_overlays:
            raise ValidationError(
                "Audio-only recovery source overlays differ",
                details={"shot_id": shot_id},
            )
        target_request = platform._request(target_frame)
        if target_request.provider != result.get("provider"):
            raise ValidationError(
                "Audio-only recovery provider assignment differs",
                details={"shot_id": shot_id},
            )
        stored = target_cache.store(
            target_request.cache_key,
            Path(source_entry["asset_uri"]),
            source_entry["validation"],
            source_entry["quality"],
        )
        recovered.append(
            {
                "shot_id": shot_id,
                "provider": target_request.provider,
                "source_cache_key": result["cache_key"],
                "target_cache_key": target_request.cache_key,
                "asset_hash": stored["asset_hash"],
                "prompt_hash": prompt_hashes[shot_id],
            }
        )

    record: dict[str, Any] = {
        "contract_version": "audio-only-render-recovery/1",
        "passed": True,
        "build_id": build_id,
        "revision": revision,
        "source_language": recovery_profile["source_language"],
        "target_language": recovery_profile["target_language"],
        "visual_projection_identical": True,
        "provider_submission_required": False,
        "recovered_shot_count": len(recovered),
        "recovered": recovered,
    }
    record["content_hash"] = content_hash(record)
    return record


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = recover_audio_only_cache(
            source_root=args.source_root,
            target_root=args.target_root,
            build_id=args.build_id,
            config_path=args.config.resolve(),
            profile=args.profile,
            provider=args.provider,
            runway_scope=args.runway_scope,
            revision=args.revision,
        )
        if args.output is not None:
            atomic_write_json(args.output, result)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except PlatformError as exc:
        print(json.dumps({"error": exc.as_dict()}, sort_keys=True, separators=(",", ":")))
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
