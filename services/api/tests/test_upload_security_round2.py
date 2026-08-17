"""Round two of the adversarial review: the fixes that did NOT hold, and the ones I broke fixing.

Five of the first round's fixes survived a second attack (the decompression-bomb guard, the
cross-site guard, the same-song race, the drop parser, both pickers). These pin the rest:

  * the caps bounded songs KEPT, never MONEY — twelve failed attempts cost $1.44 and used no quota
  * the stem lock reused a helper that answers "no" when it means "I don't know", so a corrupt
    manifest opened it, and one transient bad read LATCHED it open
  * the lock covered nothing during the minutes the paid work ran, because the row came last
  * we blocked the separated parts while serving the WHOLE uploaded song, unauthenticated
  * a sibling paid endpoint (`POST /songs/{id}/stems`) was never capped at all
  * and my own reservation bookkeeping could orphan a slot forever, or drop one and re-open the cap

Deliberately NOT here: another round on the beat pre-check. It is a courtesy filter, not a security
control (see app/audio/beatcheck.py) — the founder's call was to stop tuning it against crafted
audio and let the spend ceiling be the real defence.
"""

from __future__ import annotations

import dataclasses
import io
import json
import threading
import time

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from app import library_store, spend, storage
from app.audio import stems as stems_mod
from app.main import app
from app.planner import uploads
from app.routes import songs as songs_route
from app.routes import stems as stems_route

client = TestClient(app)
APP = {"X-PromptDJ-App": "test"}
WHO = "123456789012345678"


def DD():
    return songs_route.settings.data_dir


@pytest.fixture(autouse=True)
def _iso(monkeypatch, tmp_path):
    for mod in (library_store, storage, songs_route, uploads, stems_route, stems_mod, spend):
        if hasattr(mod, "settings"):
            monkeypatch.setattr(mod, "settings",
                                dataclasses.replace(mod.settings, data_dir=tmp_path))
    for t in list(threading.enumerate()):
        if t.name.startswith("ingest-") and t.is_alive():
            t.join(timeout=30)
    songs_route._INGEST_SLOTS = threading.Semaphore(songs_route.settings.max_concurrent_ingests)
    monkeypatch.setattr(songs_route, "_free_gb", lambda: 999.0)
    uploads.forget_cached_manifest()
    songs_route._PROGRESS.clear()
    stems_route._jobs.clear()
    with songs_route._CAP_LOCK:
        songs_route._RESERVED.clear()
    yield
    for t in list(threading.enumerate()):
        if t.name.startswith("ingest-") and t.is_alive():
            t.join(timeout=20)
    with songs_route._CAP_LOCK:
        songs_route._RESERVED.clear()
    songs_route._INGEST_SLOTS = threading.Semaphore(songs_route.settings.max_concurrent_ingests)
    uploads.forget_cached_manifest()


def _music(seconds=32.0, bpm=120.0) -> bytes:
    sr = 44100
    n = int(sr * seconds)
    x = np.zeros(n, dtype="float32")
    step = int(sr * 60.0 / bpm)
    click = (np.hanning(600) * np.sin(2 * np.pi * 180 * np.arange(600) / sr)).astype("float32")
    for t in range(0, n - 600, step):
        x[t:t + 600] += click
    x += np.random.default_rng(1).normal(0, 0.05, n).astype("float32")
    buf = io.BytesIO()
    sf.write(buf, x, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _post(data=None, *, who=WHO, role="vocals", drop="", name="s.mp3", disp="x", headers=APP):
    return client.post("/songs/add",
                       files={"file": (name, data if data is not None else _music())},
                       data={"uploaded_by": who, "role": role, "main_drop": drop,
                             "display_name": disp},
                       headers=headers)


@pytest.fixture
def finished_paid(monkeypatch):
    def stems(song_id, wav):
        for s in ("vocals", "drums", "bass", "other"):
            (DD() / f"{song_id}.{s}.mp3").write_bytes(b"SECRET")

    def analyze(song_id, wav):
        for suf in ("structure.json", "analysis.json"):
            (DD() / f"{song_id}.{suf}").write_text("{}")
        return {}

    monkeypatch.setattr(songs_route, "separate_stems", stems)
    monkeypatch.setattr(songs_route, "analyze_track", analyze)


def _await(sid, tries=800):
    for _ in range(tries):
        if (client.get(f"/songs/add/{sid}").json() or {}).get("done"):
            return
        time.sleep(0.02)
    raise AssertionError("the ingest never finished")


# --- the money hole ---------------------------------------------------------------------------

def test_failed_uploads_cannot_spend_without_end(monkeypatch, finished_paid):
    """A failure releases its slot (a Replicate outage must not burn somebody's five) and writes no
    row — so nothing counted it, and one uploader drove 12 paid separations for $1.44 using none of
    their quota. Money now has its own ceiling, and failures count against it."""
    for mod in (songs_route, spend):
        monkeypatch.setattr(mod, "settings",
                            dataclasses.replace(mod.settings, max_paid_upload_attempts=3))
    monkeypatch.setattr(songs_route, "analyze_track",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("replicate down")))
    accepted = 0
    for i in range(10):
        r = _post(_music(bpm=100 + i))
        if r.status_code == 200:
            accepted += 1
            _await(r.json()["song_id"])
    assert accepted <= 3, f"{accepted} paid attempts against a budget of 3"
    assert spend.attempts() <= 3


def test_the_budget_survives_a_restart():
    """Money already sent to Replicate is not undone by restarting the engine."""
    spend.record_attempt("a" * 64, WHO)
    spend.record_attempt("b" * 64, WHO)
    assert spend.attempts() == 2
    assert json.loads(spend._path().read_text(encoding="utf-8"))["paid_attempts"] == 2


def test_an_unreadable_spend_record_refuses_rather_than_assuming_zero():
    """If we cannot tell how much has been spent, refusing is recoverable and guessing zero is not."""
    spend._path().parent.mkdir(parents=True, exist_ok=True)
    spend._path().write_text("{ not json", encoding="utf-8")
    assert spend.remaining() == 0
    with pytest.raises(spend.BudgetSpent):
        spend.check_budget()


def test_a_spent_budget_refuses_everybody_with_a_plain_reason(monkeypatch):
    for mod in (songs_route, spend):
        monkeypatch.setattr(mod, "settings",
                            dataclasses.replace(mod.settings, max_paid_upload_attempts=0))
    r = _post()
    assert r.status_code == 429
    assert "paused" in r.json()["detail"].lower()
    assert "nothing is lost" in r.json()["detail"].lower()


# --- the lock that failed open ------------------------------------------------------------------

def test_the_stem_guard_fails_closed_when_the_catalogue_cannot_be_read():
    sid = "a" * 64
    library_store.upsert("someone's track", sid, "vocals", "english", extra={"uploaded_by": WHO})
    for s in ("vocals", "drums", "bass", "other"):
        (DD() / f"{sid}.{s}.mp3").write_bytes(b"SECRET")
    (DD() / f"{sid}.wav").write_bytes(b"x")
    uploads.forget_cached_manifest()
    assert client.get(f"/songs/{sid}/stems/vocals").status_code == 403

    library_store.manifest_path().write_text("{ not json", encoding="utf-8")
    uploads.forget_cached_manifest()
    assert client.get(f"/songs/{sid}/stems/vocals").status_code == 403, (
        "a corrupt catalogue opened the lock")
    assert client.get(f"/songs/{sid}/stems").status_code == 403


def test_an_unknown_song_is_not_handed_out_either():
    assert client.get(f"/songs/{'f' * 64}/stems/vocals").status_code in (403, 404)


def test_the_guard_covers_the_whole_paid_window(finished_paid, monkeypatch):
    """Stems land on disk minutes before the row used to be written, and for that whole window the
    guard did not exist. The row goes in FIRST now, marked pending."""
    seen = {}

    def stems(song_id, wav):
        seen["locked"] = client.get(f"/songs/{song_id}/stems/vocals").status_code
        for s in ("vocals", "drums", "bass", "other"):
            (DD() / f"{song_id}.{s}.mp3").write_bytes(b"SECRET")

    monkeypatch.setattr(songs_route, "separate_stems", stems)
    _await(_post().json()["song_id"])
    assert seen["locked"] == 403, "an upload's stems were downloadable while it was being made"


def test_a_pending_song_is_not_advertised_as_catalogue(finished_paid, monkeypatch):
    seen = {}

    def stems(song_id, wav):
        seen["listed"] = [s["id"] for s in client.get("/library").json()["songs"]]
        for s in ("vocals", "drums", "bass", "other"):
            (DD() / f"{song_id}.{s}.mp3").write_bytes(b"s")

    monkeypatch.setattr(songs_route, "separate_stems", stems)
    sid = _post().json()["song_id"]
    _await(sid)
    assert sid not in seen["listed"]


def test_a_failed_upload_leaves_no_pending_row_behind(finished_paid, monkeypatch):
    monkeypatch.setattr(songs_route, "analyze_track",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    sid = _post().json()["song_id"]
    _await(sid)
    assert not any(r["song_id"] == sid for r in library_store.load())


# --- serving the whole song ---------------------------------------------------------------------

def test_uploads_are_never_in_the_shared_catalogue(finished_paid):
    """`GET /library` is unauthenticated. Publishing every member's unreleased track on it was half
    the leak; the other half was serving the whole song."""
    sid = _post().json()["song_id"]
    _await(sid)
    assert sid not in [s["id"] for s in client.get("/library").json()["songs"]]


def test_the_whole_uploaded_song_is_never_served(finished_paid):
    sid = _post().json()["song_id"]
    _await(sid)
    assert client.get(f"/songs/{sid}/audio").status_code == 403


def test_a_catalogue_song_is_still_served_and_still_listed():
    sid = "c" * 64
    library_store.upsert("Levels", sid, "beat")
    (DD() / f"{sid}.wav").write_bytes(b"RIFFfake")
    uploads.forget_cached_manifest()
    assert client.get(f"/songs/{sid}/audio").status_code == 200
    assert sid in [s["id"] for s in client.get("/library").json()["songs"]]


def test_the_owner_can_still_find_their_own_songs(finished_paid):
    """They are out of the shared list, so `/mine` is the only route - it must work."""
    sid = _post().json()["song_id"]
    _await(sid)
    mine = client.get(f"/songs/mine/{WHO}").json()["songs"]
    assert [s["song_id"] for s in mine] == [sid]


# --- the sibling paid endpoint --------------------------------------------------------------------

def test_the_sibling_stems_endpoint_answers_to_the_budget(monkeypatch):
    """Unauthenticated, uncapped, and it accepted upload ids: you could not download somebody's
    stems but you could make the founder pay to regenerate them, over and over."""
    monkeypatch.setattr(spend, "settings",
                        dataclasses.replace(spend.settings, max_paid_upload_attempts=2))
    monkeypatch.setattr(stems_route, "separate_stems", lambda *a: None)
    codes = []
    for i in range(6):
        sid = f"{i:064x}"
        (DD() / f"{sid}.wav").write_bytes(b"x")
        codes.append(client.post(f"/songs/{sid}/stems", headers=APP).status_code)
    assert codes.count(202) <= 2, f"{codes.count(202)} paid splits against a budget of 2"
    assert 429 in codes


# --- my own reservation bugs ----------------------------------------------------------------------

def test_a_reservation_is_never_orphaned_when_the_ingest_cannot_start(monkeypatch, finished_paid):
    """`_rename_slot` re-keys the reservation, and the recovery path released the OLD key — so a
    failure after the rename shrank that person's five until a restart."""
    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("thread table full")

    monkeypatch.setattr(songs_route.threading, "Thread", Boom)
    with pytest.raises(Exception):
        _post()
    with songs_route._CAP_LOCK:
        assert songs_route._RESERVED == {}, f"orphaned: {songs_route._RESERVED}"


def test_two_claims_on_one_song_are_never_collapsed_into_one():
    """Renaming both onto the same key dropped one, re-opening the cap by one."""
    songs_route._claim_slot(WHO, "tok-a")
    songs_route._claim_slot("222222222222222222", "tok-b")
    a = songs_route._rename_slot("tok-a", "SID")
    b = songs_route._rename_slot("tok-b", "SID")
    with songs_route._CAP_LOCK:
        assert len(songs_route._RESERVED) == 2, "a reservation vanished"
    assert a != b
