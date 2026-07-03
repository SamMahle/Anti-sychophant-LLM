"""The ONLY module that writes memory.

Two jobs:

1. History writes: decision logs and outcome updates in memory/history/.
2. Corpus guard: architectural enforcement that the corpus is never written
   by the agent -- a resolved-path check before EVERY write, plus a SHA-256
   lockfile the trusted author generates so drift is detectable.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path

import frontmatter
import yaml

LOCK_FILENAME = ".corpus.lock"
VALID_OUTCOMES = ("positive", "negative", "mixed")


class CorpusWriteError(RuntimeError):
    """Raised on any attempt to write inside the corpus directory."""


def _assert_outside_corpus(path: str | Path, corpus_dir: str | Path) -> None:
    """Raise CorpusWriteError if `path` is the corpus dir or inside it.

    Called before EVERY write. Immutability must not depend on file
    permissions or convention.
    """
    target = Path(path).resolve()
    corpus = Path(corpus_dir).resolve()
    if target == corpus or corpus in target.parents:
        raise CorpusWriteError(
            f"refusing to write {target}: the corpus at {corpus} is immutable "
            "and only the trusted author may change it."
        )


# ---------------------------------------------------------------------------
# Corpus lockfile

def _corpus_hashes(corpus_dir: Path) -> dict[str, str]:
    hashes = {}
    for path in sorted(corpus_dir.glob("*.md")):
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def lock_corpus(corpus_dir: str | Path, lock_path: str | Path) -> list[str]:
    """Write SHA-256 hashes of all corpus files to the lockfile.

    Run by the TRUSTED AUTHOR after editing the corpus -- this is the one
    sanctioned write inside the corpus directory, so it bypasses the guard.
    Returns the list of locked filenames.
    """
    corpus_dir = Path(corpus_dir)
    hashes = _corpus_hashes(corpus_dir)
    Path(lock_path).write_text(
        yaml.safe_dump(hashes, default_flow_style=False, sort_keys=True),
        encoding="utf-8",
    )
    return sorted(hashes)


def verify_corpus(corpus_dir: str | Path, lock_path: str | Path) -> list[str]:
    """Return drift warnings; empty list means the corpus is intact."""
    corpus_dir = Path(corpus_dir)
    lock_path = Path(lock_path)
    if not lock_path.is_file():
        return [
            "corpus has never been locked — run 'python main.py corpus lock' "
            "(as the trusted author) to record its fingerprint."
        ]
    try:
        locked = yaml.safe_load(lock_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return [f"corpus lockfile {lock_path} is unreadable — re-lock the corpus."]

    current = _corpus_hashes(corpus_dir)
    warnings = []
    for name, digest in sorted(locked.items()):
        if name not in current:
            warnings.append(f"corpus file removed since lock: {name}")
        elif current[name] != digest:
            warnings.append(f"corpus file changed since lock: {name}")
    for name in sorted(set(current) - set(locked)):
        warnings.append(f"corpus file added since lock: {name}")
    return warnings


# ---------------------------------------------------------------------------
# History writes

def _slugify(text: str, max_words: int = 6) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())[:max_words]
    return "-".join(words) or "decision"


def log_decision(
    history_dir: str | Path,
    corpus_dir: str | Path,
    decision: str,
    domain: str,
    agent_pushed_back: bool,
    pushback_accepted: bool | None,
) -> Path:
    """Write a new decision log; return the path written."""
    history_dir = Path(history_dir)
    history_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    slug = _slugify(decision)

    path = history_dir / f"{today}_{slug}.md"
    suffix = 2
    while path.exists():
        path = history_dir / f"{today}_{slug}-{suffix}.md"
        suffix += 1

    _assert_outside_corpus(path, corpus_dir)

    meta = {
        "date": today,
        "domain": domain,
        "decision": decision,
        "agent_pushed_back": agent_pushed_back,
        "pushback_accepted": pushback_accepted,
        "outcome": "pending",
        "outcome_date": None,
        "outcome_summary": None,
    }
    frontmatter_yaml = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False)
    path.write_text(f"---\n{frontmatter_yaml}---\n", encoding="utf-8")
    return path


def _match_entry(history_dir: Path, slug_or_filename: str) -> Path:
    """Match by exact filename, or by unique slug fragment."""
    name = slug_or_filename.strip()
    exact = history_dir / (name if name.endswith(".md") else f"{name}.md")
    if exact.is_file():
        return exact
    matches = [p for p in sorted(history_dir.glob("*.md")) if name in p.stem]
    if not matches:
        raise ValueError(f"no history entry matches '{slug_or_filename}'.")
    if len(matches) > 1:
        names = ", ".join(p.name for p in matches)
        raise ValueError(
            f"'{slug_or_filename}' is ambiguous — matches: {names}. "
            "Use the full filename."
        )
    return matches[0]


def record_outcome(
    history_dir: str | Path,
    corpus_dir: str | Path,
    slug_or_filename: str,
    outcome: str,
    summary: str,
) -> Path:
    """Resolve a pending decision with its real-world outcome."""
    if outcome not in VALID_OUTCOMES:
        raise ValueError(
            f"outcome must be one of {'|'.join(VALID_OUTCOMES)}, got '{outcome}'."
        )
    history_dir = Path(history_dir)
    path = _match_entry(history_dir, slug_or_filename)
    _assert_outside_corpus(path, corpus_dir)

    post = frontmatter.load(path)
    post.metadata["outcome"] = outcome
    post.metadata["outcome_date"] = date.today().isoformat()
    post.metadata["outcome_summary"] = summary
    path.write_bytes(frontmatter.dumps(post).encode("utf-8"))
    return path


def pending_decisions(history_dir: str | Path) -> list[dict]:
    """All history entries still awaiting an outcome."""
    history_dir = Path(history_dir)
    pending = []
    if not history_dir.is_dir():
        return pending
    for path in sorted(history_dir.glob("*.md")):
        try:
            post = frontmatter.load(path)
        except Exception:
            continue
        if post.metadata.get("outcome") == "pending":
            entry = dict(post.metadata)
            entry["file"] = path.name
            pending.append(entry)
    return pending
