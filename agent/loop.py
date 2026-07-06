"""Cognitive loop orchestrator.

Trigger -> Perceive -> Retrieve -> Synthesize -> Respond -> Update.
Triggering lives at the interfaces (CLI, heartbeat); the Update stage lives
in update.py; this class wires stages 2-5 together and holds session state.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from agent import perceive as perceive_mod
from agent import respond as respond_mod
from agent import synthesize, update
from memory.retriever import Retriever


class AgentLoop:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        respond_mod.load_dotenv(self.root)

        with open(self.root / "config" / "settings.yaml", encoding="utf-8") as fh:
            self.settings = yaml.safe_load(fh)
        self.domains = perceive_mod.load_domains(self.root / "config" / "domains.yaml")

        paths = self.settings["paths"]
        self.corpus_dir = self.root / paths["corpus"]
        self.history_dir = self.root / paths["history"]
        self.heartbeat_queue = self.root / paths["heartbeat_queue"]
        self.corpus_lock = self.root / paths["corpus_lock"]

        retrieval = self.settings["retrieval"]
        self.retriever = Retriever(
            corpus_dir=self.corpus_dir,
            history_dir=self.history_dir,
            top_k=retrieval["top_k"],
            min_score=retrieval["min_score"],
            mistake_boost=retrieval["mistake_boost"],
            ignored_pushback_boost=retrieval["ignored_pushback_boost"],
            recency_half_life_days=retrieval["recency_half_life_days"],
        )
        self.conversation: list[dict] = []

    # ------------------------------------------------------------------

    def corpus_warnings(self) -> list[str]:
        """Startup integrity check against the trusted author's lockfile."""
        return update.verify_corpus(self.corpus_dir, self.corpus_lock)

    def handle(self, text: str, quiet: bool = False) -> dict:
        """Run stages 2-5 for one user message.

        quiet=True (web UI): no stdout streaming; failures come back as a
        user-presentable message in the result's "error" key instead of
        being printed to stderr.
        """
        perception = perceive_mod.perceive(text, self.domains)
        chunks = self.retriever.query(text, perception.domain)
        stats = self.retriever.similar_decision_stats(text, perception.domain)
        system_prompt = synthesize.build_system_prompt(
            voice_tone=self.retriever.voice_tone(),
            chunks=chunks,
            stats=stats,
            intent=perception.intent,
            domain=perception.domain,
        )

        self.conversation.append({"role": "user", "content": text})
        error = None
        if quiet:
            try:
                reply = respond_mod.generate(
                    system_prompt=system_prompt,
                    conversation=self.conversation,
                    model=self.settings["model"]["name"],
                    max_tokens=self.settings["model"]["max_tokens"],
                )
            except respond_mod.RespondError as exc:
                reply = None
                error = str(exc)
        else:
            reply = respond_mod.respond(
                system_prompt=system_prompt,
                conversation=self.conversation,
                model=self.settings["model"]["name"],
                max_tokens=self.settings["model"]["max_tokens"],
            )
        if reply is None:
            # Failed call: drop the dangling user turn so the session stays valid.
            self.conversation.pop()
        else:
            self.conversation.append({"role": "assistant", "content": reply})

        return {
            "perception": perception,
            "chunks": chunks,
            "stats": stats,
            "reply": reply,
            "error": error,
        }

    # ------------------------------------------------------------------
    # Update stage — delegated to update.py, then reload retrieval.

    def log_decision(
        self,
        decision: str,
        domain: str,
        agent_pushed_back: bool,
        pushback_accepted: bool | None,
    ) -> Path:
        path = update.log_decision(
            history_dir=self.history_dir,
            corpus_dir=self.corpus_dir,
            decision=decision,
            domain=domain,
            agent_pushed_back=agent_pushed_back,
            pushback_accepted=pushback_accepted,
        )
        self.retriever.reload()
        return path

    def record_outcome(self, slug_or_filename: str, outcome: str, summary: str) -> Path:
        path = update.record_outcome(
            history_dir=self.history_dir,
            corpus_dir=self.corpus_dir,
            slug_or_filename=slug_or_filename,
            outcome=outcome,
            summary=summary,
        )
        self.retriever.reload()
        return path

    def pending_decisions(self) -> list[dict]:
        return update.pending_decisions(self.history_dir)
