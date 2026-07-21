from pathlib import Path
import re
import tempfile
import unittest

from insynergy_cinematic.models import BuildState
from insynergy_cinematic.errors import ValidationError
from insynergy_cinematic.orchestrator import BuildOrchestrator
from insynergy_cinematic.prompt import PromptAssembler
from insynergy_cinematic.shot_planner import ShotPlanner


ROOT = Path(__file__).resolve().parents[1]


class PlanningTests(unittest.TestCase):
    def test_all_shots_runway_scope_is_capped_at_360_credits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            orchestrator = BuildOrchestrator(
                Path(temporary),
                profile="final",
                provider="runway",
                runway_scope="all_shots",
                environ={},
            )
            view = orchestrator.plan(ROOT / "examples" / "decision-boundary.md")
            planning = view["metrics"]["planning"]
            self.assertEqual(planning["shot_count"], 6)
            self.assertEqual(planning["provider_render_shot_count"], 6)
            self.assertEqual(planning["estimated_runway_credits"], 360)
            self.assertEqual(planning["runway_credit_limit"], 360)
            self.assertEqual(planning["estimated_provider_cost_usd"], 3.6)
            manifest = orchestrator.repository.load(view["build_id"])
            self.assertEqual(
                manifest["configuration"]["render"]["runway_scope"], "all_shots"
            )

    def test_all_shots_scope_requires_runway_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValidationError):
                BuildOrchestrator(
                    Path(temporary),
                    provider="local",
                    runway_scope="all_shots",
                    environ={},
                )

    def test_planning_stops_at_execution_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            orchestrator = BuildOrchestrator(Path(temporary), profile="preview")
            view = orchestrator.plan(ROOT / "examples" / "decision-boundary.md")
            self.assertEqual(view["state"], BuildState.AWAITING_EXECUTION_APPROVAL.value)
            self.assertRegex(view["build_id"], r"^[0-9]{8}-[0-9]{3}$")
            self.assertTrue(view["gates"]["story_quality_gate"]["passed"])
            self.assertTrue(view["gates"]["screenplay_quality_gate"]["passed"])
            self.assertNotIn("render_manifest", view["artifacts"])
            manifest = orchestrator.repository.load(view["build_id"])
            shots = orchestrator.repository.load_artifact(manifest, "shot_list")["data"]["shots"]
            allowed = {
                "runway_video",
                "animated_still",
                "motion_graphics",
                "title_card",
                "svg_animation",
                "cached_clip",
            }
            self.assertTrue(
                all(re.fullmatch(r"scene-[0-9]{3}-shot-[0-9]{2}", shot["shot_id"]) for shot in shots)
            )
            self.assertTrue(
                all(shot["render_strategy"]["asset_class"] in allowed for shot in shots)
            )
            self.assertTrue(
                all("provider" not in shot["render_strategy"] for shot in shots)
            )
            self.assertTrue(
                all(shot["render_strategy"]["execution_capability"] for shot in shots)
            )
            screenplay = orchestrator.repository.load_artifact(manifest, "screenplay")["data"]
            resolution = screenplay["scenes"][2]
            self.assertIn("Authorization Owner", resolution["actions"][0])
            self.assertIn("signs the decision record", resolution["actions"][0])
            storyboard = orchestrator.repository.load_artifact(manifest, "storyboard")["data"]
            final_frame = storyboard["frames"][-1]
            self.assertEqual(final_frame["render_strategy"]["asset_class"], "title_card")
            self.assertEqual(final_frame["camera"]["movement"], "static")
            self.assertIn("TITLE CARD READS:", final_frame["visible_action"].upper())
            gate = orchestrator.repository.load_artifact(
                manifest, "storyboard_gate_report"
            )["data"]
            self.assertTrue(gate["checks"]["all_frames_renderable"])

    def test_prompt_is_bound_to_storyboard(self) -> None:
        frame = {
            "frame_id": "frame-001",
            "shot_id": "shot-001",
            "composition": "medium eye-level frame",
            "visible_action": "The director closes a laptop.",
            "camera": {"framing": "MEDIUM", "lens": "50mm", "movement": "static", "angle": "eye_level"},
            "character_continuity": {"char-protagonist": "protagonist-charcoal"},
            "location": "Executive Review Room",
            "lighting": "low-key practical",
            "emotion": "resolve",
            "style": ["live-action realism"],
            "forbidden_style": ["cartoon"],
        }
        assembler = PromptAssembler()
        prompt = assembler.assemble(frame)
        assembler.verify(prompt, frame)
        self.assertEqual(prompt["source_contract"], "storyboard_only")
        self.assertNotIn("article", prompt["prompt"].casefold())

    def test_renderability_gate_rejects_capability_contradictions(self) -> None:
        frame = {
            "visible_action": "A title card reads: AUTHORIZATION OWNER — RISK DIRECTOR.",
            "camera": {"movement": "static"},
            "render_strategy": {
                "asset_class": "title_card",
                "execution_capability": "typographic_card",
            },
        }
        self.assertTrue(ShotPlanner._frame_renderable(frame))

        incompatible_camera = {
            **frame,
            "camera": {"movement": "slow_pull"},
        }
        self.assertFalse(ShotPlanner._frame_renderable(incompatible_camera))

        provider_leak = {
            **frame,
            "render_strategy": {**frame["render_strategy"], "provider": "runway"},
        }
        self.assertFalse(ShotPlanner._frame_renderable(provider_leak))


if __name__ == "__main__":
    unittest.main()
