"""Backend anomaly reporting — when a mix is built from imperfect/unexpected inputs we STILL generate
the music (forced tempo + fallbacks), but the backend must surface WHAT was off and WHAT TO DO about it,
so a real upload's data problems are visible instead of silent (founder rule 2026-08-07, point 2)."""

from app.planner import anomaly


def test_clean_inputs_report_nothing():
    out = anomaly.scan(
        grid_health={"song1": {"ok": True}, "song2": {"ok": True}},
        tempo_forced=False, vocal_stretch=1.0, key_why="in-band",
    )
    assert out == []


def test_forced_tempo_is_reported_with_a_named_stretch_and_an_action():
    out = anomaly.scan(grid_health={}, tempo_forced=True, vocal_stretch=1.28, key_why="")
    forced = [a for a in out if a.code == "forced_tempo"]
    assert forced, "a forced stretch must be reported"
    a = forced[0]
    assert "28%" in a.detail        # names how big the forced stretch was
    assert a.action                 # tells the operator what to do about it
    assert a.severity == "warn"


def test_low_grid_confidence_is_reported_per_track():
    gh = {"song1/beat": {"ok": False, "reason": "irregular downbeats"},
          "song2/vocal": {"ok": True}}
    out = anomaly.scan(grid_health=gh, tempo_forced=False, vocal_stretch=1.0, key_why="")
    low = [a for a in out if a.code == "low_grid_confidence"]
    assert len(low) == 1
    assert "song1/beat" in low[0].detail
    assert low[0].action


def test_key_measured_from_audio_is_reported():
    out = anomaly.scan(
        grid_health={}, tempo_forced=False, vocal_stretch=1.0,
        key_why="chroma-empirical +3 st (labels untrusted -> measured from audio)",
    )
    assert any(a.code == "key_measured" for a in out)


def test_suspicious_whole_song_beat_vocal_is_reported_not_silenced():
    out = anomaly.scan(grid_health={}, tempo_forced=False, vocal_stretch=1.0, key_why="",
                       beat_vocal_coverage=1.0)
    susp = [a for a in out if a.code == "suspicious_beat_vocal"]
    assert susp and susp[0].severity == "warn" and susp[0].action
    assert "auto-silenced" in susp[0].action.lower()  # explicitly a report, not an action taken


def test_anomalies_serialize_to_a_backend_line():
    a = anomaly.Anomaly("forced_tempo", "stretched 28%", "pick a closer partner", "warn")
    line = anomaly.format_line("mix123", a)
    assert "mix123" in line and "forced_tempo" in line and "warn" in line
