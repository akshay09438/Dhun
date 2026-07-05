"""FastAPI application entrypoint."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# Load API keys (Replicate, Anthropic) from the gitignored project-root .env
# before anything reads them. Safe no-op if the file is absent.
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.config import settings  # noqa: E402
from app.routes.songs import router as songs_router  # noqa: E402
from app.routes.stems import router as stems_router  # noqa: E402

app = FastAPI(title="Prompt-DJ API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(songs_router)
app.include_router(stems_router)
