"""Claude API call: streaming, .env loading, and graceful error handling.

Never tracebacks at the user: every failure path prints one clear message
to stderr and returns None.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import anthropic


def load_dotenv(root: str | Path) -> None:
    """Minimal stdlib .env loader: KEY=VALUE lines, # comments, quotes stripped.

    Existing environment variables always win (os.environ.setdefault).
    """
    env_path = Path(root) / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            os.environ.setdefault(key, value)


def _err(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)


def respond(
    system_prompt: str,
    conversation: list[dict],
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 2000,
) -> str | None:
    """Stream a reply from Claude to stdout; return the full text, or None.

    `conversation` is the running message list for multi-turn chat; the
    latest user message must already be appended by the caller.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        _err(
            "ANTHROPIC_API_KEY is not set. Export it or put it in a .env file "
            "at the project root (see .env.example)."
        )
        return None

    client = anthropic.Anthropic()
    try:
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=conversation,
        ) as stream:
            for token in stream.text_stream:
                sys.stdout.write(token)
                sys.stdout.flush()
            sys.stdout.write("\n")
            return stream.get_final_text()
    except anthropic.AuthenticationError:
        _err("authentication failed — check that ANTHROPIC_API_KEY is valid.")
    except anthropic.RateLimitError:
        _err("rate limited by the API — wait a moment and try again.")
    except anthropic.APIConnectionError:
        _err("could not reach the Claude API — check your network connection.")
    except anthropic.APIStatusError as exc:
        _err(f"API returned status {exc.status_code} — {exc.message}")
    return None
