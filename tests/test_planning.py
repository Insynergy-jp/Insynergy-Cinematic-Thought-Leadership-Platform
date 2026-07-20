from pathlib import Path
import re
import tempfile
import unittest

from insynergy_cinematic.models import BuildState
from insynergy_cinematic.orchestrator import BuildOrchestrator
from insynergy_cinematic.prompt import PromptAssembler


ROOT = Path(__file__).resolve().parents[1]


class PlanningTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
