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

# THE FORM DOES NOT APPLY UNTIL THE COMMUNITY IS THIS BIG (founder, 2026-08-14). Below it anybody
# who arrives is let straight in; at or above it, newcomers meet the form and wait.
#
# An empty room is the worst thing that can happen to a new community, and a form in front of an
# empty room guarantees one. Below 30 the scarce thing is people; above 30 it is quality.
OPEN_BELOW = 30

# Announced-shut state, per guild. Only ever suppresses a REPEAT of the closing message - the door
# itself is computed live from the real member list on every single arrival, so a restart clearing
# this can at worst re-announce, never let the wrong person in.
_announced_shut: dict[int, bool] = {}

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

    if approved and community_count(getattr(interaction, "guild", None)) >= MEMBER_CAP:
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
        account_created=getattr(user, "created_at", None),
        taken=community_count(getattr(interaction, "guild", None)))
    try:
        msg = await channel.send(embed=embed, view=ReviewView())
        store.set_application_message(user.id, msg.id)
    except discord.HTTPException:
        log.warning("could not post application for review", exc_info=True)


def is_open() -> bool:
    """Is the door actually in use on this server?

    Keyed on the lobby channel being configured, so with no door set up NOTHING below changes and
    the server behaves exactly as it did before this feature existed.

    DELIBERATELY NOT the same question as `taking_all_comers`. This one asks "does this server use
    the door at all"; that one asks "is it currently letting everybody in". Collapsing them would
    make a dormant door and a wide-open door the same code path."""
    return bool(getattr(CFG, "door_channel_id", None))


def community_count(guild) -> int:
    """How many REAL community members are in. THE single definition of "a member" in this file.

    Founder, 2026-08-14, asked what 30 counts: "real people, excluding the Grinder bots + my two
    accounts (akshay5397 & bearwolf101)". So three kinds of member are subtracted:

      * BOTS - Grinder runs 2+ identities and Discord lists every one as a member;
      * THE SERVER OWNER - akshay5397; the founder is not a community member of their own room;
      * ADMINS - bearwolf101 holds `@Backup Admin`, which carries Administrator.

    The two operator accounts are recognised by WHAT THEY ARE, never by username: a Discord name
    can be changed, and a renamed operator would silently start counting, closing the door a person
    early with no error anywhere. Owning a server cannot be changed by accident.

    Somebody in the lobby holds no `@Member` and is therefore NOT counted - they have not been let
    in. If they counted, a queue of five would hold the door shut for ever and the founder's
    reopen-below-30 decision could never fire.

    WARNING - NOT `store.approved_count()`, the obvious counter and the wrong one: it counts only
    people who came through the FORM, so it misses vouched friends, admins and every free arrival
    under this feature. Using it would mean the door never closes at all.

    Reading `guild_permissions.administrator` is safe here. The 2026-08-13 finding - that it returns
    `Permissions.all()` for an Administrator holder - makes it useless for asking "does this member
    hold some OTHER permission". Asking whether somebody IS an admin is exactly what it answers."""
    if guild is None:
        return 0
    owner_id = getattr(guild, "owner_id", None)
    count = 0
    for person in getattr(guild, "members", None) or ():
        if getattr(person, "bot", False):
            continue
        if owner_id is not None and getattr(person, "id", None) == owner_id:
            continue
        perms = getattr(person, "guild_permissions", None)
        if perms is not None and (getattr(perms, "administrator", False)
                                  or getattr(perms, "manage_guild", False)):
            continue
        roles = getattr(person, "roles", None) or ()
        if not any(getattr(r, "name", None) == MEMBER_ROLE for r in roles):
            continue
        count += 1
    return count


def _member_list_can_be_trusted(guild) -> bool:
    """Can we actually see the whole server right now?

    THIS IS THE GUARD THAT MATTERS. `community_count` reads `guild.members`, which is a CACHE fed
    by a privileged intent. An empty or half-filled cache counts far too few people, and counting
    too few opens the door - so the one failure mode of a naive implementation is "the bot restarts,
    the cache is not warm yet, and every stranger who arrives in the next few seconds is handed
    `@Member` on a server that is supposed to be shut". Silent, irreversible, and exactly the
    direction this file says never to be wrong in.

    Two things are checked, both of which mean "do not trust this":
      * we can see NOBODY, which is never true of a real server the bot is in;
      * Discord's own `member_count` is higher than the number we hold, i.e. not fully chunked."""
    cached = len(getattr(guild, "members", None) or ())
    if cached == 0:
        return False
    total = getattr(guild, "member_count", None)
    if isinstance(total, int) and total > cached:
        return False
    return True


def taking_all_comers(guild) -> bool:
    """Is the community still small enough that anybody may walk in without the form?

    Computed live from the real member list every time it is asked, which is what makes the
    founder's reopen-below-30 decision work: nothing is latched, nothing is cached.

    UNKNOWN COUNTS AS SHUT. With no guild, or a member list we cannot trust, this returns False -
    the restrictive answer. A stranger wrongly let in cannot be undone by a later correction; a
    person wrongly asked to fill a form can just be approved."""
    if guild is None or not _member_list_can_be_trusted(guild):
        return False
    return community_count(guild) < OPEN_BELOW


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
    if taking_all_comers(getattr(interaction, "guild", None)):
        return None      # under OPEN_BELOW everybody is admitted anyway, so there is nothing here
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


async def _let_them_in(member, *, reason: str, message: str) -> bool:
    """Hand somebody `@Member` and tell them. True if they really hold the role now.

    Shared by the two ways in - a personal vouch, and the door being open - so there is one place
    that grants membership rather than a near-copy per route."""
    guild = member.guild
    role = discord.utils.get(guild.roles, name=MEMBER_ROLE)
    if role is None:
        log.warning("arrival to let in but no @%s role exists", MEMBER_ROLE)
        return False
    try:
        await member.add_roles(role, reason=reason)
    except discord.HTTPException:
        log.warning("could not let %s in", member, exc_info=True)
        return False
    try:
        await member.send(message)
    except (discord.Forbidden, discord.HTTPException):
        pass    # DMs shut; they can see the server either way, which is the part that matters
    return True


def note_door_is_open(guild) -> None:
    """Remember that the door is currently open, so the next closing is news again.

    Pure bookkeeping - it sends nothing and touches no network. That matters: this runs BEFORE
    anybody is admitted, and anything that can fail before a grant can stop somebody getting in."""
    if taking_all_comers(guild):
        _announced_shut[getattr(guild, "id", 0)] = False


async def announce_if_just_closed(guild) -> bool:
    """Say once, in the applications room, that the door has just shut. True if it posted.

    CLOSINGS ARE ANNOUNCED, OPENINGS ARE NOT (founder, 2026-08-14). A closing changes what every
    stranger experiences, so it is worth a line. An opening is not actionable - there is nothing
    for the founder to do about it - and with the door tracking the number live, a single member
    leaving and rejoining would otherwise post a pair of messages every time."""
    shut = not taking_all_comers(guild)
    gid = getattr(guild, "id", 0)
    if not shut:
        _announced_shut[gid] = False        # it is news again next time it becomes true
        return False
    if _announced_shut.get(gid):
        return False
    _announced_shut[gid] = True
    try:
        channel = _review_channel(guild)
        if channel is None:
            return False
        await channel.send(
            f"The door just closed - there are now {OPEN_BELOW} members, so newcomers will see "
            "the form and wait for you instead of walking straight in. Nothing to do; this is "
            "just so you know it happened.")
    except Exception:  # noqa: BLE001 - A NOTE MUST NEVER COST SOMEBODY THEIR ENTRY.
        # This is the lowest-value thing in the file and it runs on the same path as the
        # highest-value one. Anything it raises is swallowed: the founder missing one message
        # is a nuisance, a vouched friend silently left in the lobby is a broken promise.
        log.warning("could not announce that the door closed", exc_info=True)
        return False
    return True


async def on_member_join(member) -> bool:
    """Somebody arrived. True if they are now a member without having filled anything in.

    TWO ways that happens, checked in this order:

      1. THE FOUNDER VOUCHED FOR THEM (`/invitefriend`). Works at any size, door open or shut.
      2. THE COMMUNITY IS STILL SMALL (under `OPEN_BELOW`). Founder, 2026-08-14: below 30 real
         members anybody may join freely; the form starts after that.

    Everybody else is untouched and simply lands in the lobby, exactly as before.

    A vouch is spent BEFORE the size check on purpose. Below 30 the same person would have got in
    either way, and silently keeping their single-use link alive would let it be forwarded later,
    once the door is shut - turning a spent vouch into a permanent hole."""
    if member.bot or not is_open():
        return False
    guild = member.guild

    # Observe the state BEFORE anyone is granted. Without this the open window is invisible: the
    # 30th person arrives while the door is open, is let in, and by the time we look it is shut
    # again - so a door that genuinely reopened and let somebody through would never be reported
    # as closing a second time. Deliberately the pure bookkeeping call, not the sending one.
    note_door_is_open(guild)

    let_in = False
    code = await which_invite_was_used(guild)
    if code is not None and code in store.open_vouch_codes() \
            and store.claim_vouch(code=code, used_by=member.id, when=_now()):
        let_in = await _let_them_in(
            member, reason="Invited personally - skipped the form",
            message=("You are in - somebody vouched for you, so you can skip the queue.\n\n"
                     "Head to the grind channel and type `/grind` to make your first mix."))
        if let_in:
            log.info("vouched: %s came in on %s without the form", member, code)
    elif taking_all_comers(guild):
        let_in = await _let_them_in(
            member, reason=f"Under {OPEN_BELOW} members - the door is open",
            message=("You are in. Grinder is small and still growing, so there is no form yet."
                     "\n\nHead to the grind channel and type `/grind` to make your first mix."))
        if let_in:
            log.info("open door: %s walked in; community now %d", member, community_count(guild))

    # Checked on EVERY arrival, not only a successful one. The 30th person walking in is what
    # shuts the door, but so is the first arrival at a server that was already over the line when
    # this feature was switched on - and that one is not let in, so a check that only ran after a
    # grant would never tell the founder anything.
    await announce_if_just_closed(guild)
    return let_in


def can_grant_member(guild) -> tuple[bool, str]:
    """Whether the bot can actually hand out @Member, and why not if it cannot.

    THE SILENT FAILURE THIS EXISTS TO STOP. Discord only lets a bot assign roles strictly BELOW
    its own highest role. `@Member` was created level with `@Grinder`, which is fine while the bot
    holds Administrator (that bypasses the check) and breaks the moment it does not. The failure is
    invisible in the worst way: the application is written as `approved`, the founder sees the card
    turn green, and the person is left staring at the lobby. There is no error anywhere unless
    somebody happens to read an ephemeral followup.

    Checked at startup and by the lock script, so it is reported before it costs somebody an
    approval rather than after."""
    if guild is None:
        return False, "no server"
    role = discord.utils.get(guild.roles, name=MEMBER_ROLE)
    if role is None:
        return False, f"the @{MEMBER_ROLE} role does not exist yet"
    me = getattr(guild, "me", None)
    if me is None:
        return False, "the bot is not in the server"
    if me.guild_permissions.administrator:
        return True, ""
    if not me.guild_permissions.manage_roles:
        return False, "the bot does not have the Manage Roles permission"
    if me.top_role.position <= role.position:
        return False, (
            f"the bot's own role sits at or below @{MEMBER_ROLE} in Server Settings > Roles, so "
            f"Discord will not let it hand that role out. Drag @{me.top_role.name} above "
            f"@{MEMBER_ROLE}")
    return True, ""
