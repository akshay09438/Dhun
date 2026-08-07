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
