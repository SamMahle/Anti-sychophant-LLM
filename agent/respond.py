"""Claude API call: streaming, .env loading, and graceful error handling.

Never tracebacks at the user: every failure path becomes one clear,
user-presentable message (RespondError), which the CLI prints to stderr
and the web UI shows in the page.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable

import anthropic


class RespondError(RuntimeError):
    """API call failed; str(exc) is a user-presentable message."""


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


def generate(
    system_prompt: str,
    conversation: list[dict],
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 2000,
    on_token: Callable[[str], None] | None = None,
) -> str:
    """Stream a reply from Claude; return the full text.

    Raises RespondError with a user-presentable message on any failure.
    `conversation` is the running message list for multi-turn chat; the
    latest user message must already be appended by the caller.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RespondError(
            "ANTHROPIC_API_KEY is not set. Export it or put it in a .env file "
            "at the project root (see .env.example)."
        )

    client = anthropic.Anthropic()
    try:
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=conversation,
        ) as stream:
            for token in stream.text_stream:
                if on_token is not None:
                    on_token(token)
            return stream.get_final_text()
    except anthropic.AuthenticationError:
        raise RespondError(
            "authentication failed — check that ANTHROPIC_API_KEY is valid."
        ) from None
    except anthropic.RateLimitError:
        raise RespondError(
            "rate limited by the API — wait a moment and try again."
        ) from None
    except anthropic.APIConnectionError:
        raise RespondError(
            "could not reach the Claude API — check your network connection."
        ) from None
    except anthropic.APIStatusError as exc:
        raise RespondError(
            f"API returned status {exc.status_code} — {exc.message}"
        ) from None


def respond(
    system_prompt: str,
    conversation: list[dict],
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 2000,
) -> str | None:
    """CLI wrapper around generate(): stream to stdout, return text or None."""

    def to_stdout(token: str) -> None:
        sys.stdout.write(token)
        sys.stdout.flush()

    try:
        text = generate(system_prompt, conversation, model, max_tokens, to_stdout)
        sys.stdout.write("\n")
        return text
    except RespondError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None
