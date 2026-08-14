"""A vocal without a language tag is loaded, paid for, and INVISIBLE.

THE INCIDENT, 2026-08-14. 103 songs were ingested - normalised, stem-separated on Replicate,
analysed, written into the catalog manifest - and the Discord picker still offered the same four
English vocals it had before. `bot.py::_vocals_for` filters vocals by language and defaults to
English, so a vocal carrying no tag matches neither list and simply never appears. Everything
reported success; the founder found it by looking at the dropdown.

The failure is silent in both directions, which is why it needs a test rather than care: nothing
errors, the manifest looks fine, and the song is genuinely there.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "ingest_catalog.py"


@pytest.fixture(scope="module")
def ingest():
    """Import the script without executing its Replicate-touching imports at call time."""
    spec = importlib.util.spec_from_file_location("ingest_catalog_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_a_vocal_keeps_its_language(ingest):
    entries: list[dict] = []
    ingest._upsert(entries, "Levitating", "a" * 64, "vocals", "english")
    assert entries[0]["language"] == "english", (
        "a vocal with no language is filtered out of BOTH picker lists and is invisible in Discord"
    )


def test_language_survives_a_re_ingest_of_the_same_song(ingest):
    """Re-running the loader is normal (it is idempotent); it must not drop the tag."""
    entries = [{"name": "Levitating", "song_id": "a" * 64, "role_hint": "vocals",
                "language": "english"}]
    ingest._upsert(entries, "Levitating", "a" * 64, "vocals", "english")
    assert len(entries) == 1
    assert entries[0]["language"] == "english"


def test_re_ingesting_without_a_language_does_not_ERASE_an_existing_one(ingest):
    """The repair path: a song already tagged by hand must not be untagged by a later plain run."""
    entries = [{"name": "Panda", "song_id": "b" * 64, "role_hint": "vocals", "language": "english"}]
    ingest._upsert(entries, "Panda", "b" * 64, "vocals", "")
    assert entries[0]["language"] == "english"


def test_a_beat_needs_no_language(ingest):
    """Beats are never language-filtered, so a blank there is correct rather than an omission."""
    entries: list[dict] = []
    ingest._upsert(entries, "Levels", "c" * 64, "beat", "")
    assert "language" not in entries[0]
    assert entries[0]["role_hint"] == "beat"


def test_language_is_carried_from_the_job_spec_to_the_entry(ingest):
    """End-to-end on the plumbing: the field has to survive main() -> ingest_one() -> _upsert()."""
    import inspect
    src = inspect.getsource(ingest.main)
    assert "language" in src, "main() drops the language field before it reaches the manifest"
    assert "language" in inspect.signature(ingest.ingest_one).parameters
    assert "language" in inspect.signature(ingest._upsert).parameters
