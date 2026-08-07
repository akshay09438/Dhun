"""Tests for the ops event store (app/events.py) — the memory behind the dev dashboard.

The store takes its data_dir from the caller, so every test just points it at tmp_path.
"""
import json

from app import events


def _mix(data_dir, **kw):
    base = dict(mix_id="m" * 64, status="ok", user_id="dev-1",
                song1_id="a" * 64, song2_id="b" * 64,
                song1_name="Father Ocean", song2_name="Der Lagi", rule=1, take=1)
    base.update(kw)
    events.record_mix(data_dir, **base)


def test_records_and_reads_back_a_mix(tmp_path):
    _mix(tmp_path)
    page = events.query_events(tmp_path)
    assert page["total"] == 1
    row = page["events"][0]
    assert row["kind"] == "mix"
    assert row["status"] == "ok"
    assert row["health"] == "green"
    assert row["song1_name"] == "Father Ocean"
    assert row["rule_label"] == "Simple"          # rule 1 -> label filled in
    assert row["extra"]["audio_url"] == f"/mix/{'m' * 64}/audio"


def test_newest_first_ordering(tmp_path):
    _mix(tmp_path, mix_id="1" * 64)
    _mix(tmp_path, mix_id="2" * 64)
    _mix(tmp_path, mix_id="3" * 64)
    ids = [e["ref_id"] for e in events.query_events(tmp_path)["events"]]
    assert ids == ["3" * 64, "2" * 64, "1" * 64]   # reverse-chronological (insertion order)


def test_pagination_returns_total_and_a_bounded_page(tmp_path):
    for i in range(5):
        _mix(tmp_path, mix_id=f"{i}" * 64)
    page = events.query_events(tmp_path, limit=2, offset=0)
    assert page["total"] == 5
    assert len(page["events"]) == 2
    page2 = events.query_events(tmp_path, limit=2, offset=4)
    assert len(page2["events"]) == 1               # last page has the remainder


def test_health_amber_when_a_warn_anomaly_is_present(tmp_path):
    _mix(tmp_path, anomalies=[{"code": "forced_tempo", "detail": "d", "action": "a", "severity": "warn"}])
    row = events.query_events(tmp_path)["events"][0]
    assert row["health"] == "amber"                # produced, but degraded
    assert row["anomalies"][0]["code"] == "forced_tempo"


def test_info_only_anomaly_stays_green(tmp_path):
    _mix(tmp_path, anomalies=[{"code": "key_measured", "detail": "d", "action": "a", "severity": "info"}])
    assert events.query_events(tmp_path)["events"][0]["health"] == "green"


def test_failed_mix_is_red_with_reason(tmp_path):
    _mix(tmp_path, status="failed", fail_reason="The mix didn't pass the quality check.")
    row = events.query_events(tmp_path)["events"][0]
    assert row["status"] == "failed"
    assert row["health"] == "red"
    assert "quality check" in row["fail_reason"]
    assert "audio_url" not in row["extra"]         # a failed mix has no audio to play


def test_filter_by_device_and_by_kind(tmp_path):
    _mix(tmp_path, mix_id="a" * 64, user_id="dev-1")
    _mix(tmp_path, mix_id="b" * 64, user_id="dev-2")
    events.record_set(tmp_path, set_id="s" * 64, status="ok", user_id="dev-1",
                      members=[{"index": 1, "kept": True}])
    assert events.query_events(tmp_path, user_id="dev-2")["total"] == 1
    assert events.query_events(tmp_path, kind="set")["total"] == 1
    assert events.query_events(tmp_path, kind="mix")["total"] == 2


def test_set_health_amber_when_a_member_is_dropped(tmp_path):
    events.record_set(tmp_path, set_id="s" * 64, status="ok", user_id="dev-1",
                      members=[{"index": 1, "kept": True}, {"index": 2, "kept": False, "reason": "no beat"}])
    row = events.query_events(tmp_path, kind="set")["events"][0]
    assert row["health"] == "amber"
    assert row["extra"]["members"][1]["kept"] is False


def test_summary_counts_totals_and_devices(tmp_path):
    _mix(tmp_path, mix_id="a" * 64, user_id="dev-1")
    _mix(tmp_path, mix_id="b" * 64, user_id="dev-2",
         anomalies=[{"code": "forced_tempo", "detail": "d", "action": "a", "severity": "warn"}])
    _mix(tmp_path, mix_id="c" * 64, user_id="dev-2", status="failed", fail_reason="boom")
    s = events.summary(tmp_path)
    assert s["total"] == 3
    assert s["failed"] == 1
    assert s["degraded"] == 1
    assert s["devices"] == 2


def test_devices_rollup_busiest_first(tmp_path):
    _mix(tmp_path, mix_id="a" * 64, user_id="dev-1")
    _mix(tmp_path, mix_id="b" * 64, user_id="dev-2")
    _mix(tmp_path, mix_id="c" * 64, user_id="dev-2", status="failed", fail_reason="boom")
    rollup = events.devices(tmp_path)
    assert rollup[0]["user_id"] == "dev-2"         # 2 events -> first
    assert rollup[0]["total"] == 2
    assert rollup[0]["failed"] == 1
    assert rollup[1]["user_id"] == "dev-1"


def test_created_at_can_be_supplied_for_deterministic_today_counts(tmp_path):
    _mix(tmp_path, mix_id="a" * 64, created_at="2020-01-01T00:00:00")   # long ago -> not "today"
    _mix(tmp_path, mix_id="b" * 64)                                     # now -> today
    s = events.summary(tmp_path)
    assert s["total"] == 2
    assert s["today_total"] == 1


def test_recording_is_non_fatal_on_a_bad_data_dir(tmp_path):
    # Point the store at a path that cannot be a directory (a file), and confirm it never raises.
    bad = tmp_path / "not_a_dir"
    bad.write_text("i am a file")
    events.record_mix(bad, mix_id="a" * 64, status="ok")   # must not raise
    assert events.query_events(bad)["total"] == 0          # read also degrades gracefully


def test_devices_include_first_seen_last_seen_and_active_days(tmp_path):
    _mix(tmp_path, mix_id="a" * 64, user_id="dev-1", created_at="2026-08-05T10:00:00")
    _mix(tmp_path, mix_id="b" * 64, user_id="dev-1", created_at="2026-08-05T11:00:00")  # same day
    _mix(tmp_path, mix_id="c" * 64, user_id="dev-1", created_at="2026-08-08T09:00:00")  # a later day
    row = next(d for d in events.devices(tmp_path) if d["user_id"] == "dev-1")
    assert row["first_at"] == "2026-08-05T10:00:00"
    assert row["last_at"] == "2026-08-08T09:00:00"
    assert row["active_days"] == 2   # two distinct calendar days
    assert row["total"] == 3


def test_retention_counts_returning_devices(tmp_path):
    # dev-1 came back on a second day; dev-2 only ever made one, on one day.
    _mix(tmp_path, mix_id="a" * 64, user_id="dev-1", created_at="2026-08-05T10:00:00")
    _mix(tmp_path, mix_id="b" * 64, user_id="dev-1", created_at="2026-08-08T10:00:00")
    _mix(tmp_path, mix_id="c" * 64, user_id="dev-2", created_at="2026-08-08T10:00:00")
    r = events.retention(tmp_path)
    assert r["total_devices"] == 2
    assert r["returning_devices"] == 1   # only dev-1 was active on 2+ days


def test_retention_new_vs_returning_today(tmp_path):
    from datetime import datetime
    today = datetime.now().isoformat(timespec="seconds")
    # dev-old first appeared long ago and is back today -> returning_today
    _mix(tmp_path, mix_id="a" * 64, user_id="dev-old", created_at="2020-01-01T10:00:00")
    _mix(tmp_path, mix_id="b" * 64, user_id="dev-old", created_at=today)
    # dev-new's very first activity is today -> new_today
    _mix(tmp_path, mix_id="c" * 64, user_id="dev-new", created_at=today)
    r = events.retention(tmp_path)
    assert r["new_today"] == 1        # dev-new
    assert r["returning_today"] == 1  # dev-old came back today


def test_via_marks_a_mix_made_inside_a_set(tmp_path):
    _mix(tmp_path, via="set")
    assert events.query_events(tmp_path)["events"][0]["via"] == "set"


def test_extra_is_valid_json_roundtrip(tmp_path):
    _mix(tmp_path, extra={"tempo_forced": True, "master_bpm": 120.0, "vocal_stretch": 1.26})
    row = events.query_events(tmp_path)["events"][0]
    assert row["extra"]["tempo_forced"] is True
    assert row["extra"]["master_bpm"] == 120.0
    # stored form is JSON text
    raw = events._connect(tmp_path).execute("SELECT extra FROM events LIMIT 1").fetchone()["extra"]
    assert isinstance(json.loads(raw), dict)
