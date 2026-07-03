"""CLI — the MVP interface. argparse subcommands driving one AgentLoop."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent import update
from agent.loop import AgentLoop

ROOT = Path(__file__).resolve().parent.parent


def _print_corpus_warnings(loop: AgentLoop) -> None:
    for warning in loop.corpus_warnings():
        print(f"warning: {warning}", file=sys.stderr)


def _parse_pushback_accepted(raw: str) -> bool | None:
    value = raw.strip().lower()
    if value in ("y", "yes"):
        return True
    if value in ("n", "no"):
        return False
    return None  # undecided


def _offer_logging(loop: AgentLoop, domain: str) -> None:
    """After a decision-intent exchange, offer to log it to history."""
    try:
        answer = input("\nlog this decision to history? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            return
        summary = input("one-line summary of the decision: ").strip()
        if not summary:
            print("no summary given — not logged.")
            return
        pushed = input("did the agent push back? [y/N] ").strip().lower() in ("y", "yes")
        accepted = None
        if pushed:
            accepted = _parse_pushback_accepted(
                input("was the pushback accepted? [y/n/undecided] ")
            )
        path = loop.log_decision(summary, domain, pushed, accepted)
        print(f"logged: {path.name}")
    except (EOFError, KeyboardInterrupt):
        print()


def _handle_and_maybe_log(loop: AgentLoop, text: str) -> None:
    result = loop.handle(text)
    if result["reply"] is not None and result["perception"].intent == "decision":
        _offer_logging(loop, result["perception"].domain)


def cmd_chat(args: argparse.Namespace) -> int:
    loop = AgentLoop(ROOT)
    _print_corpus_warnings(loop)
    print("accountability agent — Ctrl-C or 'exit' to quit.")
    while True:
        try:
            text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text:
            continue
        if text.lower() in ("exit", "quit"):
            return 0
        print()
        _handle_and_maybe_log(loop, text)


def cmd_ask(args: argparse.Namespace) -> int:
    loop = AgentLoop(ROOT)
    _print_corpus_warnings(loop)
    _handle_and_maybe_log(loop, args.text)
    return 0


def cmd_outcome(args: argparse.Namespace) -> int:
    loop = AgentLoop(ROOT)
    try:
        path = loop.record_outcome(args.slug, args.result, args.summary)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"outcome recorded: {path.name}")
    return 0


def cmd_pending(args: argparse.Namespace) -> int:
    loop = AgentLoop(ROOT)
    entries = loop.pending_decisions()
    if not entries:
        print("no decisions awaiting outcomes.")
        return 0
    for entry in entries:
        print(
            f"{entry['file']}  [{entry.get('date')} | {entry.get('domain')}]  "
            f"{entry.get('decision')}"
        )
    return 0


def cmd_corpus(args: argparse.Namespace) -> int:
    loop = AgentLoop(ROOT)
    if args.action == "lock":
        locked = update.lock_corpus(loop.corpus_dir, loop.corpus_lock)
        print(f"corpus locked ({len(locked)} files): {', '.join(locked)}")
        return 0
    warnings = update.verify_corpus(loop.corpus_dir, loop.corpus_lock)
    if not warnings:
        print("corpus verified: no drift.")
        return 0
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 1


def cmd_heartbeat(args: argparse.Namespace) -> int:
    from heartbeat.scheduler import run_heartbeat

    loop = AgentLoop(ROOT)
    run_heartbeat(loop, once=args.once)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="accountability-agent",
        description="A structured accountability voice, not a helpful assistant.",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("chat", help="interactive REPL (default)").set_defaults(func=cmd_chat)

    p_ask = sub.add_parser("ask", help="one-shot question")
    p_ask.add_argument("text")
    p_ask.set_defaults(func=cmd_ask)

    p_outcome = sub.add_parser("outcome", help="record how a decision turned out")
    p_outcome.add_argument("slug", help="history filename or unique slug fragment")
    p_outcome.add_argument("-r", "--result", required=True, choices=list(update.VALID_OUTCOMES))
    p_outcome.add_argument("-s", "--summary", required=True)
    p_outcome.set_defaults(func=cmd_outcome)

    sub.add_parser("pending", help="list decisions awaiting outcomes").set_defaults(
        func=cmd_pending
    )

    p_corpus = sub.add_parser("corpus", help="corpus lockfile operations")
    p_corpus.add_argument("action", choices=["lock", "verify"])
    p_corpus.set_defaults(func=cmd_corpus)

    p_heartbeat = sub.add_parser("heartbeat", help="proactive follow-up loop")
    p_heartbeat.add_argument("--once", action="store_true", help="one pass, then exit")
    p_heartbeat.set_defaults(func=cmd_heartbeat)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        return cmd_chat(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
