"""Bollywood / English vocal filtering in the grind picker.

WHY THIS EXISTS (founder, 2026-08-12). The catalog is **14 Bollywood vocals to 4 English ones**.
A listener in the US opening the picker met a wall of songs they had never heard of - "what is
this?" - which is a bad first thirty seconds for exactly the audience the app is trying to reach.

WHAT IT IS NOT. This filters what the picker SHOWS. It does not restrict what the engine will
mix: any beat still pairs with any vocal, and the cross-language pairs that produce the best
results (Father Ocean x Tere Bina, Rapture x Khuda Jaane) stay one tap away. A one-way door here
would have quietly deleted the app's best demos.

BEATS ARE NEVER FILTERED - they are instrumental beds and belong to neither audience. All 12 in
the catalog carry no language at all.
"""
from __future__ import annotations

import pytest

import bot as bot_mod
from api_client import Song


@pytest.fixture
def catalog(monkeypatch):
    """A stand-in catalog with the real shape: a few unlabelled beats, vocals in both languages."""
    beats = [Song(id=f"b{i}", name=f"Beat {i}", role_hint="beat") for i in range(3)]
    vocals = [
        Song(id="e1", name="Don't Start Now (Dua Lipa)", role_hint="vocals", language="english"),
        Song(id="e2", name="Bad Guy", role_hint="vocals", language="english"),
        Song(id="b1", name="Tere Bina", role_hint="vocals", language="bollywood"),
        Song(id="b2", name="Khuda Jaane", role_hint="vocals", language="bollywood"),
        Song(id="b3", name="With You (AP Dhillon)", role_hint="vocals", language="bollywood"),
    ]
    monkeypatch.setattr(bot_mod.bot, "beats", beats, raising=False)
    monkeypatch.setattr(bot_mod.bot, "vocals", vocals, raising=False)
    return beats, vocals


def _labels(view):
    return [o.label for o in view.vocal_select.options]


def test_it_opens_on_english(catalog):
    """The founder's call: a US listener is the one who gets confused, so they are the default."""
    v = bot_mod.GrindBuilderView(user_id=1)
    assert v.language == "english"
    assert len(_labels(v)) == 2
    assert "Tere Bina" not in " ".join(_labels(v))


def test_switching_to_bollywood_shows_the_other_list(catalog):
    v = bot_mod.GrindBuilderView(user_id=1)
    v.set_language("bollywood")
    labels = " ".join(_labels(v))
    assert "Tere Bina" in labels and "Khuda Jaane" in labels
    assert "Bad Guy" not in labels


def test_beats_are_never_filtered(catalog):
    """A beat is instrumental. Filtering them would halve the catalog for no reason and break
    every cross-language pair the app is best at."""
    v = bot_mod.GrindBuilderView(user_id=1)
    before = len(v.beat_select.options)
    v.language = "bollywood"
    v._refresh_options()
    assert len(v.beat_select.options) == before == 3


def test_switching_language_drops_a_vocal_from_the_other_list(catalog):
    """Otherwise the picker shows a selection that is not in its own list, and Grind it would
    build something the person can no longer see."""
    v = bot_mod.GrindBuilderView(user_id=1)
    v.sel_beat, v.sel_vocal = "b0", "e1"          # an English vocal is chosen
    v.set_language("bollywood")
    assert v.sel_vocal is None, "a vocal from the hidden list must not stay selected"
    assert v.sel_beat == "b0", "the beat is untouched - it has no language"


def test_a_vocal_in_the_new_language_survives_the_switch(catalog):
    v = bot_mod.GrindBuilderView(user_id=1)
    v.set_language("bollywood")
    v.sel_vocal = "b1"
    v.set_language("bollywood")                   # switching to the SAME language
    assert v.sel_vocal == "b1"


def test_an_empty_language_falls_back_rather_than_showing_nothing(catalog, monkeypatch):
    """If a language ever matches no songs, an empty dropdown is worse than an unfiltered one -
    the person cannot do anything at all and has no idea why."""
    monkeypatch.setattr(bot_mod.bot, "vocals",
                        [Song(id="x", name="Only Bollywood", role_hint="vocals",
                              language="bollywood")], raising=False)
    v = bot_mod.GrindBuilderView(user_id=1)       # defaults to english, which matches nothing
    assert len(_labels(v)) == 1, "must fall back to the whole list rather than go blank"


def test_the_labels_are_the_founders_words(catalog):
    """'Bollywood', not 'Hindi': three of the fourteen are Punjabi, and Bollywood is the word a
    global audience already knows."""
    assert bot_mod.LANGUAGES == {"english": "English", "bollywood": "Bollywood"}
    assert bot_mod.DEFAULT_LANGUAGE == "english"
