"""Tests for the read-only ops dashboard API (routes/admin.py).

Points admin.settings + events at a tmp data_dir, seeds a few events directly through the store,
and asserts the three GETs return them — plus the optional access-token gate.
"""
import dataclasses

from fastapi.testclient import TestClient

from app import events
from app.main import app
from app.routes import admin as admin_route

client = TestClient(app)


def _use_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(admin_route, "settings",
                        dataclasses.replace(admin_route.settings, data_dir=tmp_path))


def _seed(tmp_path):
    events.record_mix(tmp_path, mix_id="a" * 64, status="ok", user_id="dev-1",
                      song1_name="Father Ocean", song2_name="Der Lagi", rule=1, take=1)
    events.record_mix(tmp_path, mix_id="b" * 64, status="ok", user_id="dev-2", rule=4, take=1,
                      anomalies=[{"code": "forced_tempo", "detail": "d", "action": "a", "severity": "warn"}])
    events.record_mix(tmp_path, mix_id="c" * 64, status="failed", user_id="dev-2",
                      fail_reason="quality check failed")


def test_events_endpoint_returns_newest_first_with_total(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _seed(tmp_path)
    body = client.get("/admin/events").json()
    assert body["total"] == 3
    assert body["events"][0]["ref_id"] == "c" * 64          # newest first
    assert {e["health"] for e in body["events"]} == {"green", "amber", "red"}


def test_events_endpoint_filters_by_device(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _seed(tmp_path)
    body = client.get("/admin/events", params={"user_id": "dev-2"}).json()
    assert body["total"] == 2
    assert all(e["user_id"] == "dev-2" for e in body["events"])


def test_events_endpoint_paginates(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _seed(tmp_path)
    body = client.get("/admin/events", params={"limit": 2, "offset": 0}).json()
    assert body["total"] == 3
    assert len(body["events"]) == 2


def test_summary_endpoint(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _seed(tmp_path)
    s = client.get("/admin/summary").json()
    assert s["total"] == 3
    assert s["failed"] == 1
    assert s["degraded"] == 1
    assert s["devices"] == 2


def test_devices_endpoint_busiest_first(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _seed(tmp_path)
    rows = client.get("/admin/devices").json()
    assert rows[0]["user_id"] == "dev-2"
    assert rows[0]["total"] == 2
    assert rows[0]["failed"] == 1


def test_devices_endpoint_includes_retention_fields(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    events.record_mix(tmp_path, mix_id="a" * 64, status="ok", user_id="dev-1",
                      created_at="2026-08-05T10:00:00")
    events.record_mix(tmp_path, mix_id="b" * 64, status="ok", user_id="dev-1",
                      created_at="2026-08-08T10:00:00")
    rows = client.get("/admin/devices").json()
    row = next(r for r in rows if r["user_id"] == "dev-1")
    assert row["first_at"] == "2026-08-05T10:00:00"
    assert row["active_days"] == 2


def test_retention_endpoint(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    events.record_mix(tmp_path, mix_id="a" * 64, status="ok", user_id="dev-1",
                      created_at="2026-08-05T10:00:00")
    events.record_mix(tmp_path, mix_id="b" * 64, status="ok", user_id="dev-1",
                      created_at="2026-08-08T10:00:00")
    events.record_mix(tmp_path, mix_id="c" * 64, status="ok", user_id="dev-2",
                      created_at="2026-08-08T10:00:00")
    r = client.get("/admin/retention").json()
    assert r["total_devices"] == 2
    assert r["returning_devices"] == 1


def test_songs_endpoint_returns_the_music_rollup(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    events.record_mix(tmp_path, mix_id="a" * 64, status="ok", user_id="dev-1",
                      song1_id="s1" * 32, song2_id="s2" * 32,
                      song1_name="Father Ocean", song2_name="Der Lagi", rule=1, take=1)
    rows = client.get("/admin/songs").json()
    beat = next(r for r in rows if r["name"] == "Father Ocean")
    assert beat["as_beat"] == 1 and beat["as_vocal"] == 0
    assert beat["top_partner"] == "Der Lagi"


def test_time_endpoint_buckets_and_names_its_timezone(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    events.record_mix(tmp_path, mix_id="a" * 64, status="ok",
                      created_at="2026-08-10T14:00:00+05:30")
    body = client.get("/admin/time").json()
    assert len(body["by_hour"]) == 24
    assert body["report_tz"], "the page must be able to say whose clock these hours are"


def test_time_endpoint_rejects_an_out_of_range_window(tmp_path, monkeypatch):
    """The window is bounded at the route so a hand-typed URL can never ask for an unbounded scan."""
    _use_tmp(monkeypatch, tmp_path)
    assert client.get("/admin/time?days=0").status_code == 422
    assert client.get("/admin/time?days=999").status_code == 422


def test_health_reasons_endpoint_ranks_what_is_breaking(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _seed(tmp_path)
    body = client.get("/admin/health-reasons").json()
    assert body["failures"][0]["reason"] == "quality check failed"
    assert body["degradations"][0]["code"] == "forced_tempo"


def test_person_endpoint_returns_one_persons_page(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    _seed(tmp_path)
    body = client.get("/admin/person/dev-2").json()
    assert body["found"] is True
    assert body["total"] == 2 and body["failed"] == 1


def test_person_endpoint_reports_not_found_rather_than_404(tmp_path, monkeypatch):
    """An id with no activity should render an empty state on the dashboard, not an error."""
    _use_tmp(monkeypatch, tmp_path)
    r = client.get("/admin/person/nobody")
    assert r.status_code == 200
    assert r.json()["found"] is False


def test_new_endpoints_are_behind_the_same_token_gate(tmp_path, monkeypatch):
    """The gate is declared on the router, so a new route inherits it — this pins that, because a
    route added outside the router would silently expose user song choices once deployed."""
    _use_tmp(monkeypatch, tmp_path)
    monkeypatch.setenv("PROMPTDJ_DASHBOARD_TOKEN", "s3cret")
    for path in ("/admin/songs", "/admin/time", "/admin/health-reasons", "/admin/person/dev-1"):
        assert client.get(path).status_code == 401, f"{path} is not gated"
        assert client.get(path, headers={"X-Dashboard-Token": "s3cret"}).status_code == 200


def test_token_gate_open_when_unset(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    monkeypatch.delenv("PROMPTDJ_DASHBOARD_TOKEN", raising=False)
    assert client.get("/admin/summary").status_code == 200


def test_token_gate_rejects_without_header_when_set(tmp_path, monkeypatch):
    _use_tmp(monkeypatch, tmp_path)
    monkeypatch.setenv("PROMPTDJ_DASHBOARD_TOKEN", "s3cret")
    assert client.get("/admin/summary").status_code == 401
    assert client.get("/admin/summary", headers={"X-Dashboard-Token": "wrong"}).status_code == 401
    assert client.get("/admin/summary", headers={"X-Dashboard-Token": "s3cret"}).status_code == 200
