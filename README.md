# Anti-sychophant-LLM — Accountability Agent

A local-first personal accountability agent with an **inverted memory
architecture**. It is not a helpful assistant — it is a structured
accountability voice built on one asymmetric rule:

> **Pushback is free; validation must be paid for with evidence.**

## The three pillars

1. **Accountability corpus** (`memory/corpus/`) — authored by a trusted
   third party who knows you, not by you. It describes your blind spots and
   named decision patterns. The agent reads it but can **never** write to
   it: a write-path guard in code raises on any attempt, and a SHA-256
   lockfile lets the trusted author detect tampering.
2. **Behavioral history** (`memory/history/`) — decision logs written by
   the agent, one markdown file per decision, with YAML frontmatter.
   Retrieval is weighted toward past **mistakes** (inverse sycophancy):
   decisions that ended negatively rank higher, and decisions where you
   ignored the agent's pushback rank higher still. Recency decay is floored
   at 0.5 — mistakes never fully expire.
3. **Anti-sycophancy synthesizer** (`agent/synthesize.py`) — every system
   prompt prohibits validation without cited corpus/history evidence,
   requires the similar-decision base rate up front, and forbids folding
   under user pressure.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then paste your real ANTHROPIC_API_KEY
```

Then have your **trusted author** (not you) edit the three files in
`memory/corpus/` — instructions are inside each file — and lock the corpus:

```bash
python main.py corpus lock
```

## Usage

```bash
python main.py chat                  # interactive REPL (default)
python main.py ask "Should I quit my job to go full-time on this?"
python main.py pending               # decisions awaiting outcomes
python main.py outcome SLUG -r negative -s "shipped late, lost the client"
python main.py corpus verify         # detect corpus tampering
python main.py heartbeat --once      # refresh follow-up queue (cron-friendly)
python main.py heartbeat             # continuous follow-up loop
```

After any decision-flavored exchange, the CLI offers to log the decision to
history. Weeks later, the heartbeat notices decisions still `pending` past
the follow-up window (default 30 days) and queues them in
`heartbeat/HEARTBEAT.md` so the loop closes: decision → outcome → evidence
for the next decision.

## The cognitive loop

```
Trigger → Perceive → Retrieve → Synthesize → Respond → Update
```

- **Trigger** — reactive (CLI message) or proactive (heartbeat).
- **Perceive** — deterministic intent classification (decision /
  outcome_report / question) + domain tagging (`config/domains.yaml`).
- **Retrieve** — both memory layers, ranked by relevance × mistake weight ×
  recency (`memory/retriever.py`).
- **Synthesize** — the anti-sycophancy system prompt.
- **Respond** — streamed from the Claude API.
- **Update** — history writes only; the corpus is never touched
  (`agent/update.py` is the only module that writes memory).

## Design constraints

- **Local-first**: all memory is plain markdown on disk; nothing leaves the
  machine except the API call.
- **Corpus immutability is architectural**, not conventional: enforced in
  the write path and verified by hash lockfile at startup.
- **No database, no web framework, no embeddings** in the MVP. Lexical
  retrieval is isolated in a single `_relevance()` method so an embedding
  backend can be swapped in later.

## Configuration

- `config/settings.yaml` — model, retrieval weights, heartbeat cadence, paths.
- `config/domains.yaml` — user-editable domain keyword lists.

## For host agents (OpenClaw etc.)

See `interfaces/SKILL.md` for invocation rules — most importantly: never
write to `memory/corpus/`, even at the user's request.
