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
import math
import re
import shutil
import tempfile
import threading
import uuid
from pathlib import Path

import soundfile as sf
from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app import library_store, spend
from app.audio import beatcheck
from app.audio.analysis import analyze_track
from app.audio.normalize import AudioError, normalize_audio, probe_seconds
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

# ── THE CAPS ARE RESERVATIONS, NOT A COUNT OF FINISHED SONGS ─────────────────────────────────
# Measured in the 2026-08-17 security review: counting manifest rows alone does NOT cap anything.
# A row is only written when the paid work finishes, minutes later, so nothing increments while
# uploads are queuing — 30 uploads from ONE person against a cap of 5 were all accepted in 19
# seconds, committing ~$3.60 of Replicate. The 2-at-a-time semaphore bounds the RATE, never the
# bill: every queued job still pays eventually.
#
# So a slot is claimed BEFORE the file is even read, under one lock with the check, and released
# only when the row exists (or the attempt dies). Rows + live reservations is the real total.
#
# In-memory on purpose: a reservation only means "a thread of this process is working on it", and
# a restart kills those threads, so the correct value after a restart is zero.
_RESERVED: dict[str, str] = {}          # song_id (or a placeholder) -> uploader id
_CAP_LOCK = threading.RLock()


class _CapFull(Exception):
    """No slot available — carries the sentence the person should be shown."""


def _claim_slot(uploader: str, token: str) -> None:
    """Take one upload slot for `uploader`, or raise _CapFull / BudgetSpent. Atomic with the check.

    TWO SEPARATE CEILINGS, because they answer different questions (founder's call, 2026-08-17):
      * how many songs you may KEEP — per person, and a failure gives its slot straight back, so a
        Replicate outage never burns one of somebody's five;
      * how much MONEY may ever be spent — global, counting failures, in `app.spend`. The re-review
        proved the first does not imply the second: twelve failed attempts cost $1.44 and used no
        quota at all.
    """
    with _CAP_LOCK:
        spend.check_budget()          # cheapest refusal of the lot, and the one that bounds the bill
        uploads.forget_cached_manifest()
        mine = uploads.count_for(uploader) + sum(1 for u in _RESERVED.values() if u == uploader)
        if mine >= settings.max_uploads_per_user:
            raise _CapFull(f"You've added your {settings.max_uploads_per_user} songs. "
                           "Nothing is lost — that's just the limit for now.")
        total = uploads.count_all() + len(_RESERVED)
        if total >= settings.max_uploaded_songs:
            raise _CapFull("The shared upload shelf is full "
                           f"({settings.max_uploaded_songs} songs). Nothing has broken.")
        _RESERVED[token] = uploader


def _release_slot(token: str) -> None:
    """Give the slot back. Safe to call twice, and safe to call on a key that was re-named away."""
    with _CAP_LOCK:
        _RESERVED.pop(token, None)


def _rename_slot(old: str, new: str) -> str:
    """Re-key a reservation from its placeholder to the real song id. Returns the key now held.

    RETURNS THE KEY because the caller must release the RIGHT one afterwards. The re-review found
    two bugs here, both mine:
      * if anything raised after the rename, the recovery path still released the OLD token, so the
        reservation was orphaned forever and that person's five shrank until a restart;
      * two people uploading the SAME song renamed onto one key, so one reservation vanished and
        the cap re-opened by one.
    Both are handled by refusing to collapse two claims into one key, and by telling the caller
    which key it actually owns.
    """
    with _CAP_LOCK:
        if old not in _RESERVED:
            return old
        if new in _RESERVED:
            # Somebody else already holds this song's slot. Keep both claims distinct so neither is
            # silently dropped; this one stays under its own token until it is released.
            return old
        _RESERVED[new] = _RESERVED.pop(old)
        return new


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
            v = m * 60.0 + sec
            if not (0 <= sec < 60) or m < 0:
                return None
        else:
            v = float(s)
    except ValueError:
        return None
    # NaN AND INFINITY MUST DIE HERE. Every comparison against NaN is False, so "0:nan" walked
    # through the range check above AND the "past the end of the song" check, and `json.dump`
    # then wrote a literal `NaN` into the manifest that indexes all 118 catalogue songs. Python
    # reads that back happily, so nothing would notice — but the file is no longer valid JSON for
    # any other reader. Found in the 2026-08-17 security review, reachable from Discord as
    # `/add drop:0:nan`.
    if not math.isfinite(v) or v < 0:
        return None
    return v


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


def _drop_row(song_id: str) -> None:
    """Remove this song's catalogue row, through the locked + atomic writer."""
    rows = [r for r in library_store.load() if str(r.get("song_id", "")) != song_id]
    library_store.save(rows)
    uploads.forget_cached_manifest()


def _ingest(song_id: str, name: str, role: str, uploader: str, drop: float | None,
            pre_existing: set[Path], slot_key: str) -> None:
    """The paid half, on a worker thread. Stems, then analysis, then the row.

    `pre_existing` is what was already on disk BEFORE this request. On failure only the files this
    request added are removed — a song that was already here (an orphan, or a catalogue song
    somebody re-uploaded) must keep every file it had.
    """
    try:
        with _INGEST_SLOTS, library_store.song_lock(song_id):
            # RE-CHECK INSIDE THE LOCK. Two people can upload the same track seconds apart: both
            # pass dedupe (neither has a row yet) and both queue. Without this the second one
            # would overwrite the first's row — taking their name, their quota and their drop —
            # and, if it then failed, delete the stems the FIRST upload had just paid for, leaving
            # a row pointing at missing files. Both were proven in the 2026-08-17 review.
            done_already = any(str(r.get("song_id", "")) == song_id and not r.get("pending")
                               for r in library_store.load())
            if done_already:
                log.info("upload %s: somebody else finished this exact song first", song_id[:12])
                _set_stage(song_id, "ready", done=True)
                return
            # `pre_existing` stays as it was at REQUEST time, before store_wav. Re-taking it here
            # would count the wav this request just stored as "already here" and so leave it behind
            # on failure. The row check above is what protects somebody else's work: two uploads of
            # the same song serialise on this lock, so if the other one finished we have already
            # returned, and if it has not started yet it has created nothing to lose.
            wav = path_for(song_id)
            if wav is None:
                raise RuntimeError("the stored audio vanished before it could be split")
            # COUNT THE MONEY BEFORE SPENDING IT. Recorded ahead of the call, never after: an
            # attempt that dies mid-call has still been paid for, and counting it afterwards would
            # miss exactly the failures this ceiling exists to bound.
            spend.record_attempt(song_id, uploader)
            _set_stage(song_id, "separating the parts")
            separate_stems(song_id, wav)          # Replicate; cached by song_id
            _set_stage(song_id, "working out the beat and the key")
            analyze_track(song_id, wav)           # Replicate structure + free local half

            missing = [p.name for p in _artifacts(song_id) if not p.exists()]
            if missing:
                raise RuntimeError(f"the pipeline finished but these are missing: {missing}")

            _set_stage(song_id, "adding it to your songs")
            extra = {"uploaded_by": uploader, "pending": False}
            if drop is not None:
                extra["main_drop"] = float(drop)
            # The row already exists (written before the paid work so the stem guard covered it);
            # clearing `pending` is the commit point that makes the song real and visible.
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
        try:
            _drop_row(song_id)   # the pending row goes too — it promised a song that isn't there
        except Exception:  # noqa: BLE001 — a failed cleanup must not hide the original failure
            log.exception("could not remove the pending row for %s", song_id[:12])
        _set_stage(song_id, "failed", error=str(e) or e.__class__.__name__, done=True)
    finally:
        # Whatever happened, the slot goes back: on success the manifest row now counts this song,
        # and on failure nothing should have been counted at all. Released in `finally` so a crash
        # can never leak a slot and quietly shrink somebody's five forever. The MONEY is not given
        # back — `spend` only ever goes up, because a failed attempt was still paid for.
        _release_slot(slot_key)


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

    if _free_gb() < settings.min_free_disk_gb:
        raise HTTPException(507, "There isn't enough room on the machine right now. Try later.")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in settings.upload_exts:
        raise HTTPException(400, "I can take an MP3 or an M4A. Discord also caps a file at 10 MB.")

    # --- CLAIM A SLOT before a single byte is read, and hold it until the row exists ------------
    token = f"pending:{uuid.uuid4().hex}"
    try:
        _claim_slot(uploaded_by, token)
    except spend.BudgetSpent as e:
        raise HTTPException(429, str(e))
    except _CapFull as e:
        raise HTTPException(400, str(e))

    try:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in"
            _save_capped(file, src)

            # LENGTH BEFORE DECODE. A 14 MB, 4-hour, 8 kbps MP3 expands to a 2.5 GB WAV, so
            # checking the limit after normalising is far too late — one request could take the
            # machine under its free-disk floor and make the cleaner delete other people's mixes.
            claimed = probe_seconds(src)
            if claimed and claimed > settings.max_upload_seconds:
                raise HTTPException(400, "That's over 8 minutes, which is longer than I can "
                                         "work with.")

            clean = Path(td) / "clean.wav"
            try:
                # ...and cap the decode too, because the header above is the file's own claim and
                # a hostile file can lie about it.
                normalize_audio(src, clean, max_seconds=settings.max_upload_seconds + 5.0)
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
                raise HTTPException(400, "That's over 8 minutes, which is longer than I can "
                                         "work with.")
            if drop is not None and drop >= seconds:
                m, s = divmod(int(seconds), 60)
                raise HTTPException(400, f"That drop is past the end — the song is {m}:{s:02d} "
                                         "long.")

            # FREE, and the whole reason this step exists: a podcast must never reach a paid call.
            try:
                musical, score, _bpm = beatcheck.has_a_steady_beat(clean)
            except Exception:  # noqa: BLE001
                raise HTTPException(400, "I couldn't read that as audio.")
            if not musical:
                raise HTTPException(400, "I couldn't hear a beat in that, so I stopped before "
                                         "spending anything. Speech and voice notes land here.")

            # The id is the hash of these exact bytes, which is what `store_wav` will name the
            # file. Working it out BEFORE storing is what lets us record which files were already
            # here — so a later failure can never delete the audio of a song that existed before
            # this request (an orphan, or a catalogue song somebody re-uploaded).
            song_id = hashlib.sha256(clean.read_bytes()).hexdigest()
            pre_existing = {p for p in _artifacts(song_id) if p.exists()}
            stored = store_wav(clean)
            if stored != song_id:  # cannot happen; if it does, do not guess which id is real
                raise HTTPException(500, "Something went wrong storing that song.")

        # DEDUPE ON THE ROW, not the wav. `path_for` only proves the audio is here — a song half
        # ingested by an earlier failure would otherwise read as a duplicate and be waved through
        # with no stems and no analysis.
        row = next((r for r in library_store.load() if str(r.get("song_id", "")) == song_id), None)
        if row is not None:
            _release_slot(token)   # already in the catalogue: it costs nobody a slot
            return {"song_id": song_id, "name": str(row.get("name") or ""),
                    "role": str(row.get("role_hint") or ""), "status": "ready", "duplicate": True}

        # A name is never blank: an empty one is dropped by GET /library, so the song would be
        # stored, split, analysed, PAID FOR, hold a slot, and be invisible everywhere — the exact
        # 2026-08-14 failure, reachable through an attachment called " .mp3".
        name = (display_name or "").strip() or Path(file.filename or "").stem.strip() or "your song"
        name = name[:80]
        held = _rename_slot(token, song_id)
        try:
            # THE ROW GOES IN BEFORE THE PAID WORK, marked `pending`. Writing it last left a
            # minutes-wide window in which the stems existed on disk but nothing said the song was
            # an upload, so the guard on them did not exist yet (re-review finding 4). `pending`
            # keeps the old promise too: `GET /library` hides these, so a row never advertises a
            # song whose files are still arriving, and a failure deletes the row again.
            library_store.upsert(name, song_id, role, _UPLOAD_LANGUAGE,
                                 extra={"uploaded_by": uploaded_by, "pending": True,
                                        **({"main_drop": float(drop)} if drop is not None else {})})
            uploads.forget_cached_manifest()
            _set_stage(song_id, "getting it ready")
            threading.Thread(target=_ingest, name=f"ingest-{song_id[:8]}",
                             args=(song_id, name, role, uploaded_by, drop, pre_existing, held),
                             daemon=True).start()
        except BaseException:
            _drop_row(song_id)          # never leave a pending row with no thread behind it
            _release_slot(held)         # ...and release the key we ACTUALLY hold, not the old one
            raise
        return {"song_id": song_id, "name": name, "role": role, "status": "processing",
                "duplicate": False, "seconds": round(seconds, 1), "beat_score": round(score, 3)}
    except BaseException:
        _release_slot(token)   # nothing was queued, so the slot must go straight back
        raise


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
    """Serve a stored, cleaned WAV by its content id (hex-validated).

    NEVER AN UPLOAD. Locking down the separated stems while still handing out the WHOLE track was
    incoherent — the re-review pulled a 5.6 MB "unreleased demo" straight off this route with a
    plain GET. Somebody's own song is theirs; the product's job is to mix it, not to distribute it.
    Catalogue songs still serve, because the web player streams them.
    """
    if uploads.is_upload_or_unknown(song_id) and path_for(song_id) is not None:
        raise HTTPException(403, "That song isn't shared.")
    p = path_for(song_id)
    if p is None:
        raise HTTPException(404, "Song not found.")
    return FileResponse(p, media_type="audio/wav")
