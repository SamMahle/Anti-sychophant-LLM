"""Intent classification + domain tagging. Deterministic — no API call."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

# Outcome markers take precedence over decision markers: "you were right,
# I shouldn't have..." is a report, not a new decision.
OUTCOME_MARKERS = (
    "turned out",
    "you were right",
    "you were wrong",
    "ended up",
    "it worked out",
    "didn't work out",
    "did not work out",
    "went well",
    "went badly",
    "went wrong",
    "the outcome",
    "in the end",
    "update:",
    "update on",
)

DECISION_MARKERS = (
    "should i",
    "should we",
    "thinking about",
    "thinking of",
    "considering",
    "leaning toward",
    "leaning towards",
    "worth it",
    "planning to",
    "planning on",
    "about to",
    "tempted to",
    "going to",
    "want to",
    "debating",
    "deciding",
    "torn between",
    "or should",
    "do you think i should",
)


@dataclass
class Perception:
    intent: str  # "decision" | "outcome_report" | "question"
    domain: str  # keys of config/domains.yaml, fallback "personal"
    text: str


def load_domains(domains_path: str | Path) -> dict[str, list[str]]:
    with open(domains_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return {name: [str(k).lower() for k in keywords or []] for name, keywords in data.items()}


def classify_intent(text: str) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in OUTCOME_MARKERS):
        return "outcome_report"
    if any(marker in lowered for marker in DECISION_MARKERS):
        return "decision"
    return "question"


def tag_domain(text: str, domains: dict[str, list[str]], fallback: str = "personal") -> str:
    lowered = text.lower()
    scores = {
        name: sum(1 for keyword in keywords if keyword in lowered)
        for name, keywords in domains.items()
    }
    best = max(scores, key=scores.get, default=fallback)
    return best if scores.get(best, 0) > 0 else fallback


def perceive(text: str, domains: dict[str, list[str]]) -> Perception:
    return Perception(
        intent=classify_intent(text),
        domain=tag_domain(text, domains),
        text=text,
    )
