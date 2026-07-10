import dataclasses
import json
import subprocess
import time

from fastapi.testclient import TestClient

from app import storage
from app.audio import analysis as an
from app.main import app
from app.routes import analysis as an_route

client = TestClient(app)


def _use_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "settings",
                        dataclasses.replace(storage.settings, data_dir=tmp_path))
    monkeypatch.setattr(an, "settings",
                        dataclasses.replace(an.settings, data_dir=tmp_path))
    monkeypatch.setattr(an_route, "_jobs", {})


def _make_song(tmp_path) -> str:
    sid = "a" * 64
    p = tmp_path / f"{sid}.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(p)],
        check=True, capture_output=True,
    )
    return sid


def _fake_result(sid):
    return {
        "song_id": sid, "bpm": 124.0, "bpm_confidence": 0.9,
        "beats": [0.5, 1.0], "downbeats": [0.5], "phrase_starts": [0.5],
        "key": {"camelot": "8A", "tonic": "A", "mode": "minor", "confidence": 0.8},
        "sections": [{"start": 0.0, "end": 1.0, "label": "verse"}],
        "sections_confidence": 0.6, "energy_curve": [1.0],
        "vocal_regions": [], "vocal_confidence": 0.3,
        "local_analysis_version": an.LOCAL_ANALYSIS_VERSION,  # a fresh cache the route serves as-is
    }


def _poll(sid, want, tries=100):
    body = {}
    for _ in range(tries):
        body = client.get(f"/songs/{sid}/analysis").json()
        if body["status"] == want:
            return body
        time.sleep(0.05)
    return body


def test_analysis_is_async_then_ready(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    sid = _make_song(tmp_path)

    def fake_analyze(song_id, wav):
        time.sleep(0.2)  # simulate the slow cloud step
        result = _fake_result(song_id)
        an.analysis_path(song_id).write_text(json.dumps(result))
        return result

    monkeypatch.setattr(an_route, "analyze_track", fake_analyze)

    r = client.post(f"/songs/{sid}/analysis")
    assert r.status_code == 202
    assert r.json()["status"] == "processing"

    body = _poll(sid, "ready")
    assert body["status"] == "ready"
    assert body["bpm"] == 124.0
    assert body["key"]["camelot"] == "8A"
    assert body["sections"][0]["label"] == "verse"


def test_analysis_cache_hit_immediate(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    sid = _make_song(tmp_path)
    an.analysis_path(sid).write_text(json.dumps(_fake_result(sid)))

    def boom(*a, **k):
        raise AssertionError("must not re-analyze a cached song")

    monkeypatch.setattr(an_route, "analyze_track", boom)

    r = client.post(f"/songs/{sid}/analysis")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


def test_analysis_error_surfaces(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    sid = _make_song(tmp_path)

    def boom(song_id, wav):
        raise an.AnalysisError("cloud down")

    monkeypatch.setattr(an_route, "analyze_track", boom)

    r = client.post(f"/songs/{sid}/analysis")
    assert r.status_code == 202
    assert _poll(sid, "error")["status"] == "error"


def test_analysis_unknown_song(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    assert client.post("/songs/" + "b" * 64 + "/analysis").status_code == 404
    assert client.get("/songs/nothex/analysis").status_code == 404
