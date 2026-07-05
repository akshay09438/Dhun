import dataclasses
import io
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app import storage
from app.main import app
from app.routes import songs as songs_mod

client = TestClient(app)


def _audio_bytes(tmp_path: Path, name: str) -> bytes:
    p = tmp_path / name
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=1",
         "-ar", "22050", "-ac", "1", str(p)],
        check=True, capture_output=True,
    )
    return p.read_bytes()


def _use_tmp_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "settings",
                        dataclasses.replace(storage.settings, data_dir=tmp_path))


def test_upload_two_songs_ok(tmp_path, monkeypatch):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    a = _audio_bytes(tmp_path, "a.wav")
    b = _audio_bytes(tmp_path, "b.wav")

    r = client.post("/songs", files={
        "song1": ("a.wav", io.BytesIO(a), "audio/wav"),
        "song2": ("b.wav", io.BytesIO(b), "audio/wav"),
    })

    assert r.status_code == 200
    songs = r.json()["songs"]
    assert len(songs) == 2
    assert all(s["id"] and s["url"] for s in songs)

    audio = client.get(songs[0]["url"])
    assert audio.status_code == 200
    assert audio.content[:4] == b"RIFF"  # WAV header


def test_reject_non_audio():
    r = client.post("/songs", files={
        "song1": ("x.txt", io.BytesIO(b"hello"), "text/plain"),
        "song2": ("y.txt", io.BytesIO(b"hi"), "text/plain"),
    })
    assert r.status_code == 400


def test_unknown_audio_id_404():
    r = client.get("/songs/" + "a" * 64 + "/audio")
    assert r.status_code == 404


def test_bad_id_rejected():
    # non-hex id must not reach the filesystem
    assert client.get("/songs/deadbeef/audio").status_code == 404


def test_oversize_rejected(tmp_path, monkeypatch):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(songs_mod, "settings",
                        dataclasses.replace(songs_mod.settings, max_file_bytes=10))
    a = _audio_bytes(tmp_path, "a.wav")
    b = _audio_bytes(tmp_path, "b.wav")

    r = client.post("/songs", files={
        "song1": ("a.wav", io.BytesIO(a), "audio/wav"),
        "song2": ("b.wav", io.BytesIO(b), "audio/wav"),
    })
    assert r.status_code == 400
