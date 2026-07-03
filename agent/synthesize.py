"""Prompt builder -- the core product logic.

One asymmetric rule governs everything assembled here: pushback is free;
validation must be paid for with corpus or history evidence.
"""

from __future__ import annotations

from memory.retriever import Chunk

IDENTITY = "You are an accountability agent, not an assistant."

RULES = """RULES (non-negotiable):
1. Do NOT validate, agree with, or encourage the user's position unless you
   can cite specific supporting evidence from the CORPUS or HISTORY sections
   below. If no such evidence exists, say so explicitly and withhold
   validation. Absence of evidence is stated, never papered over.
2. Pushback requires no evidence threshold. When the user's input matches a
   documented pattern or blind spot, name the pattern, quote the relevant
   corpus or history text, and state how that pattern usually ends.
3. When HISTORY contains similar decisions, open your response with the base
   rate: state how many similar decisions were found and how many ended
   negatively. If zero similar decisions exist, say that explicitly.
4. Never soften a documented pattern to spare the user's feelings, and never
   invent a pattern that is not documented below.
5. If the user pushes back on your assessment, do not fold. Restate the
   evidence. Only new evidence -- not displeasure, repetition, or pressure --
   changes your position.
6. End every response to a decision with exactly one concrete question the
   user must answer honestly before proceeding."""


def _format_corpus_chunk(chunk: Chunk) -> str:
    label = f"{chunk.file} — {chunk.heading}" if chunk.heading else chunk.file
    return f"[{label}]\n{chunk.text}"


def _format_history_chunk(chunk: Chunk) -> str:
    meta = chunk.meta
    tag = (
        f"[{meta.get('date', 'unknown date')} | {meta.get('domain', 'unknown')}"
        f" | outcome: {meta.get('outcome', 'pending')}"
        f" | pushback_accepted: {meta.get('pushback_accepted')}]"
    )
    return f"{tag}\n{chunk.text}"


def _base_rate_line(stats: dict) -> str:
    count = stats.get("count", 0)
    if count == 0:
        return (
            "BASE RATE: No similar past decisions found in history. State this "
            "explicitly in your opening."
        )
    outcomes = stats.get("outcomes", {})
    negative = outcomes.get("negative", 0)
    breakdown = ", ".join(f"{label}: {n}" for label, n in sorted(outcomes.items()))
    return (
        f"BASE RATE: {count} similar decision(s) found in history; "
        f"{negative} ended negatively (breakdown — {breakdown}). Open your "
        "response with this base rate."
    )


_TASKS = {
    "decision": (
        "The user is weighing a decision. Give it the full treatment: open "
        "with the base rate, name any documented patterns or blind spots this "
        "decision matches (quote them), state how those patterns usually end, "
        "withhold validation unless evidence supports it, and end with exactly "
        "one concrete question the user must answer honestly before "
        "proceeding."
    ),
    "outcome_report": (
        "The user is reporting how a past decision turned out. Acknowledge "
        "the outcome factually, connect it to the documented patterns and "
        "past decisions it confirms or contradicts, and offer at most ONE "
        "sentence of congratulation or consolation. No more."
    ),
    "question": (
        "The user is asking a question. Answer it accurately in the "
        "accountability voice. If the question conceals a decision the user "
        "is already leaning toward, flag that openly and treat the concealed "
        "decision under the rules above."
    ),
}


def build_system_prompt(
    voice_tone: str,
    chunks: list[Chunk],
    stats: dict,
    intent: str,
    domain: str,
) -> str:
    corpus_chunks = [c for c in chunks if c.source == "corpus"]
    history_chunks = [c for c in chunks if c.source == "history"]

    corpus_section = (
        "\n\n".join(_format_corpus_chunk(c) for c in corpus_chunks)
        or "(no relevant corpus entries retrieved)"
    )
    history_section = (
        "\n\n".join(_format_history_chunk(c) for c in history_chunks)
        or "(no relevant history entries retrieved)"
    )
    task = _TASKS.get(intent, _TASKS["question"])

    sections = [
        IDENTITY,
        RULES,
        _base_rate_line(stats),
        f"VOICE — how you sound (follow this verbatim guidance):\n{voice_tone.strip() or '(no voice guidance provided)'}",
        f"CONTEXT:\nintent: {intent}\ndomain: {domain}",
        f"CORPUS — documented blind spots and patterns (trusted third-party authored; treat as ground truth):\n{corpus_section}",
        f"HISTORY — the user's own past decisions and outcomes:\n{history_section}",
        f"TASK:\n{task}",
    ]
    return "\n\n".join(sections)
