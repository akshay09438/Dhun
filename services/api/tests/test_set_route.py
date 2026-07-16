"""Tests for the /set route: the async contract, caching, the two-set cap, preconditions,
and a real end-to-end build that renders two synthetic pairs and joins them with the shipped
beat-matched seam engine (no cloud, no AI network — the deterministic fallback picks the drop).
"""

import dataclasses
import time

from fastapi.testclient import TestClient

from app import storage
from app.audio import analysis as analysis_mod
from app.audio import stems as stems_mod
from app.main import app
from app.planner import plan as plan_mod
from app.routes import mix as mix_route
from app.routes import set as set_route
from tests.test_mix_route import _tone, _write_analysis

client = TestClient(app)

BEAT1, VOC1 = "a" * 64, "b" * 64
BEAT2, VOC2 = "c" * 64, "d" * 64


def _use_tmp(monkeypatch, tmp_path):
    for mod in (storage, analysis_mod, stems_mod, mix_route, set_route):
        monkeypatch.setattr(
            mod, "settings", dataclasses.replace(mod.settings, data_dir=tmp_path)
        )
    monkeypatch.setattr(mix_route, "_jobs", {})
    monkeypatch.setattr(set_route, "_jobs", {})
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(plan_mod, "_ai_arrange", lambda opts, prompt, take: None)


def _beat(tmp_path, sid, bpm):
    """A beat song: uploaded + analyzed + split into drums/bass/other (+ its own vocals)."""
    _tone(tmp_path / f"{sid}.wav", 200.0)
    _write_analysis(tmp_path, sid, bpm, [(20.0, 62.0)])  # Song 1 sings a passage → contrast
    for name, f in (("drums", 110.0), ("bass", 55.0), ("other", 330.0), ("vocals", 660.0)):
        _tone(tmp_path / f"{sid}.{name}.mp3", f)


def _vocal(tmp_path, sid, bpm):
    """A vocal song: uploaded + analyzed + split into a vocals stem."""
    _tone(tmp_path / f"{sid}.wav", 300.0)
    _write_analysis(tmp_path, sid, bpm, [(0.0, 4.0)])
    _tone(tmp_path / f"{sid}.vocals.mp3", 440.0)


def _poll(set_id, want, tries=600):
    body = {}
    for _ in range(tries):
        body = client.get(f"/set/{set_id}").json()
        if body["status"] == want:
            return body
        time.sleep(0.05)
    return body


def _payload(*pairs):
    return {"sets": [{"song1_id": a, "song2_id": b} for a, b in pairs]}


def test_set_builds_two_mixes_into_one_continuous_wav(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _beat(tmp_path, BEAT1, 120.0)
    _vocal(tmp_path, VOC1, 118.0)
    _beat(tmp_path, BEAT2, 122.0)
    _vocal(tmp_path, VOC2, 119.0)

    r = client.post("/set", json=_payload((BEAT1, VOC1), (BEAT2, VOC2)))
    assert r.status_code == 202
    assert r.json()["status"] == "processing"  # returned at once, not blocked

    set_id = r.json()["set_id"]
    ready = _poll(set_id, "ready")
    assert ready["status"] == "ready"
    assert ready["url"] == f"/set/{set_id}/audio"

    members = ready["members"]
    assert len(members) == 2
    assert all(m["kept"] for m in members)
    # The first set starts the timeline; the second joins at a real seam partway through.
    assert members[0]["seam_at"] is None
    assert members[1]["seam_at"] is not None and members[1]["seam_at"] > 0
    assert ready["duration"] and ready["duration"] > 0

    audio = client.get(ready["url"])
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/wav"
    assert len(audio.content) > 1000  # a real WAV, not empty


def test_set_is_cached(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _beat(tmp_path, BEAT1, 120.0)
    _vocal(tmp_path, VOC1, 118.0)
    _beat(tmp_path, BEAT2, 122.0)
    _vocal(tmp_path, VOC2, 119.0)

    r1 = client.post("/set", json=_payload((BEAT1, VOC1), (BEAT2, VOC2)))
    _poll(r1.json()["set_id"], "ready")

    r2 = client.post("/set", json=_payload((BEAT1, VOC1), (BEAT2, VOC2)))
    assert r2.status_code == 200  # instant cache hit
    assert r2.json()["status"] == "ready"


def test_set_declines_a_tempo_outlier_pair_and_builds_the_rest(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    # One shared beat, two vocals: the second vocal is far off-tempo, so its set is declined
    # while the first set still builds. (Deterministic: the lone 155-BPM song is the outlier.)
    _beat(tmp_path, BEAT1, 120.0)
    _vocal(tmp_path, VOC1, 120.0)
    _vocal(tmp_path, VOC2, 155.0)

    r = client.post("/set", json=_payload((BEAT1, VOC1), (BEAT1, VOC2)))
    ready = _poll(r.json()["set_id"], "ready")
    assert ready["status"] == "ready"

    by_index = {m["index"]: m for m in ready["members"]}
    assert by_index[1]["kept"] is True
    assert by_index[2]["kept"] is False
    assert "tempo" in (by_index[2]["reason"] or "").lower()


def test_set_declines_a_mix_whose_PLAYING_tempo_is_the_outlier(tmp_path, monkeypatch):
    """The set-level decline: both pairs mix fine on their own, but the two FINISHED mixes play
    too far apart (85 vs 122) to share one set tempo — so one sits out rather than warble."""
    _use_tmp(monkeypatch, tmp_path)
    _beat(tmp_path, BEAT1, 85.0)
    _vocal(tmp_path, VOC1, 85.0)   # mixes at ~85
    _beat(tmp_path, BEAT2, 122.0)
    _vocal(tmp_path, VOC2, 122.0)  # mixes at ~122 — a 1.44x spread, far outside the safe band

    r = client.post("/set", json=_payload((BEAT1, VOC1), (BEAT2, VOC2)))
    ready = _poll(r.json()["set_id"], "ready")
    assert ready["status"] == "ready"

    kept = [m for m in ready["members"] if m["kept"]]
    dropped = [m for m in ready["members"] if not m["kept"]]
    assert len(kept) == 1 and len(dropped) == 1  # one sits out; the set still builds
    assert "tempo" in (dropped[0]["reason"] or "").lower()


def test_set_keeps_both_sets_on_one_beat_whatever_the_vocals_original_tempos(tmp_path, monkeypatch):
    """REGRESSION: two sets on the SAME beat always play at (near) the same tempo, so they must
    always join. The tempo reconciliation used to vote on the RAW song BPMs — including each
    vocal's ORIGINAL tempo, which no longer exists once the mix stretches it onto the beat's grid.
    Vocals at 80 and 103 look 1.29x apart raw (outside the 1.247x band) and one set was thrown
    away, even though both mixes actually play at ~85 and ~92 — a 1.08x gap that joins fine.
    This is the real Merrygo + Khuda Jaane / Tere Bin case the founder hit."""
    _use_tmp(monkeypatch, tmp_path)
    _beat(tmp_path, BEAT1, 85.0)
    _vocal(tmp_path, VOC1, 80.0)   # raw 80  -> stretched onto the 85 grid
    _vocal(tmp_path, VOC2, 103.0)  # raw 103 -> mix rides a moved master (~92)

    r = client.post("/set", json=_payload((BEAT1, VOC1), (BEAT1, VOC2)))
    ready = _poll(r.json()["set_id"], "ready")
    assert ready["status"] == "ready"

    by_index = {m["index"]: m for m in ready["members"]}
    assert by_index[1]["kept"] is True, by_index[1]["reason"]
    assert by_index[2]["kept"] is True, by_index[2]["reason"]  # was wrongly dropped before the fix
    assert by_index[2]["seam_at"] and by_index[2]["seam_at"] > 0  # a real transition was created


def test_set_enforces_the_two_set_cap(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    three = _payload((BEAT1, VOC1), (BEAT2, VOC2), (BEAT1, VOC2))
    assert client.post("/set", json=three).status_code == 400
    assert client.post("/set", json={"sets": []}).status_code == 400


def test_set_blocks_when_a_song_is_not_analyzed(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _beat(tmp_path, BEAT1, 120.0)
    _vocal(tmp_path, VOC1, 118.0)
    # Second pair uploaded but never analyzed/split.
    _tone(tmp_path / f"{BEAT2}.wav", 200.0)
    _tone(tmp_path / f"{VOC2}.wav", 300.0)

    r = client.post("/set", json=_payload((BEAT1, VOC1), (BEAT2, VOC2)))
    assert r.status_code == 409
    assert "analyzed" in r.json()["detail"].lower()


def test_set_rejects_bad_ids(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    assert (
        client.post("/set", json=_payload(("nothex", VOC1))).status_code == 404
    )
    assert client.get("/set/deadbeef").status_code == 404
    assert client.get("/set/" + "a" * 64 + "/audio").status_code == 404
