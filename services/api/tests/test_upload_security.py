"""One test per finding from the 2026-08-17 adversarial security review.

Every one of these FAILED against the code as first shipped. They are kept together, named after
the attack rather than the fix, so a later reader can see what was actually possible — the review
found the caps were decorative and the engine had no door on it, and neither was obvious from
reading the code that had just passed 911 other tests.
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

from app import library_store, storage
from app.audio import beatcheck
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
    for mod in (library_store, storage, songs_route, uploads, stems_route, stems_mod):
        if hasattr(mod, "settings"):
            monkeypatch.setattr(mod, "settings",
                                dataclasses.replace(mod.settings, data_dir=tmp_path))
    # START CLEAN, not just finish clean. An ingest thread leaked by an EARLIER TEST FILE still
    # holds one of the two shared slots, and two of those starve every test here - which is exactly
    # how this file passed alone and failed in the full suite.
    for t in list(threading.enumerate()):
        if t.name.startswith("ingest-") and t.is_alive():
            t.join(timeout=30)
    songs_route._INGEST_SLOTS = threading.Semaphore(songs_route.settings.max_concurrent_ingests)
    # THE DISK CHECK IS STUBBED for every test except the one that is about it. Otherwise the
    # suite passes or fails on how full the laptop happens to be: at 2.13 GB free the
    # endpoint correctly answered 507 and twelve unrelated tests went red. A test should
    # exercise the logic, not the machine.
    monkeypatch.setattr(songs_route, "_free_gb", lambda: 999.0)
    uploads.forget_cached_manifest()
    songs_route._PROGRESS.clear()
    with songs_route._CAP_LOCK:
        songs_route._RESERVED.clear()
    yield
    for t in list(threading.enumerate()):
        if t.name.startswith("ingest-") and t.is_alive():
            t.join(timeout=20)
    with songs_route._CAP_LOCK:
        songs_route._RESERVED.clear()
    # A fresh semaphore, so an ingest thread that outlived its test cannot hold a slot and starve
    # every test after it - the same wrong-lifetime trap conftest.py documents.
    songs_route._INGEST_SLOTS = threading.Semaphore(songs_route.settings.max_concurrent_ingests)
    uploads.forget_cached_manifest()


def _music(seconds=32.0, bpm=120.0) -> bytes:
    # SHORT and 16-BIT on purpose. These get stored on disk once per upload, and at 60s of
    # 32-bit float that is ~10 MB a time - a full suite run left 3.3 GB of pytest temp
    # behind and took the machine to 0.63 GB free. Just over the 30s minimum, PCM_16.
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
def slow_paid(monkeypatch):
    """Stem separation that is still RUNNING while the test makes its next request.

    Deterministic rather than timed. The original cap test passed only because the stub finished
    instantly, which closed the very window the attack uses - so this one blocks on an event the
    fixture releases at teardown, and the "still in flight" state is guaranteed rather than raced.
    """
    release = threading.Event()

    def stems(song_id, wav):
        release.wait(timeout=30)
        for s in ("vocals", "drums", "bass", "other"):
            (DD() / f"{song_id}.{s}.mp3").write_bytes(b"s")

    def analyze(song_id, wav):
        for suf in ("structure.json", "analysis.json"):
            (DD() / f"{song_id}.{suf}").write_text("{}")
        return {}

    monkeypatch.setattr(songs_route, "separate_stems", stems)
    monkeypatch.setattr(songs_route, "analyze_track", analyze)
    yield release
    release.set()


@pytest.fixture
def finished_paid(monkeypatch):
    """The paid half, stubbed and instant - for tests about what a COMPLETED upload leaves."""
    def stems(song_id, wav):
        for s in ("vocals", "drums", "bass", "other"):
            (DD() / f"{song_id}.{s}.mp3").write_bytes(b"s")

    def analyze(song_id, wav):
        for suf in ("structure.json", "analysis.json"):
            (DD() / f"{song_id}.{suf}").write_text("{}")
        return {}

    monkeypatch.setattr(songs_route, "separate_stems", stems)
    monkeypatch.setattr(songs_route, "analyze_track", analyze)


# --- F1: the caps were decorative ------------------------------------------------------------

def test_the_per_person_cap_holds_while_uploads_are_still_running(slow_paid):
    """THE CRITICAL ONE. Counting finished rows caps nothing: a row appears only when the paid
    work ends, minutes later, so 30 uploads from one person against a cap of 5 were all accepted
    in 19 seconds (~$3.60 of Replicate committed). A slot is now RESERVED before the file is read."""
    accepted = sum(1 for i in range(15)
                   if _post(_music(bpm=100 + i)).status_code == 200)
    assert accepted == songs_route.settings.max_uploads_per_user, (
        f"{accepted} uploads accepted against a cap of "
        f"{songs_route.settings.max_uploads_per_user}")


def test_the_cap_holds_under_a_burst_of_simultaneous_requests(slow_paid):
    """The same hole reached concurrently rather than in a loop."""
    got = []
    lock = threading.Lock()

    def fire(i):
        r = _post(_music(bpm=100 + i))
        with lock:
            got.append(r.status_code)

    ts = [threading.Thread(target=fire, args=(i,)) for i in range(12)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=60)
    assert got.count(200) <= songs_route.settings.max_uploads_per_user


def test_a_refused_upload_gives_its_slot_straight_back(slow_paid):
    """A rejection must not quietly consume one of somebody's five."""
    assert _post(_music(seconds=5)).status_code == 400        # too short
    assert _post(_music(seconds=5), role="").status_code == 400
    assert _post().status_code == 200, "earlier refusals ate the person's slots"


def test_a_failed_ingest_gives_its_slot_back(monkeypatch, finished_paid):
    monkeypatch.setattr(songs_route, "analyze_track",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("replicate down")))
    sid = _post().json()["song_id"]
    for _ in range(400):
        if (client.get(f"/songs/add/{sid}").json() or {}).get("done"):
            break
        time.sleep(0.05)
    with songs_route._CAP_LOCK:
        assert songs_route._RESERVED == {}, "a failed upload leaked a slot forever"


# --- F2: the engine had no door on it --------------------------------------------------------

def test_a_page_that_is_not_the_app_cannot_post():
    """CORS withholds the RESPONSE; it does not stop the request running, and a multipart POST is
    safelisted so it gets no preflight. Any page open in a browser on this machine could drive the
    paid endpoint with a forged uploader. A custom header cannot be set cross-origin without a
    preflight, and that preflight is refused."""
    r = _post(headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert "did not come from the app" in r.json()["detail"]


def test_the_guard_covers_every_mutating_route_not_just_uploads():
    r = client.post("/mix", json={"song1_id": "a" * 64, "song2_id": "b" * 64},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_reading_is_still_open_so_audio_and_the_dashboard_work():
    assert client.get("/health").status_code == 200
    assert client.get("/library").status_code == 200


def test_the_app_itself_is_let_through_from_its_own_page(finished_paid):
    """The web app sends the header, so a same-origin page keeps working."""
    r = _post(headers={**APP, "Origin": "http://localhost:5173"})
    assert r.status_code == 200


def test_a_non_browser_caller_is_not_blocked(finished_paid):
    """The bot, curl and the test suite send no Origin. Demanding the header from them buys
    nothing - anything that is not a browser can set any header it likes - and would break every
    non-browser caller."""
    r = _post(headers={})
    assert r.status_code == 200


# --- F3 / F4: two people, the same song, seconds apart ---------------------------------------

def test_a_second_upload_of_the_same_song_cannot_take_over_the_first_ones_row(finished_paid):
    data = _music()
    a = _post(data, who=WHO, disp="A's copy")
    b = _post(data, who="222222222222222222", disp="B's copy")
    assert a.status_code == 200 and b.status_code == 200
    for t in list(threading.enumerate()):
        if t.name.startswith("ingest-"):
            t.join(timeout=30)
    rows = [r for r in library_store.load() if r["song_id"] == a.json()["song_id"]]
    assert len(rows) == 1
    assert rows[0]["uploaded_by"] == WHO, "the second uploader took over the first one's song"
    assert rows[0]["name"] == "A's copy"


def test_a_second_upload_failing_cannot_delete_the_first_ones_paid_stems(monkeypatch, finished_paid):
    """The worst one. B's failure used a snapshot taken at REQUEST time, so it deleted the stems A
    had just paid for and left A's row pointing at missing files."""
    data = _music()
    a = _post(data, who=WHO)
    sid = a.json()["song_id"]
    for _ in range(600):
        if (client.get(f"/songs/add/{sid}").json() or {}).get("done"):
            break
        time.sleep(0.05)
    monkeypatch.setattr(songs_route, "analyze_track",
                        lambda *x: (_ for _ in ()).throw(RuntimeError("boom")))
    b = _post(data, who="222222222222222222")
    assert b.status_code == 200 and b.json().get("duplicate") is True, (
        "the second upload did not recognise a song that is already in the catalogue")
    for p in songs_route._artifacts(sid):
        assert p.exists(), f"{p.name} was deleted by somebody else's failed upload"


# --- F5: 14 MB in, 2.5 GB on disk ------------------------------------------------------------

def test_length_is_checked_before_the_file_is_expanded(monkeypatch):
    """The duration limit ran AFTER normalising, so a 4-hour 8 kbps MP3 was already a 2.5 GB WAV
    on disk by the time it was refused — one request could take the machine under its disk floor
    and make the cleaner delete other people's finished mixes."""
    seen = {}
    monkeypatch.setattr(songs_route, "probe_seconds", lambda p: 4 * 3600.0)

    def must_not_run(*a, **k):
        seen["decoded"] = True

    monkeypatch.setattr(songs_route, "normalize_audio", must_not_run)
    r = _post()
    assert r.status_code == 400 and "8 minutes" in r.json()["detail"]
    assert "decoded" not in seen, "the file was decoded before its length was checked"


def test_the_decode_itself_is_capped_in_case_the_header_lies(monkeypatch):
    """The probe reads the file's OWN claim, which a hostile file can fake."""
    got = {}

    def spy(src, dst, max_seconds=None):
        got["max_seconds"] = max_seconds
        raise songs_route.AudioError("stop")

    monkeypatch.setattr(songs_route, "probe_seconds", lambda p: 0.0)   # header says nothing
    monkeypatch.setattr(songs_route, "normalize_audio", spy)
    _post()
    assert got["max_seconds"], "the decode was left uncapped"
    assert got["max_seconds"] <= songs_route.settings.max_upload_seconds + 60


# --- F6: the pre-check was beaten by silence with a tick -------------------------------------

def _ticker(seconds=32.0) -> bytes:
    """Perfectly periodic, almost entirely silent, and a few tens of KB — the ideal payload."""
    sr = 44100
    n = int(sr * seconds)
    x = np.zeros(n, dtype="float32")
    tick = (np.hanning(200) * np.sin(2 * np.pi * 1000 * np.arange(200) / sr)).astype("float32")
    for t in range(0, n - 200, int(sr * 0.5)):
        x[t:t + 200] += tick
    buf = io.BytesIO()
    sf.write(buf, x, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def test_a_ticker_over_silence_never_reaches_a_paid_call(monkeypatch):
    paid = []
    monkeypatch.setattr(songs_route, "separate_stems", lambda *a: paid.append(1))
    monkeypatch.setattr(songs_route, "analyze_track", lambda *a: paid.append(1))
    r = _post(_ticker())
    assert r.status_code == 400
    assert paid == [], "a tick over silence reached the paid pipeline"


def test_the_density_bar_sits_far_below_real_music():
    """Measured over all 118 catalogue songs: weakest 0.909, the attack 0.040."""
    assert beatcheck._MIN_ACTIVITY < 0.909
    assert beatcheck._MIN_ACTIVITY > 0.040


# --- F7: NaN in the catalogue index, and a nameless song -------------------------------------

@pytest.mark.parametrize("raw", ["0:nan", "nan", "inf", "-inf", "1e400", "0:inf"])
def test_a_drop_that_is_not_a_number_is_refused(raw):
    """Every comparison against NaN is False, so "0:nan" walked through both range checks and
    `json.dump` wrote a literal NaN into the manifest indexing all 118 catalogue songs. Python
    reads that back happily; no other tool will."""
    assert songs_route.parse_drop(raw) is None


def test_the_catalogue_index_stays_valid_json_after_an_upload(finished_paid):
    sid = _post(role="beat", drop="0:30").json()["song_id"]
    for _ in range(600):
        if (client.get(f"/songs/add/{sid}").json() or {}).get("done"):
            break
        time.sleep(0.05)
    raw = library_store.manifest_path().read_text(encoding="utf-8")
    json.loads(raw)                                   # Python is tolerant...
    assert "NaN" not in raw and "Infinity" not in raw  # ...every other reader is not


def test_a_song_can_never_be_stored_with_no_name(finished_paid):
    """A blank name is dropped by GET /library, so the song would be paid for, hold a slot, and be
    invisible everywhere — the 2026-08-14 failure, reachable via an attachment called " .mp3"."""
    r = _post(disp="   ", name="   .mp3")
    assert r.status_code == 200
    assert r.json()["name"].strip(), "a nameless song was accepted"


# --- the two lockdowns ------------------------------------------------------------------------

def test_an_uploaded_songs_stems_are_never_served():
    """Somebody's unreleased track, pulled apart, downloadable by anyone with the id. Stem
    redistribution is an explicit product non-goal."""
    sid = "a" * 64
    library_store.upsert("someone's track", sid, "vocals", "english",
                         extra={"uploaded_by": WHO})
    for s in ("vocals", "drums", "bass", "other"):
        (DD() / f"{sid}.{s}.mp3").write_bytes(b"audio")
    uploads.forget_cached_manifest()
    assert client.get(f"/songs/{sid}/stems/vocals").status_code == 403


def test_a_catalogue_songs_stems_still_serve_so_the_console_works():
    sid = "b" * 64
    library_store.upsert("Levels", sid, "beat")
    for s in ("vocals", "drums", "bass", "other"):
        (DD() / f"{sid}.{s}.mp3").write_bytes(b"audio")
    uploads.forget_cached_manifest()
    assert client.get(f"/songs/{sid}/stems/vocals").status_code == 200
