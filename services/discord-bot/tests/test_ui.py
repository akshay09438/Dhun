"""Grinder UI builders — pure, testable (no Discord gateway, no network, no token)."""
import struct
import wave

import ui


def test_accent_is_the_brand_purple_sampled_from_the_artwork():
    """Changed 2026-08-10: was the web app's #6D3BF5, a BLUE-violet. The Grinder artwork is a
    RED-violet, so the old accent read as a second, clashing brand sitting beside the logo. The
    colour now lives in brand.py and is sampled from Icon.png / Main logo.png."""
    import brand
    assert ui.ACCENT == brand.PRIMARY == 0xA824CC
    assert ui.ACCENT != 0x6D3BF5


def test_cards_carry_the_grinder_mark_once_the_avatar_url_is_known():
    """Every card shows the G as its author icon — but only after login, since Discord needs a URL."""
    ui.set_avatar_url(None)
    assert ui.help_embed().author.icon_url is None
    try:
        ui.set_avatar_url("https://cdn.example/icon.png")
        for e in (ui.cooking_embed("A", "B"),
                  ui.now_playing_embed(name="N", beat="A", vocals="B", total_secs=10, user=None),
                  ui.error_embed("nope")):
            assert e.author.icon_url == "https://cdn.example/icon.png"
    finally:
        ui.set_avatar_url(None)   # module-level state — don't leak into other tests


def test_help_card_shows_the_wordmark():
    assert ui.help_embed().thumbnail.url == "attachment://logo.png"


def test_mmss():
    assert ui.mmss(0) == "0:00"
    assert ui.mmss(75) == "1:15"
    assert ui.mmss(None) == "0:00"


def test_bar_knob_moves_and_shows_times():
    b0 = ui.bar(0, 200)
    assert b0.startswith(ui._KNOB)          # knob at the very start when elapsed is 0
    assert "0:00 / 3:20" in b0
    bmid = ui.bar(100, 200)
    assert ui._KNOB in bmid and bmid.index(ui._KNOB) > 0   # knob moved right
    assert ui.bar(0, 0) and ui.bar(5, None)               # never crashes on 0/None total


def test_now_playing_hides_style_and_take():
    # the mix STYLE (rule) and TAKE number are internal-only — never shown to users. Only
    # song names + length appear on the card.
    e = ui.now_playing_embed(name="Ocean Bina", beat="Hey Brother", vocals="Bad Guy",
                             total_secs=210, user=None)
    assert e.color.value == ui.ACCENT
    assert "Ocean Bina" in e.title
    assert "Hey Brother" in e.description and "Bad Guy" in e.description
    names = [f.name for f in e.fields]
    assert "Length" in names
    assert "Style" not in names and "Take" not in names
    blob = (e.title + e.description + " ".join(f"{f.name} {f.value}" for f in e.fields)
            + (e.footer.text or "")).lower()
    assert "take" not in blob and "style" not in blob   # not even in the copy


def test_in_voice_author_line():
    e = ui.now_playing_embed(name="X", beat="a", vocals="b", total_secs=100, user=None, in_voice=True)
    assert "voice" in e.author.name.lower()


def test_cooking_hides_take():
    e = ui.cooking_embed("A", "B")
    blob = (e.title + e.description + (e.footer.text or "")).lower()
    assert "take" not in blob


def test_help_error_set_cooking_colors():
    assert ui.help_embed().color.value == ui.ACCENT
    assert ui.error_embed("nope").color.value == ui.FAIL
    assert ui.set_lineup_embed("Set 1: a x b", 300, 2, None).color.value == ui.ACCENT
    assert ui.building_embed("Set 1: a x b", 1).color.value == ui.ACCENT
    assert ui.cooking_embed("A", "B").color.value == ui.ACCENT


def test_wav_duration(tmp_path):
    p = tmp_path / "t.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(1000)
        w.writeframes(struct.pack("<2000h", *([0] * 2000)))  # 2000 frames @ 1000 Hz = 2.0 s
    assert abs(ui.wav_duration(p) - 2.0) < 1e-6
    assert ui.wav_duration(tmp_path / "missing.wav") == 0.0  # unreadable -> 0.0, never raises
