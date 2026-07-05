"""Tests for the AI driver. We exercise the deterministic fallback (no network) and
the wiring of an AI choice via a monkeypatched _ai_choose — never a real API call.
"""

import pytest

from app.planner import plan as planner
from tests.test_fence import make_analysis


def test_fallback_plan_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    a1 = make_analysis(bpm=120.0)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(16.0, 40.0)])

    mix = planner.build_mix_plan("m" * 64, a1, a2)

    assert mix.source == "rules"
    assert mix.master_bpm == 120.0
    assert mix.anchor >= 0.0
    assert mix.vocal_src[1] > mix.vocal_src[0]
    assert 0.92 <= mix.vocal_stretch <= 1.08


def test_ai_choice_is_used_when_available(monkeypatch):
    a1 = make_analysis(bpm=120.0)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(16.0, 40.0)])
    # pretend the AI picked the second drop with a beat breath
    monkeypatch.setattr(planner, "_ai_choose", lambda opts, prompt: (1, True, "big re-entry"))

    mix = planner.build_mix_plan("m" * 64, a1, a2, prompt="make it punchy")

    assert mix.source == "ai"
    assert mix.beat_breath is True
    assert mix.notes == "big re-entry"


def test_ai_choice_out_of_range_falls_back(monkeypatch):
    # _ai_choose itself guards the index, so a bad index yields None -> fallback
    a1 = make_analysis(bpm=120.0)
    a2 = make_analysis(bpm=118.0, vocal_regions=[(16.0, 40.0)])
    monkeypatch.setattr(planner, "_ai_choose", lambda opts, prompt: None)

    mix = planner.build_mix_plan("m" * 64, a1, a2)
    assert mix.source == "rules"


def test_declines_when_unmixable():
    a1 = make_analysis(bpm=120.0)
    a2 = make_analysis(bpm=150.0, vocal_regions=[(16.0, 40.0)])
    with pytest.raises(planner.MixDeclined) as exc:
        planner.build_mix_plan("m" * 64, a1, a2)
    assert "tempo" in str(exc.value).lower()


def test_extract_json_tolerates_prose():
    assert planner._extract_json('sure!\n{"chosen_drop_index": 0}\nthanks') == {"chosen_drop_index": 0}
