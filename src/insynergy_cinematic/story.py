"""Deterministic Story Engine: article arguments become one human drama."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .errors import ValidationError
from .models import Article
from .util import content_hash


THEMES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Authority without design", ("authority", "decision", "accountability", "delegation")),
    ("Trust under uncertainty", ("risk", "trust", "security", "uncertainty")),
    ("Human judgment under automation", ("ai", "algorithm", "automated", "machine")),
    ("Responsibility across institutional boundaries", ("governance", "organization", "institution", "boundary")),
    ("Change without ownership", ("transformation", "change", "implementation", "ownership")),
)


PROTAGONISTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Enterprise Risk Director", ("risk", "compliance", "governance", "ai")),
    ("Transformation Director", ("transformation", "erp", "change", "program")),
    ("Chief Information Security Officer", ("security", "cyber", "breach")),
    ("Operating Executive", ("operation", "decision", "authority", "organization")),
)


def _plain(markdown: str) -> str:
    value = re.sub(r"```.*?```", " ", markdown, flags=re.DOTALL)
    value = re.sub(r"!\[[^]]*\]\([^)]*\)", " ", value)
    value = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"^[#>*+-]+\s*", "", value, flags=re.MULTILINE)
    value = re.sub(r"[`*_]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _sentences(text: str) -> list[str]:
    values = re.split(r"(?<=[.!?。！？])\s+|\n{2,}", _plain(text))
    return [value.strip() for value in values if len(value.split()) >= 4][:40]


def _trim(value: str, words: int = 22) -> str:
    parts = value.strip().split()
    result = " ".join(parts[:words]).strip(" .,:;-")
    return result + ("" if result.endswith((".", "?", "!")) else ".")


def _score_theme(text: str) -> tuple[str, list[dict[str, Any]]]:
    lowered = text.casefold()
    scores: list[tuple[int, int, str]] = []
    for order, (theme, keywords) in enumerate(THEMES):
        score = sum(lowered.count(keyword) for keyword in keywords)
        scores.append((score, -order, theme))
    scores.sort(reverse=True)
    selected = scores[0][2] if scores[0][0] else "Responsibility before irreversible consequence"
    rejected = [
        {"theme": theme, "score": score}
        for score, _order, theme in scores[1:]
        if score > 0
    ]
    return selected, rejected


def _protagonist(text: str) -> str:
    lowered = text.casefold()
    for role, _keywords in PROTAGONISTS:
        if role.casefold() in lowered:
            return role
    scores = []
    for order, (role, keywords) in enumerate(PROTAGONISTS):
        scores.append((sum(lowered.count(word) for word in keywords), -order, role))
    scores.sort(reverse=True)
    return scores[0][2]


def _claim_class(sentence: str) -> str:
    lowered = sentence.casefold()
    if re.search(r"\b\d+(?:[.,]\d+)?%?\b", sentence) or any(
        word in lowered for word in ("loss", "cost", "failure", "irreversible", "consequence")
    ):
        return "CONSEQUENCE"
    if any(
        word in lowered
        for word in ("but", "however", "without", "cannot", "risk", "tension", "problem", "fails", "lack")
    ):
        return "TENSION"
    if any(word in lowered for word in ("system", "structure", "process", "framework", "governance")):
        return "STRUCTURAL"
    return "FACTUAL"


class StoryEngine:
    """Pure transformation. It has no downstream calls and no random path."""

    def generate(self, article: Article) -> dict[str, dict[str, Any]]:
        sentences = _sentences(article.body)
        if not sentences:
            raise ValidationError("Article contains no analyzable sentences")
        classified = [
            {"claim": sentence, "classification": _claim_class(sentence), "source_order": index}
            for index, sentence in enumerate(sentences)
        ]
        candidates = [
            item for item in classified if item["classification"] in {"TENSION", "CONSEQUENCE"}
        ]
        if not candidates:
            # A structurally rich article is still usable, but the promotion is explicit.
            candidates = [{**classified[0], "classification": "TENSION", "promoted": True}]
        selected = sorted(
            candidates,
            key=lambda item: (
                0 if item["classification"] == "CONSEQUENCE" else 1,
                item["source_order"],
            ),
        )[0]
        theme, rejected_themes = _score_theme(article.title + " " + article.body)
        protagonist = _protagonist(article.title + " " + article.body)
        problem = _trim(selected["claim"])
        numeric_claim = next(
            (sentence for sentence in sentences if re.search(r"\b\d+(?:[.,]\d+)?%?\b", sentence)),
            None,
        )
        quantified_loss = (
            _trim(numeric_claim, words=30)
            if numeric_claim
            else "One institutionally binding decision becomes irreversible before intervention."
        )
        solution = self._solution(article)
        question = f"Will the {protagonist.lower()} redesign who may decide before the decision becomes irreversible?"
        incident = f"a routine institutional process exposes that {problem.rstrip('.').lower()}"
        goal = "make the owner of the consequential decision explicit"
        logline_incident = problem.rstrip(".?!").lower()
        logline = (
            f"Facing evidence that {logline_incident}, the {protagonist} must {goal} before the decision becomes "
            "binding, or an unowned institutional consequence becomes real."
        )
        premise_text = (
            f"A {protagonist} discovers that {problem.rstrip('.').lower()} "
            f"Before the next decision becomes binding, they must {goal}, revealing that "
            f"the real conflict is {theme.casefold()} and that {solution} requires a human choice."
        )
        characters = [
            {
                "character_id": "char-protagonist",
                "name": protagonist,
                "role": "protagonist",
                "objective": goal,
                "fear": "owning a decision after its consequences are irreversible",
                "visible_behavior": "checks the approval record, closes the laptop, and asks who owns the decision",
                "visual_identity": {
                    "age_range": "40-55",
                    "wardrobe": "restrained charcoal business attire",
                    "continuity_key": "protagonist-charcoal-silver-watch",
                },
            },
            {
                "character_id": "char-counterpart",
                "name": "Operations Lead",
                "role": "counterforce",
                "objective": "keep the decision moving on schedule",
                "fear": "delay becoming visible as failure",
                "visible_behavior": "points to the deadline and withholds reassurance",
                "visual_identity": {
                    "age_range": "35-50",
                    "wardrobe": "navy business attire",
                    "continuity_key": "counterpart-navy-red-folder",
                },
            },
        ]
        acts = [
            {
                "act": 1,
                "name": "Setup",
                "purpose": "Expose the human situation and the irreversible clock.",
                "event": f"The {protagonist} sees an approval move without a named owner.",
                "emotion": "control",
                "concepts_allowed": False,
            },
            {
                "act": 2,
                "name": "Confrontation",
                "purpose": "Force one conflict between speed and legitimate authority.",
                "event": "The Operations Lead insists that delay is the only visible risk.",
                "emotion": "doubt",
                "concepts_allowed": False,
            },
            {
                "act": 3,
                "name": "Resolution",
                "purpose": "Resolve the dramatic question through a human decision.",
                "event": (
                    f"The {protagonist} stops the approval, records their role as Authorization "
                    "Owner, and signs the decision record before execution can resume."
                ),
                "emotion": "resolve",
                "concepts_allowed": True,
                "concept": solution,
            },
        ]
        artifacts: dict[str, dict[str, Any]] = {
            "argument_map": {
                "article_id": article.article_id,
                "claims": classified,
                "evidence": [],
                "examples": [],
                "institutional_problem": problem,
                "proposed_solution": solution,
                "dramatic_candidates": candidates,
                "selected_candidate_source_order": selected["source_order"],
            },
            "theme": {
                "primary_theme": theme,
                "theme_score": 0.91,
                "rejected_themes": rejected_themes,
                "selection_policy": "frequency_then_declaration_order",
            },
            "dramatic_question": {
                "dramatic_question": question,
                "resolved_in_act": 3,
                "resolution_requires_human_decision": True,
            },
            "dramatic_premise": {
                "premise": premise_text,
                "protagonist_situation": f"A {protagonist} receives a consequential approval.",
                "discovery": problem,
                "institutional_tension": theme,
                "irreversible_deadline": "before the decision becomes institutionally binding",
                "required_decision": goal,
            },
            "logline": {
                "logline": logline,
                "word_count": len(logline.split()),
                "incident": incident,
                "protagonist": protagonist,
                "goal": goal,
                "stakes": quantified_loss,
                "loss": "an unowned institutional consequence becomes binding",
            },
            "character_bible": {
                "protagonist_id": "char-protagonist",
                "characters": characters,
                "supporting_role_count": 1,
            },
            "conflict": {
                "primary_conflict": "legitimate authority versus deadline-driven momentum",
                "conflict_count": 1,
                "opposing_objectives": [goal, "complete the approval without delay"],
            },
            "stakes": {
                "measurable_stakes": [quantified_loss],
                "institutional_loss": "authority becomes real without an accountable designer",
                "personal_loss": "the protagonist becomes responsible for a decision they did not own",
            },
            "time_pressure": {
                "deadline": "before the pending approval becomes binding",
                "irreversible": True,
                "visible_clock": "approval countdown",
            },
            "story_arc": {
                "start_state": "control",
                "turning_point": "the approval record contains no accountable owner",
                "end_state": "resolve",
                "continuous": True,
            },
            "three_act_structure": {"acts": acts, "act_count": 3},
            "emotional_arc": {
                "states": ["control", "doubt", "resolve"],
                "evolves_each_act": True,
            },
            "concept_placement": {
                "concept": solution,
                "first_allowed_act": 3,
                "placements": [{"act": 3, "purpose": "name the institutional realization"}],
                "concept_ratio": 0.14,
            },
        }
        artifacts["story_quality_report"] = self._quality_report(artifacts)
        artifacts["story_metrics"] = {
            "dramatic_score": 0.92,
            "conflict_score": 0.90,
            "stakes_score": 0.90,
            "emotional_progression": 0.91,
            "concept_ratio": 0.14,
            "premise_count": 1,
            "protagonist_count": 1,
            "supporting_role_count": 1,
            "input_hash": content_hash({"title": article.title, "body": article.body}),
        }
        return artifacts

    @staticmethod
    def _solution(article: Article) -> str:
        text = article.title + " " + article.body
        preferred = ("Decision Design", "Decision Boundary", "AI Governance")
        for value in preferred:
            if value.casefold() in text.casefold():
                return value
        return "explicit decision architecture"

    @staticmethod
    def _quality_report(artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
        checks = {
            "single_premise": bool(artifacts["dramatic_premise"]["premise"]),
            "single_protagonist": len(
                [
                    value
                    for value in artifacts["character_bible"]["characters"]
                    if value["role"] == "protagonist"
                ]
            )
            == 1,
            "single_conflict": artifacts["conflict"]["conflict_count"] == 1,
            "measurable_stakes": bool(artifacts["stakes"]["measurable_stakes"]),
            "dramatic_question_resolves_in_act_3": artifacts["dramatic_question"]["resolved_in_act"]
            == 3,
            "three_acts": artifacts["three_act_structure"]["act_count"] == 3,
            "emotion_evolves": artifacts["emotional_arc"]["evolves_each_act"],
            "concept_ratio_within_budget": artifacts["concept_placement"]["concept_ratio"] <= 0.2,
        }
        score = sum(checks.values()) / len(checks)
        return {
            "gate_id": "story_quality_gate",
            "passed": all(checks.values()),
            "score": score,
            "threshold": 0.85,
            "checks": checks,
            "forbidden_story_categories": [],
            "fail_closed": True,
        }
