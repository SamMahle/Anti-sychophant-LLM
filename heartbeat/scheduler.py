"""Proactive follow-up loop.

Scans history for decisions still pending past the follow-up window and
rewrites HEARTBEAT.md from scratch each pass — idempotent, so resolved
entries drop off automatically.
"""

from __future__ import annotations

import sys
import time
from datetime import date, datetime
from pathlib import Path

import frontmatter
import schedule

HEADER = "# HEARTBEAT — pending follow-ups\n"


def _entry_age_days(meta: dict) -> int | None:
    raw = meta.get("date")
    if isinstance(raw, datetime):
        entry_date = raw.date()
    elif isinstance(raw, date):
        entry_date = raw
    elif isinstance(raw, str):
        try:
            entry_date = datetime.strptime(raw.strip(), "%Y-%m-%d").date()
        except ValueError:
            return None
    else:
        return None
    return (date.today() - entry_date).days


def check_pending(
    history_dir: str | Path,
    queue_path: str | Path,
    follow_up_days: int = 30,
) -> list[dict]:
    """One pass: find stale pending decisions and rewrite the queue file."""
    history_dir = Path(history_dir)
    queue_path = Path(queue_path)

    stale = []
    if history_dir.is_dir():
        for path in sorted(history_dir.glob("*.md")):
            try:
                post = frontmatter.load(path)
            except Exception:
                continue
            meta = post.metadata
            if meta.get("outcome") != "pending":
                continue
            age = _entry_age_days(meta)
            if age is None or age < follow_up_days:
                continue
            stale.append(
                {
                    "file": path.name,
                    "age_days": age,
                    "domain": meta.get("domain", "unknown"),
                    "decision": meta.get("decision", "(no summary)"),
                }
            )

    lines = [HEADER, ""]
    if not stale:
        lines.append("No pending follow-ups.\n")
    else:
        for entry in stale:
            slug = entry["file"].removesuffix(".md")
            lines.append(
                f"- `{entry['file']}` — {entry['age_days']} days old "
                f"[{entry['domain']}]: {entry['decision']}\n"
                f"  Resolve with: `python main.py outcome {slug} "
                f'-r positive|negative|mixed -s "what happened"`\n'
            )
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text("\n".join(lines), encoding="utf-8")
    return stale


def run_heartbeat(loop, once: bool = False) -> None:
    """Run one pass immediately; keep looping on a schedule unless `once`."""
    follow_up_days = loop.settings["heartbeat"]["follow_up_days"]
    interval_hours = loop.settings["heartbeat"]["check_interval_hours"]

    def pass_once() -> None:
        stale = check_pending(loop.history_dir, loop.heartbeat_queue, follow_up_days)
        if stale:
            print(f"{len(stale)} decision(s) awaiting follow-up → {loop.heartbeat_queue}")
            for entry in stale:
                print(
                    f"  {entry['file']} ({entry['age_days']}d, {entry['domain']}): "
                    f"{entry['decision']}"
                )
        else:
            print("no pending follow-ups.")

    pass_once()
    if once:
        return

    schedule.every(interval_hours).hours.do(pass_once)
    print(f"heartbeat running every {interval_hours}h — Ctrl-C to stop.")
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)
    except KeyboardInterrupt:
        print("\nheartbeat stopped.", file=sys.stderr)
