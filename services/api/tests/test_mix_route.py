"""Tests for the mix route: the async contract, caching, preconditions, and a real
end-to-end render on synthetic songs (no cloud, no AI network — the deterministic
fallback picks the drop).
"""

import dataclasses
import json
import time

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from app import storage
from app.audio import analysis as analysis_mod
from app.audio import stems as stems_mod
from app.main import app
from app.planner import plan as plan_mod
from app.routes import mix as mix_route
from tests.test_fence import make_analysis

client = TestClient(app)

SONG1 = "a" * 64
SONG2 = "b" * 64


def _use_tmp(monkeypatch, tmp_path):
    for mod in (storage, analysis_mod, stems_mod, mix_route):
        monkeypatch.setattr(mod, "settings",
                            dataclasses.replace(mod.settings, data_dir=tmp_path))
    monkeypatch.setattr(mix_route, "_jobs", {})
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(plan_mod, "_ai_arrange", lambda opts, prompt, take: None)  # force fallback


def _tone(path, freq, secs=6.0, sr=44100):
    t = np.linspace(0, secs, int(sr * secs), endpoint=False)
    sf.write(path, (0.4 * np.sin(2 * np.pi * freq * t)).astype("float32"), sr, format="WAV")


def _write_analysis(tmp_path, sid, bpm, vocal_regions):
    d = make_analysis(bpm=bpm, vocal_regions=vocal_regions).model_dump(exclude={"status"})
    d["song_id"] = sid
    (tmp_path / f"{sid}.analysis.json").write_text(json.dumps(d))


def _setup_pair(tmp_path, song2_bpm=118.0):
    # uploaded songs
    _tone(tmp_path / f"{SONG1}.wav", 200.0)
    _tone(tmp_path / f"{SONG2}.wav", 300.0)
    # analyses (Song 1 sings a substantial passage 20-62s so it LEADS in a gap — both vocals trade)
    _write_analysis(tmp_path, SONG1, 120.0, [(20.0, 62.0)])
    _write_analysis(tmp_path, SONG2, song2_bpm, [(0.0, 4.0)])
    # stems (WAV content in .mp3-named files, as the real cache stores)
    for name, f in (("drums", 110.0), ("bass", 55.0), ("other", 330.0), ("vocals", 660.0)):
        _tone(tmp_path / f"{SONG1}.{name}.mp3", f)  # Song 1's own vocals feed the contrast move
    _tone(tmp_path / f"{SONG2}.vocals.mp3", 440.0)


def _poll(mix_id, want, tries=240):
    body = {}
    for _ in range(tries):
        body = client.get(f"/mix/{mix_id}").json()
        if body["status"] == want:
            return body
        time.sleep(0.05)
    return body


def test_mix_is_async_then_ready_and_plays(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _setup_pair(tmp_path)

    r = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2})
    assert r.status_code == 202
    assert r.json()["status"] == "processing"  # returned at once, not blocked

    mix_id = r.json()["mix_id"]
    ready = _poll(mix_id, "ready")
    assert ready["status"] == "ready"
    assert ready["plan"]["source"] == "rules"
    assert ready["url"] == f"/mix/{mix_id}/audio"

    audio = client.get(ready["url"])
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/wav"
    assert len(audio.content) > 1000  # a real WAV, not empty


def test_mix_is_cached(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _setup_pair(tmp_path)
    mix_id = mix_route.mix_id_for(SONG1, SONG2, "")
    r1 = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2})
    _poll(mix_id, "ready")

    # second identical request must be an instant cache hit (200, ready)
    r2 = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2})
    assert r2.status_code == 200
    assert r2.json()["status"] == "ready"


def test_mix_blocks_when_not_analyzed(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _tone(tmp_path / f"{SONG1}.wav", 200.0)
    _tone(tmp_path / f"{SONG2}.wav", 300.0)  # uploaded but not analyzed/split

    r = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2})
    assert r.status_code == 409
    assert "analyzed" in r.json()["detail"].lower()


def test_mix_declines_far_tempo_with_reason(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _setup_pair(tmp_path, song2_bpm=150.0)  # too far to blend cleanly

    r = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2})
    assert r.status_code == 202
    body = _poll(r.json()["mix_id"], "error")
    assert body["status"] == "error"
    assert "tempo" in body["message"].lower()


def test_mix_carries_contrast(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _setup_pair(tmp_path)
    r = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2})
    body = _poll(r.json()["mix_id"], "ready")
    assert body["status"] == "ready"
    assert body["plan"]["s1_vocal_regions"]  # Song 1's own vocal answers (contrast) flows through


def test_regenerate_is_a_distinct_cached_take(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _setup_pair(tmp_path)
    r1 = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2, "take": 1})
    r2 = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2, "take": 2})
    assert r1.json()["mix_id"] != r2.json()["mix_id"]  # different take -> different cache slot


def test_mix_rejects_bad_song_id(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    assert client.post("/mix", json={"song1_id": "nothex", "song2_id": SONG2}).status_code == 404
    assert client.get("/mix/deadbeef").status_code == 404
    assert client.get("/mix/" + "a" * 64 + "/audio").status_code == 404


def test_engine_version_is_current():
    # bumped when the engine/plan changes so a stale cached mix is never served
    assert mix_route.ENGINE_VERSION == "m5k.0"  # Step 3 Wave 2: drop-to-just-the-beat + held-silent bass
