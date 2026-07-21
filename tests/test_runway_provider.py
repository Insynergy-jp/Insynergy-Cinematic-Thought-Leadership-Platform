from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path

from insynergy_cinematic.errors import (
    ProviderSubmissionError,
    ProviderTimeoutError,
)
from insynergy_cinematic.models import RenderRequest, RenderState
from insynergy_cinematic.providers.runway import (
    RUNWAY_API_VERSION,
    RunwayProvider,
)
from insynergy_cinematic.util import read_json


class FakeResponse:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._body = io.BytesIO(body)
        self.headers = headers or {}

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class RecordingOpener:
    def __init__(self, *responses: FakeResponse | BaseException) -> None:
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, *, timeout: int):
        self.requests.append((request, timeout))
        if not self.responses:
            raise AssertionError(f"Unexpected request: {request.full_url}")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def render_request(**overrides: object) -> RenderRequest:
    values = {
        "render_task_id": "render-task-1",
        "shot_id": "shot-001",
        "build_id": "build-001",
        "cache_key": "sha256:" + "a" * 64,
        "attempt": 1,
        "render_profile": "preview",
        "assembled_prompt": "Exact approved prompt.",
        "prompt_provenance": "sha256:" + "b" * 64,
        "duration_seconds": 5,
        "width": 1280,
        "height": 720,
        "frame_rate": 24,
        "provider": "runway",
        "strategy": "runway_video",
        "negative_style_tokens": ("cartoon",),
    }
    values.update(overrides)
    return RenderRequest(**values)


class RunwayProviderTests(unittest.TestCase):
    @staticmethod
    def provider(opener: RecordingOpener, state_path: Path | None = None) -> RunwayProvider:
        return RunwayProvider(
            base_url="https://api.dev.runwayml.com",
            api_key="test-secret",
            model_id="gen4.5",
            state_path=state_path,
            opener=opener,
        )

    def test_submit_uses_current_api_and_persists_client_idempotency(self) -> None:
        opener = RecordingOpener(FakeResponse(b'{"id":"task-123"}'))
        with tempfile.TemporaryDirectory() as temporary:
            state_path = Path(temporary) / "runway" / "jobs.json"
            provider = self.provider(opener, state_path)
            request = render_request()

            first = provider.submit(request)
            second = provider.submit(request)
            reloaded = self.provider(RecordingOpener(), state_path).submit(request)

            self.assertEqual(first.provider_task_id, "task-123")
            self.assertEqual(first.idempotency_key, request.cache_key)
            self.assertEqual(second, first)
            self.assertEqual(reloaded.provider_task_id, "task-123")
            self.assertEqual(len(opener.requests), 1)
            submitted, timeout = opener.requests[0]
            self.assertEqual(submitted.get_method(), "POST")
            self.assertEqual(
                submitted.full_url,
                "https://api.dev.runwayml.com/v1/text_to_video",
            )
            self.assertEqual(timeout, 30)
            headers = dict(submitted.header_items())
            self.assertEqual(headers["Authorization"], "Bearer test-secret")
            self.assertEqual(headers["X-runway-version"], RUNWAY_API_VERSION)
            payload = json.loads(submitted.data)
            self.assertEqual(
                set(payload), {"duration", "model", "promptText", "ratio", "seed"}
            )
            self.assertEqual(payload["promptText"], request.assembled_prompt)
            self.assertEqual(payload["model"], "gen4.5")
            self.assertEqual(payload["ratio"], "1280:720")

            persisted = json.dumps(read_json(state_path))
            self.assertNotIn(request.assembled_prompt, persisted)
            self.assertNotIn("test-secret", persisted)

    def test_new_attempt_reattaches_unless_prior_task_failed_transiently(self) -> None:
        opener = RecordingOpener(
            FakeResponse(b'{"id":"task-1"}'),
            FakeResponse(
                b'{"id":"task-1","status":"FAILED",'
                b'"failureCode":"INTERNAL"}'
            ),
            FakeResponse(b'{"id":"task-2"}'),
        )
        provider = self.provider(opener)
        first = provider.submit(render_request())

        still_first = provider.submit(render_request(attempt=2))
        failed = provider.get_status(first)
        retried = provider.submit(render_request(attempt=2))

        self.assertEqual(still_first.provider_task_id, "task-1")
        self.assertEqual(failed["failure_class"], "transient")
        self.assertEqual(retried.provider_task_id, "task-2")
        self.assertEqual(retried.idempotency_key, first.idempotency_key)
        self.assertEqual([item[0].get_method() for item in opener.requests], ["POST", "GET", "POST"])

    def test_image_conditioning_selects_image_to_video(self) -> None:
        opener = RecordingOpener(FakeResponse(b'{"id":"task-image"}'))
        provider = self.provider(opener)
        image_url = "https://assets.example/frame.png"

        provider.submit(render_request(conditioning_image_ref=image_url))

        submitted, _timeout = opener.requests[0]
        self.assertEqual(
            submitted.full_url,
            "https://api.dev.runwayml.com/v1/image_to_video",
        )
        self.assertEqual(json.loads(submitted.data)["promptImage"], image_url)

    def test_download_uses_task_output_without_leaking_authorization(self) -> None:
        opener = RecordingOpener(
            FakeResponse(b'{"id":"task-123"}'),
            FakeResponse(
                b'{"id":"task-123","status":"SUCCEEDED",'
                b'"output":["https://cdn.example/signed.mp4"]}'
            ),
            FakeResponse(b"provider-video", {"Content-Length": "14"}),
        )
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(opener, Path(temporary) / "jobs.json")
            job = provider.submit(render_request())
            destination = Path(temporary) / "output.mp4"

            def move_without_transcoding(source: Path, target: Path, _record: dict) -> None:
                os.replace(source, target)

            provider._normalize_asset = move_without_transcoding
            result = provider.download(job, destination)

            self.assertEqual(destination.read_bytes(), b"provider-video")
            self.assertEqual(result["provider_size_bytes"], 14)
            status_request, _ = opener.requests[1]
            self.assertEqual(
                status_request.full_url,
                "https://api.dev.runwayml.com/v1/tasks/task-123",
            )
            asset_request, _ = opener.requests[2]
            asset_headers = dict(asset_request.header_items())
            self.assertEqual(asset_request.full_url, "https://cdn.example/signed.mp4")
            self.assertNotIn("Authorization", asset_headers)
            self.assertNotIn("X-runway-version", asset_headers)

    def test_status_failure_class_and_cancel_contract(self) -> None:
        opener = RecordingOpener(
            FakeResponse(b'{"id":"task-123"}'),
            FakeResponse(b'{"id":"task-123","status":"RUNNING"}'),
            FakeResponse(b"{}"),
        )
        provider = self.provider(opener)
        job = provider.submit(render_request())

        cancelled = provider.cancel(job)

        self.assertEqual(cancelled["outcome"], "CANCELLED")
        self.assertEqual(opener.requests[1][0].get_method(), "GET")
        self.assertEqual(opener.requests[2][0].get_method(), "DELETE")
        self.assertEqual(
            opener.requests[2][0].full_url,
            "https://api.dev.runwayml.com/v1/tasks/task-123",
        )
        self.assertEqual(
            provider._task_failure_class("SAFETY.INPUT.TEXT"), "permanent"
        )
        self.assertEqual(provider._task_failure_class("INTERNAL"), "transient")
        self.assertEqual(provider._task_failure_class("NEW.UNKNOWN"), "permanent")

    def test_ambiguous_submission_timeout_is_fail_closed(self) -> None:
        provider = self.provider(RecordingOpener(TimeoutError("timed out")))

        with self.assertRaises(ProviderTimeoutError) as raised:
            provider.submit(render_request())

        self.assertEqual(raised.exception.failure_class, "permanent")
        self.assertTrue(raised.exception.details["submission_outcome_unknown"])

    def test_http_retryability_and_health_endpoint(self) -> None:
        too_many_requests = urllib.error.HTTPError(
            "https://api.dev.runwayml.com/v1/text_to_video",
            429,
            "Too Many Requests",
            {},
            io.BytesIO(b"sensitive provider detail"),
        )
        provider = self.provider(RecordingOpener(too_many_requests))
        with self.assertRaises(ProviderSubmissionError) as raised:
            provider.submit(render_request())
        self.assertEqual(raised.exception.failure_class, "transient")
        self.assertNotIn("sensitive", str(raised.exception.details))

        opener = RecordingOpener(FakeResponse(b'{"tier":"tier_1"}'))
        health = self.provider(opener).health_check()
        self.assertEqual(health["status"], "HEALTHY")
        self.assertEqual(
            opener.requests[0][0].full_url,
            "https://api.dev.runwayml.com/v1/organization",
        )

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_normalization_adds_audio_and_matches_target_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mp4"
            destination = root / "normalized.mp4"
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
                    "color=c=black:s=160x90:r=12:d=0.5",
                    "-an",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(source),
                ],
                check=True,
            )
            provider = self.provider(RecordingOpener())
            provider._normalize_asset(
                source,
                destination,
                {
                    "target_width": 320,
                    "target_height": 180,
                    "target_frame_rate": 24,
                    "duration_seconds": 1,
                },
            )

            probe = provider._probe_asset(destination)
            self.assertEqual(probe["width"], 320)
            self.assertEqual(probe["height"], 180)
            self.assertAlmostEqual(probe["frame_rate"], 24.0)
            self.assertTrue(probe["has_audio"])


if __name__ == "__main__":
    unittest.main()
