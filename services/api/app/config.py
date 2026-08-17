"""Application settings. Central place for paths and the upload safety limits.

Handle with care: this file defines the size/type limits that keep the upload
handler safe. Loosening them without thought widens the attack surface.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _cors_origins() -> tuple[str, ...]:
    """The exact browser origins allowed to call the API. Set `PROMPTDJ_CORS_ORIGINS`
    (comma-separated) to the real deployed origin in production; defaults to the local
    Vite dev server. In production the UI is served same-origin (see main.py), so no
    cross-origin allowance is needed at all — an empty value denies every website."""
    raw = os.environ.get("PROMPTDJ_CORS_ORIGINS", "http://localhost:5173")
    return tuple(o.strip() for o in raw.split(",") if o.strip())


def _cors_origin_regex() -> str | None:
    """The wide "any localhost port" match is a DEV-ONLY convenience (Vite may hop
    5173→5174→… when a port is busy). It is OFF by default so it never ships to
    production; opt in locally with `PROMPTDJ_DEV_CORS=1`. It never matched a remote
    origin, but shipping a permissive dev rule is poor hygiene, so it stays out of the
    default build."""
    if os.environ.get("PROMPTDJ_DEV_CORS", "").strip().lower() in ("1", "true", "yes"):
        return r"http://(localhost|127\.0\.0\.1):\d+"
    return None


@dataclass(frozen=True)
class Settings:
    # Where cleaned audio is stored (gitignored, outside any served code path).
    data_dir: Path = Path(__file__).resolve().parent.parent / "data"
    # Hard cap per uploaded file — prevents resource-exhaustion via huge uploads.
    max_file_bytes: int = 30 * 1024 * 1024  # 30 MB
    # Only these audio types are accepted; everything else is rejected.
    allowed_exts: frozenset[str] = frozenset({".mp3", ".wav", ".m4a", ".flac", ".ogg"})
    # Browser origins allowed to call the API — explicit allowlist, env-configurable.
    # Locked down (2026-07-14): the wide any-localhost-port regex no longer ships by
    # default; production sets PROMPTDJ_CORS_ORIGINS to the real origin (or leaves it,
    # since the UI is same-origin). Dev keeps working via PROMPTDJ_DEV_CORS=1.
    allowed_cors_origins: tuple[str, ...] = field(default_factory=_cors_origins)
    allowed_cors_origin_regex: str | None = field(default_factory=_cors_origin_regex)

    # --- /add: bring your own song (2026-08-17) ------------------------------------------------
    # There is NO allowlist: anyone in the Discord can upload. These four numbers are therefore the
    # only thing standing between the server and an unbounded bill or a full disk, so each is a
    # hard refusal with a plain-English reason, never a silent failure.
    #
    # Uploads are a NARROWER type gate than `allowed_exts` above: Suno exports MP3, and every extra
    # container is another decoder reachable by a stranger for no user benefit.
    upload_exts: frozenset[str] = frozenset({".mp3", ".m4a"})
    # 40 songs is roughly 2.6 GB stored (a ~48 MB wav plus ~16 MB of stems each) and about $2.80 of
    # Replicate at ~7c a song — sized against the $5 balance and the disk, not chosen for feel.
    max_uploaded_songs: int = 40
    # Per person, so one enthusiast cannot spend the whole global cap on their own.
    max_uploads_per_user: int = 5
    # Refuse below this much free disk. The janitor's own sweep target is 3.0 GB, so accepting an
    # upload under it would hand the cleaner work to do and could evict somebody's finished mix.
    min_free_disk_gb: float = 3.0
    # A song must be long enough to arrange and short enough not to dominate the queue.
    min_upload_seconds: float = 30.0
    max_upload_seconds: float = 8 * 60.0
    # Two paid pipelines at a time. Three testers uploading together must not stack GPU calls —
    # Replicate throttles hard at a low balance (a 429 saying "reduced to 6/min" means the balance
    # is nearly out, not that we are too parallel).
    max_concurrent_ingests: int = 2


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
