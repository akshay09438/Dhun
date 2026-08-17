"""Round three: the two ship-blockers an ordinary Discord member could reach, and the hang.

The third review split its findings by who can actually reach them. These are the ones a member
could hit with nothing but the `/add` command and a file they chose — the founder's stated bar for
what blocks a release. The rest (curl to localhost, forging `uploaded_by`, editing files on disk)
are recorded in the handoff rather than tested here, because reaching them means already being on
the machine.
"""

from __future__ import annotations

import dataclasses
import threading

import pytest
from fastapi.testclient import TestClient

from app import library_store, spend, storage
from app.main import app
from app.planner import uploads
from app.routes import songs as songs_route

client = TestClient(app)
APP = {"X-PromptDJ-App": "test"}
WHO = "123456789012345678"


@pytest.fixture(autouse=True)
def _iso(monkeypatch, tmp_path):
    for mod in (library_store, storage, songs_route, uploads, spend):
        if hasattr(mod, "settings"):
            monkeypatch.setattr(mod, "settings",
                                dataclasses.replace(mod.settings, data_dir=tmp_path))
    uploads.forget_cached_manifest()
    with songs_route._CAP_LOCK:
        songs_route._RESERVED.clear()
    yield
    for t in list(threading.enumerate()):
        if t.name.startswith("ingest-") and t.is_alive():
            t.join(timeout=20)
    with songs_route._CAP_LOCK:
        songs_route._RESERVED.clear()
    uploads.forget_cached_manifest()


# --- A1: the body reached the disk before anything measured it --------------------------------

def test_an_oversized_upload_is_refused_before_its_body_is_read():
    """Starlette spools anything over 1 MB to a TEMP FILE before the handler runs, so the streaming
    cap and the free-disk check were both applied after the bytes were already on the disk they
    exist to protect. Content-Length is checked before any parsing."""
    r = client.post("/songs/add",
                    headers={**APP, "Content-Length": str(500 * 1024 * 1024)},
                    content=b"x" * 32)
    assert r.status_code == 413
    assert "too big" in r.json()["detail"].lower()


def test_the_ceiling_leaves_room_for_a_legal_file():
    """A 30 MB file plus multipart envelope must still get through."""
    from app.main import _MAX_BODY_BYTES
    assert _MAX_BODY_BYTES > songs_route.settings.max_file_bytes
    assert _MAX_BODY_BYTES < 64 * 1024 * 1024


def test_a_normal_sized_request_is_not_blocked_by_the_ceiling():
    r = client.post("/songs/add",
                    files={"file": ("s.mp3", b"tiny")},
                    data={"uploaded_by": WHO, "role": "vocals"},
                    headers=APP)
    assert r.status_code != 413


# --- A2: the budget could be overshot ----------------------------------------------------------

def test_the_paid_ceiling_is_re_checked_before_spending_not_only_when_claiming(monkeypatch):
    """Slots are claimed while the budget still has room, then ALL of them spend. Measured at 44
    recorded attempts against a ceiling of 40. The check now runs again immediately before the
    money is spent, so a claim made in good faith cannot overshoot."""
    import inspect
    src = inspect.getsource(songs_route._ingest)
    i_check, i_record = src.index("check_budget"), src.index("record_attempt")
    assert i_check < i_record, "the budget is recorded without being re-checked first"


def test_the_re_check_actually_stops_the_spend(monkeypatch, tmp_path):
    """Not just present in the source — it must refuse."""
    for mod in (songs_route, spend):
        monkeypatch.setattr(mod, "settings",
                            dataclasses.replace(mod.settings, max_paid_upload_attempts=0))
    paid = []
    monkeypatch.setattr(songs_route, "separate_stems", lambda *a: paid.append(1))
    monkeypatch.setattr(songs_route, "analyze_track", lambda *a: paid.append(1))
    (tmp_path / f"{'a' * 64}.wav").write_bytes(b"x")
    songs_route._ingest("a" * 64, "n", "vocals", WHO, None, set(), "a" * 64)
    assert paid == [], "the paid call ran with no budget left"
    assert songs_route._PROGRESS["a" * 64]["stage"] == "failed"


def test_a_refusal_at_the_last_moment_still_frees_the_slot(monkeypatch, tmp_path):
    for mod in (songs_route, spend):
        monkeypatch.setattr(mod, "settings",
                            dataclasses.replace(mod.settings, max_paid_upload_attempts=0))
    monkeypatch.setattr(songs_route, "separate_stems", lambda *a: None)
    (tmp_path / f"{'b' * 64}.wav").write_bytes(b"x")
    with songs_route._CAP_LOCK:
        songs_route._RESERVED["b" * 64] = WHO
    songs_route._ingest("b" * 64, "n", "vocals", WHO, None, set(), "b" * 64)
    with songs_route._CAP_LOCK:
        assert songs_route._RESERVED == {}


# --- A3: a hung download held a slot forever ---------------------------------------------------

def test_the_stem_download_cannot_hang_forever():
    """`_release_slot` sits in a `finally` a stuck thread never reaches, so two hung downloads stop
    uploads for everybody until the engine is restarted."""
    import inspect

    from app.audio import stems as stems_mod
    src = inspect.getsource(stems_mod.separate_stems)
    assert "timeout=" in src, "the stem download has no timeout"
    assert stems_mod._DOWNLOAD_TIMEOUT_S > 0
