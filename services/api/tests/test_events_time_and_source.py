"""Tests for the two things added to the ops event store on 2026-08-10:

1. TIMEZONE CORRECTNESS. `created_at` is stored timezone-AWARE, and day/hour rollups happen in
   one chosen report zone. The bug being pinned: a naive local stamp means a different instant on
   a UTC cloud box than on the founder's IST machine, with nothing in the row to tell them apart —
   so "activity by hour" would silently blend two different clocks across the launch date.
2. SOURCE ATTRIBUTION. Every row records whether it came from the web app or the Discord bot, plus
   a display name where the surface has one.

The store takes its data_dir from the caller, so every test just points it at tmp_path.
"""
import sqlite3
from datetime import datetime

import pytest

from app import events


def _mix(data_dir, **kw):
    base = dict(mix_id="m" * 64, status="ok", user_id="dev-1",
                song1_id="a" * 64, song2_id="b" * 64,
                song1_name="Father Ocean", song2_name="Der Lagi", rule=1, take=1)
    base.update(kw)
    events.record_mix(data_dir, **base)


def _rows(data_dir):
    conn = sqlite3.connect(data_dir / "events.db")
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM events ORDER BY id")]
    finally:
        conn.close()


# --- 1. the timezone fix ----------------------------------------------------------------

def test_created_at_carries_a_utc_offset(tmp_path):
    """The core fix: a stored stamp is self-describing, so it can never be misread as a
    different instant on a machine in another zone."""
    _mix(tmp_path)
    stamp = _rows(tmp_path)[0]["created_at"]
    parsed = datetime.fromisoformat(stamp)
    assert parsed.tzinfo is not None, f"{stamp!r} has no timezone — this is the bug being fixed"
    assert parsed.utcoffset() is not None


def test_local_day_and_hour_are_stored_for_rollups(tmp_path):
    _mix(tmp_path, created_at="2026-08-10T22:53:00+05:30")
    row = _rows(tmp_path)[0]
    assert row["local_day"] == "2026-08-10"
    assert row["local_hour"] == 22


def test_rollup_uses_the_report_zone_not_the_stored_offset(tmp_path, monkeypatch):
    """A mix made at 22:53 IST is 17:23 UTC — the SAME instant, a different wall clock. With the
    report zone pinned to UTC the rollup must follow the report zone, which is the whole point of
    having one: otherwise two servers group the same event under different days."""
    monkeypatch.setenv("PROMPTDJ_REPORT_TZ", "UTC")
    _mix(tmp_path, created_at="2026-08-10T22:53:00+05:30")
    row = _rows(tmp_path)[0]
    assert row["local_hour"] == 17
    assert row["local_day"] == "2026-08-10"


def test_a_stamp_that_crosses_midnight_rolls_up_under_the_report_days_date(tmp_path, monkeypatch):
    """01:30 IST on the 11th is 20:00 UTC on the 10th — the day, not just the hour, differs. This is
    exactly the case a raw substr(created_at,1,10) would get wrong."""
    monkeypatch.setenv("PROMPTDJ_REPORT_TZ", "UTC")
    _mix(tmp_path, created_at="2026-08-11T01:30:00+05:30")
    row = _rows(tmp_path)[0]
    assert row["local_day"] == "2026-08-10"
    assert row["local_hour"] == 20


def test_an_unknown_report_zone_is_ignored_rather_than_breaking_telemetry(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMPTDJ_REPORT_TZ", "Not/AZone")
    _mix(tmp_path)                     # must not raise
    assert events.query_events(tmp_path)["total"] == 1


def test_report_tz_label_names_the_clock_the_numbers_are_in(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMPTDJ_REPORT_TZ", "Asia/Kolkata")
    assert events.report_tz_label() == "Asia/Kolkata"


# --- 2. legacy rows keep working (no data is ever rewritten) ----------------------------

def _legacy_row(data_dir, created_at, user_id="old-1"):
    """Insert a row the way the pre-fix build did: naive stamp, and no local_day/local_hour."""
    conn = events._connect(data_dir)
    try:
        conn.execute(
            """INSERT INTO events (created_at, kind, via, ref_id, user_id, status, health)
               VALUES (?, 'mix', 'single', ?, ?, 'ok', 'green')""",
            (created_at, f"legacy-{created_at}", user_id),
        )
        conn.commit()
    finally:
        conn.close()


def test_a_legacy_naive_row_still_counts_toward_today(tmp_path):
    """The 68 rows written before this change have no offset and no local_day. They were written in
    the founder's own zone, so reading their naive stamp as report-local is correct — and it means
    no existing row has to be rewritten."""
    today = events.today_local()
    _legacy_row(tmp_path, f"{today}T09:00:00")
    assert events.summary(tmp_path)["today_total"] == 1


def test_legacy_and_new_rows_roll_up_together(tmp_path):
    today = events.today_local()
    _legacy_row(tmp_path, f"{today}T09:00:00")
    _mix(tmp_path)
    s = events.summary(tmp_path)
    assert s["total"] == 2
    assert s["today_total"] == 2


def test_active_days_counts_report_days_for_a_legacy_row(tmp_path):
    _legacy_row(tmp_path, "2026-08-01T09:00:00", user_id="u1")
    _legacy_row(tmp_path, "2026-08-02T09:00:00", user_id="u1")
    dev = next(d for d in events.devices(tmp_path) if d["user_id"] == "u1")
    assert dev["active_days"] == 2
    assert dev["first_day"] == "2026-08-01"
    assert dev["last_day"] == "2026-08-02"


def test_migration_adds_the_new_columns_without_losing_rows(tmp_path):
    """An events.db from an older build must gain the columns in place — additively, so a
    deployment never needs a migration step and no row is lost."""
    conn = sqlite3.connect(tmp_path / "events.db")
    conn.execute(
        """CREATE TABLE events (
               id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, kind TEXT NOT NULL,
               via TEXT NOT NULL DEFAULT 'single', ref_id TEXT NOT NULL, user_id TEXT,
               song1_id TEXT, song2_id TEXT, song1_name TEXT, song2_name TEXT, rule INTEGER,
               rule_label TEXT, take INTEGER, status TEXT NOT NULL, health TEXT NOT NULL,
               fail_reason TEXT, anomalies TEXT, extra TEXT)"""
    )
    conn.execute(
        """INSERT INTO events (created_at, kind, via, ref_id, status, health)
           VALUES ('2026-08-01T10:00:00', 'mix', 'single', 'pre-existing', 'ok', 'green')"""
    )
    conn.commit()
    conn.close()

    _mix(tmp_path)                                  # opening the store migrates it

    conn = events._connect(tmp_path)
    try:
        have = {r["name"] for r in conn.execute("PRAGMA table_info(events)")}
    finally:
        conn.close()
    assert {name for name, _ in events._ADDED_COLUMNS} <= have
    assert events.query_events(tmp_path)["total"] == 2, "the pre-existing row must survive"


# --- 3. source + username attribution --------------------------------------------------

def test_source_and_user_name_are_recorded(tmp_path):
    _mix(tmp_path, source=events.SOURCE_DISCORD, user_name="akshay09")
    row = events.query_events(tmp_path)["events"][0]
    assert row["source"] == "discord"
    assert row["user_name"] == "akshay09"


def test_summary_splits_activity_by_source(tmp_path):
    _mix(tmp_path, mix_id="1" * 64, user_id="w1", source=events.SOURCE_WEB)
    _mix(tmp_path, mix_id="2" * 64, user_id="d1", source=events.SOURCE_DISCORD)
    _mix(tmp_path, mix_id="3" * 64, user_id="d2", source=events.SOURCE_DISCORD)
    s = events.summary(tmp_path)
    assert s["by_source"] == {"web": 1, "discord": 2}
    assert s["people_by_source"] == {"web": 1, "discord": 2}


def test_a_row_with_no_source_reads_as_unknown_not_as_web(tmp_path):
    """Rows made before the column existed must not be silently attributed to either surface —
    guessing would make the Web-vs-Discord split quietly wrong."""
    _mix(tmp_path)
    assert events.summary(tmp_path)["by_source"] == {"unknown": 1}


def test_devices_surfaces_the_source_and_the_display_name(tmp_path):
    _mix(tmp_path, mix_id="1" * 64, user_id="d1",
         source=events.SOURCE_DISCORD, user_name="akshay09")
    dev = next(d for d in events.devices(tmp_path) if d["user_id"] == "d1")
    assert dev["source"] == "discord"
    assert dev["user_name"] == "akshay09"


def test_a_later_row_without_a_name_does_not_erase_the_known_name(tmp_path):
    """The rollup keeps the most recent name we actually have, so one un-named row can't blank
    out a person who is otherwise identified."""
    _mix(tmp_path, mix_id="1" * 64, user_id="d1",
         source=events.SOURCE_DISCORD, user_name="akshay09")
    _mix(tmp_path, mix_id="2" * 64, user_id="d1", source=events.SOURCE_DISCORD)
    dev = next(d for d in events.devices(tmp_path) if d["user_id"] == "d1")
    assert dev["user_name"] == "akshay09"


def test_set_records_source_and_name_too(tmp_path):
    events.record_set(tmp_path, set_id="s" * 64, status="ok", user_id="d1",
                      members=[{"kept": True}], source=events.SOURCE_DISCORD, user_name="akshay09")
    row = events.query_events(tmp_path)["events"][0]
    assert row["kind"] == "set"
    assert row["source"] == "discord"
    assert row["user_name"] == "akshay09"


# --- 4. retention now compares report-zone days -----------------------------------------

def test_retention_counts_a_returning_person_by_report_days(tmp_path):
    today = events.today_local()
    _legacy_row(tmp_path, "2026-08-01T09:00:00", user_id="u1")
    _legacy_row(tmp_path, f"{today}T09:00:00", user_id="u1")
    _legacy_row(tmp_path, f"{today}T10:00:00", user_id="u2")
    r = events.retention(tmp_path)
    assert r["total_devices"] == 2
    assert r["returning_devices"] == 1      # u1 was active on two separate days
    assert r["new_today"] == 1              # u2 showed up for the first time today
    assert r["returning_today"] == 1        # u1 came back today


@pytest.mark.parametrize("bad", ["", "not-a-date", None])
def test_an_unparseable_stamp_never_raises(tmp_path, bad):
    """Telemetry is non-fatal by construction: a malformed stamp must degrade, never crash a mix."""
    assert events._derive_local(bad) == (None, None)
