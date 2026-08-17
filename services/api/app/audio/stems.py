"""Split a cleaned song into 4 stems (vocals/drums/bass/other) via Replicate.

The heavy AI (Demucs) runs in Replicate's cloud because it can't run on this
machine (PyTorch is incompatible with the local ARM chip). This module is just
the orchestrator: send the audio, get back 4 stems, store them.

Cost control: results are cached by the song's content id. If a song has
already been split, we return the stored stems and make NO paid API call.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import replicate

from app.config import settings

STEMS: tuple[str, ...] = ("vocals", "drums", "bass", "other")

_MODEL = "ryan5453/demucs"  # runs htdemucs, best-quality separation


class SeparationError(Exception):
    """Raised when the cloud separation cannot be completed."""


def stem_path(song_id: str, stem: str) -> Path:
    return settings.data_dir / f"{song_id}.{stem}.mp3"


def _model_ref() -> str:
    version = replicate.models.get(_MODEL).latest_version.id
    return f"{_MODEL}:{version}"


# A stem download that never returns is worse than one that fails: failure cleans up and frees the
# slot, hanging holds it forever. Generous enough for a large mp3 on a slow line.
_DOWNLOAD_TIMEOUT_S = 180

def separate_stems(song_id: str, wav_path: Path) -> dict[str, Path]:
    """Return {stem_name: file_path} for the song, splitting it if needed.

    Cached: if all four stems already exist for this song, no API call is made.
    """
    stored = {s: stem_path(song_id, s) for s in STEMS}
    if all(p.exists() for p in stored.values()):
        return stored  # cache hit — free

    try:
        with open(wav_path, "rb") as audio:
            out = replicate.run(
                _model_ref(),
                input={"audio": audio, "model": "htdemucs", "output_format": "mp3"},
            )
    except Exception as e:  # network, auth, credit, model errors
        raise SeparationError(str(e)[:200])

    if not isinstance(out, dict):
        raise SeparationError("unexpected separation output")

    result: dict[str, Path] = {}
    for s in STEMS:
        item = out.get(s)
        if item is None:
            raise SeparationError(f"separation missing stem: {s}")
        # TIMEOUT. A hung download holds one of the two ingest slots AND its uploader's
        # reservation for as long as it hangs, and `_release_slot` sits in a `finally` a stuck
        # thread never reaches - so two of these stop uploads for everybody until the engine is
        # restarted, and each one permanently costs its owner one of their five (third review, A3).
        data = (item.read() if hasattr(item, "read")
                else urllib.request.urlopen(str(item), timeout=_DOWNLOAD_TIMEOUT_S).read())
        dst = stem_path(song_id, s)
        dst.write_bytes(data)
        result[s] = dst
    return result
