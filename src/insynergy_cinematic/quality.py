"""Central fail-closed Quality Gate registry and evaluators."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .media import AssetValidator


QUALITY_GATE_REGISTRY = {
    "story_quality_gate": ("story", "2.1.7"),
    "screenplay_quality_gate": ("screenplay", "3.1.8"),
    "shot_quality_gate": ("shot_planning", "4.1.12"),
    "storyboard_quality_gate": ("storyboard", "4.1.12"),
    "agent_review_gate": ("planning_review", "7.0.1"),
    "rendering_technical_gate": ("rendering", "5.6.1"),
    "rendering_editorial_gate": ("validation", "5.6.2"),
    "composition_quality_gate": ("composition", "7.2.7"),
    "narration_audio_quality_gate": ("audio", "7.2.8"),
    "metadata_packaging_quality_gate": ("packaging", "7.2.9"),
    "execution_approval": ("approval", "1.4.1"),
    "publish_approval": ("publication", "1.4.1"),
}


def registry_document() -> dict[str, Any]:
    canonical_ids = (
        "story_quality_gate",
        "screenplay_quality_gate",
        "shot_quality_gate",
        "storyboard_quality_gate",
        "agent_review_gate",
        "rendering_technical_gate",
        "rendering_editorial_gate",
        "execution_approval",
        "publish_approval",
    )
    return {
        "schema_version": "2.0",
        "gates": [
            {
                "gate_id": gate_id,
                "stage": stage,
                "gate_type": (
                    "human_approval"
                    if "approval" in gate_id
                    else "hybrid_review"
                    if gate_id == "agent_review_gate"
                    else "automated"
                ),
                "blocking": True,
                "fail_closed": True,
                "owning_section": section,
            }
            for gate_id in canonical_ids
            for stage, section in (QUALITY_GATE_REGISTRY[gate_id],)
        ],
    }


def creative_gate_passed(report: dict[str, Any]) -> bool:
    return (
        report.get("passed") is True
        and float(report.get("score", 0)) >= float(report.get("threshold", 1))
        and report.get("fail_closed") is True
    )


def composition_gate(
    master: Path,
    *,
    width: int,
    height: int,
    frame_rate: int,
    expected_duration: float,
) -> dict[str, Any]:
    validation = AssetValidator().validate(
        master,
        width=width,
        height=height,
        frame_rate=frame_rate,
        duration_seconds=expected_duration,
        require_audio=True,
    )
    checks = {
        "file_integrity": validation["checks"]["nonempty"],
        "decode": validation["checks"]["decodable"],
        "codec": validation["checks"]["codec"],
        "resolution": validation["checks"]["width"] and validation["checks"]["height"],
        "frame_rate": validation["checks"]["frame_rate"],
        "duration": validation["checks"]["duration"],
        "audio_stream": validation["checks"]["audio"],
        "audio_signal": validation["checks"]["audio_signal"],
        "visual_content": validation["checks"]["visual_content"],
    }
    score = sum(checks.values()) / len(checks)
    return {
        "gate_id": "composition_quality_gate",
        "passed": all(checks.values()),
        "score": score,
        "threshold": 1.0,
        "checks": checks,
        "validation": validation,
        "blocking": True,
        "fail_closed": True,
    }
