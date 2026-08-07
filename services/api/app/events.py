"""The internal ops event log — the memory behind the developer dashboard.

Every mix and set OUTCOME (created or failed) is recorded as one row in a tiny SQLite
file, `events.db`, in the same gitignored `data/` folder as the audio. The read-only
dashboard (`routes/admin.py`) queries this; the mix/set pipelines write to it.

Two design rules make this safe to bolt onto the render path:

1. **Telemetry is NON-FATAL.** Every public function swallows its own errors (logs and
   moves on). Recording a mix must NEVER be able to break making the mix.
2. **The caller supplies `data_dir`.** This module reads no global settings, so it lands
   in whatever folder the caller is using — which makes it automatically hermetic under
   the test suite's `data_dir` monkeypatch (each test gets its own `tmp_path/events.db`),
   with no change to any existing test.

The store is deliberately minimal — a single flat table, ordered by insertion, paginated
on read. That is the right size for validation scale (~hundreds of users); it upgrades to
a real datastore later without changing the callers. `user_id` is the anonymous per-browser
device tag (there is no login yet); it is kept as a plain nullable column so that adding a
real `account_id` later is an additive change, not a rewrite.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("promptdj.events")

_DB_NAME = "events.db"

# The mixing rules, for a human-readable label on each row (mirrors the frontend
# types.ts RULE_LABELS and the backend rule_shuffle.RULES). Rule 2 is spec-only.
RULE_LABELS: dict[int, str] = {1: "Simple", 3: "Chop & repeat", 4: "Echo"}


def rule_label(rule: int | None) -> str:
    return RULE_LABELS.get(rule, "") if rule else ""


def health_for(status: str, anomalies: list[dict] | None) -> str:
    """The row's traffic-light health: red = it broke, amber = it played but a degraded
    condition was flagged, green = clean. Derived from the same anomaly severities the
    backend already produces — no new judgement invented here."""
    if status != "ok":
        return "red"
    for a in anomalies or []:
        if isinstance(a, dict) and a.get("severity") == "warn":
            return "amber"
    return "green"


def _db_path(data_dir: Path) -> Path:
    return Path(data_dir) / _DB_NAME


def _connect(data_dir: Path) -> sqlite3.Connection:
    """Open (creating on first use) the events DB. WAL keeps a background render-thread
    write from blocking a dashboard read. A short timeout avoids a rare lock stall."""
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_db_path(data_dir), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  TEXT    NOT NULL,
            kind        TEXT    NOT NULL,          -- 'mix' | 'set'
            via         TEXT    NOT NULL DEFAULT 'single',  -- 'single' | 'set' (a mix made inside a set)
            ref_id      TEXT    NOT NULL,          -- the mix_id or set_id
            user_id     TEXT,                      -- anonymous per-browser device tag (nullable)
            song1_id    TEXT,
            song2_id    TEXT,
            song1_name  TEXT,
            song2_name  TEXT,
            rule        INTEGER,
            rule_label  TEXT,
            take        INTEGER,
            status      TEXT    NOT NULL,          -- 'ok' | 'failed'
            health      TEXT    NOT NULL,          -- 'green' | 'amber' | 'red'
            fail_reason TEXT,
            anomalies   TEXT,                      -- JSON array of {code, detail, action, severity}
            extra       TEXT                       -- JSON blob (tempo/key facts, audio_url, set members)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_id ON events (id DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_user ON events (user_id)")
    return conn


def _insert(data_dir: Path, row: dict[str, Any]) -> None:
    """Write one row. Swallows every error — telemetry must never break the caller."""
    try:
        conn = _connect(data_dir)
        try:
            cols = ("created_at", "kind", "via", "ref_id", "user_id", "song1_id", "song2_id",
                    "song1_name", "song2_name", "rule", "rule_label", "take", "status", "health",
                    "fail_reason", "anomalies", "extra")
            conn.execute(
                f"INSERT INTO events ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
                tuple(row.get(c) for c in cols),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — a telemetry write failure is logged, never raised
        log.exception("events: failed to record a %s event for %s", row.get("kind"), row.get("ref_id"))


def record_mix(
    data_dir: Path,
    *,
    mix_id: str,
    status: str,
    user_id: str | None = None,
    via: str = "single",
    song1_id: str | None = None,
    song2_id: str | None = None,
    song1_name: str | None = None,
    song2_name: str | None = None,
    rule: int | None = None,
    take: int | None = None,
    anomalies: list[dict] | None = None,
    fail_reason: str | None = None,
    extra: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> None:
    """Record one mix outcome. `status` is 'ok' or 'failed'. Non-fatal by construction."""
    ex = dict(extra or {})
    if status == "ok":
        ex.setdefault("audio_url", f"/mix/{mix_id}/audio")
    _insert(data_dir, {
        "created_at": created_at or datetime.now().isoformat(timespec="seconds"),
        "kind": "mix",
        "via": via,
        "ref_id": mix_id,
        "user_id": user_id,
        "song1_id": song1_id,
        "song2_id": song2_id,
        "song1_name": song1_name,
        "song2_name": song2_name,
        "rule": rule,
        "rule_label": rule_label(rule),
        "take": take,
        "status": status,
        "health": health_for(status, anomalies),
        "fail_reason": fail_reason,
        "anomalies": json.dumps(anomalies or []),
        "extra": json.dumps(ex),
    })


def record_set(
    data_dir: Path,
    *,
    set_id: str,
    status: str,
    user_id: str | None = None,
    members: list[dict] | None = None,
    fail_reason: str | None = None,
    extra: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> None:
    """Record one set outcome. Health: red if the whole set failed, amber if any member was
    dropped, green if every member was kept. `members` is the serialized SetMember line-up."""
    members = members or []
    if status != "ok":
        health = "red"
    elif any(not m.get("kept", True) for m in members):
        health = "amber"
    else:
        health = "green"
    ex = dict(extra or {})
    ex["members"] = members
    if status == "ok":
        ex.setdefault("audio_url", f"/set/{set_id}/audio")
    _insert(data_dir, {
        "created_at": created_at or datetime.now().isoformat(timespec="seconds"),
        "kind": "set",
        "via": "single",
        "ref_id": set_id,
        "user_id": user_id,
        "song1_id": None,
        "song2_id": None,
        "song1_name": None,
        "song2_name": None,
        "rule": None,
        "rule_label": None,
        "take": None,
        "status": status,
        "health": health,
        "fail_reason": fail_reason,
        "anomalies": json.dumps([]),
        "extra": json.dumps(ex),
    })


def _row_to_dict(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    d["anomalies"] = json.loads(d.get("anomalies") or "[]")
    d["extra"] = json.loads(d.get("extra") or "{}")
    return d


def query_events(
    data_dir: Path,
    *,
    limit: int = 50,
    offset: int = 0,
    user_id: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """A page of events, newest first (by insertion order). Returns {events, total} so the
    dashboard can show "showing N of TOTAL" and page through every mix ever made."""
    limit = max(1, min(int(limit), 200))   # bounded page size — never an unbounded fetch
    offset = max(0, int(offset))
    where, params = [], []
    if user_id is not None:
        where.append("user_id = ?")
        params.append(user_id)
    if kind is not None:
        where.append("kind = ?")
        params.append(kind)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    try:
        conn = _connect(data_dir)
        try:
            total = conn.execute(f"SELECT COUNT(*) AS n FROM events{clause}", params).fetchone()["n"]
            rows = conn.execute(
                f"SELECT * FROM events{clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
            return {"events": [_row_to_dict(r) for r in rows], "total": total}
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — a read failure must not 500 the dashboard
        log.exception("events: query failed")
        return {"events": [], "total": 0}


def summary(data_dir: Path) -> dict[str, Any]:
    """The one-line health strip: totals and today's counts (server-local day), plus how many
    distinct devices have made anything. Numbers, not charts."""
    today = datetime.now().date().isoformat()
    try:
        conn = _connect(data_dir)
        try:
            def _count(sql: str, params: tuple = ()) -> int:
                return conn.execute(sql, params).fetchone()["n"]

            total = _count("SELECT COUNT(*) AS n FROM events")
            failed = _count("SELECT COUNT(*) AS n FROM events WHERE health='red'")
            degraded = _count("SELECT COUNT(*) AS n FROM events WHERE health='amber'")
            devices = _count("SELECT COUNT(DISTINCT user_id) AS n FROM events WHERE user_id IS NOT NULL")
            today_total = _count("SELECT COUNT(*) AS n FROM events WHERE substr(created_at,1,10)=?", (today,))
            today_failed = _count(
                "SELECT COUNT(*) AS n FROM events WHERE health='red' AND substr(created_at,1,10)=?", (today,))
            today_degraded = _count(
                "SELECT COUNT(*) AS n FROM events WHERE health='amber' AND substr(created_at,1,10)=?", (today,))
            return {
                "total": total, "failed": failed, "degraded": degraded, "devices": devices,
                "today_total": today_total, "today_failed": today_failed, "today_degraded": today_degraded,
            }
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        log.exception("events: summary failed")
        return {"total": 0, "failed": 0, "degraded": 0, "devices": 0,
                "today_total": 0, "today_failed": 0, "today_degraded": 0}


def devices(data_dir: Path) -> list[dict[str, Any]]:
    """Per-device rollup, busiest first — the honest 'user by user' view (a device, not a
    person, until login). One row per anonymous id: how many mixes it made, how many broke or
    came out degraded, and when it was last seen."""
    try:
        conn = _connect(data_dir)
        try:
            rows = conn.execute(
                """
                SELECT COALESCE(user_id, '(no id)') AS user_id,
                       COUNT(*) AS total,
                       SUM(CASE WHEN health='red'   THEN 1 ELSE 0 END) AS failed,
                       SUM(CASE WHEN health='amber' THEN 1 ELSE 0 END) AS degraded,
                       MAX(created_at) AS last_at
                FROM events
                GROUP BY COALESCE(user_id, '(no id)')
                ORDER BY total DESC, last_at DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        log.exception("events: devices rollup failed")
        return []
