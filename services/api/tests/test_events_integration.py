"""End-to-end: a real mix through the route records one ops event; a failed mix records a red one.

Reuses the mix-route test harness (synthetic songs, no cloud/AI). The event store reads its
data_dir from the caller, so the mix pipeline's tmp data_dir is where the event lands.
"""
from app import events
from app.audio import pitch
from app.routes import mix as mix_route
from tests.test_mix_route import SONG1, SONG2, _poll, _setup_pair, _use_tmp, client


def test_a_successful_mix_records_an_event(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _setup_pair(tmp_path)

    r = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2,
                                  "user_id": "dev-xyz", "generation": 0})
    mix_id = r.json()["mix_id"]
    _poll(mix_id, "ready")

    page = events.query_events(tmp_path)
    assert page["total"] == 1
    row = page["events"][0]
    assert row["ref_id"] == mix_id
    assert row["status"] == "ok"
    assert row["health"] in ("green", "amber")          # "produced" either way; degraded => amber
    assert row["user_id"] == "dev-xyz"                  # the anonymous device tag is recorded
    assert row["rule"] is not None                      # the auto-assigned rule is captured (for the dev view)
    assert row["extra"]["audio_url"] == f"/mix/{mix_id}/audio"   # playable from the dashboard


def test_a_failed_mix_records_a_red_event(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _setup_pair(tmp_path)

    # Force a genuine render failure so the outcome is a recorded 'failed' event.
    # (A key-shift failure no longer qualifies: under never-refuse it falls back to the NATIVE key
    # and the mix still succeeds — see test_mix_route.test_key_match_pitch_error_ships_native_key.)
    def boom(plan, stems, s2_voc, out):
        raise RuntimeError("render exploded")

    monkeypatch.setattr(mix_route, "render_mix", boom)

    r = client.post("/mix", json={"song1_id": SONG1, "song2_id": SONG2})
    mix_id = r.json()["mix_id"]
    _poll(mix_id, "error")

    rows = events.query_events(tmp_path)["events"]
    assert rows and rows[0]["ref_id"] == mix_id
    assert rows[0]["status"] == "failed"
    assert rows[0]["health"] == "red"
    assert rows[0]["fail_reason"]                        # the plain-language reason is captured
