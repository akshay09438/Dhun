"""Upload + serve routes — the app's edge with the outside world.

Handle with care: this accepts files from anyone. Safety properties it must keep:
  - Extension allowlist gate (UX filter; NOT the security control).
  - Streaming size cap: the body is read in chunks and aborted the moment it
    exceeds the cap, so a huge upload can never be fully buffered in memory.
  - Filenames from the client are only ever used as display text / error text,
    never as a filesystem path (storage names files by content hash).
  - Audio ids are validated as strict hex in storage.path_for before any disk
    access, so a crafted id cannot escape the data dir.

`/songs/add` (2026-08-17) is the Discord "bring your own song" route and is the
most exposed thing in the project: there is NO allowlist, so anyone who joins
the server can reach it, and every accepted file spends real money. Its rules,
in the order they run — cheapest and free first, so nothing costs anything
until it has earned the spend:

  1. who + what: a plausible uploader id, a role we understand, a drop we can parse
  2. the caps: per person, global, and free disk
  3. the file: extension, then a STREAMED size cap
  4. free local work: decode, duration, then the beat pre-check (app/audio/beatcheck)
  5. dedupe on the MANIFEST ROW, not the wav — a half-ingested song must not
     read as a duplicate and be waved through with no stems
  6. only now, the paid calls: stems, then structure + analysis, under a
     semaphore so three testers cannot stack GPU calls
  7. the manifest row LAST. It is the commit point: a row pointing at files that
     do not exist is worse than no row.

Any failure removes every file THIS request created and never counts against
the cap — a half-ingested song holding a cap slot it cannot be mixed from is
the worst outcome of the lot.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import tempfile
import threading
from pathlib import Path

import soundfile as sf
from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app import library_store
from app.audio import beatcheck
from app.audio.analysis import analyze_track
from app.audio.normalize import AudioError, normalize_audio
from app.audio.stems import separate_stems
from app.config import settings
from app.models import Song
from app.planner import uploads
from app.storage import path_for, store_wav

router = APIRouter()
log = logging.getLogger("promptdj.songs")

_CHUNK = 1024 * 1024  # 1 MB

# A Discord snowflake is 17-20 digits. Validated so the id can never be anything but digits — it is
# used as a manifest value and as a cap key, never as a path, but a strict shape costs nothing.
_DISCORD_ID = re.compile(r"^\d{5,25}$")

_ROLES = {"beat", "vocals"}

# Uploads default to English rather than blank. A BLANK language is the one value that matches
# neither picker list, which is exactly how 103 songs went missing on 2026-08-14. Nobody is
# prompting a Suno user for a language, so the default has to be a value that can be seen.
# Uploads never enter the featured dropdown anyway, and `/mine` filters on uploaded_by ALONE.
_UPLOAD_LANGUAGE = "english"

# Only `max_concurrent_ingests` paid pipelines at a time.
_INGEST_SLOTS = threading.Semaphore(settings.max_concurrent_ingests)

# What each in-flight upload is doing, for the Discord card's progress line. In-memory: a restart
# loses the progress text, never the song — the manifest row is the only durable truth.
_PROGRESS: dict[str, dict] = {}
_PROGRESS_LOCK = threading.Lock()


def _set_stage(song_id: str, stage: str, *, error: str = "", done: bool = False) -> None:
    with _PROGRESS_LOCK:
        _PROGRESS[song_id] = {"stage": stage, "error": error, "done": done}


def parse_drop(raw: str) -> float | None:
    """"1:24", "84", "1:24.5" -> seconds. None when it is not a time at all.

    Accepted because the uploader is typing it by hand under no instruction; rejecting a format
    somebody reasonably used would cost them the upload.
    """
    s = (raw or "").strip()
    if not s:
        return None
    try:
        if ":" in s:
            mins, _, secs = s.partition(":")
            m, sec = float(mins), float(secs)
            if sec < 0 or sec >= 60 or m < 0:
                return None
            return m * 60.0 + sec
        v = float(s)
        return v if v >= 0 else None
    except ValueError:
        return None


def _validate_ext(f: UploadFile) -> None:
    ext = Path(f.filename or "").suffix.lower()
    if ext not in settings.allowed_exts:
        raise HTTPException(400, f"'{f.filename}' is not a supported audio file.")


def _save_capped(f: UploadFile, dst: Path) -> None:
    """Stream the upload to ``dst``, aborting if it exceeds the size cap.

    Never materializes the whole body in memory — reads in chunks and stops the
    moment the cumulative size crosses the limit.
    """
    total = 0
    with dst.open("wb") as out:
        while chunk := f.file.read(_CHUNK):
            total += len(chunk)
            if total > settings.max_file_bytes:
                raise HTTPException(400, f"'{f.filename}' is larger than 30 MB.")
            out.write(chunk)


def _process(f: UploadFile) -> Song:
    _validate_ext(f)
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in"
        _save_capped(f, src)
        out = Path(td) / "out.wav"
        try:
            normalize_audio(src, out)
        except AudioError:
            raise HTTPException(400, f"Could not read '{f.filename}' as audio.")
        song_id = store_wav(out)
    return Song(id=song_id, original_name=f.filename or "song", url=f"/songs/{song_id}/audio")


@router.post("/songs")
def upload_songs(song1: UploadFile, song2: UploadFile):
    """Accept two songs, clean each, and return records the client can play."""
    return {"songs": [_process(song1), _process(song2)]}


def _free_gb() -> float:
    return shutil.disk_usage(settings.data_dir).free / 1e9


def _artifacts(song_id: str) -> list[Path]:
    """Every file a full ingest produces for one song."""
    d = settings.data_dir
    return ([d / f"{song_id}.wav", d / f"{song_id}.structure.json", d / f"{song_id}.analysis.json"]
            + [d / f"{song_id}.{s}.mp3" for s in ("vocals", "drums", "bass", "other")])


def _ingest(song_id: str, name: str, role: str, uploader: str, drop: float | None,
            pre_existing: set[Path]) -> None:
    """The paid half, on a worker thread. Stems, then analysis, then the row.

    `pre_existing` is what was already on disk BEFORE this request. On failure only the files this
    request added are removed — a song that was already here (an orphan, or a catalogue song
    somebody re-uploaded) must keep every file it had.
    """
    try:
        with _INGEST_SLOTS, library_store.song_lock(song_id):
            wav = path_for(song_id)
            if wav is None:
                raise RuntimeError("the stored audio vanished before it could be split")
            _set_stage(song_id, "separating the parts")
            separate_stems(song_id, wav)          # Replicate; cached by song_id
            _set_stage(song_id, "working out the beat and the key")
            analyze_track(song_id, wav)           # Replicate structure + free local half

            missing = [p.name for p in _artifacts(song_id) if not p.exists()]
            if missing:
                raise RuntimeError(f"the pipeline finished but these are missing: {missing}")

            _set_stage(song_id, "adding it to your songs")
            extra = {"uploaded_by": uploader}
            if drop is not None:
                extra["main_drop"] = float(drop)
            # LAST. The row is the commit point, and it is what the caps count.
            library_store.upsert(name, song_id, role, _UPLOAD_LANGUAGE, extra=extra)
            uploads.forget_cached_manifest()      # the very next grind must see it
        _set_stage(song_id, "ready", done=True)
        log.info("upload %s ready: %r role=%s by=%s drop=%s", song_id[:12], name, role, uploader, drop)
    except Exception as e:  # noqa: BLE001 — every failure path must clean up and stay visible
        log.exception("upload %s failed", song_id[:12])
        for p in [q for q in _artifacts(song_id) if q.exists() and q not in pre_existing]:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                log.warning("could not remove %s after a failed upload", p.name)
        _set_stage(song_id, "failed", error=str(e) or e.__class__.__name__, done=True)


@router.post("/songs/add")
def add_song(file: UploadFile,
             uploaded_by: str = Form(...),
             role: str = Form(...),
             main_drop: str = Form(""),
             display_name: str = Form("")) -> dict:
    """Accept somebody's own song. Returns as soon as the FREE checks pass; the paid work runs on.

    Everything that can refuse for free refuses here, so the caller gets a plain reason in a second
    or two rather than a failure minutes later.
    """
    if not _DISCORD_ID.fullmatch(uploaded_by or ""):
        raise HTTPException(400, "I couldn't tell who you are, so I didn't start.")
    role = (role or "").strip().lower()
    if role not in _ROLES:
        raise HTTPException(400, "Tell me whether this is a beat or a vocal.")

    drop = parse_drop(main_drop)
    if role == "beat" and drop is None:
        raise HTTPException(400, "For a beat I need the drop — like 1:24, or 84 for seconds.")

    # --- the caps, before a single byte is read -----------------------------------------------
    uploads.forget_cached_manifest()   # count against the manifest as it is RIGHT NOW
    mine = uploads.count_for(uploaded_by)
    if mine >= settings.max_uploads_per_user:
        raise HTTPException(400, f"You've added your {settings.max_uploads_per_user} songs. "
                                 "Nothing is lost — that's just the limit for now.")
    if uploads.count_all() >= settings.max_uploaded_songs:
        raise HTTPException(400, "The shared upload shelf is full "
                                 f"({settings.max_uploaded_songs} songs). Nothing has broken.")
    if _free_gb() < settings.min_free_disk_gb:
        raise HTTPException(507, "There isn't enough room on the machine right now. Try later.")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in settings.upload_exts:
        raise HTTPException(400, "I can take an MP3 or an M4A. Discord also caps a file at 10 MB.")

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in"
        _save_capped(file, src)
        clean = Path(td) / "clean.wav"
        try:
            normalize_audio(src, clean)
        except AudioError:
            raise HTTPException(400, "I couldn't read that as audio.")

        try:
            info = sf.info(str(clean))
            seconds = float(info.frames) / float(info.samplerate or 1)
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "I couldn't read that as audio.")
        if seconds < settings.min_upload_seconds:
            raise HTTPException(400, "That's too short to mix — 30 seconds is the minimum.")
        if seconds > settings.max_upload_seconds:
            raise HTTPException(400, "That's over 8 minutes, which is longer than I can work with.")
        if drop is not None and drop >= seconds:
            m, s = divmod(int(seconds), 60)
            raise HTTPException(400, f"That drop is past the end — the song is {m}:{s:02d} long.")

        # FREE, and the whole reason this step exists: a podcast must never reach a paid call.
        try:
            musical, score, _bpm = beatcheck.has_a_steady_beat(clean)
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "I couldn't read that as audio.")
        if not musical:
            raise HTTPException(400, "I couldn't hear a beat in that, so I stopped before "
                                     "spending anything. Speech and voice notes land here.")

        # The id is the hash of these exact bytes, which is what `store_wav` will name the file.
        # Working it out BEFORE storing is what lets us record which files were already here — so a
        # later failure can never delete the audio of a song that existed before this request (an
        # orphan, or a catalogue song somebody re-uploaded).
        song_id = hashlib.sha256(clean.read_bytes()).hexdigest()
        pre_existing = {p for p in _artifacts(song_id) if p.exists()}
        stored = store_wav(clean)
        if stored != song_id:  # cannot happen; if it ever does, do not guess which id is real
            raise HTTPException(500, "Something went wrong storing that song.")

    # DEDUPE ON THE ROW, not the wav. `path_for` only proves the audio is here — a song half
    # ingested by an earlier failure would otherwise read as a duplicate and be waved through with
    # no stems and no analysis.
    row = next((r for r in library_store.load() if str(r.get("song_id", "")) == song_id), None)
    if row is not None:
        return {"song_id": song_id, "name": str(row.get("name") or ""), "role": str(row.get("role_hint") or ""),
                "status": "ready", "duplicate": True}

    name = (display_name or Path(file.filename or "").stem or "your song").strip()[:80]
    _set_stage(song_id, "getting it ready")
    threading.Thread(target=_ingest, name=f"ingest-{song_id[:8]}",
                     args=(song_id, name, role, uploaded_by, drop, pre_existing), daemon=True).start()
    return {"song_id": song_id, "name": name, "role": role, "status": "processing",
            "duplicate": False, "seconds": round(seconds, 1), "beat_score": round(score, 3)}


@router.get("/songs/add/{song_id}")
def add_status(song_id: str) -> dict:
    """Where an in-flight upload has got to, for the Discord card's progress line."""
    if path_for(song_id) is None and song_id not in _PROGRESS:
        raise HTTPException(404, "No such upload.")
    with _PROGRESS_LOCK:
        st = dict(_PROGRESS.get(song_id) or {})
    if st:
        return {"song_id": song_id, **st}
    # No memory of it (a restart): the manifest row is the durable answer.
    known = any(str(r.get("song_id", "")) == song_id for r in library_store.load())
    return {"song_id": song_id, "stage": "ready" if known else "unknown",
            "error": "", "done": bool(known)}


@router.get("/songs/mine/{discord_id}")
def my_songs(discord_id: str) -> dict:
    """Somebody's own uploads. Filtered on uploaded_by and NOTHING else — see uploads.mine."""
    if not _DISCORD_ID.fullmatch(discord_id or ""):
        raise HTTPException(400, "Not a valid account id.")
    uploads.forget_cached_manifest()
    songs = [{"song_id": r.get("song_id"), "name": r.get("name"),
              "role_hint": r.get("role_hint"), "main_drop": r.get("main_drop")}
             for r in uploads.mine(discord_id) if path_for(str(r.get("song_id", ""))) is not None]
    return {"songs": songs, "used": len(songs), "limit": settings.max_uploads_per_user}


@router.get("/songs/{song_id}/audio")
def get_audio(song_id: str):
    """Serve a stored, cleaned WAV by its content id (hex-validated)."""
    p = path_for(song_id)
    if p is None:
        raise HTTPException(404, "Song not found.")
    return FileResponse(p, media_type="audio/wav")
