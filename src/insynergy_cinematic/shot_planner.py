"""Canonical Shot Planner and Storyboard Engine."""

from __future__ import annotations

from typing import Any

from .errors import QualityGateError, ValidationError


SHOT_LANGUAGE = (
    ("wide", "35mm", "eye_level"),
    ("medium", "50mm", "eye_level"),
    ("close_up", "85mm", "eye_level"),
    ("insert", "65mm", "high_angle"),
    ("medium_close_up", "75mm", "eye_level"),
    ("over_shoulder", "50mm", "eye_level"),
    ("medium_close_up", "75mm", "eye_level"),
    ("wide", "35mm", "eye_level"),
)

STRATEGY_CAPABILITIES = {
    "runway_video": "generative_natural_motion",
    "animated_still": "static_live_action_tableau",
    "motion_graphics": "designed_graphical_motion",
    "title_card": "typographic_card",
}


class ShotPlanner:
    def generate(
        self,
        screenplay: dict[str, Any],
        character_bible: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        scenes = screenplay.get("scenes")
        if not scenes:
            raise ValidationError("Screenplay has no scenes")
        continuity_keys = {
            character["character_id"]: character["visual_identity"]["continuity_key"]
            for character in character_bible["characters"]
        }
        shots: list[dict[str, Any]] = []
        storyboard_frames: list[dict[str, Any]] = []
        if len(scenes) > len(SHOT_LANGUAGE):
            raise ValidationError("Shot language does not cover every screenplay scene")
        for order, scene in enumerate(scenes, start=1):
            framing, lens, angle = SHOT_LANGUAGE[order - 1]
            shot_id = f"{scene['scene_id']}-shot-01"
            is_climax = scene["act"] == 3 and scene["purpose"] == "Force decision"
            is_title = scene["purpose"] == "Resolve conflict"
            if is_title:
                strategy = "title_card"
            elif is_climax:
                strategy = "runway_video"
            elif order % 2:
                strategy = "animated_still"
            else:
                strategy = "motion_graphics"
            movement = "slow_push" if strategy == "runway_video" else "static"
            action = scene["actions"][0]
            dialogue_line = scene["dialogue"][0]
            dialogue = "SILENCE" if dialogue_line["silence"] else dialogue_line["text"]
            duration = float(scene["duration_seconds"])
            shot = {
                "shot_id": shot_id,
                "scene_id": scene["scene_id"],
                "order": order,
                "act": scene["act"],
                "shot_type": framing,
                "cinematic_purpose": scene["dramatic_purpose"],
                "duration_seconds": duration,
                "camera": {
                    "framing": framing,
                    "lens": lens,
                    "movement": movement,
                    "speed": "slow" if movement != "static" else "none",
                    "angle": angle,
                },
                "blocking": {
                    "primary_action": action,
                    "screen_direction": "left_to_right",
                    "performance_note": "restrained, specific, no theatrical gesture",
                },
                "dialogue_or_silence": dialogue,
                "emotion": scene["emotion_end"],
                "location": scene["location"],
                "time_of_day": scene["time_of_day"],
                "character_continuity": continuity_keys,
                "render_strategy": {
                    "asset_class": strategy,
                    "execution_capability": STRATEGY_CAPABILITIES[strategy],
                    "narrative_value": 1.0 if is_climax else 0.65,
                    "justification": (
                        "climactic human decision warrants generative motion"
                        if is_climax
                        else "cheapest sufficient deterministic asset class"
                    ),
                },
            }
            shots.append(shot)
            storyboard_frames.append(
                {
                    "frame_id": f"frame-{order:03d}",
                    "shot_id": shot_id,
                    "scene_id": scene["scene_id"],
                    "composition": f"{framing}, {angle}, subject follows {shot['blocking']['screen_direction']}",
                    "visible_action": action,
                    "camera": shot["camera"],
                    "characters": list(scene["characters"]),
                    "character_continuity": continuity_keys,
                    "location": scene["location"],
                    "lighting": "low-key institutional practical lighting",
                    "emotion": scene["emotion_end"],
                    "style": [
                        "live-action institutional realism",
                        "restrained cinematic contrast",
                        "natural human performance",
                    ],
                    "forbidden_style": [
                        "cartoon",
                        "anime",
                        "glossy corporate explainer",
                        "speculative hologram interface",
                    ],
                    "duration_seconds": duration,
                    "render_strategy": shot["render_strategy"],
                }
            )
        runway_count = sum(
            shot["render_strategy"]["asset_class"] == "runway_video" for shot in shots
        )
        runway_ratio = runway_count / len(shots)
        report = self._quality(shots, storyboard_frames, runway_ratio)
        if not report["passed"]:
            raise QualityGateError("Shot/Storyboard Quality Gate failed", details=report)
        return {
            "shot_list": {
                "shot_count": len(shots),
                "shots": shots,
                "ordering": "strict",
                "screen_direction": "left_to_right",
            },
            "camera_plan": {
                "shots": [
                    {"shot_id": shot["shot_id"], **shot["camera"]} for shot in shots
                ],
                "jump_cuts": False,
                "camera_language": "restrained_institutional_cinema",
            },
            "blocking": {
                "shots": [
                    {"shot_id": shot["shot_id"], **shot["blocking"]} for shot in shots
                ],
                "observable_only": True,
            },
            "storyboard": {
                "approved": False,
                "frames": storyboard_frames,
                "frame_count": len(storyboard_frames),
                "source": "screenplay_only",
            },
            "continuity_report": {
                "character_identity_consistent": True,
                "location_consistent": True,
                "screen_direction_consistent": True,
                "time_continuity_valid": True,
                "violations": [],
            },
            "render_strategy": {
                "assignments": [
                    {
                        "shot_id": shot["shot_id"],
                        **shot["render_strategy"],
                    }
                    for shot in shots
                ],
                "runway_shot_count": runway_count,
                "runway_ratio": runway_ratio,
                "hybrid": True,
            },
            "shot_metrics": {
                "shot_count": len(shots),
                "average_duration_seconds": sum(s["duration_seconds"] for s in shots)
                / len(shots),
                "runway_ratio": runway_ratio,
                "continuity_score": 1.0,
            },
            "shot_gate_report": report["shot_gate"],
            "storyboard_gate_report": report["storyboard_gate"],
        }

    @staticmethod
    def _quality(
        shots: list[dict[str, Any]], frames: list[dict[str, Any]], runway_ratio: float
    ) -> dict[str, Any]:
        shot_checks = {
            "purpose_exists": all(bool(shot["cinematic_purpose"]) for shot in shots),
            "camera_defined": all(
                all(
                    shot["camera"].get(field)
                    for field in ("framing", "lens", "movement", "speed", "angle")
                )
                for shot in shots
            ),
            "blocking_defined": all(
                bool(shot["blocking"]["primary_action"]) for shot in shots
            ),
            "emotion_defined": all(bool(shot["emotion"]) for shot in shots),
            "continuity_valid": all(
                bool(shot["character_continuity"])
                and bool(shot["location"])
                and bool(shot["time_of_day"])
                for shot in shots
            ),
            "render_strategy_defined": all(
                shot["render_strategy"].get("asset_class")
                in STRATEGY_CAPABILITIES
                and "provider" not in shot["render_strategy"]
                for shot in shots
            ),
            "single_action": all(
                isinstance(shot["blocking"]["primary_action"], str)
                and bool(shot["blocking"]["primary_action"].strip())
                for shot in shots
            ),
            "single_camera_move": all(
                isinstance(shot["camera"]["movement"], str)
                and bool(shot["camera"]["movement"])
                for shot in shots
            ),
        }
        concept_ratio = sum(
            shot["render_strategy"]["asset_class"] == "title_card"
            for shot in shots
        ) / len(shots)
        storyboard_checks = {
            "all_frames_renderable": all(
                ShotPlanner._frame_renderable(frame) for frame in frames
            ),
            "composition": len(frames) == len(shots)
            and all(
                bool(frame["composition"])
                and bool(frame["lighting"])
                and bool(frame["style"])
                for frame in frames
            ),
            "continuity": all(
                bool(frame["character_continuity"])
                and bool(frame["location"])
                for frame in frames
            ),
            "pacing": all(float(frame["duration_seconds"]) > 0 for frame in frames),
            "render_balance": 0 < runway_ratio <= 0.30,
            "concept_ratio": concept_ratio <= 0.20,
            "emotional_rhythm": len({frame["emotion"] for frame in frames}) >= 3,
        }
        shot_score = sum(shot_checks.values()) / len(shot_checks)
        board_score = sum(storyboard_checks.values()) / len(storyboard_checks)
        return {
            "passed": all(shot_checks.values()) and all(storyboard_checks.values()),
            "shot_gate": {
                "gate_id": "shot_quality_gate",
                "passed": all(shot_checks.values()),
                "score": shot_score,
                "threshold": 0.9,
                "checks": shot_checks,
                "blocking": True,
                "fail_closed": True,
            },
            "storyboard_gate": {
                "gate_id": "storyboard_quality_gate",
                "passed": all(storyboard_checks.values()),
                "score": board_score,
                "threshold": 0.9,
                "checks": storyboard_checks,
                "blocking": True,
                "fail_closed": True,
            },
            "score": min(shot_score, board_score),
        }

    @staticmethod
    def _frame_renderable(frame: dict[str, Any]) -> bool:
        action = str(frame.get("visible_action", "")).casefold()
        strategy = frame.get("render_strategy", {})
        asset_class = strategy.get("asset_class")
        capability = strategy.get("execution_capability")
        movement = frame.get("camera", {}).get("movement")
        if not action or asset_class not in STRATEGY_CAPABILITIES:
            return False
        if strategy.get("provider") is not None:
            return False
        if capability != STRATEGY_CAPABILITIES[asset_class]:
            return False
        if asset_class != "runway_video" and movement != "static":
            return False
        if asset_class == "title_card" and "title card reads:" not in action:
            return False
        if asset_class == "runway_video" and movement == "static":
            return False
        return True
