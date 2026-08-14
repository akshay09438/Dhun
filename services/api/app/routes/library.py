"""The preloaded song library (curated-catalog MVP).

Users no longer upload files — they pick from a curated list of songs we've already
ingested, split, and analyzed (and whose tempo grid we've verified by hand). The
catalog is a manifest: data/library/manifest.json maps display names to EXISTING
song ids, so picking a catalog song reuses every cache (no cloud cost, no fresh
BPM misread — the whole point of the catalog).

Read-only: this route never writes or ingests. New songs are added by ingesting a
file through the normal upload path once (operator-side), verifying its analysis,
then adding a manifest entry.
"""

from __future__ import annotations

import json
import logging
import re

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings
from app.storage import path_for

router = APIRouter()
log = logging.getLogger("promptdj.library")

_HEX_ID = re.compile(r"[0-9a-f]{64}")


class LibrarySong(BaseModel):
    id: str
    original_name: str
    url: str
    status: str = "ready"
    role_hint: str = ""  # "beat" | "vocals" | "" — a display nudge, not a restriction
    # WHICH AUDIENCE THIS VOCAL IS FOR (2026-08-12): "bollywood" | "english" | "".
    #
    # Why it exists: the catalog is 14 Bollywood vocals to 4 English ones, so a US listener
    # opening the picker met a wall of songs they had never heard of. The clients FILTER on this;
    # the engine does NOT — any beat still mixes with any vocal, so the cross-language pairs that
    # produce the best results (Father Ocean x Tere Bina) stay reachable by switching the toggle.
    #
    # Empty on beats by design: a beat is an instrumental bed and belongs to neither audience.
    language: str = ""
    # SHOWN IN THE DISCORD PICKER (2026-08-14). A Discord select menu holds 25 options and no more,
    # so with 63 beats and 59 English vocals most of the catalog was unreachable and WHICH 25
    # appeared was an accident of manifest order. `scripts/set_featured.py` chooses them
    # deliberately - beats from the house band, vocals ranked by how many of those beats they can
    # actually pair with on tempo (measured: 26 of 59 English vocals pair with NO house beat).
    # The ENGINE ignores this completely: every song stays fully mixable, and the web app shows all
    # of them. It only decides what fits in a dropdown.
    featured: bool = False


def _manifest_path():
    return settings.data_dir / "library" / "manifest.json"


def song_names(ids, data_dir=None) -> dict:
    """Map catalog song ids -> display names, for labelling ops events on the dashboard.
    Best-effort and read-only: a missing/broken manifest, or an unknown id, simply yields no
    entry (never raises). `data_dir` lets a caller resolve against its own (possibly test) data
    folder; defaults to the configured one."""
    dd = data_dir if data_dir is not None else settings.data_dir
    p = dd / "library" / "manifest.json"
    out: dict[str, str] = {}
    if not p.exists():
        return out
    try:
        entries = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return out
    wanted = set(ids)
    for e in entries if isinstance(entries, list) else []:
        sid = str(e.get("song_id", ""))
        if sid in wanted:
            name = str(e.get("name", "")).strip()
            if name:
                out[sid] = name
    return out


@router.get("/library")
def get_library() -> dict:
    """The curated catalog: every manifest entry whose audio actually exists."""
    p = _manifest_path()
    if not p.exists():
        return {"songs": []}
    try:
        entries = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.exception("library manifest unreadable")
        return {"songs": []}

    songs: list[LibrarySong] = []
    for e in entries if isinstance(entries, list) else []:
        sid = str(e.get("song_id", ""))
        name = str(e.get("name", "")).strip()
        if not name or not _HEX_ID.fullmatch(sid):
            continue  # malformed entry — skip, never crash the catalog
        if path_for(sid) is None:
            continue  # audio missing on disk — hide rather than 500 later
        songs.append(LibrarySong(
            id=sid,
            original_name=name,
            url=f"/songs/{sid}/audio",
            role_hint=str(e.get("role_hint", "")),
            language=str(e.get("language", "")),
            featured=bool(e.get("featured", False)),
        ))
    return {"songs": [s.model_dump() for s in songs]}
