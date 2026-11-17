"""Status HTTP endpoint for the deployed scheduler (stdlib only, daemon thread).

Railway health: binds $PORT (the platform injects it) and serves a JSON snapshot
of the scheduler's own state — no secrets, no tenant data, just counters and
timestamps. `/` and `/status` return the snapshot; everything else 404s.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def make_handler(state_fn: Callable[[], dict[str, Any]]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 — stdlib naming
            if self.path not in ("/", "/status"):
                self.send_response(404)
                self.end_headers()
                return
            payload = json.dumps(state_fn(), default=str).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: N802, A002
            pass  # health pings stay out of the logs

    return Handler


class StatusServer:
    """Tiny JSON status server. start() binds and serves in a daemon thread;
    shutdown() stops it. Never raises into the scheduler loop."""

    def __init__(self, port: int, state_fn: Callable[[], dict[str, Any]]) -> None:
        self.port = port
        self.state_fn = state_fn
        self._server: ThreadingHTTPServer | None = None

    def start(self) -> None:
        try:
            self._server = ThreadingHTTPServer(("0.0.0.0", self.port), make_handler(self.state_fn))
            thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            thread.start()
        except OSError as exc:
            # Port taken or blocked: the scheduler loop must still run (gate W9 —
            # a health endpoint is a convenience, not a dependency).
            print(f"status server unavailable on port {self.port}: {exc}")

    def shutdown(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server = None
