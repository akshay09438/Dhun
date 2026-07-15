"""FastAPI application entrypoint."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# Load API keys (Replicate, Anthropic) from the gitignored project-root .env
# before anything reads them. Safe no-op if the file is absent.
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.config import settings  # noqa: E402
from app.routes.analysis import router as analysis_router  # noqa: E402
from app.routes.library import router as library_router  # noqa: E402
from app.routes.live import router as live_router  # noqa: E402
from app.routes.mix import router as mix_router  # noqa: E402
from app.routes.set import router as set_router  # noqa: E402
from app.routes.songs import router as songs_router  # noqa: E402
from app.routes.stems import router as stems_router  # noqa: E402

app = FastAPI(title="Prompt-DJ API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_cors_origins),
    allow_origin_regex=settings.allowed_cors_origin_regex,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(songs_router)
app.include_router(stems_router)
app.include_router(analysis_router)
app.include_router(mix_router)
app.include_router(set_router)
app.include_router(live_router)
app.include_router(library_router)

# Serve the built web app (apps/web/dist) at "/" so a single origin — and a single
# tunnel — serves both the UI and the API (no CORS, keys never cross-origin). Mounted
# LAST, after the API routers, so specific API paths still win. A no-op in local dev,
# where the frontend runs on the Vite server and dist/ may not be built yet.
_DIST = Path(__file__).resolve().parents[3] / "apps" / "web" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="web")
