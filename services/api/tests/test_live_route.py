import json
from fastapi.testclient import TestClient
from app.main import app
from app.audio.analysis import analysis_path

client = TestClient(app)
HEX = "a" * 64


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


def test_context_returns_bpm_and_downbeats():
    _seed_analysis(HEX, bpm=124.0, downbeats=(0.5, 2.5, 4.5))
    r = client.get(f"/live/context/{HEX}")
    assert r.status_code == 200
    assert r.json()["bpm"] == 124.0 and r.json()["downbeats"][0] == 0.5
