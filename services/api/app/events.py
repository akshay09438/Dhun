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
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

log = logging.getLogger("promptdj.events")

_DB_NAME = "events.db"

# The mixing rules, for a human-readable label on each row (mirrors the frontend
# types.ts RULE_LABELS and the backend rule_shuffle.RULES). Rule 2 is spec-only.
RULE_LABELS: dict[int, str] = {1: "Simple", 3: "Chop & repeat", 4: "Echo"}

# Where a mix was made FROM. Kept separate from `via` ('single' | 'set'), which describes
# how it was made, not where — overloading one column for both would lose information.
SOURCE_WEB = "web"
SOURCE_DISCORD = "discord"

# ---------------------------------------------------------------------------
# TIME. Read this before touching a timestamp.
#
# `created_at` is stored TIMEZONE-AWARE (ISO 8601 WITH the UTC offset, e.g.
# "2026-08-10T22:53:00+05:30"). That is the single source of truth for when something
# happened, and it is self-describing: it pins the real instant AND the wall clock the
# operator saw. Storing a naive local time (what this module did until 2026-08-10) is a
# silent trap — the same string means a different instant on a UTC cloud box than on a
# machine in IST, with nothing in the row to tell the two apart, so a time-of-day chart
# would quietly mix them.
#
# Day and hour ROLLUPS are a separate concern: they must be in ONE chosen zone or they
# cannot be compared. So each row also stores the pre-computed `local_day` / `local_hour`
# in the REPORT timezone (PROMPTDJ_REPORT_TZ, else the machine's own zone) — which makes
# every dashboard rollup a plain indexed GROUP BY instead of timezone arithmetic in SQL.
# These are DERIVED, never authoritative: `created_at` can always recompute them if the
# report zone ever changes, so this is not a one-way door.
#
# Rows written before this change have no offset and no local_day. They were written in
# the founder's own local zone, so reading their naive stamp AS report-local is correct —
# `_DAY` / `_HOUR` below fall back to exactly that, so no existing row is ever rewritten.
# ---------------------------------------------------------------------------
_REPORT_TZ_ENV = "PROMPTDJ_REPORT_TZ"

# SQL expressions for "which local day / hour is this row", new rows and legacy rows alike.
_DAY = "COALESCE(local_day, substr(created_at, 1, 10))"
_HOUR = "COALESCE(local_hour, CAST(substr(created_at, 12, 2) AS INTEGER))"


def rule_label(rule: int | None) -> str:
    return RULE_LABELS.get(rule, "") if rule else ""


def _report_zone() -> tzinfo | None:
    """The zone every day/hour number is expressed in. `None` means "use this machine's
    own zone", which is the right default for a solo operator. Set PROMPTDJ_REPORT_TZ to an
    IANA name (e.g. "Asia/Kolkata") to pin it — REQUIRED once the API runs on a cloud box in
    UTC, otherwise the rollups would be grouped by UTC days rather than the operator's."""
    name = os.environ.get(_REPORT_TZ_ENV, "").strip()
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 — a bad zone name must not break telemetry
        log.warning("events: ignoring unknown %s=%r; using this machine's zone", _REPORT_TZ_ENV, name)
        return None


def _to_report(dt: datetime) -> datetime:
    """Convert an aware datetime into the report zone (DST-correct when an IANA name is set)."""
    zone = _report_zone()
    return dt.astimezone(zone) if zone is not None else dt.astimezone()


def report_tz_label() -> str:
    """The report zone's name, so the dashboard can SAY which clock its hours are in — a user
    in another country still lands in the operator's timezone, and the page must not pretend
    otherwise."""
    name = os.environ.get(_REPORT_TZ_ENV, "").strip()
    if name and _report_zone() is not None:
        return name
    return datetime.now().astimezone().strftime("%Z") or "local time"


def _derive_local(iso: str) -> tuple[str | None, int | None]:
    """The (local_day, local_hour) a stored stamp rolls up under. An offset-carrying stamp is
    converted; a naive one (a legacy row, or a test-injected stamp) is read as already-local."""
    try:
        dt = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return None, None
    if dt.tzinfo is None:
        return dt.date().isoformat(), dt.hour
    local = _to_report(dt)
    return local.date().isoformat(), local.hour


def _now_iso() -> str:
    """Now, as a timezone-AWARE ISO stamp. `.astimezone()` attaches this machine's real offset."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def today_local() -> str:
    """Today's date in the report zone — the basis for every "today" count."""
    return _to_report(datetime.now().astimezone()).date().isoformat()


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
            extra       TEXT,                      -- JSON blob (tempo/key facts, audio_url, set members)
            source      TEXT,                      -- 'web' | 'discord' (NULL on rows predating this column)
            user_name   TEXT,                      -- display name where known (a Discord username); web has none
            local_day   TEXT,                      -- YYYY-MM-DD in the report zone (derived; see the TIME note)
            local_hour  INTEGER                    -- 0-23 in the report zone (derived)
        )
        """
    )
    _migrate(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_id ON events (id DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_user ON events (user_id)")
    # The dashboard's rollups group by local day and filter by source; index both so the
    # per-day / per-source panels stay cheap as the log grows.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_day ON events (local_day)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_source ON events (source)")
    return conn


# Columns added after the table first shipped. Adding one is idempotent and additive: an
# existing DB gains the column as NULL and every read COALESCEs a sensible fallback, so no
# row is ever rewritten and no deployment needs a migration step.
_ADDED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("source", "TEXT"),
    ("user_name", "TEXT"),
    ("local_day", "TEXT"),
    ("local_hour", "INTEGER"),
)


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring an events.db created by an older build up to the current columns."""
    have = {r["name"] for r in conn.execute("PRAGMA table_info(events)")}
    for name, decl in _ADDED_COLUMNS:
        if name not in have:
            conn.execute(f"ALTER TABLE events ADD COLUMN {name} {decl}")


def _insert(data_dir: Path, row: dict[str, Any]) -> None:
    """Write one row. Swallows every error — telemetry must never break the caller."""
    try:
        conn = _connect(data_dir)
        try:
            cols = ("created_at", "kind", "via", "ref_id", "user_id", "song1_id", "song2_id",
                    "song1_name", "song2_name", "rule", "rule_label", "take", "status", "health",
                    "fail_reason", "anomalies", "extra", "source", "user_name",
                    "local_day", "local_hour")
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
    source: str | None = None,
    user_name: str | None = None,
) -> None:
    """Record one mix outcome. `status` is 'ok' or 'failed'. Non-fatal by construction.

    `source` is where it was made ('web' | 'discord') and `user_name` a display name where one
    exists (a Discord username; the web app has no login yet). Both are recorded only — like
    `user_id`, they never reach the cache id or the audio."""
    ex = dict(extra or {})
    if status == "ok":
        ex.setdefault("audio_url", f"/mix/{mix_id}/audio")
    stamp = created_at or _now_iso()
    day, hour = _derive_local(stamp)
    _insert(data_dir, {
        "created_at": stamp,
        "source": source,
        "user_name": user_name,
        "local_day": day,
        "local_hour": hour,
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
    source: str | None = None,
    user_name: str | None = None,
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
    stamp = created_at or _now_iso()
    day, hour = _derive_local(stamp)
    _insert(data_dir, {
        "created_at": stamp,
        "source": source,
        "user_name": user_name,
        "local_day": day,
        "local_hour": hour,
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
    """The health strip: all-time and today's counts, how many distinct people have made
    anything, and the Web-vs-Discord split. "Today" is the report zone's day (see the TIME
    note) — grouping by the raw stored string would silently use UTC days on a cloud box.
    Numbers only; the dashboard turns counts into rates."""
    today = today_local()
    try:
        conn = _connect(data_dir)
        try:
            def _count(sql: str, params: tuple = ()) -> int:
                return conn.execute(sql, params).fetchone()["n"]

            total = _count("SELECT COUNT(*) AS n FROM events")
            failed = _count("SELECT COUNT(*) AS n FROM events WHERE health='red'")
            degraded = _count("SELECT COUNT(*) AS n FROM events WHERE health='amber'")
            devices = _count("SELECT COUNT(DISTINCT user_id) AS n FROM events WHERE user_id IS NOT NULL")
            today_total = _count(f"SELECT COUNT(*) AS n FROM events WHERE {_DAY}=?", (today,))
            today_failed = _count(
                f"SELECT COUNT(*) AS n FROM events WHERE health='red' AND {_DAY}=?", (today,))
            today_degraded = _count(
                f"SELECT COUNT(*) AS n FROM events WHERE health='amber' AND {_DAY}=?", (today,))
            # Where the work is coming from. A row predating the `source` column counts as
            # 'unknown' rather than being silently attributed to either surface.
            by_source = {r["s"]: r["n"] for r in conn.execute(
                "SELECT COALESCE(source,'unknown') AS s, COUNT(*) AS n FROM events GROUP BY s")}
            people_by_source = {r["s"]: r["n"] for r in conn.execute(
                """SELECT COALESCE(source,'unknown') AS s, COUNT(DISTINCT user_id) AS n
                   FROM events WHERE user_id IS NOT NULL GROUP BY s""")}
            return {
                "total": total, "failed": failed, "degraded": degraded, "devices": devices,
                "today_total": today_total, "today_failed": today_failed, "today_degraded": today_degraded,
                "mixes": _count("SELECT COUNT(*) AS n FROM events WHERE kind='mix'"),
                "sets": _count("SELECT COUNT(*) AS n FROM events WHERE kind='set'"),
                "by_source": by_source,
                "people_by_source": people_by_source,
                "report_tz": report_tz_label(),
            }
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        log.exception("events: summary failed")
        return {"total": 0, "failed": 0, "degraded": 0, "devices": 0,
                "today_total": 0, "today_failed": 0, "today_degraded": 0,
                "mixes": 0, "sets": 0, "by_source": {}, "people_by_source": {},
                "report_tz": report_tz_label()}


def devices(data_dir: Path) -> list[dict[str, Any]]:
    """Per-device rollup, busiest first — the honest 'user by user' view (a device, not a
    person, until login). One row per anonymous id: how many mixes it made, how many broke or
    came out degraded, and when it was last seen."""
    try:
        conn = _connect(data_dir)
        try:
            rows = conn.execute(
                f"""
                SELECT COALESCE(user_id, '(no id)') AS user_id,
                       COUNT(*) AS total,
                       SUM(CASE WHEN health='red'   THEN 1 ELSE 0 END) AS failed,
                       SUM(CASE WHEN health='amber' THEN 1 ELSE 0 END) AS degraded,
                       MIN(created_at) AS first_at,
                       MAX(created_at) AS last_at,
                       -- the report-zone days, so retention compares like with like
                       MIN({_DAY}) AS first_day,
                       MAX({_DAY}) AS last_day,
                       COUNT(DISTINCT {_DAY}) AS active_days,
                       -- one person could in principle appear from both surfaces; show the
                       -- newest one we saw rather than inventing a merged label
                       (SELECT COALESCE(e2.source,'unknown') FROM events e2
                         WHERE COALESCE(e2.user_id,'(no id)') = COALESCE(events.user_id,'(no id)')
                         ORDER BY e2.id DESC LIMIT 1) AS source,
                       (SELECT e3.user_name FROM events e3
                         WHERE COALESCE(e3.user_id,'(no id)') = COALESCE(events.user_id,'(no id)')
                           AND e3.user_name IS NOT NULL
                         ORDER BY e3.id DESC LIMIT 1) AS user_name
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


def retention(data_dir: Path) -> dict[str, Any]:
    """Honest, device-level retention — 'are the same people coming back to make more?'. It counts
    DEVICES (a persistent per-browser tag), not verified people: a returning device is a real return
    signal, but a new browser / cleared storage reads as new, so treat these as directional until login.

    - total_devices:     distinct devices that have made anything
    - returning_devices:  devices active on 2+ distinct days (came back another day at least once)
    - new_today:          devices whose FIRST activity was today
    - returning_today:    devices active today whose first activity was on an earlier day
    Dates are the REPORT ZONE's day (same basis as the summary strip) — read off each device's
    first_day/last_day rollup rather than slicing the raw stamp, which would be the UTC day
    once the API runs on a cloud box."""
    today = today_local()
    devs = devices(data_dir)
    total = len(devs)
    new_today = sum(1 for d in devs if (d.get("first_day") or "") == today)
    returning_today = sum(
        1 for d in devs
        if (d.get("last_day") or "") == today and (d.get("first_day") or "") < today
    )
    returning_devices = sum(1 for d in devs if (d.get("active_days") or 0) >= 2)
    return {
        "total_devices": total,
        "returning_devices": returning_devices,
        "new_today": new_today,
        "returning_today": returning_today,
    }


# ---------------------------------------------------------------------------
# DASHBOARD ROLLUPS
#
# Everything below answers ONE operator question and returns plain numbers — the dashboard
# draws them with bare divs, not a charting library. All of them aggregate IN SQL (a COUNT or
# a GROUP BY over an indexed column), so none is an unbounded fetch: the only place rows are
# read into memory is one person's own history, which is capped.
# ---------------------------------------------------------------------------

# How far apart two mixes can be and still count as the same sitting at the keyboard.
_SITTING_GAP_MINUTES = 30
# Hard ceiling on how many of one person's rows the sittings calculation will read.
_PERSON_ROW_CAP = 2000


def _all(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def song_stats(data_dir: Path) -> list[dict[str, Any]]:
    """MUSIC-level rollup: for each catalog song, how often it was picked as the beat, how often
    as the vocal, how often a mix using it broke or came out degraded, and who it is most often
    paired with. This is what says "these two songs are all anyone uses" or "every mix with this
    song is degraded" — the catalog-quality signal the mix feed alone cannot show.

    Only 'mix' rows have a song pair (a 'set' row's members live in `extra`), so sets are skipped."""
    try:
        conn = _connect(data_dir)
        try:
            def _side(id_col: str, name_col: str) -> dict[str, dict[str, Any]]:
                rows = _all(conn, f"""
                    SELECT {id_col} AS sid,
                           MAX({name_col}) AS name,
                           COUNT(*) AS used,
                           SUM(CASE WHEN health='red'   THEN 1 ELSE 0 END) AS failed,
                           SUM(CASE WHEN health='amber' THEN 1 ELSE 0 END) AS degraded
                    FROM events
                    WHERE kind='mix' AND {id_col} IS NOT NULL
                    GROUP BY {id_col}
                """)
                return {r["sid"]: r for r in rows}

            beats, vocals = _side("song1_id", "song1_name"), _side("song2_id", "song2_name")

            # Most frequent partner per song, both directions. Bounded by catalog size squared
            # (a 30-song catalog is at most a few hundred rows), so this is cheap to read.
            pairs = _all(conn, """
                SELECT song1_id, song2_id, MAX(song1_name) AS n1, MAX(song2_name) AS n2,
                       COUNT(*) AS n
                FROM events
                WHERE kind='mix' AND song1_id IS NOT NULL AND song2_id IS NOT NULL
                GROUP BY song1_id, song2_id
            """)
            best: dict[str, tuple[int, str]] = {}
            for p in pairs:
                for sid, partner in ((p["song1_id"], p["n2"]), (p["song2_id"], p["n1"])):
                    if partner and p["n"] > best.get(sid, (0, ""))[0]:
                        best[sid] = (p["n"], partner)

            out: list[dict[str, Any]] = []
            for sid in set(beats) | set(vocals):
                b, v = beats.get(sid), vocals.get(sid)
                as_beat = (b or {}).get("used", 0)
                as_vocal = (v or {}).get("used", 0)
                out.append({
                    "song_id": sid,
                    "name": (b or {}).get("name") or (v or {}).get("name") or sid[:8],
                    "as_beat": as_beat,
                    "as_vocal": as_vocal,
                    "used": as_beat + as_vocal,
                    "failed": (b or {}).get("failed", 0) + (v or {}).get("failed", 0),
                    "degraded": (b or {}).get("degraded", 0) + (v or {}).get("degraded", 0),
                    "top_partner": best.get(sid, (0, None))[1],
                })
            out.sort(key=lambda r: (-r["used"], r["name"]))
            return out
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — a rollup failure must never 500 the dashboard
        log.exception("events: song_stats failed")
        return []


def _bucketed(conn: sqlite3.Connection, where: str = "", params: tuple = ()) -> dict[str, Any]:
    """The by-hour / by-weekday shape, shared by the WHEN view and one person's page."""
    clause = f" AND {where}" if where else ""
    by_hour = {int(r["h"]): r["n"] for r in conn.execute(
        f"SELECT {_HOUR} AS h, COUNT(*) AS n FROM events WHERE {_HOUR} IS NOT NULL{clause} GROUP BY h",
        params)}
    by_dow = {int(r["d"]): r["n"] for r in conn.execute(
        f"""SELECT CAST(strftime('%w', {_DAY}) AS INTEGER) AS d, COUNT(*) AS n
            FROM events WHERE {_DAY} IS NOT NULL{clause} GROUP BY d""", params)}
    return {
        # Dense 0-23 / 0-6 arrays so the dashboard never has to fill gaps itself. strftime('%w')
        # is 0=Sunday, which is the order the UI labels them in.
        "by_hour": [by_hour.get(h, 0) for h in range(24)],
        "by_weekday": [by_dow.get(d, 0) for d in range(7)],
    }


def time_stats(data_dir: Path, days: int = 30) -> dict[str, Any]:
    """WHEN-level rollup: activity by hour of day, by weekday, and a day-by-day line for the last
    `days` days. Bounded on purpose — a window is both cheaper and what an operator actually reads.

    HONEST LIMIT, surfaced in the UI via `report_tz`: these hours are the OPERATOR's clock. A user
    in another country making a mix at their 9pm lands here at whatever that instant is locally, so
    this shows when the service is busy, not when a given person likes to make music."""
    days = max(1, min(int(days), 365))
    try:
        conn = _connect(data_dir)
        try:
            out = _bucketed(conn)
            # Only days that actually have activity; the UI fills the calendar gaps.
            out["by_day"] = _all(conn, f"""
                SELECT {_DAY} AS day, COUNT(*) AS n,
                       SUM(CASE WHEN health='red'   THEN 1 ELSE 0 END) AS failed,
                       SUM(CASE WHEN health='amber' THEN 1 ELSE 0 END) AS degraded
                FROM events
                WHERE {_DAY} IS NOT NULL
                GROUP BY day ORDER BY day DESC LIMIT ?
            """, (days,))
            out["by_day"].reverse()          # oldest -> newest, the direction a line is read
            out["days"] = days
            out["report_tz"] = report_tz_label()
            return out
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        log.exception("events: time_stats failed")
        return {"by_hour": [0] * 24, "by_weekday": [0] * 7, "by_day": [], "days": days,
                "report_tz": report_tz_label()}


def health_reasons(data_dir: Path) -> dict[str, Any]:
    """WHAT IS BREAKING: failure reasons and degradation codes, most common first. Turns a feed of
    red and amber dots into a ranked list of things to actually go and fix."""
    try:
        conn = _connect(data_dir)
        try:
            failures = _all(conn, """
                SELECT COALESCE(fail_reason, '(no reason recorded)') AS reason, COUNT(*) AS n
                FROM events WHERE status <> 'ok' GROUP BY reason ORDER BY n DESC
            """)
            # Anomalies are a JSON array per row, so they are counted here rather than in SQL. Only
            # amber rows carry them, which keeps this to a small slice of the log.
            codes: dict[str, int] = {}
            for r in conn.execute(
                    "SELECT anomalies FROM events WHERE health='amber' AND anomalies IS NOT NULL"):
                try:
                    for a in json.loads(r["anomalies"] or "[]"):
                        if isinstance(a, dict) and a.get("code"):
                            codes[a["code"]] = codes.get(a["code"], 0) + 1
                except (ValueError, TypeError):
                    continue
            return {
                "failures": failures,
                "degradations": [{"code": c, "n": n}
                                 for c, n in sorted(codes.items(), key=lambda kv: -kv[1])],
            }
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        log.exception("events: health_reasons failed")
        return {"failures": [], "degradations": []}


def person(data_dir: Path, user_id: str) -> dict[str, Any]:
    """ONE person's page: their totals, the songs they reach for, when they use it, and how many
    separate sittings they have had. This is the "go inside a user id" view — on Discord `user_id`
    is a real account, so it is trustworthy; on the web it is a per-browser tag, so the same human
    on a phone and a laptop reads as two people."""
    try:
        conn = _connect(data_dir)
        try:
            head = conn.execute(f"""
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN health='red'   THEN 1 ELSE 0 END) AS failed,
                       SUM(CASE WHEN health='amber' THEN 1 ELSE 0 END) AS degraded,
                       SUM(CASE WHEN kind='set'     THEN 1 ELSE 0 END) AS sets,
                       MIN(created_at) AS first_at, MAX(created_at) AS last_at,
                       MIN({_DAY}) AS first_day, MAX({_DAY}) AS last_day,
                       COUNT(DISTINCT {_DAY}) AS active_days,
                       MAX(take) AS max_take, AVG(take) AS avg_take
                FROM events WHERE user_id = ?
            """, (user_id,)).fetchone()
            if head is None or not head["total"]:
                return {"user_id": user_id, "total": 0, "found": False}

            out: dict[str, Any] = {"user_id": user_id, "found": True, **dict(head)}
            out["source"] = (conn.execute(
                "SELECT COALESCE(source,'unknown') AS s FROM events WHERE user_id=? ORDER BY id DESC LIMIT 1",
                (user_id,)).fetchone() or {"s": "unknown"})["s"]
            name_row = conn.execute(
                "SELECT user_name FROM events WHERE user_id=? AND user_name IS NOT NULL "
                "ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
            out["user_name"] = name_row["user_name"] if name_row else None
            out.update(_bucketed(conn, "user_id = ?", (user_id,)))

            out["top_beats"] = _all(conn, """
                SELECT MAX(song1_name) AS name, COUNT(*) AS n FROM events
                WHERE user_id=? AND kind='mix' AND song1_id IS NOT NULL
                GROUP BY song1_id ORDER BY n DESC, name LIMIT 5
            """, (user_id,))
            out["top_vocals"] = _all(conn, """
                SELECT MAX(song2_name) AS name, COUNT(*) AS n FROM events
                WHERE user_id=? AND kind='mix' AND song2_id IS NOT NULL
                GROUP BY song2_id ORDER BY n DESC, name LIMIT 5
            """, (user_id,))
            out["sittings"] = _sittings(conn, user_id)
            out["report_tz"] = report_tz_label()
            return out
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        log.exception("events: person(%s) failed", user_id)
        return {"user_id": user_id, "total": 0, "found": False}


def _sittings(conn: sqlite3.Connection, user_id: str) -> int:
    """How many separate visits this person made — consecutive mixes more than
    _SITTING_GAP_MINUTES apart start a new one. Six mixes in one evening is a very different
    story from six mixes across six weeks, and a raw total cannot tell them apart.

    This is the one place rows are read rather than aggregated (consecutive-row gaps are awkward
    in SQL across SQLite versions), so it is capped: one person's own stamps, at most
    _PERSON_ROW_CAP of them."""
    stamps: list[datetime] = []
    for r in conn.execute(
            "SELECT created_at FROM events WHERE user_id=? ORDER BY created_at LIMIT ?",
            (user_id, _PERSON_ROW_CAP)):
        try:
            dt = datetime.fromisoformat(r["created_at"])
        except (ValueError, TypeError):
            continue
        # Compare like with like: a naive legacy stamp gets this machine's offset attached, so a
        # mixed-vintage history cannot raise "can't subtract offset-naive and offset-aware".
        stamps.append(dt if dt.tzinfo else dt.astimezone())
    if not stamps:
        return 0
    gap = _SITTING_GAP_MINUTES * 60
    return 1 + sum(1 for a, b in zip(stamps, stamps[1:])
                   if (b - a).total_seconds() > gap)
