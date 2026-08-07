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


def test_set_NEVER_declines_a_far_tempo_pair_it_forces_it_onto_the_beat(tmp_path, monkeypatch):
    """Never-decline is a PRODUCT rule and must hold inside a SET too, not only for a single mix — a
    far-apart vocal is stretched fully onto the beat and beat-locked, never dropped for tempo. (Bug:
    the set builder's mixability gate called the fence WITHOUT force_tempo, so it still used the old
    'too far apart' decline — e.g. Innerbloom 122 × Jugni Ji 95 was skipped even though the same pair
    mixes fine on its own. Founder 2026-08-07, reported after a 5-mix set dropped members 3 and 5.)"""
    _use_tmp(monkeypatch, tmp_path)
    # One shared beat, two vocals: one in-band, one ~28% apart (the shape of Innerbloom × Jugni Ji).
    _beat(tmp_path, BEAT1, 122.0)
    _vocal(tmp_path, VOC1, 122.0)
    _vocal(tmp_path, VOC2, 95.0)  # far apart — must be FORCED onto the 122 beat, not skipped

    r = client.post("/set", json=_payload((BEAT1, VOC1), (BEAT1, VOC2)))
    ready = _poll(r.json()["set_id"], "ready")
    assert ready["status"] == "ready"

    by_index = {m["index"]: m for m in ready["members"]}
    assert by_index[1]["kept"] is True
    # The far pair is kept (forced onto the beat) and NEVER declined for tempo.
    assert by_index[2]["kept"] is True, by_index[2]["reason"]
    assert "too far apart" not in (by_index[2]["reason"] or "").lower()


def test_seam_positions_match_the_rendered_set_across_a_cut(tmp_path, monkeypatch):
    """`_seam_positions` is a SECOND copy of the engine's sample accounting, so it can silently drift
    from the audio. Pin them together on a CUT seam: the reported duration must match the real WAV,
    and the reported seam must be where the cut actually lands (member 1's full length).
    (Caught for real: the cut shipped 282.3s of audio while the manifest claimed 259.75s.)"""
    _use_tmp(monkeypatch, tmp_path)
    _beat(tmp_path, BEAT1, 85.0)
    _vocal(tmp_path, VOC1, 85.0)
    _beat(tmp_path, BEAT2, 122.0)
    _vocal(tmp_path, VOC2, 122.0)

    r = client.post("/set", json=_payload((BEAT1, VOC1), (BEAT2, VOC2)))
    ready = _poll(r.json()["set_id"], "ready")
    assert ready["status"] == "ready"

    import soundfile as sf
    real = sf.info(str(tmp_path / f"{ready['set_id']}.set.wav")).duration
    assert abs(ready["duration"] - real) < 0.05, (
        f"manifest says {ready['duration']}s but the WAV is {real}s"
    )
    seam = {m["index"]: m for m in ready["members"]}[2]["seam_at"]
    member1 = sf.info(str(tmp_path / f"{ready['set_id']}_1.bestparts.wav")).duration
    assert abs(seam - member1) < 0.1, f"cut reported at {seam}s but member 1 is {member1}s long"


def test_set_CUTS_between_mixes_too_far_apart_to_blend_and_keeps_both(tmp_path, monkeypatch):
    """A tempo gap must never drop a member. Both pairs mix fine on their own but the FINISHED mixes
    play 85 vs 122 — too far apart to CROSSFADE (nothing is stretched at a seam, so an 8-bar overlap
    would just grind). That seam is CUT instead, and BOTH sets play. (Founder call, 2026-07-16.)"""
    _use_tmp(monkeypatch, tmp_path)
    _beat(tmp_path, BEAT1, 85.0)
    _vocal(tmp_path, VOC1, 85.0)   # mixes at ~85
    _beat(tmp_path, BEAT2, 122.0)
    _vocal(tmp_path, VOC2, 122.0)  # mixes at ~122 — a 1.44x gap, far outside the blendable band

    r = client.post("/set", json=_payload((BEAT1, VOC1), (BEAT2, VOC2)))
    ready = _poll(r.json()["set_id"], "ready")
    assert ready["status"] == "ready"

    assert all(m["kept"] for m in ready["members"]), [m["reason"] for m in ready["members"]]
    assert len(ready["members"]) == 2  # nothing sits out any more
    assert ready["duration"] and ready["duration"] > 0


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


def test_set_enforces_the_max_mixes_cap(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    # Over the cap (6 > MAX_MIXES_PER_SET) -> 400; empty -> 400.
    over = _payload(*([(BEAT1, VOC1)] * (set_route.MAX_MIXES_PER_SET + 1)))
    assert client.post("/set", json=over).status_code == 400
    assert client.post("/set", json={"sets": []}).status_code == 400
    # Three pairs is now WITHIN the raised cap, so it is NOT rejected on count (proceeds to prereqs).
    three = _payload((BEAT1, VOC1), (BEAT2, VOC2), (BEAT1, VOC2))
    assert client.post("/set", json=three).status_code != 400


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


# ---- auto rule assignment: seed = user + set_index, each mix ruled by its position -------------

def test_set_auto_assigns_rules_from_the_shuffler(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _beat(tmp_path, BEAT1, 120.0); _vocal(tmp_path, VOC1, 118.0)
    _beat(tmp_path, BEAT2, 122.0); _vocal(tmp_path, VOC2, 119.0)
    monkeypatch.setattr(set_route, "_run_set", lambda *a, **k: None)  # id-only check; skip the render
    from app.planner import rule_shuffle

    body = {"sets": [{"song1_id": BEAT1, "song2_id": VOC1},
                     {"song1_id": BEAT2, "song2_id": VOC2}],
            "user_id": "u-set", "set_index": 0}
    id1 = client.post("/set", json=body).json()["set_id"]
    id2 = client.post("/set", json=body).json()["set_id"]
    assert id1 == id2  # deterministic -> same id -> a rebuild hits cache

    expected = [(BEAT1, VOC1, rule_shuffle.rule_for_set("u-set", 0, 0)),
                (BEAT2, VOC2, rule_shuffle.rule_for_set("u-set", 0, 1))]
    assert id1 == set_route.set_id_for(expected)  # each mix ruled by its position in the set


def test_set_consecutive_indices_and_users_diverge(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _beat(tmp_path, BEAT1, 120.0); _vocal(tmp_path, VOC1, 118.0)
    _beat(tmp_path, BEAT2, 122.0); _vocal(tmp_path, VOC2, 119.0)
    monkeypatch.setattr(set_route, "_run_set", lambda *a, **k: None)

    def sid(user, idx):
        return client.post("/set", json={
            "sets": [{"song1_id": BEAT1, "song2_id": VOC1},
                     {"song1_id": BEAT2, "song2_id": VOC2}],
            "user_id": user, "set_index": idx}).json()["set_id"]

    assert sid("A", 0) != sid("A", 1)  # a user's consecutive sets differ (G3)
    assert sid("A", 0) != sid("B", 0)  # different users differ (G4)
