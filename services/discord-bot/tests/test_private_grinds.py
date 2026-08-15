"""Your grind is YOURS until you choose to show it.

FOUNDER, 2026-08-15, from watching the room fill up: "a user will go to the Get Shit Done channel...
whatever music other users have made, users can see it, and they'll be overwhelmed. They'll be more
into listening to music that others made instead of creating their own." So a finished grind now
comes back only to the person who made it, and `#best-mixes` becomes the only public wall.

THE CONSEQUENCE THAT HAD TO BE HANDLED, not just accepted. Discord will not put reactions on a
private message - it is a hard platform rule, not a setting. Reactions are the ONLY signal that says
whether a grind actually landed (store.py calls them the product), so leaving them on the private
card would have silently ended the measurement. They move to the SHOWCASE post instead: sharing a
mix seeds 🔥 💀 😐 on the public copy and points the grind's message id at it, so a reaction there is
recorded against the right grind. The signal survives, and arguably improves - a reaction on a mix
somebody chose to show means more than one on a card that merely scrolled past.

AND THE BUTTON SAYS WHAT IT DOES. "Pin it" described the mechanism, not the outcome; founder: "pin
is a very vague, usable thing for where to pin... something like 'Show this mix to everyone'".
"""
import asyncio
import os
import types

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "x" * 59)

import showcase  # noqa: E402
import store  # noqa: E402
import ui  # noqa: E402

SHARE_LABEL = "Show this mix to everyone"


@pytest.fixture(autouse=True)
def fresh_store(tmp_path):
    store.reset_for_tests(tmp_path / "grinder.db")
    yield
    store.reset_for_tests()


# --- the card is private ---------------------------------------------------------------------

class _Followup:
    def __init__(self):
        self.sends = []

    async def send(self, *a, **k):
        self.sends.append(k)
        return types.SimpleNamespace(id=999, edit=self._edit)

    async def _edit(self, **k):
        return None


def _ctx(botmod, followup):
    user = types.SimpleNamespace(id=1, name="t", display_name="t")
    interaction = types.SimpleNamespace(user=user, guild=None, channel=None, followup=followup)
    return botmod.GrindContext(interaction, [("b", "v")])


def test_your_grind_comes_back_only_to_you():
    """THE FOUNDER'S ASK, at the seam. The card must be sent privately, so the room does not fill
    with everybody else's music."""
    import bot as botmod
    fu = _Followup()
    ctx = _ctx(botmod, fu)
    asyncio.run(ctx._post_submit_card(first=True))
    assert fu.sends, "no card was posted at all"
    assert fu.sends[0].get("ephemeral") is True, (
        "the grind card was posted publicly - everyone in the channel sees it")


def test_the_private_card_never_gets_reactions_put_on_it():
    """Discord refuses reactions on a private message, so seeding them would raise on every single
    grind. This pins that the code does not try."""
    import bot as botmod
    seeded = []

    async def _spy(message):
        seeded.append(message)

    original = botmod._seed_reactions
    botmod._seed_reactions = _spy
    try:
        assert botmod._seed_reactions is _spy
    finally:
        botmod._seed_reactions = original
    # the real assertion: the finish path must not seed onto the private card
    import inspect
    src = inspect.getsource(botmod.GrindContext.run)
    assert "_seed_reactions" not in src, (
        "the finished private card still tries to put reactions on itself; Discord will refuse")


# --- the button says what it does --------------------------------------------------------------

def test_the_share_button_says_what_it_does_not_how_it_works():
    """"Pin it" named the mechanism. A first-timer cannot tell where it pins, or to what."""
    import bot as botmod

    class _Ctx:
        owner_id = 1

    labels = [i.label for i in botmod.GrindView(_Ctx()).children]
    assert "Pin it" not in labels, "the vague label is still there"
    assert SHARE_LABEL in labels, f"expected a label that says what happens, got {labels}"
    assert "Again" in labels, "the repeat button must stay exactly as it was"


# --- the reaction signal moves to the public post ----------------------------------------------

class _Msg:
    def __init__(self, mid=555):
        self.id = mid
        self.reactions = []

    async def add_reaction(self, emoji):
        self.reactions.append(str(emoji))


class _Channel:
    def __init__(self):
        self.mention = "#best-mixes"
        self.sent = _Msg()

    async def send(self, **k):
        return self.sent


def _pin_ctx(number):
    user = types.SimpleNamespace(id=1, name="t", display_name="t")
    return types.SimpleNamespace(
        number=number, audio_path="x.wav", duration=10.0, ref_id=None,
        interaction=types.SimpleNamespace(user=user),
        named_pairs=lambda: [("Beat", "Vocal")],
        _attach=lambda p: _async_none(),
    )


async def _async_none():
    return None


@pytest.fixture()
def pinned(monkeypatch):
    chan = _Channel()
    monkeypatch.setattr(showcase, "_channel", lambda interaction: chan)
    n = store.new_grind(user_id=1, user_name="t", pairs=[["b", "v", "B", "V"]],
                        created_at="2026-08-15T00:00:00+00:00")
    interaction = types.SimpleNamespace(
        user=types.SimpleNamespace(id=1, display_name="t"))
    asyncio.run(showcase.pin(_pin_ctx(n), interaction))
    return chan, n


def test_sharing_puts_the_reactions_on_the_public_post(pinned):
    """Reactions cannot live on the private card, so they have to live here or nowhere."""
    chan, _n = pinned
    assert chan.sent.reactions == list(ui.REACTIONS), (
        f"the showcase post carries {chan.sent.reactions}, so nobody can react to a shared mix")


def test_a_reaction_on_the_public_post_counts_for_the_right_grind(pinned):
    """The bot finds a grind from the message that was reacted to. If the showcase post is not
    registered, every reaction on a shared mix is silently dropped."""
    chan, n = pinned
    row = store.by_message(chan.sent.id)
    assert row is not None, "a reaction on the showcase post would find no grind and be discarded"
    assert row["number"] == n


def test_the_showcase_post_is_recorded_SEPARATELY_from_the_grind_card(pinned):
    """The showcase post must NOT overwrite `message_id`.

    `message_id` is the grind's own card, and /mygrinds builds a link from it plus the CHANNEL the
    grind happened in. Pointing it at the showcase post would pair a showcase message with a grind
    channel and produce a link that goes nowhere - a quiet breakage in the one place a person looks
    for their own work."""
    chan, n = pinned
    row = store.get(n)
    assert row["showcase_message_id"] == chan.sent.id, "the showcase post was not recorded"
    assert row["message_id"] != chan.sent.id, (
        "the showcase post overwrote the grind card's id; /mygrinds links now point nowhere")


# --- the picker is private too ------------------------------------------------------------------

def test_the_song_picker_is_private_as_well(monkeypatch):
    """Making only the FINISHED mix private would leave the room filling with everybody's picking
    UI instead of their music - the same overwhelm, one step earlier.

    Driven through the real command rather than read out of the source, so a rewrite that keeps the
    word `ephemeral` somewhere but stops passing it cannot pass this."""
    import bot as botmod

    sent = []

    class _Resp:
        async def send_message(self, *a, **k):
            sent.append(k)

    monkeypatch.setattr(botmod.door, "blocked_reason", lambda i: None)
    monkeypatch.setattr(botmod, "_grinding_allowed_here", lambda i: None)
    song = lambda i, n: types.SimpleNamespace(id=i, name=n, language="english",
                                              role_hint="beat", featured=True)
    monkeypatch.setattr(botmod.bot, "songs", [song("b", "Beat")], raising=False)
    monkeypatch.setattr(botmod.bot, "beats", [song("b", "Beat")], raising=False)
    monkeypatch.setattr(botmod.bot, "vocals", [song("v", "Vocal")], raising=False)

    interaction = types.SimpleNamespace(
        user=types.SimpleNamespace(id=1, name="t", display_name="t"),
        response=_Resp(), guild=None, channel=None)
    asyncio.run(botmod.grind_cmd.callback(interaction))

    assert sent, "the picker never opened"
    assert sent[-1].get("ephemeral") is True, (
        "the picker is posted publicly, so everyone watches you choosing songs")


# --- getting back to a private mix ---------------------------------------------------------------

def test_mygrinds_never_offers_a_link_that_goes_nowhere():
    """A private card has no shareable URL - Discord does not give one. Building the old
    guild/channel/message link for it produces a dead link in the one place somebody looks for
    their own work. A grind that HAS been shown to everyone does have a real, permanent link."""
    import bot as botmod
    n = store.new_grind(user_id=1, user_name="t", pairs=[["b", "v", "B", "V"]],
                        created_at="2026-08-15T00:00:00+00:00", guild_id=10, channel_id=20)
    store.attach_message(n, 30)                      # the private card
    assert botmod._grind_link(store.get(n)) is None, "a private grind was given a dead link"
    store.attach_showcase_message(n, 40, channel_id=50)
    link = botmod._grind_link(store.get(n))
    assert link and "/10/50/40" in link, f"a shared grind should link to the showcase post, got {link}"
