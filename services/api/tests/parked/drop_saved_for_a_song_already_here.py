"""A drop typed for a song the app already has must be saved, not silently binned.

THE BUG, IN ONE SENTENCE. `POST /songs/add` dedupes on the manifest ROW and returns as soon as it
recognises the song — which is right, and is why re-adding costs nobody a slot or a penny — but it
returned BEFORE `main_drop` was ever written. So somebody who re-attached their own beat, was asked
where the drop hits, and answered, had their answer thrown away with nothing on screen saying so.

IT BIT THE FOUNDER FIRST, which is how it was found. Both of their own uploads are stored as
`vocals` with NO drop, because until 2026-08-18 declaring a beat forced you to supply a drop and
declaring a vocal did not — so the fastest route past a question the app should not have been
asking was to call every song a vocal. The moment they used the new `/grind my_beat:` on either
one, they were standing on this.

The first test below is the founder's exact sequence.
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
from app.main import app
from app.planner import uploads
from app.routes import songs as songs_route
from app.routes import stems as stems_route

client = TestClient(app)
WHO = "111222333444555666"     # its own account, so nothing here can fill another file's quota
SOMEBODY_ELSE = "987654321098765432"


def DD():
    return songs_route.settings.data_dir


@pytest.fixture(autouse=True)
def _iso(monkeypatch, tmp_path):
    for mod in (library_store, storage, songs_route, uploads, stems_route):
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


def _music(seconds=31.0, bpm=128.0) -> bytes:
    """DELIBERATELY NOT the same audio the other upload test files generate.

    They use bpm=120, 32.0s and rng seed 1; identical parameters produce identical BYTES, and a
    song's id is the hash of those bytes - so this file's song and theirs were literally the same
    song, sharing every id-keyed structure in the process. Changing the seed and the tempo gives
    this file a song of its own.
    """
    sr = 44100
    n = int(sr * seconds)
    x = np.zeros(n, dtype="float32")
    step = int(sr * 60.0 / bpm)
    click = (np.hanning(600) * np.sin(2 * np.pi * 180 * np.arange(600) / sr)).astype("float32")
    for t in range(0, n - 600, step):
        x[t:t + 600] += click
    x += np.random.default_rng(20260818).normal(0, 0.05, n).astype("float32")
    buf = io.BytesIO()
    sf.write(buf, x, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


AUDIO = _music()

# THE FIXTURE IS 32 SECONDS, AND THAT ALREADY MADE ONE ROUND OF THESE TESTS WORTHLESS. A
# realistic-looking "1:24" is PAST THE END of the test audio, so the route refused it with a 400
# long before reaching the branch under test - six tests went red for a reason that had nothing to
# do with the bug, which looks exactly like proof and is not. The drop has to sit inside the song.
DROP = "0:20"
DROP_SECS = 20.0


def _post(*, who=WHO, role="vocals", drop="", name="s.mp3", disp="My Track"):
    return client.post("/songs/add",
                       files={"file": (name, AUDIO)},
                       data={"uploaded_by": who, "role": role,
                             "main_drop": drop, "display_name": disp},
                       headers={"X-PromptDJ-App": "test"})


@pytest.fixture
def no_paid_calls(monkeypatch):
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
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        st = client.get(f"/songs/add/{song_id}").json()
        if st.get("done"):
            return st
        time.sleep(0.02)
    raise AssertionError("the ingest never finished")


def _row(song_id):
    return next(e for e in library_store.load() if e["song_id"] == song_id)


def _in_as_a_vocal_with_no_drop():
    """The founder's starting state: the song is here, as a vocal, with no drop recorded."""
    first = _post(role="vocals", drop="")
    assert first.status_code == 200, first.text
    sid = first.json()["song_id"]
    assert _finish(sid)["stage"] == "ready"
    assert _row(sid).get("main_drop") is None, "the setup is wrong - it already had a drop"
    return sid


def test_a_drop_typed_for_a_song_already_here_is_saved(no_paid_calls, monkeypatch):
    """THE FOUNDER'S EXACT SEQUENCE, and the whole point of the change.

    Red before the fix: main_drop stayed None, because the route returns as soon as it recognises
    the song and that return came BEFORE the drop was ever written."""
    sid = _in_as_a_vocal_with_no_drop()

    paid = []
    monkeypatch.setattr(songs_route, "separate_stems", lambda *a: paid.append("stems"))
    monkeypatch.setattr(songs_route, "analyze_track", lambda *a: paid.append("analysis"))

    second = _post(role="beat", drop=DROP)
    assert second.status_code == 200, second.text
    assert second.json()["duplicate"] is True, "the setup is wrong - it was not recognised"
    assert _row(sid)["main_drop"] == DROP_SECS,         "the drop was typed, accepted, and thrown away without a word"

    # AND IT IS STILL FREE. The early return exists so a duplicate costs nobody a slot or a penny;
    # recording the drop must not have bought that back at the price of paying twice.
    time.sleep(0.2)
    assert paid == [], f"a duplicate started paid work: {paid}"


def test_a_re_upload_changes_the_drop_and_absolutely_nothing_else(no_paid_calls):
    """Every guard in one place, over ONE ingest.

    Deliberately not six separate tests: each one would need its own real ingest, and six more of
    those measurably tipped an already-loaded machine into unrelated timeouts elsewhere in the
    suite. The assertions are what matter, not the test count."""
    first = _post(role="vocals", drop="", disp="The Original Name")
    sid = first.json()["song_id"]
    _finish(sid)
    before = dict(_row(sid))

    # A VOCAL IS NEVER GIVEN A DROP. It is never asked for one either.
    _post(role="vocals", drop=DROP)
    assert _row(sid).get("main_drop") is None, "a vocal was given a drop"

    # A STRANGER CANNOT MOVE YOUR DROP. A song is recognised by its SOUND, so two people really can
    # land on the same row - sending the same bytes must not hand over the controls.
    _post(role="beat", drop=DROP, who=SOMEBODY_ELSE)
    assert _row(sid).get("main_drop") is None, "a stranger rewrote the drop on a row they do not own"

    # AN UNREADABLE TIME NEVER REACHES THE ROW - it is refused before the song is even stored.
    refused = _post(role="beat", drop="whenever")
    assert refused.status_code == 400, "a beat with an unreadable drop was accepted"
    assert _row(sid).get("main_drop") is None, "a refused upload still moved the row"

    # AND THE OWNER'S REAL DROP DOES land - while everything else stays exactly as it was.
    _post(role="beat", drop=DROP, disp="A Different Name")
    after = _row(sid)
    assert after["main_drop"] == DROP_SECS, "the one field that SHOULD change did not"
    assert after["name"] == before["name"], "the name was overwritten by a re-upload"
    assert after["uploaded_by"] == before["uploaded_by"], "ownership moved"
    assert after["role_hint"] == before["role_hint"], "the role was silently changed"
    assert after["language"] == before["language"]
