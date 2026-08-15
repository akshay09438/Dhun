"""What Grinder SAYS has to match what Grinder DOES.

THIS HAS NOW ROTTED THREE TIMES. `ui.help_embed` carries a comment about the first two - a "The
Booth" that had been split into two rooms, and a `/grind beat: vocal:` option form that no longer
existed - and calls it "the same failure mode that left #read-this-first advertising three deleted
commands for two versions". It happened again on 2026-08-15, and this time to a live server with
real strangers on it.

SEVEN LINES WERE FOUND WRONG ON 2026-08-16, all from one day's changes:

  * `#read-this-first`      "Hit 📌"  - the button had been renamed 📣 "Show this mix to everyone"
  * `#read-this-first`      "React 🔥 💀 😐 to anything you hear" - Discord REFUSES reactions on a
                            private message, and every grind card is private now
  * `#get-shit-done` topic  "everyone grinds here, in the open" - grinds became private
  * the "not here" refusal  "out in the open, so you can see what other people are throwing
                            together" - you never see anybody else's
  * `/help`                 "React to grinds - yours and everyone else's" - same
  * `/help`                 "the room keeps playing past grinds by itself" - that station was
                            removed on 2026-08-12
  * `/mygrinds` (empty)     "Go to #the-grinder" - no such channel; it is #get-shit-done

These tests are the brake. They do not check for pretty words - they check that no line promises a
behaviour the product does not have. A newcomer reads all of this before they trust anything.
"""
import os

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "x" * 59)

import server_setup  # noqa: E402
import ui  # noqa: E402


def _all_text(embed) -> str:
    bits = [embed.title or "", embed.description or ""]
    bits += [f"{f.name} {f.value}" for f in embed.fields]
    if embed.footer and embed.footer.text:
        bits.append(embed.footer.text)
    return "\n".join(bits).lower()


# --- /help ---------------------------------------------------------------------------------------

def test_help_does_not_offer_reactions_on_other_peoples_grinds():
    """A grind card is private and Discord will not take a reaction on one. Reactions exist only on
    a mix somebody chose to SHOW, in the showcase."""
    text = _all_text(ui.help_embed())
    assert "everyone else's" not in text, (
        "/help still says you can react to other people's grinds; nobody can see anybody else's")


def test_help_does_not_promise_the_room_plays_by_itself():
    """The station was removed on 2026-08-12 - 'a room that starts playing things nobody requested
    is chaos, not company'. /play now only picks up what /stop paused."""
    text = _all_text(ui.help_embed())
    assert "by itself" not in text and "keeps playing past grinds" not in text, (
        "/help still promises the listening room auto-plays past grinds")


def test_help_says_how_to_get_a_mix_back():
    """The card is ephemeral, so the single most useful thing a newcomer can know is that a mix is
    not lost when it disappears off their screen."""
    text = _all_text(ui.help_embed())
    assert "/mygrinds" in text
    assert "again" in text or "back" in text, (
        "nothing tells a newcomer they can get a mix back after their card is gone")


# --- /mygrinds -----------------------------------------------------------------------------------

def test_mygrinds_does_not_send_people_to_a_channel_that_does_not_exist():
    """`the-grinder` was renamed `get-shit-done` on the live server. Copy that TYPES a channel name
    rots the moment the founder renames one, which is the rule the rest of this file already
    follows with live mentions."""
    body = (ui.mygrinds_embed(user=None, total=0, rows=[]).description or "").lower()
    assert "#the-grinder" not in body, "it points at a channel that no longer exists"


# --- the refusal you get for grinding in the wrong room -------------------------------------------

def test_the_wrong_room_message_does_not_claim_grinding_is_public(monkeypatch):
    """It confines /grind to the grind rooms for a good reason, but the reason it GIVES stopped
    being true when grinds went private.

    Checks the sentence a person is actually sent, not the source text - the file explains the old
    wording in a comment, and a test that greps for a phrase would fail on the explanation of why
    the phrase was removed."""
    import types

    import bot as botmod
    monkeypatch.setattr(botmod.CFG, "grind_category_id", 111, raising=False)
    monkeypatch.setattr(botmod.booth, "room_of", lambda _user: None)
    interaction = types.SimpleNamespace(
        user=types.SimpleNamespace(id=1),
        channel=types.SimpleNamespace(category=None, category_id=999),   # the wrong room
        guild=types.SimpleNamespace(text_channels=[]))

    said = (botmod._grinding_allowed_here(interaction) or "").lower()

    assert said, "grinding in the wrong room was allowed"
    assert "out in the open" not in said and "what other people are throwing" not in said, (
        "the refusal still tells people they will see what everyone else is throwing together")


# --- the welcome, which is the first thing anybody reads -------------------------------------------

def test_the_welcome_names_the_button_that_actually_exists():
    """📌 became 📣 'Show this mix to everyone' on 2026-08-15. A newcomer hunting for a pin icon
    finds nothing."""
    text = "\n".join(_all_text(e) for e in server_setup.welcome_embeds(None))
    assert "📌" not in text, "the welcome still tells people to hit 📌"
    assert "📣" in text, "the welcome never names the button that shares a mix"


def test_the_welcome_does_not_ask_for_reactions_that_cannot_be_given():
    """"React to anything you hear" - on a private card, Discord refuses."""
    text = "\n".join(_all_text(e) for e in server_setup.welcome_embeds(None))
    assert "anything you hear" not in text, (
        "the welcome asks for reactions on grind cards, which Discord will not allow")


# --- the room intros and topics --------------------------------------------------------------------

def test_the_grind_rooms_intro_does_not_say_everyone_grinds_in_the_open():
    title, body = server_setup.channel_copy()[server_setup.GRIND_CHANNEL]
    text = f"{title} {body}".lower()
    assert "in the open" not in text, "the grind room still advertises public grinding"
    assert "react 🔥 💀 😐 to theirs" not in text, "it asks people to react to grinds they cannot see"


def test_the_grind_room_topic_does_not_say_in_the_open():
    """The topic sits directly under the channel name and is read before any pinned post."""
    assert "in the open" not in server_setup.topic_for(server_setup.GRIND_CHANNEL).lower()


def test_the_showcase_intro_names_the_right_button():
    title, body = server_setup.channel_copy()[server_setup.SHOWCASE_CHANNEL]
    assert "📌" not in f"{title} {body}", "the showcase still tells people to hit 📌"
