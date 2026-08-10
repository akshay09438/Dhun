"""Tests for the ops dashboard rollups (app/events.py): the MUSIC, WHEN, HEALTH and one-person views.

Each rollup answers one operator question, so each test pins the answer to that question rather
than the shape of the SQL. The store takes its data_dir from the caller, so tests point it at tmp_path.
"""
from app import events

BEAT_A, BEAT_B = "a" * 64, "b" * 64
VOC_X, VOC_Y = "x" * 64, "y" * 64


def _mix(data_dir, mix_id, *, s1=BEAT_A, s2=VOC_X, n1="Father Ocean", n2="Der Lagi",
         status="ok", anomalies=None, user_id="dev-1", created_at=None, take=1, **kw):
    events.record_mix(data_dir, mix_id=mix_id.ljust(64, "0"), status=status, user_id=user_id,
                      song1_id=s1, song2_id=s2, song1_name=n1, song2_name=n2,
                      rule=1, take=take, anomalies=anomalies, created_at=created_at, **kw)


# --- MUSIC view -------------------------------------------------------------------------

def test_song_stats_separates_beat_use_from_vocal_use(tmp_path):
    """The catalog-quality question: is a song being used as a beat, as a vocal, or not at all."""
    _mix(tmp_path, "1", s1=BEAT_A, s2=VOC_X)
    _mix(tmp_path, "2", s1=BEAT_A, s2=VOC_Y, n2="Tujhe Bhula Diya")
    _mix(tmp_path, "3", s1=BEAT_B, s2=VOC_X, n1="Innerbloom")

    rows = {r["song_id"]: r for r in events.song_stats(tmp_path)}
    assert rows[BEAT_A]["as_beat"] == 2 and rows[BEAT_A]["as_vocal"] == 0
    assert rows[VOC_X]["as_vocal"] == 2 and rows[VOC_X]["as_beat"] == 0
    assert rows[BEAT_B]["as_beat"] == 1


def test_song_stats_counts_failures_and_degradations_per_song(tmp_path):
    """"Every mix using this song is degraded" is the signal that a catalog entry is the problem."""
    _mix(tmp_path, "1", s1=BEAT_A, status="failed")
    _mix(tmp_path, "2", s1=BEAT_A, anomalies=[{"code": "key_measured", "severity": "warn"}])
    _mix(tmp_path, "3", s1=BEAT_A)
    row = next(r for r in events.song_stats(tmp_path) if r["song_id"] == BEAT_A)
    assert row["as_beat"] == 3
    assert row["failed"] == 1
    assert row["degraded"] == 1


def test_song_stats_reports_the_most_frequent_partner(tmp_path):
    _mix(tmp_path, "1", s1=BEAT_A, s2=VOC_X, n2="Der Lagi")
    _mix(tmp_path, "2", s1=BEAT_A, s2=VOC_X, n2="Der Lagi")
    _mix(tmp_path, "3", s1=BEAT_A, s2=VOC_Y, n2="Tujhe Bhula Diya")
    row = next(r for r in events.song_stats(tmp_path) if r["song_id"] == BEAT_A)
    assert row["top_partner"] == "Der Lagi"


def test_song_stats_is_busiest_first(tmp_path):
    """Ordered by total appearances, so the songs people actually reach for are at the top.
    Each mix uses a DISTINCT vocal here so only the beats accumulate — otherwise one repeated
    vocal would out-rank both beats and the ordering being tested would be hidden."""
    _mix(tmp_path, "1", s1=BEAT_B, s2="v0" * 32, n1="Rarely used")
    for i in range(3):
        _mix(tmp_path, f"x{i}", s1=BEAT_A, s2=f"v{i + 1}" * 32, n1="Popular")
    order = [r["song_id"] for r in events.song_stats(tmp_path)]
    assert order[0] == BEAT_A, "used 3 times, so it leads"
    assert order.index(BEAT_A) < order.index(BEAT_B)


def test_song_stats_ignores_sets_which_have_no_song_pair(tmp_path):
    """A set row carries its members in `extra`, not in song1_id/song2_id — counting it would
    add a phantom song with a null id."""
    events.record_set(tmp_path, set_id="s" * 64, status="ok", members=[{"kept": True}])
    _mix(tmp_path, "1")
    assert {r["song_id"] for r in events.song_stats(tmp_path)} == {BEAT_A, VOC_X}


def test_song_stats_on_an_empty_log_is_empty_not_an_error(tmp_path):
    assert events.song_stats(tmp_path) == []


# --- WHEN view --------------------------------------------------------------------------

def test_time_stats_buckets_by_hour_of_day(tmp_path):
    _mix(tmp_path, "1", created_at="2026-08-10T14:00:00+05:30")
    _mix(tmp_path, "2", created_at="2026-08-10T14:45:00+05:30")
    _mix(tmp_path, "3", created_at="2026-08-10T23:10:00+05:30")
    by_hour = events.time_stats(tmp_path)["by_hour"]
    assert len(by_hour) == 24, "a dense 24-slot array so the UI never fills gaps"
    assert by_hour[14] == 2
    assert by_hour[23] == 1
    assert sum(by_hour) == 3


def test_time_stats_buckets_by_weekday(tmp_path):
    # 2026-08-10 is a Monday; strftime('%w') is 0=Sunday, so Monday is index 1.
    _mix(tmp_path, "1", created_at="2026-08-10T12:00:00+05:30")
    _mix(tmp_path, "2", created_at="2026-08-10T13:00:00+05:30")
    _mix(tmp_path, "3", created_at="2026-08-09T13:00:00+05:30")   # Sunday
    by_weekday = events.time_stats(tmp_path)["by_weekday"]
    assert len(by_weekday) == 7
    assert by_weekday[1] == 2
    assert by_weekday[0] == 1


def test_time_stats_day_line_is_oldest_first_with_health(tmp_path):
    _mix(tmp_path, "1", created_at="2026-08-08T12:00:00+05:30")
    _mix(tmp_path, "2", created_at="2026-08-09T12:00:00+05:30", status="failed")
    _mix(tmp_path, "3", created_at="2026-08-09T13:00:00+05:30")
    days = events.time_stats(tmp_path)["by_day"]
    assert [d["day"] for d in days] == ["2026-08-08", "2026-08-09"], "read left-to-right in time"
    assert days[1]["n"] == 2 and days[1]["failed"] == 1


def test_time_stats_window_is_bounded(tmp_path):
    for d in range(1, 6):
        _mix(tmp_path, f"{d}", created_at=f"2026-08-0{d}T12:00:00+05:30")
    assert len(events.time_stats(tmp_path, days=2)["by_day"]) == 2
    assert events.time_stats(tmp_path, days=10_000)["days"] == 365, "clamped, never unbounded"


def test_time_stats_names_the_clock_its_hours_are_in(tmp_path, monkeypatch):
    """The page must be able to SAY whose timezone this is — a user abroad still lands in the
    operator's clock, and an unlabelled hours chart invites the wrong conclusion."""
    monkeypatch.setenv("PROMPTDJ_REPORT_TZ", "Asia/Kolkata")
    assert events.time_stats(tmp_path)["report_tz"] == "Asia/Kolkata"


# --- HEALTH view ------------------------------------------------------------------------

def test_health_reasons_ranks_failures(tmp_path):
    _mix(tmp_path, "1", status="failed", fail_reason="No beat detected.")
    _mix(tmp_path, "2", status="failed", fail_reason="No beat detected.")
    _mix(tmp_path, "3", status="failed", fail_reason="Two vocals overlap.")
    reasons = events.health_reasons(tmp_path)["failures"]
    assert reasons[0] == {"reason": "No beat detected.", "n": 2}


def test_health_reasons_ranks_degradation_codes(tmp_path):
    _mix(tmp_path, "1", anomalies=[{"code": "key_measured", "severity": "warn"}])
    _mix(tmp_path, "2", anomalies=[{"code": "key_measured", "severity": "warn"},
                                   {"code": "tempo_forced", "severity": "warn"}])
    degradations = events.health_reasons(tmp_path)["degradations"]
    assert degradations[0] == {"code": "key_measured", "n": 2}
    assert {"code": "tempo_forced", "n": 1} in degradations


def test_health_reasons_on_a_clean_log_is_empty(tmp_path):
    _mix(tmp_path, "1")
    assert events.health_reasons(tmp_path) == {"failures": [], "degradations": []}


# --- ONE PERSON view --------------------------------------------------------------------

def test_person_totals_and_health(tmp_path):
    _mix(tmp_path, "1", user_id="u1")
    _mix(tmp_path, "2", user_id="u1", status="failed")
    _mix(tmp_path, "3", user_id="u2")
    p = events.person(tmp_path, "u1")
    assert p["found"] is True
    assert p["total"] == 2 and p["failed"] == 1


def test_person_for_an_unknown_id_reports_not_found_rather_than_erroring(tmp_path):
    """The dashboard should render an empty state, not an error page, for an id with no activity."""
    p = events.person(tmp_path, "nobody")
    assert p["found"] is False and p["total"] == 0


def test_person_lists_their_favourite_songs(tmp_path):
    _mix(tmp_path, "1", user_id="u1", s1=BEAT_A, n1="Father Ocean")
    _mix(tmp_path, "2", user_id="u1", s1=BEAT_A, n1="Father Ocean")
    _mix(tmp_path, "3", user_id="u1", s1=BEAT_B, n1="Innerbloom")
    p = events.person(tmp_path, "u1")
    assert p["top_beats"][0] == {"name": "Father Ocean", "n": 2}


def test_person_has_its_own_hour_pattern(tmp_path):
    _mix(tmp_path, "1", user_id="u1", created_at="2026-08-10T21:00:00+05:30")
    _mix(tmp_path, "2", user_id="u2", created_at="2026-08-10T09:00:00+05:30")
    p = events.person(tmp_path, "u1")
    assert p["by_hour"][21] == 1
    assert p["by_hour"][9] == 0, "another person's activity must not leak into this page"


def test_person_carries_their_source_and_display_name(tmp_path):
    _mix(tmp_path, "1", user_id="752918281408610445",
         source=events.SOURCE_DISCORD, user_name="akshay09")
    p = events.person(tmp_path, "752918281408610445")
    assert p["source"] == "discord"
    assert p["user_name"] == "akshay09"


def test_sittings_groups_mixes_made_in_one_evening(tmp_path):
    """Six mixes in one sitting is a different story from six across six weeks, and a bare total
    cannot tell them apart."""
    for i, minute in enumerate(("00", "05", "20")):
        _mix(tmp_path, f"{i}", user_id="u1", created_at=f"2026-08-10T21:{minute}:00+05:30")
    assert events.person(tmp_path, "u1")["sittings"] == 1


def test_sittings_splits_on_a_long_gap(tmp_path):
    _mix(tmp_path, "1", user_id="u1", created_at="2026-08-10T21:00:00+05:30")
    _mix(tmp_path, "2", user_id="u1", created_at="2026-08-10T21:10:00+05:30")
    _mix(tmp_path, "3", user_id="u1", created_at="2026-08-12T09:00:00+05:30")
    assert events.person(tmp_path, "u1")["sittings"] == 2


def test_sittings_handles_a_history_mixing_legacy_and_new_stamps(tmp_path):
    """A naive legacy stamp next to an aware one must not raise "can't subtract offset-naive and
    offset-aware" — a real crash risk on the founder's own 3 days of pre-fix rows."""
    _mix(tmp_path, "1", user_id="u1", created_at="2026-08-08T21:00:00")           # naive (legacy)
    _mix(tmp_path, "2", user_id="u1", created_at="2026-08-10T21:00:00+05:30")     # aware (new)
    p = events.person(tmp_path, "u1")
    assert p["found"] is True
    assert p["sittings"] == 2


def test_person_active_days_and_take_stats(tmp_path):
    _mix(tmp_path, "1", user_id="u1", take=1, created_at="2026-08-08T21:00:00+05:30")
    _mix(tmp_path, "2", user_id="u1", take=3, created_at="2026-08-09T21:00:00+05:30")
    p = events.person(tmp_path, "u1")
    assert p["active_days"] == 2
    assert p["max_take"] == 3
