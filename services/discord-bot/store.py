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
CREATE INDEX IF NOT EXISTS ix_grinds_user ON grinds(user_id);
CREATE INDEX IF NOT EXISTS ix_reactions_grind ON reactions(grind_number);
"""


def connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
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
