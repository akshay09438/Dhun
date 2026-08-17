"""A vocal without a language tag is loaded, paid for, and INVISIBLE.

THE INCIDENT, 2026-08-14. 103 songs were ingested - normalised, stem-separated on Replicate,
analysed, written into the catalog manifest - and the Discord picker still offered the same four
English vocals it had before. `bot.py::_vocals_for` filters vocals by language and defaults to
English, so a vocal carrying no tag matches neither list and simply never appears. Everything
reported success; the founder found it by looking at the dropdown.

The failure is silent in both directions, which is why it needs a test rather than care: nothing
errors, the manifest looks fine, and the song is genuinely there.

WHERE THIS LIVES NOW (2026-08-17): the upsert moved out of `scripts/ingest_catalog.py` into
`app.library_store`, so the operator script and the /add endpoint share ONE writer and cannot
diverge. These tests moved with it unchanged in meaning - they now assert against the real,
persisted manifest rather than an in-memory list, which is strictly stronger.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import inspect
import sys
from pathlib import Path

import pytest

from app import library_store

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "ingest_catalog.py"


@pytest.fixture
def store(monkeypatch, tmp_path):
    """`library_store` pointed at a throwaway data dir, so each test gets a clean manifest."""
    monkeypatch.setattr(library_store, "settings",
                        dataclasses.replace(library_store.settings, data_dir=tmp_path))
    return library_store


@pytest.fixture(scope="module")
def ingest():
    """Import the script without executing its Replicate-touching imports at call time."""
    spec = importlib.util.spec_from_file_location("ingest_catalog_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _row(store, song_id: str) -> dict:
    return next(r for r in store.load() if r["song_id"] == song_id)


def test_a_vocal_keeps_its_language(store):
    store.upsert("Levitating", "a" * 64, "vocals", "english")
    assert _row(store, "a" * 64)["language"] == "english", (
        "a vocal with no language is filtered out of BOTH picker lists and is invisible in Discord"
    )


def test_language_survives_a_re_ingest_of_the_same_song(store):
    """Re-running the loader is normal (it is idempotent); it must not drop the tag."""
    store.upsert("Levitating", "a" * 64, "vocals", "english")
    store.upsert("Levitating", "a" * 64, "vocals", "english")
    assert len(store.load()) == 1
    assert _row(store, "a" * 64)["language"] == "english"


def test_re_ingesting_without_a_language_does_not_ERASE_an_existing_one(store):
    """The repair path: a song already tagged by hand must not be untagged by a later plain run."""
    store.upsert("Panda", "b" * 64, "vocals", "english")
    store.upsert("Panda", "b" * 64, "vocals", "")
    assert _row(store, "b" * 64)["language"] == "english"


def test_a_beat_needs_no_language(store):
    """Beats are never language-filtered, so a blank there is correct rather than an omission."""
    store.upsert("Levels", "c" * 64, "beat", "")
    row = _row(store, "c" * 64)
    assert "language" not in row
    assert row["role_hint"] == "beat"


def test_language_is_carried_from_the_job_spec_to_the_entry(ingest):
    """End-to-end on the plumbing: the field has to survive main() -> ingest_one() -> upsert()."""
    src = inspect.getsource(ingest.main)
    assert "language" in src, "main() drops the language field before it reaches the manifest"
    assert "language" in inspect.signature(ingest.ingest_one).parameters
    assert "language" in inspect.signature(library_store.upsert).parameters


def test_the_script_no_longer_writes_the_manifest_itself(ingest):
    """One writer, or the two paths drift. A private _upsert/_save here would be that drift
    starting again — and the concurrency and atomicity guarantees only hold for the shared one."""
    assert not hasattr(ingest, "_upsert")
    assert not hasattr(ingest, "_save_manifest")
    assert "library_store.upsert" in inspect.getsource(ingest.ingest_one)
