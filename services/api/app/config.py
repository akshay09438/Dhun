"""Application settings. Central place for paths and the upload safety limits.

Handle with care: this file defines the size/type limits that keep the upload
handler safe. Loosening them without thought widens the attack surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    # Where cleaned audio is stored (gitignored, outside any served code path).
    data_dir: Path = Path(__file__).resolve().parent.parent / "data"
    # Hard cap per uploaded file — prevents resource-exhaustion via huge uploads.
    max_file_bytes: int = 30 * 1024 * 1024  # 30 MB
    # Only these audio types are accepted; everything else is rejected.
    allowed_exts: frozenset[str] = frozenset({".mp3", ".wav", ".m4a", ".flac", ".ogg"})
    # Browser origins allowed to call the API (Vite dev server).
    allowed_cors_origins: tuple[str, ...] = ("http://localhost:5173",)


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
