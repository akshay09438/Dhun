"""Pure-helper tests — no network, no token."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from helpers import match_songs, safe_filename, style_label  # noqa: E402


class _S:
    def __init__(self, name, sid="x"):
        self.name = name
        self.id = sid


def test_style_label_by_rule():
    assert style_label(1) == "Simple"
    assert style_label(3) == "Chop & repeat"
    assert style_label(4) == "Echo"


def test_style_label_falls_back_to_notes():
    assert style_label(None, "Rule 3 — chop & repeat: the hook fires…") == "Chop & repeat"
    assert style_label(None, "echo + reverb bed") == "Echo"
    assert style_label(None, "a plain mix") == "Simple"
    assert style_label(None, None) == "Simple"


def test_match_songs_substring_case_insensitive():
    pool = [_S("Father Ocean"), _S("Don't Start Now"), _S("Faded")]
    names = [s.name for s in match_songs(pool, "fa")]
    assert names == ["Father Ocean", "Faded"]


def test_match_songs_empty_query_returns_all_capped():
    pool = [_S(f"song {i}") for i in range(40)]
    assert len(match_songs(pool, "")) == 25
    assert len(match_songs(pool, "", limit=10)) == 10


def test_safe_filename_strips_and_bounds():
    assert safe_filename("Ocean × Bina!") == "Ocean _ Bina_"
    assert safe_filename("") == "mix"
    assert len(safe_filename("z" * 200)) == 60
