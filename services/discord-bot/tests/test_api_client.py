"""api_client tests using an httpx MockTransport — no live engine needed."""
import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api_client import EngineError, PromptDJClient  # noqa: E402


def _client_with(handler) -> PromptDJClient:
    c = PromptDJClient("http://test")
    # Swap the internal AsyncClient for one backed by our mock handler.
    c._client = httpx.AsyncClient(base_url="http://test",
                                  transport=httpx.MockTransport(handler))
    return c


def test_library_parses_songs():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"songs": [
            {"id": "a" * 64, "original_name": "Father Ocean", "role_hint": "beat"},
            {"id": "b" * 64, "original_name": "Dooriyan", "role_hint": "vocals"},
        ]})

    async def go():
        c = _client_with(handler)
        songs = await c.library()
        await c.close()
        return songs

    songs = asyncio.run(go())
    assert [s.name for s in songs] == ["Father Ocean", "Dooriyan"]
    assert songs[0].role_hint == "beat"


def test_start_mix_returns_id_and_sends_user_and_generation():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json
        seen.update(json.loads(req.content))
        return httpx.Response(202, json={"mix_id": "c" * 64, "status": "processing"})

    async def go():
        c = _client_with(handler)
        mid = await c.start_mix("a" * 64, "b" * 64, user_id="u1", generation=2)
        await c.close()
        return mid

    mid = asyncio.run(go())
    assert mid == "c" * 64
    assert seen["user_id"] == "u1" and seen["generation"] == 2


def test_start_mix_raises_friendly_engine_error():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "Song 2 hasn't been analyzed yet."})

    async def go():
        c = _client_with(handler)
        try:
            await c.start_mix("a" * 64, "b" * 64, user_id="u1")
        finally:
            await c.close()

    try:
        asyncio.run(go())
        assert False, "expected EngineError"
    except EngineError as e:
        assert "analyzed" in str(e)


def test_wait_for_mix_polls_until_ready():
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(200, json={"status": "processing"})
        return httpx.Response(200, json={"status": "ready",
                                         "plan": {"rule": 4, "notes": "echo + reverb"}})

    async def go():
        c = _client_with(handler)
        res = await c.wait_for_mix("d" * 64, poll=0.0, timeout=5.0)
        await c.close()
        return res

    res = asyncio.run(go())
    assert res.status == "ready" and res.rule == 4 and calls["n"] == 3
