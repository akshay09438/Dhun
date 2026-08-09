"""Thin async HTTP client to the local Prompt-DJ engine (the FastAPI app on :8000).

The bot never touches audio or the mix engine directly — it reuses the exact HTTP API the
web app uses (GET /library, POST /mix, poll GET /mix/{id}, GET /mix/{id}/audio). That keeps
the bot a pure front-end: all mixing quality, caching, rules and arrangement stay in one
place (the engine), never re-implemented here.
"""
from __future__ import annotations

import asyncio
import dataclasses

import httpx


@dataclasses.dataclass
class Song:
    id: str
    name: str
    role_hint: str = ""


@dataclasses.dataclass
class MixResult:
    mix_id: str
    status: str                 # "ready" | "error" | "processing" | "idle"
    message: str | None = None
    rule: int | None = None     # 1 simple / 3 chop / 4 echo — for the style label
    notes: str | None = None


@dataclasses.dataclass
class SetResult:
    set_id: str
    status: str                 # "ready" | "error" | "processing" | "idle"
    message: str | None = None
    duration: float | None = None
    members: list | None = None  # [{index, song1_id, song2_id, rule, kept, seam_at, reason}]


class EngineError(RuntimeError):
    """A plain-language failure from the engine, safe to show a user."""


def _friendly(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict) and body.get("detail"):
            return str(body["detail"])
    except Exception:  # noqa: BLE001 — non-JSON body
        pass
    return f"The engine returned an error ({resp.status_code}). Is it running?"


class PromptDJClient:
    def __init__(self, base_url: str, timeout: float = 30.0):
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self._base, timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def health(self) -> bool:
        try:
            r = await self._client.get("/library")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def library(self) -> list[Song]:
        r = await self._client.get("/library")
        r.raise_for_status()
        data = r.json()
        return [
            Song(id=s["id"], name=s.get("original_name", ""), role_hint=s.get("role_hint", ""))
            for s in data.get("songs", [])
        ]

    async def start_mix(self, song1_id: str, song2_id: str, user_id: str,
                        generation: int = 0, prompt: str = "") -> str:
        """Kick off (or hit the cache for) a mix; returns its id. Uses the same
        auto-rule shuffler the web app uses (user_id + generation)."""
        payload = {
            "song1_id": song1_id, "song2_id": song2_id, "prompt": prompt,
            "user_id": user_id, "generation": generation,
        }
        r = await self._client.post("/mix", json=payload)
        if r.status_code not in (200, 202):
            raise EngineError(_friendly(r))
        return r.json()["mix_id"]

    async def mix_status(self, mix_id: str) -> MixResult:
        r = await self._client.get(f"/mix/{mix_id}")
        r.raise_for_status()
        d = r.json()
        plan = d.get("plan") or {}
        return MixResult(
            mix_id=mix_id, status=d.get("status", "idle"), message=d.get("message"),
            rule=plan.get("rule") if isinstance(plan, dict) else None,
            notes=plan.get("notes") if isinstance(plan, dict) else None,
        )

    async def wait_for_mix(self, mix_id: str, *, poll: float = 2.0, timeout: float = 600.0,
                           on_progress=None) -> MixResult:
        """Poll until the mix is ready or errors (or we give up). `on_progress(elapsed)` is
        awaited each tick so the caller can update a 'still mixing…' message."""
        elapsed = 0.0
        while True:
            res = await self.mix_status(mix_id)
            if res.status in ("ready", "error"):
                return res
            if on_progress is not None:
                await on_progress(elapsed)
            await asyncio.sleep(poll)
            elapsed += poll
            if elapsed >= timeout:
                return MixResult(mix_id=mix_id, status="error",
                                 message="This mix took too long. Try again, or pick another pair.")

    async def fetch_audio(self, mix_id: str, dest_path) -> str:
        async with self._client.stream("GET", f"/mix/{mix_id}/audio") as r:
            r.raise_for_status()
            with open(dest_path, "wb") as f:
                async for chunk in r.aiter_bytes():
                    f.write(chunk)
        return str(dest_path)

    async def mix_name(self, song1_name: str, song2_name: str, prompt: str = "") -> str | None:
        try:
            r = await self._client.post(
                "/mix/name",
                json={"song1_name": song1_name, "song2_name": song2_name, "prompt": prompt})
            r.raise_for_status()
            return r.json().get("name")
        except httpx.HTTPError:
            return None

    # ---- Sets (a continuous back-to-back set of 2–5 mixes) --------------------------------
    async def start_set(self, pairs: list[tuple[str, str]], user_id: str, set_index: int = 0) -> str:
        """Kick off (or hit the cache for) a set from ordered (beat, vocals) pairs; returns its id.
        Uses the same auto-rule shuffler the web set builder uses (user_id + set_index)."""
        payload = {
            "sets": [{"song1_id": a, "song2_id": b} for a, b in pairs],
            "user_id": user_id, "set_index": set_index,
        }
        r = await self._client.post("/set", json=payload)
        if r.status_code not in (200, 202):
            raise EngineError(_friendly(r))
        return r.json()["set_id"]

    async def set_status(self, set_id: str) -> SetResult:
        r = await self._client.get(f"/set/{set_id}")
        r.raise_for_status()
        d = r.json()
        return SetResult(set_id=set_id, status=d.get("status", "idle"), message=d.get("message"),
                         duration=d.get("duration"), members=d.get("members"))

    async def wait_for_set(self, set_id: str, *, poll: float = 3.0, timeout: float = 1200.0,
                           on_progress=None) -> SetResult:
        """Poll until the set is ready or errors (sets render several mixes, so allow longer)."""
        elapsed = 0.0
        while True:
            res = await self.set_status(set_id)
            if res.status in ("ready", "error"):
                return res
            if on_progress is not None:
                await on_progress(elapsed)
            await asyncio.sleep(poll)
            elapsed += poll
            if elapsed >= timeout:
                return SetResult(set_id=set_id, status="error",
                                 message="This set took too long. Try fewer mixes, or try again.")

    async def fetch_set_audio(self, set_id: str, dest_path) -> str:
        async with self._client.stream("GET", f"/set/{set_id}/audio") as r:
            r.raise_for_status()
            with open(dest_path, "wb") as f:
                async for chunk in r.aiter_bytes():
                    f.write(chunk)
        return str(dest_path)
