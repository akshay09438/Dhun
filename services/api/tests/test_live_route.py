import dataclasses
import json

from fastapi.testclient import TestClient

from app import storage
from app.audio import analysis as an
from app.audio.analysis import analysis_path
from app.main import app

client = TestClient(app)
HEX = "a" * 64


def _use_tmp(monkeypatch, tmp_path):
    """Redirect the data dir to a temp path so a test never reads/writes the real data/
    (mirrors test_analysis_route._use_tmp — the seeded analysis must not leak or collide)."""
    monkeypatch.setattr(storage, "settings",
                        dataclasses.replace(storage.settings, data_dir=tmp_path))
    monkeypatch.setattr(an, "settings",
                        dataclasses.replace(an.settings, data_dir=tmp_path))


def _seed_analysis(song_id, bpm=120.0, downbeats=(0.0, 2.0, 4.0)):
    analysis_path(song_id).write_text(json.dumps(
        {"song_id": song_id, "bpm": bpm, "downbeats": list(downbeats),
         "beats": [], "phrase_starts": [], "sections": [], "energy_curve": [],
         "vocal_regions": []}))


def test_command_returns_a_liveop():
    r = client.post("/live/command", json={"song1_id": HEX, "song2_id": HEX, "text": "take the bass out"})
    assert r.status_code == 200
    body = r.json()
    assert body["op"] == "mute" and body["target"] == "bass"


def test_command_declines_out_of_scope():
    r = client.post("/live/command", json={"song1_id": HEX, "song2_id": HEX, "text": "make it faster"})
    assert r.json()["op"] == "decline"


def test_bad_song_id_is_404():
    r = client.post("/live/command", json={"song1_id": "nothex", "song2_id": HEX, "text": "x"})
    assert r.status_code == 404


def test_context_returns_bpm_and_downbeats(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    _seed_analysis(HEX, bpm=124.0, downbeats=(0.5, 2.5, 4.5))
    r = client.get(f"/live/context/{HEX}")
    assert r.status_code == 200
    assert r.json()["bpm"] == 124.0 and r.json()["downbeats"][0] == 0.5


import dataclasses as _dc

from app.routes import live as live_route


def _use_live_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(live_route, "settings",
                        _dc.replace(live_route.settings, data_dir=tmp_path))


def test_vocal_bus_bad_id_is_404():
    r = client.get("/live/vocal-bus/nothex")
    assert r.status_code == 404


def test_vocal_bus_without_a_plan_is_409(monkeypatch, tmp_path):
    _use_live_tmp(monkeypatch, tmp_path)
    r = client.get(f"/live/vocal-bus/{HEX}")
    assert r.status_code == 409


def test_vocal_bus_serves_the_wav_when_present(monkeypatch, tmp_path):
    _use_live_tmp(monkeypatch, tmp_path)
    (tmp_path / f"{HEX}.livearr.wav").write_bytes(b"RIFF....WAVEfake")  # pre-seeded "ready"
    r = client.get(f"/live/vocal-bus/{HEX}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/")


from app.models import MixPlan


def test_live_vocal_render_uses_the_arranged_bus(monkeypatch, tmp_path):
    """The live Vocals must be the ARRANGED, beat-locked bus (render_vocal_bus) — the same
    vocal as the Download — NOT the old continuous full-vocal that drifted/wandered."""
    _use_live_tmp(monkeypatch, tmp_path)
    plan = MixPlan(
        mix_id=HEX, song1_id=HEX, song2_id=HEX, master_bpm=120.0, vocal_stretch=1.0,
        vocal_src=(0.0, 2.0), anchor=2.0,
        placements=[], s1_vocal_regions=[], take=1, notes="", source="rules",
    )
    (tmp_path / f"{HEX}.mixplan.json").write_text(plan.model_dump_json())

    seen = {}

    def fake_bus(plan_arg, song1_stems, song2_vocal, out):
        seen["called"] = True
        out.write_bytes(b"RIFFfake")

    monkeypatch.setattr(live_route, "render_vocal_bus", fake_bus)
    live_route._run_vocal_bus(HEX)
    assert seen.get("called") is True
    assert (tmp_path / f"{HEX}.livearr.wav").exists()
from app.planner import suggest as suggest_mod


def _seed_plan_and_sections(tmp_path, monkeypatch):
    monkeypatch.setattr(suggest_mod, "_ai_suggest", lambda *a, **k: None)  # force fallback, no AI
    plan = MixPlan(mix_id=HEX, song1_id=HEX, song2_id=HEX, master_bpm=120.0,
                   vocal_stretch=1.0, vocal_src=(0.0, 2.0), anchor=1.0)
    (tmp_path / f"{HEX}.mixplan.json").write_text(plan.model_dump_json())
    analysis_path(HEX).write_text(json.dumps(
        {"song_id": HEX, "bpm": 120.0, "downbeats": [], "beats": [], "phrase_starts": [],
         "sections": [{"start": 0.0, "end": 30.0, "label": "intro"},
                      {"start": 30.0, "end": 60.0, "label": "chorus"}],
         "energy_curve": [], "vocal_regions": []}))


def test_suggestions_bad_id_is_404():
    assert client.get("/live/suggestions/nothex").status_code == 404


def test_suggestions_without_a_plan_is_409(monkeypatch, tmp_path):
    _use_live_tmp(monkeypatch, tmp_path)
    assert client.get(f"/live/suggestions/{HEX}").status_code == 409


def test_suggestions_returns_sections_with_vocabulary_chips(monkeypatch, tmp_path):
    _use_live_tmp(monkeypatch, tmp_path)
    _seed_plan_and_sections(tmp_path, monkeypatch)
    r = client.get(f"/live/suggestions/{HEX}")
    assert r.status_code == 200
    secs = r.json()["sections"]
    assert [s["label"] for s in secs] == ["intro", "chorus"]
    known = {"Bring the vocal in", "Take the vocal out", "Take the bass out",
             "Drop to just the beat", "Bring it all back", "Fade it out"}
    for s in secs:
        assert s["chips"] and all(c["text"] in known for c in s["chips"])
