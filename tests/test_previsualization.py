from __future__ import annotations

import struct
import json
import tempfile
import unittest
import zlib
from copy import deepcopy
from pathlib import Path
import shutil

from insynergy_cinematic.errors import ApprovalRequiredError, ValidationError
from insynergy_cinematic.config import DEFAULT_CONFIG
from insynergy_cinematic.models import BuildState
from insynergy_cinematic.orchestrator import BuildOrchestrator
from insynergy_cinematic.previsualization import (
    PreviewFrameResult,
    PrevisualizationService,
)


ROOT = Path(__file__).resolve().parents[1]
ARTICLE = ROOT / "examples" / "decision-boundary.md"


def fixture_png(seed: int, width: int = 320, height: int = 180) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            row.extend(
                (
                    (x * 3 + seed * 23) % 256,
                    (y * 5 + seed * 31) % 256,
                    ((x + y) * 2 + seed * 47) % 256,
                )
            )
        rows.append(bytes(row))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )


class FakePreviewProvider:
    def __init__(self, *, malformed: bool = False) -> None:
        self.plan_calls = 0
        self.image_calls = 0
        self.malformed = malformed

    def create_plan(self, request):
        self.plan_calls += 1
        shots = request["shot_list"]["shots"]
        scenes = []
        for shot in shots:
            scenes.append(
                {
                    "scene_id": shot["scene_id"],
                    "shot_id": shot["shot_id"],
                    "order": shot["order"],
                    "duration_seconds": shot["duration_seconds"],
                    "scene_composition": f"{shot['camera']['framing']} composition",
                    "direction": shot["blocking"]["performance_note"],
                    "camera_work": (
                        f"{shot['camera']['lens']} {shot['camera']['movement']}"
                    ),
                    "narration": (
                        "Intentional silence."
                        if shot["dialogue_or_silence"] == "SILENCE"
                        else shot["dialogue_or_silence"]
                    ),
                    "tempo": "measured",
                    "image_prompt": (
                        f"Institutional cinematic still of {shot['blocking']['primary_action']}"
                    ),
                    "video_prompt": (
                        f"Future motion shot: {shot['blocking']['primary_action']}; "
                        f"camera {shot['camera']['movement']}"
                    ),
                    "risk_flags": [],
                }
            )
        if self.malformed:
            scenes[0].pop("tempo")
        return {
            "plan": {"summary": "Review the sealed eight-shot decision arc.", "scenes": scenes},
            "response_id": "resp-fixture-plan",
            "model_resolved": "gpt-5.6-sol",
            "usage": {"input_tokens": 100, "output_tokens": 200, "total_tokens": 300},
        }

    def generate_frame(self, request):
        self.image_calls += 1
        return PreviewFrameResult(
            image_bytes=fixture_png(self.image_calls),
            response_id=f"resp-fixture-image-{self.image_calls}",
            model_resolved="gpt-image-fixture",
            output_format="png",
            usage={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
        )


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class PrevisualizationTests(unittest.TestCase):
    def make_orchestrator(
        self, workspace: Path, preview_provider: FakePreviewProvider, **kwargs
    ):
        return BuildOrchestrator(
            workspace,
            profile="preview",
            pre_render_preview_mode="storyboard_animatic",
            preview_provider=preview_provider,
            environ=kwargs.pop("environ", {}),
            **kwargs,
        )

    def test_zero_runway_preview_is_cached_sealed_and_approved_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            provider = FakePreviewProvider()
            orchestrator = self.make_orchestrator(Path(temporary), provider)
            planned = orchestrator.plan(ARTICLE)
            self.assertEqual(planned["state"], BuildState.PLANNED.value)
            preflight = orchestrator.preview_preflight(planned["build_id"])
            self.assertTrue(preflight["passed"])
            self.assertFalse(preflight["openai_provider_initialized"])
            self.assertEqual(preflight["runway_api_calls"], 0)

            preview = orchestrator.previsualize(planned["build_id"])
            self.assertEqual(
                preview["state"],
                BuildState.AWAITING_STORYBOARD_PREVIEW_APPROVAL.value,
            )
            self.assertEqual((provider.plan_calls, provider.image_calls), (1, 8))
            self.assertEqual(preview["previsualization"]["runway_api_calls"], 0)
            for name in (
                "previsualization_plan",
                "image_prompt_set",
                "video_prompt_set",
                "storyboard_preview_manifest",
                "storyboard_preview_quality_report",
            ):
                self.assertIn(name, preview["artifacts"])
            animatic = Path(preview["previsualization"]["animatic_path"])
            review_html = Path(preview["previsualization"]["review_html_path"])
            self.assertTrue(animatic.is_file())
            self.assertTrue(review_html.is_file())
            manifest = orchestrator.repository.load(planned["build_id"])
            preview_document = orchestrator.repository.load_artifact(
                manifest, "storyboard_preview_manifest"
            )["data"]
            quality_document = orchestrator.repository.load_artifact(
                manifest, "storyboard_preview_quality_report"
            )["data"]
            self.assertEqual(
                preview_document["animatic"]["overlay_contract"],
                "preview-shot-identity-timecode/1",
            )
            self.assertTrue(preview_document["animatic"]["ffmpeg_version"])
            self.assertTrue(
                quality_document["checks"]["shot_identity_overlay_present"]
            )

            replay = orchestrator.previsualize(planned["build_id"])
            self.assertEqual(replay["state"], preview["state"])
            self.assertEqual((provider.plan_calls, provider.image_calls), (1, 8))
            recomposed = orchestrator.recompose_preview(planned["build_id"])
            self.assertEqual(recomposed["state"], preview["state"])
            self.assertEqual((provider.plan_calls, provider.image_calls), (1, 8))

            approved = orchestrator.approve(
                planned["build_id"],
                gate="storyboard-preview",
                actor="creative-reviewer",
            )
            self.assertEqual(
                approved["state"], BuildState.AWAITING_EXECUTION_APPROVAL.value
            )
            self.assertIn(
                "storyboard_preview_approval_binding", approved["artifacts"]
            )
            execution = orchestrator.approve(
                planned["build_id"], gate="execution", actor="render-reviewer"
            )
            self.assertEqual(execution["approvals"]["execution"]["decision"], "APPROVED")

    def test_corrupted_preview_fails_closed_before_runway_provider_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            provider = FakePreviewProvider()
            orchestrator = self.make_orchestrator(
                Path(temporary),
                provider,
                provider="runway",
                environ={
                    "RUNWAY_BASE_URL": "https://api.dev.runwayml.com",
                    "RUNWAY_API_KEY": "unused-before-admission",
                    "RUNWAY_MODEL_GEN45": "gen4.5",
                },
            )
            planned = orchestrator.plan(ARTICLE)
            orchestrator.previsualize(planned["build_id"])
            orchestrator.approve(
                planned["build_id"], gate="storyboard-preview", actor="creative-reviewer"
            )
            orchestrator.approve(
                planned["build_id"], gate="execution", actor="render-reviewer"
            )
            manifest = orchestrator.repository.load(planned["build_id"])
            preview_manifest = orchestrator.repository.load_artifact(
                manifest, "storyboard_preview_manifest"
            )["data"]
            Path(preview_manifest["frames"][0]["asset_path"]).write_bytes(b"corrupted")
            calls = 0

            def provider_spy(_manifest):
                nonlocal calls
                calls += 1
                return {}

            orchestrator._providers = provider_spy  # type: ignore[method-assign]
            with self.assertRaises(ApprovalRequiredError):
                orchestrator.execute(planned["build_id"])
            self.assertEqual(calls, 0)

    def test_malformed_gpt_plan_and_environment_self_review_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            malformed = FakePreviewProvider(malformed=True)
            orchestrator = self.make_orchestrator(Path(temporary), malformed)
            planned = orchestrator.plan(ARTICLE)
            with self.assertRaises(ValidationError):
                orchestrator.previsualize(planned["build_id"])
            self.assertEqual(malformed.image_calls, 0)

        with tempfile.TemporaryDirectory() as temporary:
            provider = FakePreviewProvider()
            orchestrator = self.make_orchestrator(Path(temporary), provider)
            planned = orchestrator.plan(ARTICLE)
            orchestrator.previsualize(planned["build_id"])
            with self.assertRaises(ValidationError):
                orchestrator.approve(
                    planned["build_id"],
                    gate="storyboard-preview",
                    actor="same-user",
                    workflow_initiator="same-user",
                    environment_reviewer="same-user",
                    environment_reviewer_id=238604656,
                    prevent_self_review=True,
                    environment_review_hash="sha256:" + "a" * 64,
                    environment_policy_hash="sha256:" + "b" * 64,
                )

            approved = orchestrator.approve(
                planned["build_id"],
                gate="storyboard-preview",
                actor="Insynergy-jp",
                workflow_initiator="Insynergy-jp",
                environment_reviewer="Insynergy-jp",
                environment_reviewer_id=238604656,
                prevent_self_review=False,
                environment_review_hash="sha256:" + "a" * 64,
                environment_policy_hash="sha256:" + "b" * 64,
            )
            manifest = orchestrator.repository.load(planned["build_id"])
            binding = orchestrator.repository.load_artifact(
                manifest, "storyboard_preview_approval_binding"
            )
            self.assertEqual(
                approved["state"], BuildState.AWAITING_EXECUTION_APPROVAL.value
            )
            self.assertEqual(binding["environment_reviewer_id"], 238604656)
            self.assertEqual(
                binding["planning_hash"], orchestrator._planning_hash(manifest)
            )
            self.assertEqual(
                binding["environment_policy_hash"], "sha256:" + "b" * 64
            )

    def test_image_budget_rejects_before_preview_provider_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            values = deepcopy(DEFAULT_CONFIG)
            values["pre_render_preview"]["mode"] = "storyboard_animatic"
            values["pre_render_preview"]["max_images"] = 4
            config_path = workspace / "preview-budget.json"
            config_path.write_text(json.dumps(values), encoding="utf-8")
            provider = FakePreviewProvider()
            orchestrator = BuildOrchestrator(
                workspace,
                config_path=config_path,
                preview_provider=provider,
                environ={},
            )
            planned = orchestrator.plan(ARTICLE)
            with self.assertRaises(ValidationError):
                orchestrator.preview_preflight(planned["build_id"])
            with self.assertRaises(ValidationError):
                orchestrator.previsualize(planned["build_id"])
            self.assertEqual((provider.plan_calls, provider.image_calls), (0, 0))

    def test_exact_cache_replay_has_zero_current_usage_and_tampering_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            provider = FakePreviewProvider()
            orchestrator = self.make_orchestrator(workspace, provider)
            planned = orchestrator.plan(ARTICLE)
            manifest = orchestrator.repository.load(planned["build_id"])
            service = PrevisualizationService(
                config=orchestrator.config,
                build_root=orchestrator.repository.build_dir(planned["build_id"]),
                cache_root=orchestrator.repository.root / "previsualization-cache",
                provider=provider,
            )
            arguments = {
                "build_id": planned["build_id"],
                "planning_hash": orchestrator._planning_hash(manifest),
                "screenplay": orchestrator.repository.load_artifact(
                    manifest, "screenplay"
                )["data"],
                "shot_list": orchestrator.repository.load_artifact(
                    manifest, "shot_list"
                )["data"],
                "storyboard": orchestrator.repository.load_artifact(
                    manifest, "storyboard"
                )["data"],
            }
            first = service.run(**arguments)
            replay = service.run(**arguments)
            self.assertEqual((provider.plan_calls, provider.image_calls), (1, 8))
            self.assertEqual(
                replay["storyboard_preview_manifest"]["provider_calls"],
                {"gpt_plan": 0, "gpt_image": 0, "runway": 0},
            )
            self.assertEqual(
                replay["storyboard_preview_manifest"]["usage_summary"][
                    "total_tokens"
                ],
                0,
            )
            self.assertEqual(
                first["storyboard_preview_manifest"]["animatic"]["content_hash"],
                replay["storyboard_preview_manifest"]["animatic"]["content_hash"],
            )

            cached_frame = next(
                (orchestrator.repository.root / "previsualization-cache" / "frames").glob(
                    "*.png"
                )
            )
            cached_frame.write_bytes(b"tampered")
            with self.assertRaises(ValidationError):
                service.run(**arguments)


if __name__ == "__main__":
    unittest.main()
