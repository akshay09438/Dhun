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

    # 3.1 (set transitions): the persisted plan carries the mix's OWN beat grid + length, so a set-join
    # is arithmetic over the plans (no re-analysis of the WAV).
    plan = ready["plan"]
    assert plan["out_downbeats"], "the mix's output-time downbeats must be persisted on the plan"
    assert plan["mix_duration"] and plan["mix_duration"] > 0
    assert plan["out_downbeats"][0] >= 0.0
    assert set(plan["out_phrase_starts"]) <= set(plan["out_downbeats"])  # phrase boundaries are downbeats


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
    assert mix_route.ENGINE_VERSION == "m6.5"  # m6.5: Phase-0 vocal chain turned ON in the shipped path (SHIPPED_CHAIN)


def test_shipped_chain_is_enabled_with_the_founder_approved_dials():
    """Guards the product's shipped SOUND. The vocal chain is turned on in the shipped pipeline via
    SHIPPED_CHAIN (routes/mix.py). If it silently reverted to enabled=False, or a dial were fat-fingered,
    every other backend test would still pass — the golden gate only protects the DISABLED path, so it
    stays green on a regression to OFF — while the app shipped a different-sounding mix. Lock the
    founder-approved config here so any such revert fails loudly.
    """
    c = mix_route.SHIPPED_CHAIN
    assert c.enabled is True
    assert (
        c.saturate_wet,
        c.presence_gain_db,
        c.reverb_wet,
        c.duck_depth_db,
        c.compress_ratio,
        c.highpass_hz,
        c.deess_intensity,
    ) == (0.3, 4.0, 0.08, 1.0, 2.0, 120, 0.4)
    # The MODEL default must stay OFF, so the disabled path (and the golden gate) is unaffected:
    # the shipped sound is opted in via SHIPPED_CHAIN, not by changing the VocalChainConfig default.
    from app.models import VocalChainConfig

    assert VocalChainConfig().enabled is False


def test_mix_id_folds_the_chain_config_hash(monkeypatch):
    """Phase 0 T1.4: the vocal-chain config hash is part of the mix cache id, so a tuning-week
    dial change invalidates the cache (never serves a stale render)."""
    base = mix_route.mix_id_for(SONG1, SONG2, "")
    monkeypatch.setattr(mix_route, "_CHAIN_CONFIG_HASH", "deadbeefdeadbeef")
    assert mix_route.mix_id_for(SONG1, SONG2, "") != base


def test_mix_carries_camelot_fit(tmp_path, monkeypatch):
    """Phase 0 T1.2: the informational key-fit flows through the route onto the served plan."""
    _use_tmp(monkeypatch, tmp_path)
    _setup_pair(tmp_path)
    r = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2})
    body = _poll(r.json()["mix_id"], "ready")
    assert body["status"] == "ready"
    assert body["plan"]["camelot_fit"] is not None  # attached, logged, never gated
