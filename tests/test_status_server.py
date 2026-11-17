"""Status endpoint: JSON snapshot over stdlib HTTP, no deps, no DB."""
import json
import urllib.request

from substrate.status_server import StatusServer


def test_status_endpoint_serves_snapshot():
    state = {"status": "running", "cycles_started": 3, "service": "substrate-scheduler"}
    server = StatusServer(port=0, state_fn=lambda: dict(state))
    server.start()
    try:
        port = server._server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=5) as resp:
            payload = json.loads(resp.read())
        assert payload["status"] == "running"
        assert payload["cycles_started"] == 3
    finally:
        server.shutdown()


def test_unknown_paths_404():
    server = StatusServer(port=0, state_fn=lambda: {})
    server.start()
    try:
        port = server._server.server_address[1]
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/nope", timeout=5)
            raised = False
        except Exception:
            raised = True
        assert raised  # urllib raises HTTPError 404 for unknown paths
    finally:
        server.shutdown()
