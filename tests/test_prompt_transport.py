from __future__ import annotations

from copy import deepcopy
import unittest

from insynergy_cinematic.prompt import PromptAssembler
from insynergy_cinematic.util import content_hash


def full_auto_frame(shot: int) -> dict:
    base = {
        "frame_id": f"frame-{shot:03d}",
        "shot_id": f"scene-{shot:03d}-shot-01",
        "camera": {
            "angle": "eye_level",
            "framing": "over_shoulder_medium_close_up",
            "lens": "50mm",
            "movement": "slow_push",
        },
        "character_continuity": {
            "char-counterpart": "counterpart-navy-red-folder",
            "char-protagonist": "protagonist-charcoal-silver-watch",
        },
        "location": "Home Office",
        "emotion": "confidence",
        "lighting": (
            "Near-black room with cool monitor blue on face and hands and one "
            "soft practical edge."
        ),
        "style": [
            "original premium technology film",
            "restrained live-action realism",
            "natural human performance",
            "subtle film grain",
        ],
        "forbidden_style": [
            "logo",
            "trademark",
            "branded interface",
            "cyberpunk",
            "hologram",
            "robot",
            "cartoon",
            "anime",
            "readable generated text",
        ],
    }
    if shot == 1:
        return {
            **base,
            "composition": (
                "Developer on the left third, monitor on the right two-thirds, "
                "dark hallway held in negative space behind."
            ),
            "visible_action": (
                "At 00:18, the developer enables autonomous execution, parallel "
                "runs, automatic retry, and continued execution on the desktop "
                "workstation, leaves the spending limit off, clicks RUN with the "
                "physical mouse within the first second, remains silent with "
                "closed-mouth confidence, releases the mouse, pushes the chair back, "
                "and stands while the desktop monitor and run remain active."
            ),
        }
    if shot != 6:
        raise ValueError("Only the bounded Full Auto shots are test fixtures")
    frame = deepcopy(base)
    frame.update(
        {
            "composition": (
                "The physical mouse and the developer's mouse hand occupy the lower "
                "foreground; STOP sits lower-left beneath one white arrow cursor, "
                "stopping and waiting status is center-left, exactly twelve "
                "active-agent indicators sit immediately beside it, and the "
                "still-rising usage field remains in the upper right; keep all "
                "consequences in one focal plane with the developer's profile at far left."
            ),
            "visible_action": (
                "The developer hurriedly grips the physical mouse and moves the "
                "on-screen arrow cursor to the restrained red STOP control. The "
                "cursor settles over STOP; the developer clicks the left mouse "
                "button once and the control visibly depresses. The screen changes "
                "to Stopping and Waiting for active workers, but an adjacent panel "
                "still shows twelve active agent indicators pulsing while only the "
                "usage total continues increasing from $744 to $746 to $748."
            ),
            "camera": {
                "angle": "eye_level_insert",
                "framing": "macro_insert_to_side_profile",
                "lens": "100mm_macro",
                "movement": "locked_macro",
            },
            "lighting": (
                "Muted red confined to STOP and worker count; all remaining light "
                "is cool white and blue."
            ),
            "emotion": "frustration",
            "style": [
                "original premium technology film",
                "restrained live-action realism",
                "precise macro detail",
                "natural human performance",
                "subtle film grain",
            ],
            "forbidden_style": [
                "logo",
                "trademark",
                "branded interface",
                "theatrical panic",
                "repeated clicking",
                "multiple cursors",
                "touchscreen gesture",
                "finger touching the display",
                "trackpad interaction",
                "horror",
                "hologram",
                "cartoon",
                "anime",
                "readable generated text",
            ],
        }
    )
    return frame


class PromptTransportTests(unittest.TestCase):
    def test_full_auto_prompts_are_deterministic_and_runway_bounded(self) -> None:
        assembler = PromptAssembler()
        for shot in (1, 6):
            with self.subTest(shot=shot):
                frame = full_auto_frame(shot)
                first = assembler.assemble(frame, max_utf16_units=1000)
                second = assembler.assemble(frame, max_utf16_units=1000)
                self.assertEqual(first, second)
                assembler.verify(first, frame)
                self.assertLessEqual(assembler.utf16_length(first["prompt"]), 1000)
                self.assertTrue(first["transport"]["compacted"])
                self.assertEqual(
                    first["transport"]["contract_version"],
                    "utf16-bounded-prompt/1",
                )
                self.assertIn("readable generated text", first["prompt"])

    def test_shot_one_preserves_launch_boundary_cues(self) -> None:
        prompt = PromptAssembler().assemble(
            full_auto_frame(1), max_utf16_units=1000
        )["prompt"]
        self.assertIn("00:18", prompt)
        self.assertIn("spending limit off", prompt)
        self.assertIn("RUN", prompt)
        self.assertIn("physical mouse", prompt)

    def test_shot_six_preserves_stop_consequence_cues(self) -> None:
        prompt = PromptAssembler().assemble(
            full_auto_frame(6), max_utf16_units=1000
        )["prompt"]
        for cue in (
            "STOP",
            "one white arrow cursor",
            "twelve active-agent indicators",
            "$744",
            "$746",
            "$748",
            "Stopping and Waiting for active workers",
            "physical mouse",
            "left mouse button once",
        ):
            with self.subTest(cue=cue):
                self.assertIn(cue, prompt)

    def test_short_prompt_remains_verbatim(self) -> None:
        assembler = PromptAssembler()
        frame = full_auto_frame(1)
        frame["composition"] = "Developer beside a desktop monitor."
        frame["visible_action"] = "The developer clicks RUN once."
        frame["character_continuity"] = {"char-protagonist": "charcoal-watch"}
        frame["style"] = ["live-action realism"]
        frame["forbidden_style"] = ["logo"]
        source = assembler.assemble(frame)
        bounded = assembler.assemble(frame, max_utf16_units=1000)
        self.assertEqual(bounded["prompt"], source["prompt"])
        self.assertFalse(bounded["transport"]["compacted"])
        self.assertEqual(
            bounded["transport"]["source_prompt_hash"],
            content_hash(source["prompt"]),
        )


if __name__ == "__main__":
    unittest.main()
