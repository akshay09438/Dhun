"""FastAPI application entrypoint."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# Load API keys (Replicate, Anthropic) from the gitignored project-root .env
# before anything reads them. Safe no-op if the file is absent.
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

import logging  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.config import settings  # noqa: E402
from app.routes.admin import router as admin_router  # noqa: E402
from app.routes.analysis import router as analysis_router  # noqa: E402
from app.routes.library import router as library_router  # noqa: E402
from app.routes.live import router as live_router  # noqa: E402
from app.routes.mix import router as mix_router  # noqa: E402
from app.routes.set import router as set_router  # noqa: E402
from app.routes.songs import router as songs_router  # noqa: E402
from app.routes.stems import router as stems_router  # noqa: E402

from contextlib import asynccontextmanager  # noqa: E402

from app import janitor  # noqa: E402


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Start the disk janitor with the engine, stop it with the engine.

    It only WATCHES: every cycle asks storage for a dry run first, and sweeps only when a sweep
    would actually reach the cushion. On a healthy disk it deletes nothing and costs one
    disk-usage call a minute. See app/janitor.py for why the trigger lives apart from the policy.
    """
    janitor.start()
    try:
        yield
    finally:
        await janitor.stop()


log = logging.getLogger("promptdj.api")

app = FastAPI(title="Prompt-DJ API", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_cors_origins),
    allow_origin_regex=settings.allowed_cors_origin_regex,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── CROSS-SITE REQUEST GUARD ─────────────────────────────────────────────────────────────────
# CORS DOES NOT STOP THE REQUEST. It withholds the RESPONSE from a disallowed origin; the request
# still executes and its side effects still happen. `multipart/form-data` is a CORS-safelisted
# content type, so a POST carrying one gets no preflight at all — which meant (proven in the
# 2026-08-17 security review) that ANY web page open in a browser on this machine could drive
# `POST /songs/add` in a loop and spend the Replicate balance, with a forged `uploaded_by`.
#
# The fix is the standard one and it needs no shared secret: require a header a browser CANNOT
# set on a cross-origin request without triggering a preflight. The preflight is then answered by
# the CORS middleware above, which refuses any origin not on the allowlist. A same-origin page,
# the bot, and curl are all unaffected — they simply send the header.
#
# GETs are deliberately NOT covered: they are reads, they are what the audio <source> tags and the
# dashboard use, and requiring a header there would break plain browser media loading.
_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_APP_HEADER = "x-promptdj-app"


@app.middleware("http")
async def _require_app_header(request, call_next):
    """Refuse a mutating request that came FROM A PAGE and does not carry the app header.

    Conditioned on `Origin` deliberately. This defence only ever protects against a browser —
    anything else (the bot, curl, a script) can set whatever headers it likes, so demanding the
    header from them buys nothing and would only break every non-browser caller. A browser, on the
    other hand, always attaches `Origin` to a cross-origin POST and cannot add a custom header
    without a preflight that the CORS middleware above then refuses. So: an Origin present with no
    app header is the attack, and it is the only case blocked.
    """
    if (request.method in _MUTATING
            and "origin" in request.headers
            and _APP_HEADER not in request.headers):
        log.warning("blocked a %s to %s from origin %r with no %s header",
                    request.method, request.url.path, request.headers.get("origin"), _APP_HEADER)
        return JSONResponse(
            {"detail": "This request did not come from the app."}, status_code=403)
    return await call_next(request)


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
app.include_router(admin_router)  # read-only internal ops dashboard API (/admin/*)

# Serve the built web app (apps/web/dist) at "/" so a single origin — and a single
# tunnel — serves both the UI and the API (no CORS, keys never cross-origin). Mounted
# LAST, after the API routers, so specific API paths still win. A no-op in local dev,
# where the frontend runs on the Vite server and dist/ may not be built yet.
_DIST = Path(__file__).resolve().parents[3] / "apps" / "web" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="web")
