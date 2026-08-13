"""The door: applying to join, and the founder choosing who gets in.

Founder, 2026-08-13: "the first 50 users will be admitted. All the users who want to actually use
the Discord bot would have to fill out a form, and I would be choosing whom to give access to based
on the form... I don't want random gamers or random teams to join, but people who actually use
Suno.ai, who use Midjourney, or who are actually DJs. I want to spot them and give them first
access."

THE SHAPE THAT FOLLOWS FROM "CHOOSING", and it is not the obvious one. Approving cards as they
arrive is first-come-first-served wearing a review flow: by the time a good application shows up
the seats are gone. So applications POOL. `/applications` shows everyone still waiting side by
side, and `/applications suno` narrows the pool to a word the founder typed.

THE LINE THIS FILE MUST NOT CROSS. Grinder never scores, ranks, recommends or flags an applicant.
Searching for a word the founder typed is a filing cabinet; "this one looks promising" is an
opinion, and an opinion shown before a human's own read poisons that read. Same reasoning as the
standing rule that no card ever judges a grind - a different surface, the same failure.

Nothing in here is wired to the live server by anything this module does. Closing the door is a
separate, deliberate step: `scripts/lock_the_door.py`.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import discord

import store
from botconfig import load_config

log = logging.getLogger("promptdj.discord")
CFG = load_config()

# The founder's own five questions, in their words and their order. The list is the contract: the
# store keeps answers keyed by these labels, so changing one is a copy change, not a schema change.
# Discord allows a maximum of five short text inputs in one modal, so this is exactly full.
# EMAIL IS QUESTION 2 AND IT IS REQUIRED (founder, 2026-08-13). It replaced "What you expect" -
# their pick, because it overlapped almost entirely with "Why you want to join" and in practice
# both boxes got the same sentence.
#
# Why it had to move INTO the form rather than stay a follow-up: Discord cannot force anybody
# through a second pop-up. They can dismiss it and walk away, so "optional" was never a setting
# somebody chose - it was the only honest label for a step nobody can be made to finish. Inside
# the modal, Discord itself refuses the submission without it.
QUESTIONS: tuple[tuple[str, str, int], ...] = (
    ("Your name", "What should we call you?", 100),
    ("Your email", "you@example.com - so we can tell you the outcome", 200),
    ("Your relation to music", "DJ, producer, listener, something else?", 300),
    ("AI tools you have used", "Suno, Midjourney, ChatGPT, none yet...", 300),
    ("Why you want to join", "What made you want in?", 400),
)

# Which question is the email, by NAME not index, so reordering the list cannot silently point
# validation at the wrong box.
EMAIL_LABEL = "Your email"

# What Discord must not let somebody skip. Name and email are the two the founder needs in
# order to reach a person at all; a thin answer to the rest is itself information.
REQUIRED = ("Your name", EMAIL_LABEL)

# The first fifty seats. Changeable in one place; raising it is painless, lowering it means removing
# people, so it starts where the validation bar is (~50 real casual creators).
MEMBER_CAP = 50

# The role that IS membership. Approving somebody is exactly "give them this".
MEMBER_ROLE = "Member"

_ROLE_MISSING = ("The `@Member` role does not exist yet, so there is nothing to grant. "
                 "Run `scripts/lock_the_door.py` first.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------------------
# The form.
# --------------------------------------------------------------------------------------
class ApplicationModal(discord.ui.Modal, title="Ask to join Grinder"):
    """Five short questions. Everything is optional to Discord except what we mark required, and
    only the first is required here - a form that refuses to submit loses the applicant, and a
    thin answer is itself information the founder can act on."""

    def __init__(self) -> None:
        super().__init__(timeout=None)
        self._inputs: list[discord.ui.TextInput] = []
        for i, (label, placeholder, maxlen) in enumerate(QUESTIONS):
            ti = discord.ui.TextInput(
                label=label,
                placeholder=placeholder,
                max_length=maxlen,
                required=(label in REQUIRED),
                # The email is a one-liner whatever its length allowance.
                style=(discord.TextStyle.short
                       if maxlen <= 100 or label == EMAIL_LABEL
                       else discord.TextStyle.paragraph),
            )
            self._inputs.append(ti)
            self.add_item(ti)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        answers = {label: (ti.value or "").strip()
                   for (label, _, _), ti in zip(QUESTIONS, self._inputs)}
        user = interaction.user
        try:
            store.save_application(user_id=user.id, user_name=user.display_name,
                                   answers=answers, when=_now())
        except Exception:  # noqa: BLE001 - never lose an applicant to a storage hiccup
            log.exception("could not save an application")
            await interaction.response.send_message(
                "Something went wrong saving that. Try again in a minute.", ephemeral=True)
            return

        # SAVED FIRST, WARNED SECOND. A bad-looking address is worth flagging, but refusing
        # the whole application would throw away four answers they just typed - Discord keeps
        # nothing from a rejected modal, so they would rewrite the lot. Re-applying replaces
        # the row, so "press it again" is a real fix rather than a dead end.
        warning = ""
        if not looks_like_an_email(answers.get(EMAIL_LABEL, "")):
            warning = (f"\n\n:warning:  `{answers.get(EMAIL_LABEL, chr(39)+chr(39))}` does not look "
                       "like an email address, so we may not be able to reach you. Press "
                       "**Ask to join** again to fix it - it replaces this application "
                       "rather than adding another.")

        await interaction.response.send_message(waiting_message() + warning, ephemeral=True)
        await post_for_review(interaction, answers)


def looks_like_an_email(value: str) -> bool:
    """Deliberately loose. The point is to catch a typo like "akshay at gmail", not to police what
    is a valid address - every strict email regex on the internet rejects somebody's real one, and
    a rejected applicant is a worse outcome than an address that bounces."""
    v = (value or "").strip()
    if " " in v or v.count("@") != 1:
        return False
    local, _, domain = v.partition("@")
    return bool(local) and "." in domain and not domain.startswith(".") \
        and not domain.endswith(".")


class DoorView(discord.ui.View):
    """The one button in the lobby. `timeout=None` and a fixed `custom_id` make it PERSISTENT:
    the lobby post sits there for weeks and must still work after a restart, which a default view
    would not - it would go dead and read as a broken community to the newcomer."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Ask to join", emoji="🚪",
                       style=discord.ButtonStyle.primary, custom_id="door:apply")
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        existing = store.application(interaction.user.id)
        if existing is not None and existing["state"] == "approved":
            await interaction.response.send_message("You are already in.", ephemeral=True)
            return
        await interaction.response.send_modal(ApplicationModal())


# --------------------------------------------------------------------------------------
# The review.
# --------------------------------------------------------------------------------------
def application_embed(*, user_name: str, user_id: int, answers: dict,
                      account_created: datetime | None = None,
                      taken: int | None = None, state: str = "pending") -> discord.Embed:
    """One application, laid out to be READ. No score, no ranking, no recommendation.

    The seat count sits on the card because the founder is spending a scarce thing and should see
    the cost at the moment of the decision, not afterwards."""
    colour = {"approved": 0x2ECC71, "declined": 0x95A5A6}.get(state, 0xA824CC)
    e = discord.Embed(title=f"{user_name}", colour=discord.Colour(colour))
    e.set_footer(text=f"user id {user_id}")
    for label, _, _ in QUESTIONS:
        value = (answers.get(label) or "").strip()
        e.add_field(name=label, value=value[:1024] if value else "(left blank)", inline=False)
    if account_created is not None:
        e.add_field(name="Discord account created", value=account_created.strftime("%d %b %Y"),
                    inline=True)
    if taken is not None:
        e.add_field(name="Seats", value=f"{taken} of {MEMBER_CAP} taken", inline=True)
    if state == "approved":
        e.description = "Approved."
    elif state == "declined":
        e.description = "Not now. They keep their place in the lobby and can be approved later."
    return e


class ReviewView(discord.ui.View):
    """Approve / Not now. Persistent for the same reason as the door button: the founder reads a
    pool that has been accumulating for days, and yesterday's cards must still work.

    THE IDS ARE FIXED, and the applicant is looked up from the MESSAGE. An earlier version put the
    applicant's id inside the custom_id (`door:approve:1536...`), which reads as the obvious way to
    carry it. It is not: Discord matches a persistent button by its EXACT id, so the single view
    registered at startup (`door:approve:0`) matched none of the real cards. The bot did not
    recognise its own buttons, never answered, and Discord told the founder "Grinder didn't respond
    in time" - with nothing in the log, because no handler ever ran.

    The card's message id is already stored against the application, so it is the natural key."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success,
                       custom_id="door:approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _decide(interaction, button, approved=True)

    @discord.ui.button(label="Not now", style=discord.ButtonStyle.secondary,
                       custom_id="door:decline")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _decide(interaction, button, approved=False)


async def _decide(interaction: discord.Interaction, button: discord.ui.Button, *,
                  approved: bool) -> None:
    row = store.application_by_message(getattr(interaction.message, "id", 0))
    if row is None:
        await interaction.response.send_message(
            "I cannot tell whose application this card is. It may predate a restart - "
            "`/applications` still has them all.", ephemeral=True)
        return
    user_id = row["user_id"]
    if row["state"] != "pending":
        await interaction.response.send_message(f"Already {row['state']}.", ephemeral=True)
        return

    if approved and store.approved_count() >= MEMBER_CAP:
        # WARNS, never refuses. The number is the founder's; a tool that hard-blocks its owner is
        # worse than one that asks. A second press goes through because the state check above is
        # what actually guards against a double-grant.
        await interaction.response.send_message(
            f"All {MEMBER_CAP} seats are taken. Press Approve again to go over the cap.",
            ephemeral=True)
        return

    # ANSWER DISCORD FIRST, THEN DO THE WORK. A button has THREE SECONDS to respond or Discord
    # gives up and shows the presser "Grinder didn't respond in time" - which is what the founder
    # got on their first real approval, 2026-08-13. Everything below this line makes API calls
    # (fetch the member, add the role, DM them), and any one of them can outlast three seconds on
    # a slow connection. Deferring acknowledges the press immediately and buys fifteen minutes.
    #
    # It has to be `defer()` on a BUTTON, which defers an UPDATE to the existing message - so the
    # card is edited in place afterwards via `edit_original_response`, exactly as before. From here
    # on nothing may use `interaction.response`; it is already used.
    await interaction.response.defer()

    if not store.decide_application(user_id=user_id, state="approved" if approved else "declined",
                                    by=interaction.user.id, when=_now()):
        await interaction.followup.send("Somebody just decided that one.", ephemeral=True)
        return

    granted_note = ""
    if approved:
        granted_note = await _grant_member(interaction.guild, user_id)

    answers = json.loads(row["answers"])
    embed = application_embed(
        user_name=row["user_name"] or str(user_id), user_id=user_id, answers=answers,
        taken=store.approved_count(), state="approved" if approved else "declined")
    await interaction.edit_original_response(embed=embed, view=None)
    if granted_note:
        await interaction.followup.send(granted_note, ephemeral=True)
    await _tell_the_applicant(interaction, user_id, approved=approved)


async def _grant_member(guild, user_id: int) -> str:
    """Give somebody the role that IS membership. Returns a note for the founder, or "" if fine."""
    if guild is None:
        return _ROLE_MISSING
    role = discord.utils.get(guild.roles, name=MEMBER_ROLE)
    if role is None:
        return _ROLE_MISSING
    # fetch, not get: `get_member` reads a cache this bot does not keep (Intents.default()), so it
    # returns None for everybody and an approval would report "not in the server any more" about
    # somebody standing right there. Same root cause as the review card never posting.
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except discord.NotFound:
            return "They are not in the server any more, so there was no one to give the role to."
        except discord.HTTPException as e:
            return f"Could not look them up: {e}"
    try:
        await member.add_roles(role, reason="Application approved")
    except discord.Forbidden:
        return (f"I cannot hand out `@{MEMBER_ROLE}`. My own role has to sit ABOVE it in the "
                "server settings.")
    except discord.HTTPException as e:
        return f"Could not grant the role: {e}"
    return ""


async def _tell_the_applicant(interaction, user_id: int, *, approved: bool) -> None:
    """DM them, and fall back to the lobby if their DMs are shut. Never fatal: a decision that
    stuck must not look failed because a DM bounced."""
    text = ("You are in. Head to the grind channel and type `/grind`."
            if approved else
            "Thanks for applying. The room is small and full for now, so not yet - your "
            "application stays in the pile and nothing is lost.")
    try:
        user = interaction.client.get_user(user_id) or await interaction.client.fetch_user(user_id)
        await user.send(text)
        return
    except (discord.Forbidden, discord.HTTPException, AttributeError):
        pass
    channel = _door_channel(interaction.guild)
    if channel is not None:
        try:
            await channel.send(f"<@{user_id}> {text}")
        except discord.HTTPException:
            log.warning("could not reach applicant %s at all", user_id)


def _door_channel(guild):
    if guild is None or not getattr(CFG, "door_channel_id", None):
        return None
    return guild.get_channel(CFG.door_channel_id)


def _review_channel(guild):
    if guild is None or not getattr(CFG, "applications_channel_id", None):
        return None
    return guild.get_channel(CFG.applications_channel_id)


async def post_for_review(interaction, answers: dict) -> None:
    """Put an application in front of the founder. Silent if no review channel is configured -
    the application is already stored, so it is never lost, and `/applications` still finds it.

    THE GUILD COMES FROM THE INTERACTION, not from a search. The first version asked every guild
    "is this user one of your members?" and took the one that said yes - which needs a member
    cache the bot does not have, because it runs on `Intents.default()`. So `get_member` returned
    None for everybody, the search found no guild, and every application was silently stored and
    never shown. Found on the founder's first real test, 2026-08-13: the form worked, the card
    never appeared.

    An interaction already carries the server it happened in. Asking it is both simpler and free
    of any dependency on what happens to be cached."""
    user = interaction.user
    channel = _review_channel(getattr(interaction, "guild", None))
    if channel is None:
        log.info("no applications channel configured; %s's application is stored only", user.id)
        return
    embed = application_embed(
        user_name=user.display_name, user_id=user.id, answers=answers,
        account_created=getattr(user, "created_at", None), taken=store.approved_count())
    try:
        msg = await channel.send(embed=embed, view=ReviewView())
        store.set_application_message(user.id, msg.id)
    except discord.HTTPException:
        log.warning("could not post application for review", exc_info=True)


def is_open() -> bool:
    """Is the door actually in use on this server?

    Keyed on the lobby channel being configured, so with no door set up NOTHING below changes and
    the server behaves exactly as it did before this feature existed."""
    return bool(getattr(CFG, "door_channel_id", None))


def blocked_reason(interaction) -> str | None:
    """None if this person may use the bot, otherwise the sentence to send back.

    WHY THIS EXISTS, and it is not belt-and-braces. Until this, the gate was ONLY channel
    permissions: an unapproved person could not see a grind channel, so they could not grind there.
    Two ways that fails, both real:

      * `_grinding_allowed_here` in bot.py allows grinding EVERYWHERE when no grind category is
        configured - including the lobby, which every unapproved person can see by design;
      * a channel created later, or one overwrite set wrongly, is open until somebody notices.

    A permission mistake should cost visibility, not the whole gate. The founder's ask was that
    approved people use the bot, so the bot itself checks.

    Admins are never blocked - locking the owner out of their own bot to enforce their own rule
    would be absurd, and they are the one who approves people."""
    if not is_open():
        return None                                  # the door is not in use; nothing changes
    member = getattr(interaction, "user", None)
    perms = getattr(member, "guild_permissions", None)
    if perms is not None and (perms.manage_guild or perms.administrator):
        return None
    roles = getattr(member, "roles", None)
    if roles is not None and any(getattr(r, "name", None) == MEMBER_ROLE for r in roles):
        return None
    row = store.application(getattr(member, "id", 0))
    if row is not None and row["state"] == "pending":
        return ("Your application is in. Grinder is invite only while it is small, so hold tight - "
                "you will hear back.")
    return ("Grinder is invite only right now. Head to the door and ask to join: "
            f"<#{CFG.door_channel_id}>")


def waiting_message() -> str:
    """What somebody reads the moment they apply.

    Founder, 2026-08-13: send them a music link too - "this is the kind of music which you
    can create, and please wait for the moderators' approval".

    The link matters more than it looks. Between applying and being approved a person has
    NOTHING: they cannot see a channel, hear a room, or watch anybody else grind. Hearing what
    Grinder actually makes is the only thing standing between "I am waiting for something
    good" and "I filled in a form and nothing happened". Configured rather than hard-coded, so
    the founder can point it at their best mix of the moment without a code change."""
    lines = [
        "Got it. Your application is in.",
        "",
        "This is a small room on purpose, so it is not instant. Somebody reads every one of "
        "these by hand, and you will hear back by DM - and by email if your DMs are shut.",
    ]
    url = (getattr(CFG, "sample_mix_url", "") or "").strip()
    if url:
        # The founder's own framing: this is what people make in here, and once you are in you can
        # make things like it. Said as a fact about the room, not as a promise about them.
        lines += ["",
                  "This is the kind of thing people are making in here. Once you are in, you can "
                  "make things like this:",
                  url]
    return "\n".join(lines)


def lobby_embed() -> discord.Embed:
    """The only thing a newcomer can see. Says what this is, that it is small on purpose, and what
    to press. No hype, and no promise about how fast a decision comes."""
    e = discord.Embed(
        title="Grinder is invite only for now",
        description=(
            "Grinder makes mashups out of two songs. You pick a beat and a vocal, it builds the "
            "mix, and it plays out loud in the listening rooms.\n\n"
            "The room is small on purpose while it is being built, so there are a limited number "
            "of places. Press the button, answer five short questions, and you will hear back.\n\n"
            "There is nothing else to do here until then."),
        colour=discord.Colour(0xA824CC))
    return e


# --------------------------------------------------------------------------------------
# Vouch links: somebody the founder invites personally, who never sees the form.
# --------------------------------------------------------------------------------------
# Founder, 2026-08-13: "if I personally want to invite someone who I know, they don't have to fill
# out the form to enter... whatever is the simplest way for my friend of mine to enter without
# filling the form."
#
# For the FRIEND this is one click and nothing else - which is the whole point, and the reason a
# link beat asking the founder for a friend's 18-digit user id.
#
# Discord cannot attach a role to an invite, so the bot has to work out WHICH link somebody used.
# The trick is counting: remember every invite's use count, and when somebody joins, look for the
# one that changed. A single-use invite does not come back with a higher count - it VANISHES once
# spent, so a disappeared code counts as used too. Both cases are handled below; missing that
# second one is the classic way this feature half-works.

_invite_uses: dict[int, dict[str, int]] = {}   # guild id -> {code: uses}


async def remember_invites(guild) -> None:
    """Snapshot every invite's use count. Called at startup and after each join."""
    try:
        _invite_uses[guild.id] = {inv.code: (inv.uses or 0) for inv in await guild.invites()}
    except discord.Forbidden:
        log.warning("cannot read invites (needs Manage Server) - vouch links will not work")
    except discord.HTTPException:
        log.warning("could not refresh the invite list", exc_info=True)


async def which_invite_was_used(guild) -> str | None:
    """The code somebody just joined on, or None if it cannot be told apart.

    None is a normal answer, not a failure: two people joining in the same instant, or a join
    through a vanity URL, are genuinely ambiguous. The caller treats None as "not vouched", which
    means the person lands in the lobby like anybody else - the safe direction to be wrong in."""
    before = _invite_uses.get(guild.id, {})
    try:
        current = {inv.code: (inv.uses or 0) for inv in await guild.invites()}
    except (discord.Forbidden, discord.HTTPException):
        return None

    grew = [c for c, n in current.items() if n > before.get(c, 0)]
    # A single-use invite is DELETED the moment it is used, so it is absent rather than higher.
    vanished = [c for c in before if c not in current]
    _invite_uses[guild.id] = current

    candidates = grew + vanished
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        log.info("two invites changed at once - cannot tell which was used: %s", candidates)
    return None


async def create_vouch_invite(channel, created_by: int) -> str | None:
    """A single-use link that lets one person straight in, no form.

    Single use on purpose: a vouch is for one named friend. A link that keeps working is a hole in
    the door that widens every time it is forwarded."""
    try:
        inv = await channel.create_invite(max_age=604800, max_uses=1, unique=True,
                                          reason=f"Vouch invite created by {created_by}")
    except discord.HTTPException:
        log.warning("could not create a vouch invite", exc_info=True)
        return None
    store.add_vouch(code=inv.code, created_by=created_by, when=_now())
    _invite_uses.setdefault(channel.guild.id, {})[inv.code] = 0
    return inv.url


async def on_member_join(member) -> bool:
    """Let a vouched arrival straight in. True if they were vouched and are now a member.

    Everybody else is untouched and simply lands in the lobby, exactly as before."""
    if member.bot or not is_open():
        return False
    guild = member.guild
    code = await which_invite_was_used(guild)
    if code is None or code not in store.open_vouch_codes():
        return False
    if not store.claim_vouch(code=code, used_by=member.id, when=_now()):
        return False

    role = discord.utils.get(guild.roles, name=MEMBER_ROLE)
    if role is None:
        log.warning("vouched arrival but no @%s role exists", MEMBER_ROLE)
        return False
    try:
        await member.add_roles(role, reason="Invited personally - skipped the form")
    except discord.HTTPException:
        log.warning("could not let a vouched member in", exc_info=True)
        return False

    log.info("vouched: %s came in on %s without the form", member, code)
    try:
        await member.send(
            "You are in - somebody vouched for you, so you can skip the queue.\n\n"
            "Head to the grind channel and type `/grind` to make your first mix.")
    except (discord.Forbidden, discord.HTTPException):
        pass    # DMs shut; they can see the server either way, which is the part that matters
    return True
