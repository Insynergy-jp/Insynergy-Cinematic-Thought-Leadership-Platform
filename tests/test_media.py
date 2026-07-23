import io
import json
import math
from copy import deepcopy
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave
import zipfile

from insynergy_cinematic.config import DEFAULT_CONFIG
from insynergy_cinematic.errors import ValidationError
from insynergy_cinematic.media import (
    AssetValidator,
    OpenAITTSNarrator,
    SoundtrackMixer,
    YouTubeMastering,
    write_srt,
)
from insynergy_cinematic.models import BuildState
from insynergy_cinematic.orchestrator import BuildOrchestrator


ROOT = Path(__file__).resolve().parents[1]


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
        return False


def _wav_bytes(duration: float = 0.75, frequency: float = 220.0) -> bytes:
    target = io.BytesIO()
    sample_rate = 24000
    with wave.open(target, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        frames = bytearray()
        for index in range(round(duration * sample_rate)):
            sample = round(10000 * math.sin(2 * math.pi * frequency * index / sample_rate))
            frames.extend(struct.pack("<h", sample))
        output.writeframes(bytes(frames))
    return target.getvalue()


@unittest.skipUnless(
    shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required"
)
class ProductionMediaTests(unittest.TestCase):
    @staticmethod
    def _source(path: Path, *, duration: float = 3.0) -> None:
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
                f"testsrc2=s=320x180:r=24:d={duration}",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=110:sample_rate=48000:duration={duration}",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(path),
            ],
            check=True,
        )

    def test_openai_narrator_uses_allowlisted_speech_request_and_mixes_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            master = Path(temporary) / "master.mp4"
            self._source(master)
            requests = []

            def fake_urlopen(request, timeout):
                requests.append((request, timeout))
                return _FakeResponse(_wav_bytes())

            narrator = OpenAITTSNarrator(
                api_key="tts-secret-not-for-artifacts",
                model="gpt-4o-mini-tts",
                voice="marin",
                instructions="Calm documentary narration.",
            )
            with patch(
                "insynergy_cinematic.media.urllib.request.urlopen",
                side_effect=fake_urlopen,
            ):
                result = narrator.mix(
                    master,
                    [
                        {
                            "start_seconds": 0.2,
                            "end_seconds": 1.25,
                            "text": "Authority requires an owner.",
                        },
                        {
                            "start_seconds": 1.5,
                            "end_seconds": 2.6,
                            "text": "The record makes accountability visible.",
                        },
                    ],
                    duration_seconds=3.0,
                )

            self.assertEqual(len(requests), 2)
            request, timeout = requests[0]
            payload = json.loads(request.data)
            self.assertEqual(request.full_url, OpenAITTSNarrator.API_URL)
            self.assertEqual(timeout, 120)
            self.assertEqual(payload["model"], "gpt-4o-mini-tts")
            self.assertEqual(payload["voice"], "marin")
            self.assertEqual(payload["response_format"], "wav")
            self.assertNotIn("tts-secret-not-for-artifacts", json.dumps(result))
            validation = AssetValidator().validate(
                master,
                width=320,
                height=180,
                frame_rate=24,
                duration_seconds=3.0,
                require_audio=True,
            )
            self.assertTrue(validation["audio_non_silent"])
            self.assertEqual(result["narration_engine"], "openai-speech-api")
            self.assertTrue(result["ai_generated_voice"])

    def test_openai_narrator_requires_dedicated_key(self) -> None:
        with self.assertRaises(ValidationError):
            OpenAITTSNarrator(api_key="", instructions="Calm narration.")

    def test_soundtrack_mix_is_hash_bound_and_trimmed_to_master(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            master = root / "master.mp4"
            soundtrack = root / "soundtrack.mp3"
            self._source(master, duration=3.0)
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
                    "sine=frequency=330:sample_rate=48000:duration=4",
                    str(soundtrack),
                ],
                check=True,
            )
            from insynergy_cinematic.util import file_hash

            soundtrack_hash = file_hash(soundtrack)
            result = SoundtrackMixer().mix(
                master,
                soundtrack,
                duration_seconds=3.0,
                gain_db=-20.0,
                expected_hash=soundtrack_hash,
            )

            validation = AssetValidator().validate(
                master,
                width=320,
                height=180,
                frame_rate=24,
                duration_seconds=3.0,
                require_audio=True,
            )
            self.assertTrue(validation["audio_non_silent"])
            self.assertEqual(result["soundtrack_hash"], soundtrack_hash)
            self.assertEqual(result["soundtrack_duration_seconds"], 3.0)

    def test_youtube_mastering_and_delivery_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            master = Path(temporary) / "master.mp4"
            self._source(master, duration=2.0)
            YouTubeMastering().master(
                master,
                width=640,
                height=360,
                frame_rate=24,
                video_bitrate="1M",
                audio_bitrate="192k",
            )
            validation = AssetValidator().validate(
                master,
                width=640,
                height=360,
                frame_rate=24,
                duration_seconds=2.0,
                require_audio=True,
                require_youtube_ready=True,
            )
            self.assertTrue(validation["youtube_ready"])
            self.assertTrue(all(validation["youtube_checks"].values()))

    def test_srt_contains_timed_narration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "captions.en.srt"
            result = write_srt(
                destination,
                [
                    {
                        "start_seconds": 0.65,
                        "end_seconds": 9.65,
                        "text": "Authority requires an owner.",
                    }
                ],
                duration_seconds=10.0,
            )
            contents = destination.read_text(encoding="utf-8")
            self.assertIn("00:00:00,650 --> 00:00:09,650", contents)
            self.assertIn("Authority requires an owner.", contents)
            self.assertEqual(result["caption_language"], "en")

    def test_srt_preserves_japanese_dialogue_language(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "captions.ja.srt"
            result = write_srt(
                destination,
                [
                    {
                        "start_seconds": 0.65,
                        "end_seconds": 2.65,
                        "text": "朝には終わってるだろ。",
                    }
                ],
                duration_seconds=3.0,
                language="ja",
            )

            self.assertIn(
                "朝には終わってるだろ。", destination.read_text(encoding="utf-8")
            )
            self.assertEqual(result["caption_language"], "ja")

    def test_final_build_packages_production_narration_and_youtube_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            config = deepcopy(DEFAULT_CONFIG)
            config["render"]["final"] = {
                "width": 640,
                "height": 360,
                "frame_rate": 24,
                "max_duration_seconds": 5,
            }
            config_path = workspace / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            orchestrator = BuildOrchestrator(
                workspace,
                config_path=config_path,
                profile="final",
                provider="local",
                narration_provider="openai",
                environ={"OPENAI_TTS_API_KEY": "dedicated-test-key"},
            )
            planned = orchestrator.plan(ROOT / "examples" / "decision-boundary.md")
            build_id = planned["build_id"]
            orchestrator.approve(build_id, gate="execution", actor="test-operator")
            with patch(
                "insynergy_cinematic.media.urllib.request.urlopen",
                side_effect=lambda request, timeout: _FakeResponse(_wav_bytes()),
            ):
                ready = orchestrator.execute(build_id)
            self.assertEqual(ready["state"], BuildState.READY.value)
            self.assertTrue(
                ready["gates"]["composition_quality_gate"]["checks"][
                    "youtube_delivery"
                ]
            )
            self.assertEqual(
                ready["gates"]["narration_audio_quality_gate"]["narration_engine"],
                "openai-speech-api",
            )
            output = workspace / ".insynergy" / "builds" / build_id / "output"
            self.assertTrue((output / "captions.en.srt").is_file())
            disclosure = (output / "youtube-description.txt").read_text(encoding="utf-8")
            self.assertIn("AI-generated narration voice", disclosure)
            orchestrator.approve(build_id, gate="publish", actor="test-operator")
            published = orchestrator.publish(build_id)
            package_reference = Path(
                published["artifacts"]["publish_package"]["path"]
            )
            package_record = json.loads(package_reference.read_text(encoding="utf-8"))
            package_path = Path(package_record["data"]["package_uri"])
            with zipfile.ZipFile(package_path) as package:
                names = set(package.namelist())
            self.assertIn("media/master.mp4", names)
            self.assertIn("media/captions.en.srt", names)
            self.assertIn("metadata/youtube-description.txt", names)


if __name__ == "__main__":
    unittest.main()
