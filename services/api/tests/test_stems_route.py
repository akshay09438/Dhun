import dataclasses
import subprocess
import time

from fastapi.testclient import TestClient

from app import storage
from app.audio import stems as stems_mod
from app.audio.stems import STEMS, SeparationError, stem_path
from app.main import app
from app.routes import stems as stems_route

client = TestClient(app)


def _use_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "settings",
                        dataclasses.replace(storage.settings, data_dir=tmp_path))
    monkeypatch.setattr(stems_mod, "settings",
                        dataclasses.replace(stems_mod.settings, data_dir=tmp_path))
    # a fresh, empty job registry per test
    monkeypatch.setattr(stems_route, "_jobs", {})


def _make_song(tmp_path) -> str:
    sid = "a" * 64
    p = tmp_path / f"{sid}.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(p)],
        check=True, capture_output=True,
    )
    return sid


def _write_all_stems(song_id):
    for s in STEMS:
        stem_path(song_id, s).write_bytes(b"stemdata")


def _poll(sid, want, tries=100):
    body = {}
    for _ in range(tries):
        body = client.get(f"/songs/{sid}/stems").json()
        if body["status"] == want:
            return body
        time.sleep(0.05)
    return body


def test_split_is_async_returns_processing_then_ready(tmp_path, monkeypatch):
    """POST must NOT block for the whole (slow) split — it returns 'processing'
    immediately, and the stems appear via polling once the job finishes."""
    _use_tmp(monkeypatch, tmp_path)
    sid = _make_song(tmp_path)

    def fake_sep(song_id, wav):
        time.sleep(0.2)  # simulate a slow cloud split
        out = {}
        for s in STEMS:
            p = stem_path(song_id, s)
            p.write_bytes(b"stemdata")
            out[s] = p
        return out

    monkeypatch.setattr(stems_route, "separate_stems", fake_sep)

    r = client.post(f"/songs/{sid}/stems")
    assert r.status_code == 202
    assert r.json()["status"] == "processing"       # returned immediately, not blocked

    ready = _poll(sid, "ready")
    assert ready["status"] == "ready"
    assert set(ready["stems"]) == set(STEMS)

    audio = client.get(ready["stems"]["vocals"])
    assert audio.status_code == 200
    assert audio.content == b"stemdata"


def test_split_cache_hit_is_ready_immediately(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    sid = _make_song(tmp_path)
    _write_all_stems(sid)

    def boom(*a, **k):
        raise AssertionError("must not split again on a cache hit")

    monkeypatch.setattr(stems_route, "separate_stems", boom)

    r = client.post(f"/songs/{sid}/stems")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert set(body["stems"]) == set(STEMS)


def test_split_unknown_song(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    r = client.post("/songs/" + "a" * 64 + "/stems")
    assert r.status_code == 404


def test_split_error_surfaces_as_status(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    sid = _make_song(tmp_path)

    def boom(song_id, wav):
        raise SeparationError("no credit")

    monkeypatch.setattr(stems_route, "separate_stems", boom)

    r = client.post(f"/songs/{sid}/stems")
    assert r.status_code == 202
    body = _poll(sid, "error")
    assert body["status"] == "error"


def test_get_stem_validates_inputs(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    assert client.get("/songs/" + "a" * 64 + "/stems/vocals").status_code == 404   # no file
    assert client.get("/songs/deadbeef/stems/vocals").status_code == 404            # bad id
    assert client.get("/songs/" + "a" * 64 + "/stems/notastem").status_code == 404  # bad stem
