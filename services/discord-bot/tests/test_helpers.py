"""Pure-helper tests — no network, no token."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from helpers import (match_songs, safe_filename, select_option_specs,  # noqa: E402
                     style_label)


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


def test_select_option_specs_marks_the_selected_song_default():
    # The bug: after a pick, the dropdown reset to its placeholder because the chosen
    # song was never flagged as the selected (default) option on re-render.
    pool = [_S("Father Ocean", "a"), _S("Dooriyan", "b")]
    assert select_option_specs(pool, "b") == [
        ("Father Ocean", "a", False),
        ("Dooriyan", "b", True),
    ]


def test_select_option_specs_none_selected_has_no_default():
    pool = [_S("x", "1"), _S("y", "2")]
    assert select_option_specs(pool, None) == [("x", "1", False), ("y", "2", False)]


def test_safe_filename_strips_and_bounds():
    assert safe_filename("Ocean × Bina!") == "Ocean _ Bina_"
    assert safe_filename("") == "mix"
    assert len(safe_filename("z" * 200)) == 60
