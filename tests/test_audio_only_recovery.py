from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from insynergy_cinematic.config import load_config
from insynergy_cinematic.errors import ValidationError
from insynergy_cinematic.rendering import RenderCache, RenderingPlatform
from insynergy_cinematic.storage import ContentAddressableStore
from tools.recover_audio_only_cache import (
    FULL_AUTO_V13_JA_RAGE,
    recover_audio_only_cache,
)


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "20260723-001"


def envelope(data: dict) -> dict:
    return {"data": data}


def frame(shot_id: str, sound: str) -> dict:
    return {
        "frame_id": f"frame-{shot_id[-2:]}",
        "scene_id": shot_id.split("-shot")[0],
        "shot_id": shot_id,
        "duration_seconds": 3.0,
        "composition": "Developer and desktop monitor.",
        "visible_action": "The developer watches the monitor.",
        "camera": {
            "framing": "medium",
            "lens": "50mm",
            "movement": "static",
            "speed": "none",
            "angle": "eye_level",
        },
        "character_continuity": {"protagonist": "full-auto-v11"},
        "characters": ["protagonist"],
        "location": "Home Office",
        "lighting": "cool monitor blue",
        "emotion": "control",
        "style": ["restrained live-action realism"],
        "forbidden_style": ["logo", "trademark"],
        "render_strategy": {
            "asset_class": "animated_still",
            "execution_capability": "static_live_action_tableau",
        },
        "ui_overlays": ["RUN #001 STARTED"],
        "sound_design": sound,
    }


class AudioOnlyRecoveryTests(unittest.TestCase):
    def _prepare(
        self,
        root: Path,
        *,
        visual_change: bool = False,
        v13_rage: bool = False,
    ) -> tuple[Path, Path]:
        source = root / "source"
        target = root / "target"
        source_artifacts = source / ".insynergy" / "builds" / BUILD_ID / "artifacts"
        target_artifacts = target / ".insynergy" / "builds" / BUILD_ID / "artifacts"
        source_artifacts.mkdir(parents=True)
        target_artifacts.mkdir(parents=True)
        config_name = "production-config-v13.json" if v13_rage else "production-config.json"
        config_value = json.loads(
            (ROOT / "creative" / "full-auto-30s" / config_name).read_text(encoding="utf-8")
        )
        config_value["soundtrack"]["path"] = ""
        (source / "config.json").write_text(json.dumps(config_value), encoding="utf-8")
        (target / "config.json").write_text(json.dumps(config_value), encoding="utf-8")

        source_frames = [frame(f"scene-{index:03d}-shot-01", "Japanese line") for index in range(1, 9)]
        target_frames = [deepcopy(item) for item in source_frames]
        target_frames[0]["sound_design"] = "English line"
        target_frames[6]["sound_design"] = "English shout"
        if visual_change:
            target_frames[6]["visible_action"] = "A different visual action."

        (source_artifacts / "storyboard.json").write_text(
            json.dumps(envelope({"frames": source_frames})), encoding="utf-8"
        )
        (target_artifacts / "storyboard.json").write_text(
            json.dumps(envelope({"frames": target_frames})), encoding="utf-8"
        )
        if v13_rage:
            narration = {"language": "ja", "segments": [
                {"scene_id": "scene-001", "text": "全部任せよう。"},
                {"scene_id": "scene-005", "text": "……全部？"},
                {"scene_id": "scene-007", "text": "誰が承認した？"},
            ]}
            source_narration = narration
            target_narration = deepcopy(narration)
        else:
            source_narration = {"language": "ja", "segments": [
                {"scene_id": "scene-001", "text": "朝には終わってるだろ。"},
                {"scene_id": "scene-007", "text": "なんて俺はクソなんだ！"},
            ]}
            target_narration = {"language": "en", "segments": [
                {"scene_id": "scene-001", "text": "It'll be done by morning."},
                {"scene_id": "scene-007", "text": "I'm such a fucking idiot!"},
            ]}
        (source_artifacts / "narration_script.json").write_text(
            json.dumps(envelope(source_narration)), encoding="utf-8"
        )
        (target_artifacts / "narration_script.json").write_text(
            json.dumps(envelope(target_narration)), encoding="utf-8"
        )

        config = load_config(
            workspace=source,
            config_path=source / "config.json",
            profile="final",
            provider="runway",
            runway_scope="hybrid",
            narration_provider="openai",
        )
        source_cache = RenderCache(
            source / ".insynergy" / "render-cache",
            ContentAddressableStore(source / ".insynergy" / "cas"),
        )
        platform = RenderingPlatform(
            config=config,
            build_root=source / ".insynergy" / "builds" / BUILD_ID,
            provider_registry={"local": object(), "runway": object()},
            cache=source_cache,
        )
        results = []
        for item in source_frames:
            request = platform._request(item)
            asset = root / f"{item['shot_id']}.mp4"
            asset.write_bytes((item["shot_id"] + "-validated-picture").encode())
            validation = {
                "passed": True,
                "storyboard_postproduction": {"exact_strings": item["ui_overlays"]},
            }
            quality = {"passed": True, "score": 1.0}
            stored = source_cache.store(request.cache_key, asset, validation, quality)
            results.append({
                "shot_id": item["shot_id"],
                "state": "COMPLETED",
                "provider": request.provider,
                "cache_key": request.cache_key,
                "asset_hash": stored["asset_hash"],
                "quality_score": 1.0,
                "validation": validation,
            })
        (source_artifacts / "render_manifest.json").write_text(
            json.dumps(envelope({"all_ready": True, "results": results})), encoding="utf-8"
        )
        return source, target

    def test_recovers_all_validated_picture_assets_when_only_audio_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source, target = self._prepare(Path(temporary))
            with patch.dict(os.environ, {}, clear=False):
                result = recover_audio_only_cache(
                    source_root=source,
                    target_root=target,
                    build_id=BUILD_ID,
                    config_path=target / "config.json",
                    profile="final",
                    provider="runway",
                    runway_scope="hybrid",
                )
            self.assertTrue(result["passed"])
            self.assertEqual(result["recovered_shot_count"], 8)
            self.assertFalse(result["provider_submission_required"])
            self.assertEqual(
                len(list((target / ".insynergy" / "render-cache").glob("*.json"))),
                8,
            )

    def test_rejects_any_visual_storyboard_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source, target = self._prepare(Path(temporary), visual_change=True)
            with self.assertRaisesRegex(ValidationError, "visual storyboard change"):
                recover_audio_only_cache(
                    source_root=source,
                    target_root=target,
                    build_id=BUILD_ID,
                    config_path=target / "config.json",
                    profile="final",
                    provider="runway",
                    runway_scope="hybrid",
                )

    def test_recovers_v13_picture_for_japanese_rage_performance_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source, target = self._prepare(Path(temporary), v13_rage=True)
            result = recover_audio_only_cache(
                source_root=source,
                target_root=target,
                build_id=BUILD_ID,
                config_path=target / "config.json",
                profile="final",
                provider="runway",
                runway_scope="hybrid",
                revision=FULL_AUTO_V13_JA_RAGE,
            )
            self.assertTrue(result["passed"])
            self.assertEqual(result["revision"], FULL_AUTO_V13_JA_RAGE)
            self.assertEqual(result["source_language"], "ja")
            self.assertEqual(result["target_language"], "ja")
            self.assertEqual(result["recovered_shot_count"], 8)
            self.assertFalse(result["provider_submission_required"])


if __name__ == "__main__":
    unittest.main()
