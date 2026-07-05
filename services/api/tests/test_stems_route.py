import dataclasses
import subprocess

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


def _make_song(tmp_path) -> str:
    sid = "a" * 64
    p = tmp_path / f"{sid}.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(p)],
        check=True, capture_output=True,
    )
    return sid


def test_make_stems_ok(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    sid = _make_song(tmp_path)

    def fake_sep(song_id, wav):
        out = {}
        for s in STEMS:
            p = stem_path(song_id, s)
            p.write_bytes(b"stemdata")
            out[s] = p
        return out

    monkeypatch.setattr(stems_route, "separate_stems", fake_sep)

    r = client.post(f"/songs/{sid}/stems")
    assert r.status_code == 200
    body = r.json()
    assert body["song_id"] == sid
    assert set(body["stems"]) == set(STEMS)

    audio = client.get(body["stems"]["vocals"])
    assert audio.status_code == 200
    assert audio.content == b"stemdata"


def test_make_stems_unknown_song(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    r = client.post("/songs/" + "a" * 64 + "/stems")
    assert r.status_code == 404


def test_make_stems_separation_error(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    sid = _make_song(tmp_path)

    def boom(song_id, wav):
        raise SeparationError("no credit")

    monkeypatch.setattr(stems_route, "separate_stems", boom)
    r = client.post(f"/songs/{sid}/stems")
    assert r.status_code == 502


def test_get_stem_validates_inputs(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    assert client.get("/songs/" + "a" * 64 + "/stems/vocals").status_code == 404   # no file
    assert client.get("/songs/deadbeef/stems/vocals").status_code == 404            # bad id
    assert client.get("/songs/" + "a" * 64 + "/stems/notastem").status_code == 404  # bad stem
