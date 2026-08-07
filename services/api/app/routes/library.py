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
        ))
    return {"songs": [s.model_dump() for s in songs]}
