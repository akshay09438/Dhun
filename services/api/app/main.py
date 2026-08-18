"""FastAPI application entrypoint."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# Load API keys (Replicate, Anthropic) from the gitignored project-root .env
# before anything reads them. Safe no-op if the file is absent.
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

import logging  # noqa: E402
import logging.handlers  # noqa: E402

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

# THE ENGINE KEEPS ITS OWN DIARY, exactly as Grinder does.
#
# WHY THIS EXISTS. On 2026-08-18 an upload failed with "The read operation timed out" and there was
# NO WAY TO FIND OUT WHY. The engine only ever wrote to the console window it was launched from, so
# `_ingest`'s `log.exception("upload %s failed", ...)` - which carries the full traceback and the
# exact line - went to a window nobody was reading and was gone. All that survived was the 200-char
# summary the bot shows a person, and a summary is not a diagnosis: two separate hypotheses were
# built on it and both were wrong.
#
# Grinder learned this on 2026-08-14, when it wrote no log for two days and a HEALTHY bot was shut
# down and debugged because nothing could be read to check on it. Same lesson, other half of the
# app, four days later.
#
# Rotating, because an unbounded log on a disk this project keeps filling is its own bug. Never
# fatal: an engine that cannot open its log must still serve mixes.
try:
    _LOGDIR = Path(__file__).resolve().parents[1] / "logs"
    _LOGDIR.mkdir(parents=True, exist_ok=True)
    _fh = logging.handlers.RotatingFileHandler(
        _LOGDIR / "engine.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(_fh)
    logging.getLogger().setLevel(logging.INFO)
    log.info("engine logging to %s", _LOGDIR / "engine.log")
except OSError:
    log.warning("could not open the engine log file; console only")

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

# ── SIZE, BEFORE THE BODY IS READ ────────────────────────────────────────────────────────────
# The streaming cap inside the upload handler is applied too late to protect the DISK. Starlette
# materialises the whole file part before the handler is entered, spooling anything over 1 MB to a
# temp file — so by the time `_save_capped` counts a byte, the bytes are already on the disk the
# free-space check exists to protect (measured in the 2026-08-17 third review: the handler saw a
# 12 MB body in full, and `_free_gb()` ran after it was buffered).
#
# `Content-Length` is checked here, before any parsing. A client can lie about it, but a lying
# client is then caught by the streaming cap it was always caught by — this closes the case where
# an HONEST large upload writes gigabytes of temp that nothing accounted for. Discord's own ceiling
# is a tier, not a control: a Nitro member can attach 500 MB, and a boosted server raises it for
# everybody.
_MAX_BODY_BYTES = 40 * 1024 * 1024  # a little over the 30 MB per-file cap, to allow for the envelope


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
    if request.method in _MUTATING:
        raw = request.headers.get("content-length")
        try:
            declared = int(raw) if raw is not None else 0
        except ValueError:
            declared = 0
        if declared > _MAX_BODY_BYTES:
            log.warning("refused a %s to %s declaring %d bytes (ceiling %d)",
                        request.method, request.url.path, declared, _MAX_BODY_BYTES)
            return JSONResponse(
                {"detail": "That file is too big. The limit is 30 MB, and Discord's own limit is "
                           "usually 10 MB."}, status_code=413)
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
