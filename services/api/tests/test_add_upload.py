"""`/songs/add` — the bring-your-own-song endpoint, and the most exposed thing in the project.

There is NO allowlist: anyone who joins the Discord can reach this, and every accepted file spends
real money on Replicate. So the tests here are mostly about REFUSING things, cheaply, with a reason
a person can act on — and about the two failure modes that would actually hurt:

  * a half-ingested song that occupies a cap slot and cannot be mixed
  * a failed upload deleting the files of a song that was already on disk

The paid calls are stubbed. What is NOT stubbed is the order things happen in, which is the whole
safety design: everything free runs first, so a podcast is refused before it costs anything.
"""

from __future__ import annotations

import dataclasses
import json
import threading

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from app import library_store, storage
from app.audio import beatcheck
from app.main import app
from app.planner import uploads
from app.routes import songs as songs_route

client = TestClient(app)


def DD():
    """The data dir as the ROUTE sees it — the fixture repoints it per test."""
    return songs_route.settings.data_dir

WHO = "123456789012345678"
OTHER = "987654321098765432"


@pytest.fixture(autouse=True)
def _iso(monkeypatch, tmp_path):
    for mod in (library_store, storage, songs_route, uploads):
        if hasattr(mod, "settings"):
            monkeypatch.setattr(mod, "settings",
                                dataclasses.replace(mod.settings, data_dir=tmp_path))
    uploads.forget_cached_manifest()
    songs_route._PROGRESS.clear()
    yield
    # WAIT FOR ANY INGEST THIS TEST STARTED. The paid half runs on a daemon thread, and several
    # tests deliberately never wait for it (they only care that the request was accepted). Left
    # running, such a thread still holds this song's `library_store.song_lock` and one of the two
    # ingest slots — and because the fixture audio is deterministic, the NEXT test uses the same
    # song id and blocks on that lock until it times out. It passed alone and failed in the full
    # suite, which is the same shape as the conftest.py incident: protection scoped to the wrong
    # lifetime. Joining here bounds every thread to the test that created it.
    for t in list(threading.enumerate()):
        if t.name.startswith("ingest-") and t.is_alive():
            t.join(timeout=20)
    uploads.forget_cached_manifest()


def _music(seconds: float = 60.0, bpm: float = 120.0) -> bytes:
    """A click track — unambiguously periodic, so it passes the beat pre-check on merit."""
    sr = 44100
    n = int(sr * seconds)
    x = np.zeros(n, dtype="float32")
    step = int(sr * 60.0 / bpm)
    click = (np.hanning(600) * np.sin(2 * np.pi * 180 * np.arange(600) / sr)).astype("float32")
    for t in range(0, n - 600, step):
        x[t:t + 600] += click
    x += np.random.default_rng(1).normal(0, 0.01, n).astype("float32")
    import io
    buf = io.BytesIO()
    sf.write(buf, x, sr, format="WAV")
    return buf.getvalue()


def _speech(seconds: float = 60.0) -> bytes:
    """Irregular bursts with pauses — a podcast, as far as the pre-check is concerned."""
    sr = 44100
    rng = np.random.default_rng(7)
    n = int(sr * seconds)
    x = np.zeros(n, dtype="float32")
    t = 0
    while t < n - sr:
        d = int(sr * rng.uniform(0.08, 0.30))
        x[t:t + d] += (rng.normal(0, 1, d) * np.hanning(d) * rng.uniform(0.3, 1.0)).astype("float32")
        t += d + int(sr * rng.uniform(0.02, 0.45))
        if rng.random() < 0.06:
            t += int(sr * rng.uniform(0.4, 1.5))
    import io
    buf = io.BytesIO()
    sf.write(buf, x / (np.max(np.abs(x)) or 1), sr, format="WAV")
    return buf.getvalue()


def _post(data: bytes = None, *, name="my song.mp3", who=WHO, role="vocals", drop="", disp=""):
    return client.post("/songs/add",
                       files={"file": (name, data if data is not None else _music(), "audio/mpeg")},
                       data={"uploaded_by": who, "role": role,
                             "main_drop": drop, "display_name": disp})


@pytest.fixture
def no_paid_calls(monkeypatch):
    """Stub the two Replicate calls, writing the files they would produce."""
    def fake_stems(song_id, wav):
        for s in ("vocals", "drums", "bass", "other"):
            (DD() / f"{song_id}.{s}.mp3").write_bytes(b"stem")

    def fake_analyze(song_id, wav):
        for suffix in ("structure.json", "analysis.json"):
            (DD() / f"{song_id}.{suffix}").write_text(json.dumps({"bpm": 120.0}))
        return {"bpm": 120.0}

    monkeypatch.setattr(songs_route, "separate_stems", fake_stems)
    monkeypatch.setattr(songs_route, "analyze_track", fake_analyze)
    return monkeypatch


def _finish(song_id: str, timeout: float = 20.0) -> dict:
    """Wait for the background half, then report what the status endpoint says."""
    import time
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        st = client.get(f"/songs/add/{song_id}").json()
        if st.get("done"):
            return st
        time.sleep(0.02)
    raise AssertionError("the ingest never finished")


# --- refusing, for free -------------------------------------------------------------------

def test_a_role_is_required():
    r = _post(role="")
    assert r.status_code == 400 and "beat or a vocal" in r.json()["detail"]


def test_a_beat_must_bring_its_drop():
    """The energy detector measured ~36% precision and Suno masters flat, so we ask instead."""
    r = _post(role="beat")
    assert r.status_code == 400 and "drop" in r.json()["detail"].lower()


def test_a_vocal_is_asked_for_nothing_extra(no_paid_calls):
    r = _post(role="vocals")
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("raw,secs", [("1:24", 84.0), ("84", 84.0), ("1:24.5", 84.5), ("0:07", 7.0)])
def test_the_drop_formats_people_actually_type(raw, secs):
    assert songs_route.parse_drop(raw) == secs


@pytest.mark.parametrize("raw", ["", "soon", "1:99", "-4", "the drop"])
def test_a_drop_we_cannot_read_is_not_guessed(raw):
    assert songs_route.parse_drop(raw) is None


def test_a_drop_past_the_end_is_refused():
    r = _post(_music(seconds=40), role="beat", drop="9:00")
    assert r.status_code == 400 and "past the end" in r.json()["detail"]


def test_only_mp3_and_m4a():
    r = _post(name="track.wav")
    assert r.status_code == 400 and "MP3" in r.json()["detail"]


def test_a_stranger_without_an_account_id_gets_nowhere():
    r = _post(who="not-an-id")
    assert r.status_code == 400


def test_too_short_and_too_long_are_both_refused():
    assert _post(_music(seconds=10)).status_code == 400
    assert _post(_music(seconds=9 * 60)).status_code == 400


def test_a_podcast_is_refused_before_anything_is_paid_for(monkeypatch):
    """THE POINT OF THE PRE-CHECK. If this ever regresses we pay Replicate for spoken word."""
    called = []
    monkeypatch.setattr(songs_route, "separate_stems", lambda *a: called.append("paid"))
    monkeypatch.setattr(songs_route, "analyze_track", lambda *a: called.append("paid"))
    r = _post(_speech())
    assert r.status_code == 400
    assert "beat" in r.json()["detail"].lower()
    assert called == [], "a podcast reached a paid call"


def test_the_bar_sits_below_every_song_in_the_catalogue():
    """Measured 2026-08-17: the weakest of 118 catalogue songs scores 0.072, a podcast 0.001. The
    bar must stay clear of real music — a false reject costs a person their upload."""
    assert beatcheck._MIN_SCORE < 0.072
    assert beatcheck._MIN_SCORE > 0.008


# --- the caps -----------------------------------------------------------------------------

def _seed(n: int, who: str = WHO):
    for i in range(n):
        library_store.upsert(f"song {i} {who}", f"{i:063x}{who[-1]}", "vocals", "english",
                             extra={"uploaded_by": who})
    uploads.forget_cached_manifest()


def test_five_each_and_then_a_plain_no(no_paid_calls):
    _seed(songs_route.settings.max_uploads_per_user)
    r = _post()
    assert r.status_code == 400
    assert "limit" in r.json()["detail"].lower()
    assert "lost" in r.json()["detail"].lower(), "the refusal should reassure, not alarm"


def test_one_persons_cap_does_not_block_somebody_else(no_paid_calls):
    _seed(songs_route.settings.max_uploads_per_user)
    assert _post(who=OTHER).status_code == 200


def test_the_shared_shelf_has_a_ceiling(no_paid_calls, monkeypatch):
    monkeypatch.setattr(songs_route, "settings",
                        dataclasses.replace(songs_route.settings, max_uploaded_songs=3))
    for i in range(3):
        library_store.upsert(f"s{i}", f"{i:064x}", "vocals", "english",
                             extra={"uploaded_by": f"9999999999999999{i}"})
    uploads.forget_cached_manifest()
    r = _post()
    assert r.status_code == 400 and "full" in r.json()["detail"]


def test_a_full_disk_refuses_rather_than_fills_up(monkeypatch):
    monkeypatch.setattr(songs_route, "_free_gb", lambda: 0.5)
    r = _post()
    assert r.status_code == 507


# --- what a finished upload leaves behind ---------------------------------------------------

def test_a_finished_upload_has_every_file_and_a_row(no_paid_calls):
    r = _post(role="beat", drop="0:30", disp="My Track")
    assert r.status_code == 200, r.text
    sid = r.json()["song_id"]
    assert _finish(sid)["stage"] == "ready"
    for p in songs_route._artifacts(sid):
        assert p.exists(), f"{p.name} missing after a 'ready' upload"
    row = next(e for e in library_store.load() if e["song_id"] == sid)
    assert row["uploaded_by"] == WHO
    assert row["main_drop"] == 30.0
    assert row["role_hint"] == "beat"
    assert row["language"] == "english", "a blank language is how 103 songs went missing"
    assert not row.get("featured"), "an upload must never displace a curated song in the dropdown"


def test_a_vocal_upload_is_written_as_vocals_not_vocal(no_paid_calls):
    """The manifest contract is beat | vocals | "". The singular silently fails the picker filter."""
    sid = _post(role="vocals").json()["song_id"]
    _finish(sid)
    row = next(e for e in library_store.load() if e["song_id"] == sid)
    assert row["role_hint"] == "vocals"


def test_the_row_is_written_last(no_paid_calls, monkeypatch):
    """A row pointing at files that do not exist is worse than no row."""
    seen = {}

    def fake_analyze(song_id, wav):
        seen["row_at_analysis"] = any(e["song_id"] == song_id for e in library_store.load())
        for suffix in ("structure.json", "analysis.json"):
            (DD() / f"{song_id}.{suffix}").write_text("{}")
        return {}

    monkeypatch.setattr(songs_route, "analyze_track", fake_analyze)
    sid = _post().json()["song_id"]
    _finish(sid)
    assert seen["row_at_analysis"] is False


# --- failing safely -------------------------------------------------------------------------

def test_a_failed_upload_leaves_no_row_and_costs_no_cap_slot(no_paid_calls, monkeypatch):
    monkeypatch.setattr(songs_route, "analyze_track",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("replicate is down")))
    sid = _post().json()["song_id"]
    st = _finish(sid)
    assert st["stage"] == "failed" and st["error"]
    assert not any(e["song_id"] == sid for e in library_store.load())
    uploads.forget_cached_manifest()
    assert uploads.count_for(WHO) == 0, "a failed attempt burned one of this person's five"


def test_a_failed_upload_cleans_up_its_own_files(no_paid_calls, monkeypatch):
    monkeypatch.setattr(songs_route, "analyze_track",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    sid = _post().json()["song_id"]
    _finish(sid)
    left = [p.name for p in songs_route._artifacts(sid) if p.exists()]
    assert left == [], f"a failed upload left {left} behind"


def test_a_failure_never_deletes_a_song_that_was_already_here(no_paid_calls, monkeypatch):
    """The dangerous one. An orphan (audio on disk, no catalogue row) re-uploaded and then failing
    must keep every file it had — deleting somebody's paid-for audio is unrecoverable."""
    data = _music()
    first = _post(data).json()["song_id"]
    _finish(first)
    for e in list(library_store.load()):  # drop the row, keep the files -> exactly an orphan
        if e["song_id"] == first:
            rows = [r for r in library_store.load() if r["song_id"] != first]
            library_store.save(rows)
    uploads.forget_cached_manifest()

    monkeypatch.setattr(songs_route, "analyze_track",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    again = _post(data).json()["song_id"]
    assert again == first
    _finish(again)
    assert (DD() / f"{first}.wav").exists(), "a failed retry deleted the original audio"
    assert (DD() / f"{first}.vocals.mp3").exists()


# --- dedupe --------------------------------------------------------------------------------

def test_the_same_song_twice_does_not_pay_twice(no_paid_calls):
    data = _music()
    sid = _post(data).json()["song_id"]
    _finish(sid)
    r2 = _post(data)
    assert r2.status_code == 200
    assert r2.json()["duplicate"] is True and r2.json()["status"] == "ready"


def test_a_half_ingested_song_is_not_mistaken_for_a_duplicate(no_paid_calls):
    """Dedupe reads the manifest ROW, not the wav. If it read the wav, this upload would be waved
    through with no stems and no analysis, and could never be mixed."""
    data = _music()
    monkeypatched = _post(data).json()["song_id"]
    _finish(monkeypatched)
    rows = [r for r in library_store.load() if r["song_id"] != monkeypatched]
    library_store.save(rows)
    uploads.forget_cached_manifest()
    r = _post(data)
    assert r.json()["duplicate"] is False, "an orphan read as a duplicate"


# --- /mine ---------------------------------------------------------------------------------

def test_mine_lists_only_your_own_songs(no_paid_calls):
    library_store.upsert("mine", "a" * 64, "vocals", "english", extra={"uploaded_by": WHO})
    library_store.upsert("theirs", "b" * 64, "vocals", "english", extra={"uploaded_by": OTHER})
    library_store.upsert("catalogue", "c" * 64, "beat")
    for sid in ("a" * 64, "b" * 64, "c" * 64):
        (DD() / f"{sid}.wav").write_bytes(b"x")
    uploads.forget_cached_manifest()
    names = [s["name"] for s in client.get(f"/songs/mine/{WHO}").json()["songs"]]
    assert names == ["mine"]


def test_mine_is_filtered_by_uploader_and_nothing_else(no_paid_calls):
    """THE ONE THAT MATTERS. A language tag hid 103 songs on 2026-08-14. An upload's language is a
    default nobody was asked for, so it must never be able to hide somebody's own song from them."""
    library_store.upsert("no language at all", "d" * 64, "vocals", "", extra={"uploaded_by": WHO})
    library_store.upsert("bollywood one", "e" * 64, "vocals", "bollywood", extra={"uploaded_by": WHO})
    for sid in ("d" * 64, "e" * 64):
        (DD() / f"{sid}.wav").write_bytes(b"x")
    uploads.forget_cached_manifest()
    got = {s["name"] for s in client.get(f"/songs/mine/{WHO}").json()["songs"]}
    assert got == {"no language at all", "bollywood one"}


def test_mine_reports_how_many_slots_are_left(no_paid_calls):
    _seed(2)
    for i in range(2):
        (DD() / f"{i:063x}{WHO[-1]}.wav").write_bytes(b"x")
    body = client.get(f"/songs/mine/{WHO}").json()
    assert body["used"] == 2 and body["limit"] == songs_route.settings.max_uploads_per_user


# --- concurrency ----------------------------------------------------------------------------

def test_only_two_paid_pipelines_run_at_once(no_paid_calls, monkeypatch):
    """Three testers uploading together must not stack GPU calls — Replicate throttles hard at a
    low balance, and a 429 there reads as 'nearly out of credit', not 'too parallel'."""
    peak = {"now": 0, "max": 0}
    lock = threading.Lock()
    gate = threading.Event()

    def slow_stems(song_id, wav):
        with lock:
            peak["now"] += 1
            peak["max"] = max(peak["max"], peak["now"])
        gate.wait(timeout=3)
        with lock:
            peak["now"] -= 1
        for s in ("vocals", "drums", "bass", "other"):
            (DD() / f"{song_id}.{s}.mp3").write_bytes(b"s")

    monkeypatch.setattr(songs_route, "separate_stems", slow_stems)
    ids = [_post(_music(bpm=100 + i), who=f"11111111111111{i:03d}").json()["song_id"]
           for i in range(4)]
    import time
    time.sleep(0.6)
    assert peak["max"] <= songs_route.settings.max_concurrent_ingests, (
        f"{peak['max']} paid pipelines ran at once, cap is {songs_route.settings.max_concurrent_ingests}")
    gate.set()
    for sid in ids:
        _finish(sid)
