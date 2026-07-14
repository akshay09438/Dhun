"""CORS policy for the browser.

Locked down 2026-07-14: only an explicit allowlist ships by default (the standard Vite
dev origin). The wide "any localhost port" match is now a DEV-ONLY opt-in
(`PROMPTDJ_DEV_CORS=1`) so a permissive rule never reaches production; the deployed
origin is set via `PROMPTDJ_CORS_ORIGINS`. A remote website is never trusted.
"""

from fastapi.testclient import TestClient

from app import config
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


def test_cors_blocks_other_localhost_ports_by_default():
    # The lockdown: the wide any-localhost-port regex no longer ships by default, so a
    # non-allowlisted localhost port is NOT trusted (was allowed before the hardening).
    r = _preflight("http://localhost:5174")
    assert r.headers.get("access-control-allow-origin") != "http://localhost:5174"


def test_cors_still_blocks_a_remote_origin():
    # A remote website is never trusted, in any configuration.
    r = _preflight("http://evil.example.com")
    assert (
        r.headers.get("access-control-allow-origin") != "http://evil.example.com"
    )


def test_dev_flag_reenables_any_localhost_port(monkeypatch):
    # Local convenience only (Vite hops ports): opt in with PROMPTDJ_DEV_CORS=1. Off otherwise.
    monkeypatch.setenv("PROMPTDJ_DEV_CORS", "1")
    assert config._cors_origin_regex() == r"http://(localhost|127\.0\.0\.1):\d+"
    monkeypatch.delenv("PROMPTDJ_DEV_CORS", raising=False)
    assert config._cors_origin_regex() is None


def test_prod_origins_come_from_env(monkeypatch):
    # Production sets the real deployed origin(s); default is the local dev server only.
    monkeypatch.setenv("PROMPTDJ_CORS_ORIGINS", "https://promptdj.app, https://www.promptdj.app")
    assert config._cors_origins() == ("https://promptdj.app", "https://www.promptdj.app")
    monkeypatch.delenv("PROMPTDJ_CORS_ORIGINS", raising=False)
    assert config._cors_origins() == ("http://localhost:5173",)
