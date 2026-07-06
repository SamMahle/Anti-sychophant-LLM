"""Local browser UI — the friendly face on the same AgentLoop.

Stdlib http.server only (no new dependencies, per the closed tech stack).
Binds to 127.0.0.1: the page in your browser talks to a tiny server on
your own machine; the agent stays local-first.

Corpus rule carried over from SKILL.md: this interface exposes NO way to
read into or write to memory/corpus/ — the trusted author edits those
files directly and locks them.
"""

from __future__ import annotations

import json
import os
import threading
import webbrowser
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent.loop import AgentLoop

ROOT = Path(__file__).resolve().parent.parent
UI_PATH = Path(__file__).with_name("web_ui.html")
DEFAULT_PORT = 8765


def _age_days(raw) -> int | None:
    if isinstance(raw, datetime):
        parsed = raw.date()
    elif isinstance(raw, date):
        parsed = raw
    elif isinstance(raw, str):
        try:
            parsed = datetime.strptime(raw.strip(), "%Y-%m-%d").date()
        except ValueError:
            return None
    else:
        return None
    return (date.today() - parsed).days


def _save_api_key(key: str) -> None:
    """Write/replace ANTHROPIC_API_KEY in the project-root .env."""
    env_path = ROOT / ".env"
    lines: list[str] = []
    if env_path.is_file():
        lines = [
            line
            for line in env_path.read_text(encoding="utf-8").splitlines()
            if not line.strip().startswith("ANTHROPIC_API_KEY")
        ]
    lines.append(f"ANTHROPIC_API_KEY={key}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ["ANTHROPIC_API_KEY"] = key


class Handler(BaseHTTPRequestHandler):
    loop: AgentLoop  # set by run_web()
    lock = threading.Lock()  # AgentLoop session state is single-threaded

    # ------------------------------------------------------------ plumbing

    def log_message(self, fmt, *args):  # silence per-request stderr noise
        pass

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    # ------------------------------------------------------------- routes

    def do_GET(self):
        if self.path == "/":
            self._send(200, UI_PATH.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            self._json(self._state())
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        routes = {
            "/api/chat": self._chat,
            "/api/key": self._key,
            "/api/log": self._log,
            "/api/outcome": self._outcome,
        }
        handler = routes.get(self.path)
        if handler is None:
            self._json({"error": "not found"}, 404)
            return
        try:
            handler(self._body())
        except Exception as exc:  # never traceback at the browser
            self._json({"error": f"unexpected error: {exc}"}, 500)

    # ------------------------------------------------------------ handlers

    def _state(self) -> dict:
        loop = self.loop
        follow_up_days = loop.settings["heartbeat"]["follow_up_days"]
        pending = []
        for entry in loop.pending_decisions():
            age = _age_days(entry.get("date"))
            pending.append({
                "file": entry["file"],
                "date": str(entry.get("date", "")),
                "domain": str(entry.get("domain", "")),
                "decision": str(entry.get("decision", "")),
                "age_days": age,
                "stale": age is not None and age >= follow_up_days,
            })
        return {
            "key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "corpus_warnings": loop.corpus_warnings(),
            "pending": pending,
            "follow_up_days": follow_up_days,
        }

    def _chat(self, body: dict) -> None:
        text = str(body.get("message", "")).strip()
        if not text:
            self._json({"error": "empty message"}, 400)
            return
        with self.lock:
            result = self.loop.handle(text, quiet=True)
        stats = result["stats"]
        self._json({
            "reply": result["reply"],
            "error": result["error"],
            "intent": result["perception"].intent,
            "domain": result["perception"].domain,
            "similar": {"count": stats["count"], "outcomes": stats["outcomes"]},
        })

    def _key(self, body: dict) -> None:
        key = str(body.get("key", "")).strip()
        if not key:
            self._json({"error": "empty key"}, 400)
            return
        _save_api_key(key)
        self._json({"ok": True})

    def _log(self, body: dict) -> None:
        summary = str(body.get("summary", "")).strip()
        if not summary:
            self._json({"error": "a one-line summary is required"}, 400)
            return
        domain = str(body.get("domain", "personal"))
        pushed = bool(body.get("agent_pushed_back", False))
        accepted = body.get("pushback_accepted")  # true | false | null
        if accepted is not None:
            accepted = bool(accepted)
        with self.lock:
            path = self.loop.log_decision(summary, domain, pushed, accepted)
        self._json({"ok": True, "file": path.name})

    def _outcome(self, body: dict) -> None:
        try:
            with self.lock:
                path = self.loop.record_outcome(
                    str(body.get("slug", "")),
                    str(body.get("result", "")),
                    str(body.get("summary", "")).strip(),
                )
        except ValueError as exc:
            self._json({"error": str(exc)}, 400)
            return
        self._json({"ok": True, "file": path.name})


def run_web(port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    Handler.loop = AgentLoop(ROOT)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"accountability agent running at {url}  (Ctrl-C to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
