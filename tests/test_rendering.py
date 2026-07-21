from pathlib import Path
from copy import deepcopy
import json
import shutil
import subprocess
import tempfile
import unittest

from insynergy_cinematic.config import DEFAULT_CONFIG
from insynergy_cinematic.errors import AssetValidationError, StateConflictError
from insynergy_cinematic.media import AssetValidator
from insynergy_cinematic.models import BuildState, RenderRequest
from insynergy_cinematic.orchestrator import BuildOrchestrator
from insynergy_cinematic.providers.runway import RunwayProvider
from insynergy_cinematic.rendering import RenderCache


ROOT = Path(__file__).resolve().parents[1]


class RenderingTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_content_gate_rejects_silent_solid_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            placeholder = Path(temporary) / "placeholder.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=320x180:r=24:d=1",
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=r=48000:cl=stereo:d=1",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(placeholder),
                ],
                check=True,
            )

            with self.assertRaises(AssetValidationError) as raised:
                AssetValidator().validate(
                    placeholder,
                    width=320,
                    height=180,
                    frame_rate=24,
                    duration_seconds=1,
                    require_audio=True,
                )

            self.assertFalse(raised.exception.details["checks"]["audio_signal"])
            self.assertFalse(raised.exception.details["checks"]["visual_content"])

    def test_exact_cache_key_changes_with_profile_and_provider(self) -> None:
        base = dict(shot_hash="sha256:a", prompt_hash="sha256:b", provider="local", provider_version="1", profile="preview")
        first = RenderCache.key(**base)
        self.assertEqual(first, RenderCache.key(**base))
        changed = dict(base)
        changed["profile"] = "final"
        self.assertNotEqual(first, RenderCache.key(**changed))
        changed = dict(base)
        changed["provider_version"] = "2"
        self.assertNotEqual(first, RenderCache.key(**changed))

    def test_runway_mapping_is_deterministic_and_prompt_is_verbatim(self) -> None:
        provider = RunwayProvider(
            base_url="https://provider.invalid", api_key="secret", model_id="gen4.5"
        )
        request = RenderRequest(
            render_task_id="render-task-1",
            shot_id="shot-001",
            build_id="build-001",
            cache_key="sha256:" + "a" * 64,
            attempt=1,
            render_profile="preview",
            assembled_prompt="Exact approved prompt.",
            prompt_provenance="sha256:" + "b" * 64,
            duration_seconds=8,
            width=1280,
            height=720,
            frame_rate=24,
            provider="runway",
            strategy="runway_video",
            negative_style_tokens=("cartoon",),
        )
        first = provider.map_request(request)
        second = provider.map_request(request)
        self.assertEqual(first, second)
        self.assertEqual(first["promptText"], request.assembled_prompt)
        self.assertEqual(first["duration"], 5)
        self.assertEqual(first["ratio"], "1280:720")
        self.assertNotIn("negative_prompt", first)
        self.assertNotIn("secret", json.dumps(first))

    def test_end_to_end_local_build_and_cache_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            orchestrator = BuildOrchestrator(Path(temporary), profile="preview", provider="local")
            planned = orchestrator.plan(ROOT / "examples" / "decision-boundary.md")
            build_id = planned["build_id"]
            orchestrator.approve(build_id, gate="execution", actor="test-operator")
            mismatched = BuildOrchestrator(
                Path(temporary),
                profile="preview",
                provider="runway",
                environ={
                    "RUNWAY_BASE_URL": "https://provider.invalid",
                    "RUNWAY_API_KEY": "secret",
                    "RUNWAY_MODEL_GEN45": "gen4.5",
                },
            )
            with self.assertRaises(StateConflictError):
                mismatched.execute(build_id)
            ready = orchestrator.execute(build_id)
            self.assertEqual(ready["state"], BuildState.READY.value)
            composition_gate = ready["gates"]["composition_quality_gate"]
            self.assertTrue(composition_gate["checks"]["visual_content"])
            self.assertTrue(composition_gate["checks"]["audio_signal"])
            self.assertGreater(composition_gate["validation"]["spatial_stddev"], 4.0)
            self.assertGreater(composition_gate["validation"]["audio_rms_dbfs"], -45.0)
            self.assertTrue(
                ready["gates"]["narration_audio_quality_gate"]["checks"]["audio_non_silent"]
            )
            master = Path(temporary) / ".insynergy" / "builds" / build_id / "output" / "master.mp4"
            self.assertTrue(master.is_file())
            orchestrator.approve(build_id, gate="publish", actor="test-operator")
            published = orchestrator.publish(build_id)
            self.assertEqual(published["state"], BuildState.PUBLISHED.value)
            package = published["artifacts"]["publish_package"]
            self.assertTrue(Path(package["path"]).is_file())

            changed = deepcopy(DEFAULT_CONFIG)
            changed["render"]["budget_usd"] = 21.0
            config_path = Path(temporary) / "changed-config.json"
            config_path.write_text(json.dumps(changed), encoding="utf-8")
            second = BuildOrchestrator(
                Path(temporary), config_path=config_path, profile="preview", provider="local"
            )
            second_plan = second.plan(ROOT / "examples" / "decision-boundary.md")
            self.assertNotEqual(second_plan["build_id"], build_id)
            second.approve(second_plan["build_id"], gate="execution", actor="test-operator")
            reused = second.execute(second_plan["build_id"])
            self.assertEqual(reused["metrics"]["rendering"]["cache_hit_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
