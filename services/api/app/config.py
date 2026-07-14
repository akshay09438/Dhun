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


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
