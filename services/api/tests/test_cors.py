"""CORS policy for the browser dev server.

The Vite dev server doesn't always land on :5173 — if that port is taken it moves
to :5174, :5175, etc. The browser must still be allowed to call the API from that
origin, or every request fails at the network layer with "Failed to fetch". These
tests pin: any localhost port is a trusted dev origin, but a remote site is not.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _preflight(origin: str):
    return client.options(
        "/songs",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
        },
    )


def test_cors_allows_the_standard_dev_origin():
    r = _preflight("http://localhost:5173")
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_allows_any_localhost_port():
    # Reproduces the "Failed to fetch" bug: the app was served on :5174 (because
    # :5173 was busy) but the API only trusted :5173, so the browser blocked it.
    r = _preflight("http://localhost:5174")
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5174"


def test_cors_still_blocks_a_remote_origin():
    # Widening to localhost must NOT open the API to arbitrary websites.
    r = _preflight("http://evil.example.com")
    assert (
        r.headers.get("access-control-allow-origin") != "http://evil.example.com"
    )
