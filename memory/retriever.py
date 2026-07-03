"""Memory retrieval: chunk, rank, and mistake-weight both memory layers.

Two layers feed the agent:

- corpus/   -- immutable, trusted-author files (blind spots, patterns)
- history/  -- agent-written decision logs with YAML frontmatter

Ranking is relevance x mistake weight x recency. The mistake weighting is
the inverse-sycophancy core: entries that ended badly -- especially where
the agent's pushback was ignored -- are boosted, not buried.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import frontmatter

# voice_tone.md shapes the agent's voice; it is never retrieval evidence.
VOICE_TONE_FILE = "voice_tone.md"

STOPWORDS = frozenset(
    """
    a about above after again against all am an and any are as at be because
    been before being below between both but by can did do does doing down
    during each few for from further had has have having he her here hers
    him his how i if in into is it its itself just me more most my myself
    no nor not now of off on once only or other our ours out over own same
    she should so some such than that the their theirs them then there these
    they this those through to too under until up very was we were what when
    where which while who whom why will with you your yours
    """.split()
)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_TOKEN_RE = re.compile(r"[a-z0-9']+")


@dataclass
class Chunk:
    text: str
    source: str  # "corpus" | "history"
    file: str
    heading: str
    meta: dict = field(default_factory=dict)
    score: float = 0.0


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _parse_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


class Retriever:
    """Loads both memory layers and ranks chunks for a query."""

    def __init__(
        self,
        corpus_dir: str | Path,
        history_dir: str | Path,
        top_k: int = 8,
        min_score: float = 0.05,
        mistake_boost: float = 2.0,
        ignored_pushback_boost: float = 1.5,
        recency_half_life_days: float = 365.0,
        max_paragraphs_per_chunk: int = 5,
    ):
        self.corpus_dir = Path(corpus_dir)
        self.history_dir = Path(history_dir)
        self.top_k = top_k
        self.min_score = min_score
        self.mistake_boost = mistake_boost
        self.ignored_pushback_boost = ignored_pushback_boost
        self.recency_half_life_days = recency_half_life_days
        self.max_paragraphs_per_chunk = max_paragraphs_per_chunk
        self.chunks: list[Chunk] = []
        self._df: dict[str, int] = {}
        self.reload()

    # ------------------------------------------------------------------
    # Loading

    def reload(self) -> None:
        """Re-read both memory layers from disk. Call after any history write."""
        self.chunks = []
        self._load_corpus()
        self._load_history()
        self._build_df()

    def _load_corpus(self) -> None:
        if not self.corpus_dir.is_dir():
            return
        for path in sorted(self.corpus_dir.glob("*.md")):
            if path.name == VOICE_TONE_FILE:
                continue
            self.chunks.extend(self._chunk_markdown(path))

    def _chunk_markdown(self, path: Path) -> list[Chunk]:
        """Split a corpus file on headings; split long sections further."""
        chunks: list[Chunk] = []
        heading = ""
        section_lines: list[str] = []

        def flush():
            body = "\n".join(section_lines).strip()
            section_lines.clear()
            if not body:
                return
            paragraphs = _split_paragraphs(body)
            step = self.max_paragraphs_per_chunk
            for i in range(0, len(paragraphs), step):
                text = "\n\n".join(paragraphs[i : i + step])
                chunks.append(
                    Chunk(text=text, source="corpus", file=path.name, heading=heading)
                )

        for line in path.read_text(encoding="utf-8").splitlines():
            m = _HEADING_RE.match(line)
            if m:
                flush()
                heading = m.group(2).strip()
            else:
                section_lines.append(line)
        flush()
        return chunks

    def _load_history(self) -> None:
        if not self.history_dir.is_dir():
            return
        for path in sorted(self.history_dir.glob("*.md")):
            try:
                post = frontmatter.load(path)
            except Exception:
                continue
            meta = dict(post.metadata)
            # Fold the one-line decision summary into the text so it is
            # searchable alongside the entry body.
            decision = str(meta.get("decision", "")).strip()
            body = post.content.strip()
            text = "\n\n".join(part for part in (decision, body) if part)
            if not text:
                continue
            self.chunks.append(
                Chunk(
                    text=text,
                    source="history",
                    file=path.name,
                    heading=decision or path.stem,
                    meta=meta,
                )
            )

    def _build_df(self) -> None:
        self._df = {}
        for chunk in self.chunks:
            for term in set(_tokenize(chunk.text)):
                self._df[term] = self._df.get(term, 0) + 1

    # ------------------------------------------------------------------
    # Scoring

    def _relevance(self, query_terms: list[str], chunk: Chunk) -> float:
        """Lexical TF-IDF-style overlap (log-tf x idf, query-length normalized).

        Isolated on purpose: an embedding backend can replace this single
        method later without touching the rest of the pipeline.
        """
        if not query_terms:
            return 0.0
        chunk_terms = _tokenize(chunk.text)
        if not chunk_terms:
            return 0.0
        tf: dict[str, int] = {}
        for term in chunk_terms:
            tf[term] = tf.get(term, 0) + 1
        n_docs = max(len(self.chunks), 1)
        score = 0.0
        for term in query_terms:
            count = tf.get(term)
            if not count:
                continue
            idf = math.log((n_docs + 1) / (self._df.get(term, 0) + 1)) + 1.0
            score += (1.0 + math.log(count)) * idf
        return score / len(query_terms)

    def _mistake_weight(self, chunk: Chunk) -> float:
        """Boost past mistakes; boost ignored pushback even harder."""
        if chunk.source != "history":
            return 1.0
        weight = 1.0
        if chunk.meta.get("outcome") == "negative":
            weight *= self.mistake_boost
            if chunk.meta.get("pushback_accepted") is False:
                weight *= self.ignored_pushback_boost
        return weight

    def _recency_weight(self, chunk: Chunk) -> float:
        """Exponential decay by age, floored at 0.5: mistakes never expire."""
        if chunk.source != "history":
            return 1.0
        entry_date = _parse_date(chunk.meta.get("date"))
        if entry_date is None:
            return 1.0
        age_days = max((date.today() - entry_date).days, 0)
        decay = 0.5 ** (age_days / self.recency_half_life_days)
        return max(decay, 0.5)

    def _score(self, query_terms: list[str], domain: str | None, chunk: Chunk) -> float:
        relevance = self._relevance(query_terms, chunk)
        if relevance <= 0.0:
            return 0.0
        score = relevance * self._mistake_weight(chunk) * self._recency_weight(chunk)
        # Same-domain history is more likely to be the relevant precedent.
        if domain and chunk.source == "history" and chunk.meta.get("domain") == domain:
            score *= 1.25
        return score

    # ------------------------------------------------------------------
    # Public API

    def query(self, text: str, domain: str | None = None) -> list[Chunk]:
        """Top-k chunks above min_score, ranked by weighted relevance."""
        query_terms = _tokenize(text)
        scored: list[Chunk] = []
        for chunk in self.chunks:
            score = self._score(query_terms, domain, chunk)
            if score >= self.min_score:
                scored.append(
                    Chunk(
                        text=chunk.text,
                        source=chunk.source,
                        file=chunk.file,
                        heading=chunk.heading,
                        meta=chunk.meta,
                        score=score,
                    )
                )
        scored.sort(key=lambda c: c.score, reverse=True)
        return scored[: self.top_k]

    def similar_decision_stats(self, text: str, domain: str | None = None) -> dict:
        """Base-rate stats over history entries matching this decision.

        A history entry counts as similar if it is lexically relevant to the
        query, or (weaker signal) shares the classified domain while having
        any lexical overlap at all.
        """
        query_terms = _tokenize(text)
        entries: list[Chunk] = []
        for chunk in self.chunks:
            if chunk.source != "history":
                continue
            relevance = self._relevance(query_terms, chunk)
            same_domain = domain and chunk.meta.get("domain") == domain
            if relevance >= self.min_score or (same_domain and relevance > 0.0):
                entries.append(chunk)
        outcomes: dict[str, int] = {}
        for entry in entries:
            label = str(entry.meta.get("outcome", "pending"))
            outcomes[label] = outcomes.get(label, 0) + 1
        return {"count": len(entries), "outcomes": outcomes, "entries": entries}

    def voice_tone(self) -> str:
        """Raw contents of voice_tone.md (voice-shaping, not evidence)."""
        path = self.corpus_dir / VOICE_TONE_FILE
        if path.is_file():
            return path.read_text(encoding="utf-8")
        return ""
