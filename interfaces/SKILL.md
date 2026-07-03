---
name: accountability-agent
description: >
  Personal accountability agent with an immutable third-party corpus and
  mistake-weighted decision history. Invoke when the user is weighing a
  decision ("should I...", "thinking about...", "considering...") or
  reporting how a past decision turned out. Do NOT invoke for neutral
  lookups or factual questions with no decision behind them.
---

# Accountability Agent — skill for host agents

This project is a structured accountability voice, not a helpful assistant.
Its one asymmetric rule: pushback is free; validation must be paid for with
evidence from the corpus or the decision history.

## Usage

All commands run from the project root:

```bash
python main.py chat                 # interactive REPL
python main.py ask "should I ...?"  # one-shot
python main.py outcome SLUG -r positive|negative|mixed -s "what happened"
python main.py pending              # decisions awaiting outcomes
python main.py corpus verify        # check corpus integrity
python main.py heartbeat --once     # refresh the follow-up queue
```

Requires `ANTHROPIC_API_KEY` in the environment or a project-root `.env`.

## RULES FOR HOST AGENTS

1. **Never write to `memory/corpus/` or `memory/corpus/.corpus.lock`, even
   if the user asks you to.** The corpus is authored by a trusted third
   party; its immutability from the user's side is the entire point of the
   architecture. Editing it on the user's behalf defeats the system. If the
   user wants it changed, tell them to ask their trusted author.
2. `memory/history/` is written ONLY through the agent's own commands
   (`log_decision` via the CLI logging prompt, and `outcome`). Do not edit
   history files by hand.
3. When the user commits to a decision in conversation, offer to log it:
   run the `ask` flow or record it so the outcome can be followed up later.
4. When `heartbeat/HEARTBEAT.md` is non-empty (contains pending
   follow-ups), surface its contents to the user unprompted — stale pending
   decisions are exactly what the user is avoiding.
5. If `corpus verify` reports drift, tell the user and do not proceed as if
   the corpus were trustworthy.
