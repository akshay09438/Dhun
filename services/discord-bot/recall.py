"""Getting a finished grind's audio back after its card is gone.

A grind card is ephemeral, so Discord deletes it when its owner reloads - and with it the MP3 that
was attached. Measured on 2026-08-16 across every grind ever made: 23 of 38 could no longer be
played by anybody, and exactly one had been showcased (the only permanent copy there is).

This is the drawer behind the counter. It keeps NOTHING new: the engine already holds every render
for seven days and the grind row already stores its `ref_id`, so a lost mix is simply asked for
again. Fetching it also re-stamps the render as recently used, so the act of recovering a mix moves
it to the back of the eviction queue instead of leaving it next in line.

The one rule here is honesty. Local copy, then the engine, then `None` - and `None` means gone, not
"try again in a moment". Callers must say so plainly; the old `pin` told people a mix deleted days
ago was "still arriving", which is how somebody ends up waiting for something that is never coming.
"""
from __future__ import annotations

import json
import logging
import tempfile
import uuid
from pathlib import Path

import store

log = logging.getLogger("promptdj.discord")


def is_a_set(row) -> bool:
    """True when this grind is several pairs joined into one continuous track.

    It decides WHICH engine route can serve the audio, and the routes are not interchangeable:
    asking `/mix/{id}` for a set id is a 404, which would read exactly like "evicted" and quietly
    turn every recoverable set into a lost one."""
    try:
        return len(json.loads(row["pairs"])) > 1
    except (ValueError, TypeError, KeyError, IndexError):
        return False


async def audio_for(row, api) -> Path | None:
    """The finished audio for a grind, or None when it honestly cannot be had.

    Order is cheapest-first: the copy on disk, then the engine. Never a re-render - a fresh render
    would be a DIFFERENT take, and handing somebody a different mix when they asked for theirs is
    the same broken promise as handing them nothing.
    """
    if row is None:
        return None

    path = row["audio_path"]
    if path and Path(path).exists():
        return Path(path)

    ref = row["ref_id"]
    if not ref:
        # Nothing to ask for. This is Aashwin's second mix: the bot was killed mid-render, so the
        # row never learned where the finished audio went. `_render` now records the reference the
        # moment the engine accepts the job, so new grinds cannot land here.
        return None

    dest = Path(tempfile.gettempdir()) / f"grind_{uuid.uuid4().hex[:10]}.wav"
    try:
        if is_a_set(row):
            await api.fetch_set_audio(ref, dest)
        else:
            await api.fetch_audio(ref, dest)
    except Exception:  # noqa: BLE001 - any failure here means "cannot be had", and the caller
        # must be able to say that plainly. A 404 (evicted past its seven days) and the engine
        # being down are the same answer to the person waiting: not right now.
        log.info("grind #%s could not be recovered from the engine", row["number"], exc_info=True)
        return None

    if not dest.exists():
        return None

    # Remember it, so recovering the same mix twice costs one download rather than two.
    try:
        store.set_audio_path(row["number"], str(dest))
    except Exception:  # noqa: BLE001 - never fail a recovered mix over bookkeeping
        log.warning("could not record the recovered audio path for grind #%s",
                    row["number"], exc_info=True)
    return dest


def label_of(row) -> str:
    """"Beat x Vocal", or "long grind, N tracks" - the same wording `/mygrinds` lists."""
    try:
        pairs = json.loads(row["pairs"])
    except (ValueError, TypeError, KeyError, IndexError):
        return "a grind"
    if len(pairs) == 1:
        return f"{pairs[0][2]} x {pairs[0][3]}"
    return f"long grind, {len(pairs)} tracks"


async def recovered_file(row, api, attach):
    """(file, sentence) - what to hand back, and what to say with it.

    THREE OUTCOMES, AND THEY MUST NOT BE CONFLATED. `showcase.pin` conflated the first two and told
    people a mix deleted days ago was "still arriving":

      * here it is
      * the render is past its seven days - genuinely gone, so say gone and offer a fresh take
      * it exists but will not fit down a Discord upload - a completely different problem, and
        calling that "gone" would be a lie about a file sitting right there

    `attach` is passed in rather than imported so the transcode can be exercised for real in
    production and stubbed in tests, where running ffmpeg over invented bytes would prove nothing.
    """
    number = row["number"]
    name = label_of(row)

    wav = await audio_for(row, api)
    if wav is None:
        return None, (
            f"Grind #{number} ({name}) is gone. I keep the audio for seven days and this one is "
            f"past that, so there is nothing left to send — sorry. Run 🔁 **Again** on it and you "
            f"will get a fresh take of the same two songs.")

    clip = await attach(wav)
    if clip is None:
        return None, (
            f"Grind #{number} ({name}) is here, but it is too long to send as a file — Discord "
            f"will not take one that big. Play it in a listening room instead.")

    return clip, f"Grind #{number} — {name}"
