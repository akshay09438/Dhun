"""Grinder UI builders — pure, testable (no Discord gateway, no network, no token)."""
import struct
import wave

import ui


def _blob(e) -> str:
    parts = [e.title or "", e.description or "",
             (e.footer.text or "") if e.footer else ""]
    for f in e.fields:
        parts += [f.name or "", f.value or ""]
    return "\n".join(parts)


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
        for e in (ui.submit_embed(user=None, beat="A", vocals="B"),
                  ui.grind_embed(number=1, user=None, pairs=[("A", "B")], total_secs=10),
                  ui.error_embed("nope")):
            assert e.author.icon_url == "https://cdn.example/icon.png"
    finally:
        ui.set_avatar_url(None)   # module-level state — don't leak into other tests


def test_help_card_shows_the_remix_banner_not_the_wordmark():
    """Changed 2026-08-12 on the founder's instruction: /help used the GRINDER wordmark disc while
    #read-this-first used the "Remix anything." banner, so a newcomer met two different identities.
    One image, used in both places."""
    e = ui.help_embed(banner_name="remix-banner.jpg")
    assert e.image.url == "attachment://remix-banner.jpg"


def test_help_card_names_the_real_rooms_as_live_links():
    """It used to say "The Booth" - a channel that has not existed since the rooms were split into
    Bollywood_House and Hollywood_Blends. Typed names rot the moment the founder renames a room;
    a <#id> mention follows the rename. This is the same failure that left #read-this-first
    advertising three deleted commands for two versions."""
    class R:
        def __init__(self, i):
            self.id = i

    text = "\n".join(f.value for f in ui.help_embed(rooms=[R(111), R(222)]).fields)
    assert "<#111>" in text and "<#222>" in text
    assert "The Booth" not in text


def test_help_card_still_reads_without_any_rooms_configured():
    """A server with no listening rooms yet must still get a help card, not a crash or a dangling
    sentence."""
    text = "\n".join(f.value for f in ui.help_embed(rooms=[]).fields)
    assert "a listening room" in text


def test_help_card_teaches_the_playback_controls():
    """They were unreachable knowledge before: /skip and /stop existed with nothing telling anyone
    they did."""
    text = "\n".join(f.value for f in ui.help_embed().fields)
    for cmd in ("/skip", "/stop", "/play"):
        assert cmd in text


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


def test_the_grind_card_hides_the_style_and_the_take():
    """The mixing rule and the take number are internal only, on the ops dashboard, never on a
    card. Song names, length, and who made it is the whole vocabulary."""
    e = ui.grind_embed(number=147, user=None, pairs=[("Hey Brother", "Bad Guy")], total_secs=210)
    assert e.color.value == ui.ACCENT
    assert "147" in e.title
    assert "Hey Brother" in e.description and "Bad Guy" in e.description
    names = [f.name for f in e.fields]
    assert "Length" in names
    assert "Style" not in names and "Take" not in names
    blob = _blob(e).lower()
    assert "take" not in blob and "style" not in blob


def test_a_long_grind_numbers_its_running_order():
    """The running order is the whole point of a long grind: it says what you built, in order.
    There is no "just landed" marker any more - nothing lands after the fact, because every pair
    is chosen up front and the set arrives complete."""
    e = ui.grind_embed(number=9, user=None, pairs=[("A", "B"), ("C", "D")], total_secs=400)
    assert "long grind" in e.title and "2 tracks" in e.title
    first, second = e.description.splitlines()[0], e.description.splitlines()[1]
    assert "A" in first and "B" in first and first.startswith("`1`")
    assert "C" in second and "D" in second and second.startswith("`2`")
    assert "just landed" not in e.description


def test_the_booth_banner_says_how_many_are_listening():
    one = ui.grind_embed(number=1, user=None, pairs=[("A", "B")], total_secs=10,
                         booth_listeners=1)
    many = ui.grind_embed(number=1, user=None, pairs=[("A", "B")], total_secs=10,
                          booth_listeners=4)
    assert "1 listening" in one.description
    assert "4 listening" in many.description
    assert "PLAYING LIVE" in many.description


def test_a_queued_grind_states_its_position_without_judging_it():
    e = ui.grind_embed(number=1, user=None, pairs=[("A", "B")], total_secs=10, queued_behind=2)
    assert "waiting for the room" in e.description
    assert "2 ahead of it" in e.description


def test_the_submit_card_names_both_songs_and_predicts_nothing():
    e = ui.submit_embed(user=None, beat="Midnight City", vocals="Kabhi Kabhi Aditi")
    assert "Midnight City" in e.description and "Kabhi Kabhi Aditi" in e.description
    assert "grinding..." in e.description
    assert "take" not in _blob(e).lower()


# --- the rule that shapes every card ---------------------------------------------------
# Grinder never evaluates, rates, judges or predicts a grind. An opinion on the card tells people
# what to think before they hear it, and it contaminates the 🔥/💀/😐 data, which is the actual
# product signal. This test is the thing that stops a future card quietly reintroducing one.
JUDGEMENT_WORDS = (
    "clean grind", "rough grind", "shouldn't work", "should not work",
    "no business together", "might actually get along", "could go either way",
    "someone stop", "verdict", "score", "rating", "rated", "quality",
    "banger", "cursed", "disaster", "risky", "risk", "warning", "degraded",
    "good match", "bad match", "perfect match", "incompatible",
)
TECHNICAL_WORDS = ("bpm", "camelot", "semitone", "tempo", "key of", "hz")


def _every_card():
    return [
        ui.submit_embed(user=None, beat="A", vocals="B"),
        ui.grind_embed(number=1, user=None, pairs=[("A", "B")], total_secs=200),
        ui.grind_embed(number=2, user=None, pairs=[("A", "B"), ("C", "D")], total_secs=400,
                       ),
        ui.grind_embed(number=3, user=None, pairs=[("A", "B")], total_secs=200,
                       booth_listeners=4),
        ui.grind_embed(number=4, user=None, pairs=[("A", "B")], total_secs=200, queued_behind=1),
        ui.booth_live_embed(listeners=3, grinds_this_session=5, last_up="A x B"),
        ui.mygrinds_embed(user=None, total=2, rows=[(1, "A x B", None)]),
        ui.help_embed(),
    ]


def test_no_card_ever_rates_or_predicts_a_grind():
    for e in _every_card():
        blob = _blob(e).lower()
        for word in JUDGEMENT_WORDS:
            assert word not in blob, f"a card judged the grind: {word!r} in {e.title!r}"


def test_no_card_ever_shows_a_technical_readout():
    for e in _every_card():
        blob = _blob(e).lower()
        for word in TECHNICAL_WORDS:
            assert word not in blob, f"a card leaked engine internals: {word!r} in {e.title!r}"


def test_colors():
    assert ui.help_embed().color.value == ui.ACCENT
    assert ui.error_embed("nope").color.value == ui.FAIL
    assert ui.submit_embed(user=None, beat="A", vocals="B").color.value == ui.ACCENT
    assert ui.grind_embed(number=1, user=None, pairs=[("A", "B")],
                          total_secs=1).color.value == ui.ACCENT


def test_wav_duration(tmp_path):
    p = tmp_path / "t.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(1000)
        w.writeframes(struct.pack("<2000h", *([0] * 2000)))  # 2000 frames @ 1000 Hz = 2.0 s
    assert abs(ui.wav_duration(p) - 2.0) < 1e-6
    assert ui.wav_duration(tmp_path / "missing.wav") == 0.0  # unreadable -> 0.0, never raises
