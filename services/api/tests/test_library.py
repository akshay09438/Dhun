"""The curated song catalog: manifest-driven, read-only, never crashes the Setup screen."""

import dataclasses
import json

from fastapi.testclient import TestClient

from app import storage
from app.main import app
from app.routes import library as library_route

client = TestClient(app)

GOOD = "a" * 64
MISSING = "b" * 64


def _use_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(library_route, "settings",
                        dataclasses.replace(library_route.settings, data_dir=tmp_path))
    monkeypatch.setattr(storage, "settings",
                        dataclasses.replace(storage.settings, data_dir=tmp_path))


def _write_manifest(tmp_path, entries):
    (tmp_path / "library").mkdir(parents=True, exist_ok=True)
    (tmp_path / "library" / "manifest.json").write_text(
        json.dumps(entries), encoding="utf-8"
    )


def test_no_manifest_is_an_empty_catalog(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    r = client.get("/library")
    assert r.status_code == 200 and r.json() == {"songs": []}


def test_catalog_lists_entries_whose_audio_exists(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    (tmp_path / f"{GOOD}.wav").write_bytes(b"RIFFfake")  # the stored song audio
    _write_manifest(tmp_path, [
        {"name": "Father Ocean", "song_id": GOOD, "role_hint": "beat"},
        {"name": "Ghost Song", "song_id": MISSING},  # audio missing -> hidden
        {"name": "", "song_id": GOOD},  # malformed -> skipped
        {"name": "Evil", "song_id": "../../etc/passwd"},  # non-hex id -> skipped
    ])
    r = client.get("/library")
    assert r.status_code == 200
    songs = r.json()["songs"]
    assert len(songs) == 1
    assert songs[0]["original_name"] == "Father Ocean"
    assert songs[0]["id"] == GOOD
    assert songs[0]["url"] == f"/songs/{GOOD}/audio"
    assert songs[0]["role_hint"] == "beat"
    assert songs[0]["status"] == "ready"


def test_corrupt_manifest_degrades_to_empty(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    (tmp_path / "library").mkdir(parents=True)
    (tmp_path / "library" / "manifest.json").write_text("{not json", encoding="utf-8")
    r = client.get("/library")
    assert r.status_code == 200 and r.json() == {"songs": []}
