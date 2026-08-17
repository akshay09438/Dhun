"""Thin async HTTP client to the local Prompt-DJ engine (the FastAPI app on :8000).

The bot never touches audio or the mix engine directly — it reuses the exact HTTP API the
web app uses (GET /library, POST /mix, poll GET /mix/{id}, GET /mix/{id}/audio). That keeps
the bot a pure front-end: all mixing quality, caching, rules and arrangement stay in one
place (the engine), never re-implemented here.
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging

import httpx

log = logging.getLogger("promptdj.discord")

# Every request this client makes is tagged with where it came from, so the ops dashboard can
# separate Discord activity from web activity. Attribution only — the engine records it and
# never lets it reach a cache id or the audio.
SOURCE = "discord"


@dataclasses.dataclass
class Song:
    id: str
    name: str
    role_hint: str = ""
    # "bollywood" | "english" | "" - which audience a VOCAL is for. Empty on beats, which are
    # instrumental and belong to neither. Used only to filter what the picker SHOWS; the engine
    # will still mix any beat with any vocal.
    language: str = ""
    # Part of the curated 25 shown in the dropdown - see LibrarySong.featured in the engine. A
    # Discord select holds 25 options, so the bot sorts featured songs FIRST and the rest follow.
    featured: bool = False


@dataclasses.dataclass
class MixResult:
    mix_id: str
    status: str                 # "ready" | "error" | "processing" | "idle"
    message: str | None = None
    rule: int | None = None     # 1 simple / 3 chop / 4 echo — for the style label
    notes: str | None = None
    # WHERE IT IS, so the card can move (2026-08-11). All optional: an engine that predates
    # these simply leaves them None and the card falls back to a plain "grinding...".
    stage: str | None = None            # what the engine is doing right now, in plain words
    queue_position: int | None = None   # 1-based place in the line, or None once it is rendering
    queue_eta_secs: int | None = None   # rough wait. An estimate on a card, never a promise


@dataclasses.dataclass
class SetResult:
    set_id: str
    status: str                 # "ready" | "error" | "processing" | "idle"
    message: str | None = None
    stage: str | None = None            # kept in step with MixResult so one card handler serves both
    queue_position: int | None = None
    queue_eta_secs: int | None = None
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
            Song(id=s["id"], name=s.get("original_name", ""), role_hint=s.get("role_hint", ""),
                 language=s.get("language", ""), featured=bool(s.get("featured", False)))
            for s in data.get("songs", [])
        ]

    async def start_mix(self, song1_id: str, song2_id: str, user_id: str,
                        generation: int = 0, prompt: str = "",
                        user_name: str | None = None) -> str:
        """Kick off (or hit the cache for) a mix; returns its id. Uses the same
        auto-rule shuffler the web app uses (user_id + generation).

        `source`/`user_name` are ops attribution only — they let the dashboard tell a Discord
        mix from a web one and show a real username instead of a bare account id. The engine
        records them and nothing else, so they never change the mix or which cache slot it lands in."""
        payload = {
            "song1_id": song1_id, "song2_id": song2_id, "prompt": prompt,
            "user_id": user_id, "generation": generation,
            "source": SOURCE, "user_name": user_name,
        }
        r = await self._client.post("/mix", json=payload)
        if r.status_code not in (200, 202):
            raise EngineError(_friendly(r))
        return r.json()["mix_id"]

    # --- bring your own song -------------------------------------------------------------
    # The bot NEVER ingests anything itself: it has no numpy, no Replicate and no ffmpeg, and a
    # second copy of that pipeline is exactly how uploads would start behaving differently from
    # the catalogue. It hands the bytes to the engine and reports what comes back.

    async def add_song(self, data: bytes, filename: str, *, uploaded_by: str, role: str,
                       main_drop: str = "", display_name: str = "") -> dict:
        """Hand an uploaded file to the engine. Returns as soon as the FREE checks pass.

        Raises EngineError with the engine's own plain-English reason on a refusal — those
        sentences are written to be shown to a person unchanged.
        """
        r = await self._client.post(
            "/songs/add",
            files={"file": (filename, data)},
            data={"uploaded_by": uploaded_by, "role": role,
                  "main_drop": main_drop, "display_name": display_name},
            timeout=120.0)
        if r.status_code != 200:
            raise EngineError(_friendly(r))
        return r.json()

    async def add_status(self, song_id: str) -> dict:
        """Where an in-flight upload has got to, for the progress line on the card."""
        r = await self._client.get(f"/songs/add/{song_id}")
        if r.status_code != 200:
            raise EngineError(_friendly(r))
        return r.json()

    async def wait_for_add(self, song_id: str, *, poll: float = 2.0, timeout: float = 900.0,
                           on_stage=None) -> dict:
        """Poll until the ingest finishes, calling `on_stage(text)` whenever the stage CHANGES.

        Long timeout on purpose: stem separation plus the structure analysis is minutes, and the
        person is watching a card that says what is happening.
        """
        waited, last = 0.0, None
        while waited < timeout:
            st = await self.add_status(song_id)
            stage = str(st.get("stage") or "")
            if on_stage is not None and stage and stage != last:
                last = stage
                await on_stage(stage)
            if st.get("done"):
                return st
            await asyncio.sleep(poll)
            waited += poll
        raise EngineError("That took longer than expected. Your song may still be on its way.")

    async def my_songs(self, discord_id: str) -> dict:
        """Somebody's own uploads. Filtered by who added them and nothing else."""
        r = await self._client.get(f"/songs/mine/{discord_id}")
        if r.status_code != 200:
            raise EngineError(_friendly(r))
        return r.json()

    async def keep_render(self, render_id: str) -> bool:
        """Ask the engine never to routine-tidy this render. Used when a grind is pinned to
        #best-mixes: the founder's rule is that those are the ones that must not be removed.

        Never raises. A pin that posted successfully must not report failure because a housekeeping
        marker could not be written — the worst case is that the mix ages out of the local cache
        later, while the MP3 stays in the showcase channel where people actually listen to it."""
        try:
            r = await self._client.post(f"/keep/{render_id}")
            return r.status_code == 200
        except Exception:  # noqa: BLE001 — bookkeeping, never fatal to a successful pin
            log.warning("could not mark %s as kept", render_id, exc_info=True)
            return False

    async def mix_status(self, mix_id: str) -> MixResult:
        r = await self._client.get(f"/mix/{mix_id}")
        r.raise_for_status()
        d = r.json()
        plan = d.get("plan") or {}
        return MixResult(
            mix_id=mix_id, status=d.get("status", "idle"), message=d.get("message"),
            rule=plan.get("rule") if isinstance(plan, dict) else None,
            notes=plan.get("notes") if isinstance(plan, dict) else None,
            stage=d.get("stage"), queue_position=d.get("queue_position"),
            queue_eta_secs=d.get("queue_eta_secs"),
        )

    async def wait_for_mix(self, mix_id: str, *, poll: float = 2.0, timeout: float = 600.0,
                           on_progress=None) -> MixResult:
        """Poll until the mix is ready or errors (or we give up). `on_progress(elapsed, res)` is
        awaited each tick so the caller can move the card - it is handed the whole result, not
        just a clock, because "6th in line" and "mixing it down" are the useful things to show
        and only the engine knows them."""
        elapsed = 0.0
        while True:
            res = await self.mix_status(mix_id)
            if res.status in ("ready", "error"):
                return res
            if on_progress is not None:
                await on_progress(elapsed, res)
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
    async def start_set(self, pairs: list[tuple[str, str]], user_id: str, set_index: int = 0,
                        user_name: str | None = None) -> str:
        """Kick off (or hit the cache for) a set from ordered (beat, vocals) pairs; returns its id.
        Uses the same auto-rule shuffler the web set builder uses (user_id + set_index).
        `source`/`user_name` are ops attribution only — see start_mix."""
        payload = {
            "sets": [{"song1_id": a, "song2_id": b} for a, b in pairs],
            "user_id": user_id, "set_index": set_index,
            "source": SOURCE, "user_name": user_name,
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
                         duration=d.get("duration"), members=d.get("members"),
                         stage=d.get("stage"), queue_position=d.get("queue_position"),
                         queue_eta_secs=d.get("queue_eta_secs"))

    async def wait_for_set(self, set_id: str, *, poll: float = 3.0, timeout: float = 1200.0,
                           on_progress=None) -> SetResult:
        """Poll until the set is ready or errors (sets render several mixes, so allow longer)."""
        elapsed = 0.0
        while True:
            res = await self.set_status(set_id)
            if res.status in ("ready", "error"):
                return res
            if on_progress is not None:
                await on_progress(elapsed, res)   # same shape as wait_for_mix, so one card handler serves both
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
