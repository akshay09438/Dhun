from app.models import Section, TrackAnalysis
from app.planner import suggest
from app.planner.suggest import suggest_moves


def _analysis(labels):
    secs = [Section(start=float(i * 30), end=float((i + 1) * 30), label=lbl)
            for i, lbl in enumerate(labels)]
    return TrackAnalysis(song_id="a" * 64, status="ready", sections=secs)


def test_fallback_maps_labels_to_vocabulary_chips(monkeypatch):
    monkeypatch.setattr(suggest, "_ai_suggest", lambda *a, **k: None)  # no AI -> fallback
    out = suggest_moves(_analysis(["intro", "chorus", "verse", "outro"]))
    assert [s.label for s in out] == ["intro", "chorus", "verse", "outro"]
    # every chip is from the closed vocabulary, 1-3 per section
    for s in out:
        assert 1 <= len(s.chips) <= 3
        for c in s.chips:
            assert c.text in suggest._VOCAB
            assert (c.op, c.targets) == (suggest._VOCAB[c.text][0], list(suggest._VOCAB[c.text][1]))
    # outro suggests the fade
    assert any(c.op == "fade" for c in out[-1].chips)
    # chorus suggests bringing the vocal in
    assert any(c.text == "Bring the vocal in" for c in out[1].chips)


def test_no_sections_gives_one_default_section(monkeypatch):
    monkeypatch.setattr(suggest, "_ai_suggest", lambda *a, **k: None)
    out = suggest_moves(TrackAnalysis(song_id="a" * 64, status="ready", sections=[]))
    assert len(out) == 1 and out[0].chips  # a single default section with default chips


def test_ai_chips_used_and_unknown_dropped(monkeypatch):
    # AI returns a good chip for section 0 and an off-menu chip that must be dropped.
    monkeypatch.setattr(suggest, "_ai_suggest",
                        lambda *a, **k: {0: ["Bring the vocal in", "Teleport the drums"]})
    out = suggest_moves(_analysis(["intro", "outro"]))
    texts0 = [c.text for c in out[0].chips]
    assert "Bring the vocal in" in texts0 and "Teleport the drums" not in texts0
    assert out[1].chips  # section 1 (no AI entry) falls back, still non-empty
