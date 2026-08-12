"""Grinder's own small database: grind numbers, reactions, and what's been pinned.

WHY THE BOT HAS ITS OWN STORE rather than writing to the engine's `events.db`:
the bot talks to the engine over HTTP and nothing else. Reaching into the engine's SQLite from a
second process would make two programs owners of one file and turn a schema change into a
cross-service migration. This file is small, local, and entirely the bot's own.

The cost, recorded honestly: the ops dashboard reads `events.db`, so it does NOT see reactions yet.
Surfacing them there is a follow-up (an engine endpoint the bot posts to, or the dashboard reading
both), deliberately not built tonight.

REACTIONS ARE THE PRODUCT. 🔥 / 💀 / 😐 are the only signal that says whether a grind actually
landed, so they are recorded per person per grind, and a removal deletes the row - somebody
changing their mind must not be counted twice.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "grinder.db"

# One connection, one lock. discord.py runs on a single event loop, but voice playback and the
# render waiter both touch this, and SQLite objects are not safe to share across threads unclaimed.
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS grinds (
    number      INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id  INTEGER UNIQUE,          -- the card, so a reaction can find its grind
    guild_id    INTEGER,
    channel_id  INTEGER,
    user_id     INTEGER NOT NULL,        -- who made it (owner: only they may append)
    user_name   TEXT,
    created_at  TEXT    NOT NULL,
    pairs       TEXT    NOT NULL,        -- JSON [[beat_id, vocal_id, beat_name, vocal_name], ...]
    ref_id      TEXT,                    -- engine mix_id or set_id, for tracing back
    pinned_at   TEXT                     -- set once 📌 has posted it to the showcase
);
CREATE TABLE IF NOT EXISTS reactions (
    grind_number INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    emoji        TEXT    NOT NULL,
    created_at   TEXT    NOT NULL,
    PRIMARY KEY (grind_number, user_id, emoji)
);
CREATE TABLE IF NOT EXISTS room_sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     INTEGER,
    room_id      INTEGER NOT NULL,        -- which listening room
    room_name    TEXT,
    user_id      INTEGER NOT NULL,        -- who was listening
    user_name    TEXT,
    joined_at    TEXT    NOT NULL,
    left_at      TEXT,                    -- NULL while they are still in the room
    seconds      REAL,                    -- filled in on leave; the drop-off signal
    playing_number INTEGER                -- which grind was out loud when they arrived, if any
);
CREATE INDEX IF NOT EXISTS ix_grinds_user ON grinds(user_id);
CREATE INDEX IF NOT EXISTS ix_reactions_grind ON reactions(grind_number);
CREATE INDEX IF NOT EXISTS ix_sessions_open ON room_sessions(user_id, room_id, left_at);
"""

# Columns added after the first release. SQLite has no "ADD COLUMN IF NOT EXISTS", and an existing
# grinder.db in the wild predates these, so they are applied by inspection at connect time rather
# than by a migration tool this app does not have.
_ADDED_COLUMNS = (
    # Where the finished audio sits on disk. The station replays it straight from there, so a
    # replay costs no download and writes no new file - and when the disk janitor sweeps an old
    # render, that mix simply drops out of rotation instead of erroring.
    ("grinds", "audio_path", "TEXT"),
)


def _apply_added_columns(c: sqlite3.Connection) -> None:
    for table, column, decl in _ADDED_COLUMNS:
        existing = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
        _apply_added_columns(_conn)
        _conn.commit()
    return _conn


def reset_for_tests(path: Path | None = None) -> None:
    """Point the store at a temp file. Tests only."""
    global _conn, DB_PATH
    if _conn is not None:
        _conn.close()
        _conn = None
    if path is not None:
        DB_PATH = path


def new_grind(*, user_id: int, user_name: str, pairs: list, created_at: str,
              guild_id: int | None = None, channel_id: int | None = None) -> int:
    """Claim the next grind number. Claimed at SUBMIT, not at completion, so the number on the
    card that says 'grinding...' is the number the finished grind keeps."""
    import json
    with _lock:
        c = connect()
        cur = c.execute(
            "INSERT INTO grinds (user_id, user_name, pairs, created_at, guild_id, channel_id) "
            "VALUES (?,?,?,?,?,?)",
            (user_id, user_name, json.dumps(pairs), created_at, guild_id, channel_id))
        c.commit()
        return int(cur.lastrowid)


def attach_message(number: int, message_id: int) -> None:
    """Remember which Discord message is this grind's card, so a reaction can be traced back."""
    with _lock:
        c = connect()
        c.execute("UPDATE grinds SET message_id=? WHERE number=?", (message_id, number))
        c.commit()


def set_pairs(number: int, pairs: list, ref_id: str | None = None) -> None:
    import json
    with _lock:
        c = connect()
        c.execute("UPDATE grinds SET pairs=?, ref_id=COALESCE(?, ref_id) WHERE number=?",
                  (json.dumps(pairs), ref_id, number))
        c.commit()


def get(number: int) -> sqlite3.Row | None:
    with _lock:
        return connect().execute("SELECT * FROM grinds WHERE number=?", (number,)).fetchone()


def by_message(message_id: int) -> sqlite3.Row | None:
    with _lock:
        return connect().execute("SELECT * FROM grinds WHERE message_id=?",
                                 (message_id,)).fetchone()


def mark_pinned(number: int, when: str) -> bool:
    """True if this call is the one that pinned it. False if it was already pinned - which is what
    stops a second press posting a duplicate into the showcase."""
    with _lock:
        c = connect()
        cur = c.execute("UPDATE grinds SET pinned_at=? WHERE number=? AND pinned_at IS NULL",
                        (when, number))
        c.commit()
        return cur.rowcount == 1


def mark_unpinned(number: int) -> None:
    """Undo a pin claim when the post itself failed, so a retry is not blocked by a pin that
    never actually happened."""
    with _lock:
        c = connect()
        c.execute("UPDATE grinds SET pinned_at=NULL WHERE number=?", (number,))
        c.commit()


def add_reaction(*, grind_number: int, user_id: int, emoji: str, when: str) -> None:
    with _lock:
        c = connect()
        c.execute("INSERT OR IGNORE INTO reactions (grind_number, user_id, emoji, created_at) "
                  "VALUES (?,?,?,?)", (grind_number, user_id, emoji, when))
        c.commit()


def remove_reaction(*, grind_number: int, user_id: int, emoji: str) -> None:
    with _lock:
        c = connect()
        c.execute("DELETE FROM reactions WHERE grind_number=? AND user_id=? AND emoji=?",
                  (grind_number, user_id, emoji))
        c.commit()


def reaction_counts(grind_number: int) -> dict[str, int]:
    with _lock:
        rows = connect().execute(
            "SELECT emoji, COUNT(*) n FROM reactions WHERE grind_number=? GROUP BY emoji",
            (grind_number,)).fetchall()
    return {r["emoji"]: r["n"] for r in rows}


def recent_for_user(user_id: int, limit: int = 10) -> list[sqlite3.Row]:
    with _lock:
        return connect().execute(
            "SELECT * FROM grinds WHERE user_id=? AND message_id IS NOT NULL "
            "ORDER BY number DESC LIMIT ?", (user_id, limit)).fetchall()


def count_for_user(user_id: int) -> int:
    with _lock:
        row = connect().execute("SELECT COUNT(*) n FROM grinds WHERE user_id=?",
                                (user_id,)).fetchone()
    return int(row["n"])


# --- the station ------------------------------------------------------------------------------
# When a room's queue empties it replays what the community has already made, favouring the mixes
# people reacted to with 🔥. THE BOT STILL NEVER JUDGES A MIX: this is an ordering over the
# community's own votes, never Grinder's opinion, and nothing about the ordering is ever shown or
# announced. A visible ranking would prejudice the reaction data, which is the real product signal.

FIRE = "🔥"


def set_audio_path(number: int, path: str) -> None:
    """Remember where a finished grind's audio lives, so the station can replay it from disk
    without re-rendering or re-downloading."""
    with _lock:
        c = connect()
        c.execute("UPDATE grinds SET audio_path=? WHERE number=?", (str(path), number))
        c.commit()


def station_candidates(limit: int = 50) -> list[sqlite3.Row]:
    """Past grinds that could go out on air, best-first.

    Ordered by 🔥 count, then most recent. Only grinds that actually have audio recorded - a grind
    still rendering, or one whose file the disk janitor has since swept, must never be offered
    (the caller checks the file still exists; this just avoids obviously dead rows).

    A LEFT JOIN rather than a subquery so a grind with no reactions at all still appears, at the
    back. A room that has only ever made unreacted mixes must still have something to play.
    """
    with _lock:
        return connect().execute(
            "SELECT g.*, COALESCE(SUM(CASE WHEN r.emoji=? THEN 1 ELSE 0 END), 0) AS fires "
            "FROM grinds g LEFT JOIN reactions r ON r.grind_number = g.number "
            "WHERE g.audio_path IS NOT NULL "
            "GROUP BY g.number "
            "ORDER BY fires DESC, g.number DESC LIMIT ?", (FIRE, limit)).fetchall()


# --- listening data ---------------------------------------------------------------------------
# The two gaps recorded as blocking the community phase: do people actually listen, and when do
# they drop off. Neither is answerable without knowing who was in a room and for how long.

def room_arrival(*, guild_id: int | None, room_id: int, room_name: str, user_id: int,
                 user_name: str, when: str, playing_number: int | None = None) -> None:
    """Someone joined a listening room. Idempotent per open session: Discord fires voice-state
    updates for mute/deafen/camera as well as joins, so re-recording an arrival for somebody
    already in the room would invent listeners who never arrived."""
    with _lock:
        c = connect()
        open_row = c.execute(
            "SELECT id FROM room_sessions WHERE user_id=? AND room_id=? AND left_at IS NULL",
            (user_id, room_id)).fetchone()
        if open_row is not None:
            return
        c.execute(
            "INSERT INTO room_sessions (guild_id, room_id, room_name, user_id, user_name, "
            "joined_at, playing_number) VALUES (?,?,?,?,?,?,?)",
            (guild_id, room_id, room_name, user_id, user_name, when, playing_number))
        c.commit()


def open_session(*, user_id: int, room_id: int):
    """The still-open listening session for this person in this room, or None. Used to work out
    how long they stayed without putting clock arithmetic into SQL."""
    with _lock:
        return connect().execute(
            "SELECT * FROM room_sessions WHERE user_id=? AND room_id=? AND left_at IS NULL "
            "ORDER BY id DESC LIMIT 1", (user_id, room_id)).fetchone()


def room_departure(*, room_id: int, user_id: int, when: str, seconds: float | None = None) -> None:
    """Someone left. Closes the most recent open session for that person in that room; a departure
    with no matching arrival (a restart mid-session) is ignored rather than inventing a row."""
    with _lock:
        c = connect()
        row = c.execute(
            "SELECT id, joined_at FROM room_sessions WHERE user_id=? AND room_id=? "
            "AND left_at IS NULL ORDER BY id DESC LIMIT 1", (user_id, room_id)).fetchone()
        if row is None:
            return
        c.execute("UPDATE room_sessions SET left_at=?, seconds=? WHERE id=?",
                  (when, seconds, row["id"]))
        c.commit()


def listening_summary() -> dict:
    """The plain answer to 'is anybody actually listening, and for how long'."""
    with _lock:
        c = connect()
        row = c.execute(
            "SELECT COUNT(*) sessions, COUNT(DISTINCT user_id) people, "
            "       AVG(seconds) avg_secs, MAX(seconds) max_secs, SUM(seconds) total_secs "
            "FROM room_sessions WHERE left_at IS NOT NULL").fetchone()
        open_now = c.execute(
            "SELECT COUNT(*) n FROM room_sessions WHERE left_at IS NULL").fetchone()
    return {"sessions": int(row["sessions"] or 0), "people": int(row["people"] or 0),
            "avg_secs": round(row["avg_secs"], 1) if row["avg_secs"] else 0.0,
            "max_secs": round(row["max_secs"], 1) if row["max_secs"] else 0.0,
            "total_secs": round(row["total_secs"], 1) if row["total_secs"] else 0.0,
            "in_a_room_now": int(open_now["n"] or 0)}
