"""`/setup` — Grinder builds the community server for you.

Discord will not let a bot create a *server*: the API endpoint that does it makes the BOT the
owner, and handing ownership back to a human is not properly supported, so the founder would not
own their own community. Driving the founder's own account with browser automation is worse — that
is self-botting under Discord's terms and risks the account. So the split is:

    the founder  creates an empty server (three clicks) and invites the bot
    this module  builds everything inside it

Which is nearly all of it: categories, channels, topics, permissions, roles, the server icon, the
custom emojis, and the welcome post.

IDEMPOTENT BY DESIGN. Every step checks for what it would create and skips it if it is already
there, so running `/setup` twice is safe and never duplicates a channel. That matters because the
first run can partially fail on a rate limit or a missing permission — the fix is then simply to
run it again.

NOT set here:
  * the server NAME — the founder named it; silently renaming someone's server is rude.
  * the BANNER and INVITE SPLASH — Discord gates these behind boost levels 2 and 1. The artwork is
    shipped and ready (`brand.BANNER`); `apply_banner` will set it the moment the server qualifies.
"""
from __future__ import annotations

import dataclasses
import logging

import discord

import brand

log = logging.getLogger("grinder.setup")


@dataclasses.dataclass(frozen=True)
class ChannelSpec:
    name: str
    topic: str = ""
    voice: bool = False
    # True for channels only the bot and staff should post in (#welcome). Everyone
    # can still READ them — this stops a welcome channel filling up with chatter.
    read_only: bool = False
    # A prettier name to create the channel WITH. Discord slugifies text-channel names (lowercase,
    # hyphenated) but leaves voice-channel names alone, so a voice channel can read "The Booth".
    # `label` is used for BOTH creating and looking up — they have to be the same string, or the
    # idempotency check misses the channel it just made and creates a duplicate every run.
    display: str = ""

    @property
    def label(self) -> str:
        return self.display or self.name


@dataclasses.dataclass(frozen=True)
class CategorySpec:
    name: str
    channels: tuple[ChannelSpec, ...]


# The community, as a data structure. Change this list to change the server — it is deliberately
# the only place the layout is described, so re-shaping the community is a one-place edit.
STRUCTURE: tuple[CategorySpec, ...] = (
    CategorySpec("🚪 START HERE", (
        ChannelSpec("read-this-first", "how it works, 30 seconds", read_only=True),
        ChannelSpec("rules", "the no-rules rules", read_only=True),
        ChannelSpec("announcements", "changelog, events", read_only=True),
    )),
    CategorySpec("⚙️ GRIND", (
        # THE channel. Everyone grinds here, in public, on purpose. The whole Midjourney mechanic
        # is that generation happens in one place where strangers watch each other work - scatter
        # it across channels and nobody sees anyone else's, which kills the only reason to be in a
        # server rather than using the app alone.
        ChannelSpec("the-grinder", "type /grind - everyone grinds here, in the open"),
        # The curated half. The grinder is everything: the wins, the disasters, the noise.
        # Fresh-grinds is the highlight reel, filled by anyone hitting 📌 on a card. Failures are
        # entertaining but you still want somewhere to send a newcomer.
        ChannelSpec("fresh-grinds", "the ones that survived"),
        ChannelSpec("the-booth", voice=True, display="The Booth"),
    )),
    CategorySpec("💬 TALK", (
        # The biggest gap in the old layout: nowhere to just talk. A server whose only channels are
        # functional reads as a support desk, not a place. People need somewhere to say "yo"
        # without it being A Contribution.
        ChannelSpec("general", "talk about whatever"),
        ChannelSpec("requests", "broken things, missing things, wild ideas"),
    )),
)

# Old name -> new name. A RENAME rather than create-and-delete, because renaming keeps the messages,
# the pins and the channel's history; creating a replacement throws all of that away.
RENAMES: tuple[tuple[str, str], ...] = (
    ("getting-started", "read-this-first"),
    ("i-made-this", "fresh-grinds"),
)

# Channels the new layout does not have. Only ever deleted when EMPTY - see `delete_retired`.
# #feedback folds into #requests: nobody stops to ask themselves "is this a request or feedback?",
# so both channels end up half dead. One voice channel, not two: with a small server two rooms
# guarantee both are empty, because everyone is waiting in the wrong one.
RETIRED: tuple[str, ...] = ("feedback", "general voice")
RETIRED_VOICE: tuple[str, ...] = ("General",)

# Four roles. Three of them carry ZERO permissions and exist purely so a name shows up in colour,
# which does more for retention than most features.
ROLES: tuple[tuple[str, int, str], ...] = (
    ("First Grind", brand.MID, "Automatic, on your first grind. Proof you have done it."),
    ("Head Grinder", brand.PRIMARY, "Most 🔥 in a week. Rotates."),
    ("Founding Member", brand.PINK, "First 100 members. Hard cap."),
    ("Resident DJ", brand.DEEP, "Kept from the old layout; harmless."),
)

# Deleted, not kept: an opt-in role with no way to opt in. Only an admin can hand it out, so
# "grab @Session Crew to be pinged" was never possible. @everyone is the right tool until the
# server is big enough that broad pings annoy people; then it comes back as a reaction-role.
RETIRED_ROLES: tuple[str, ...] = ("Session Crew",)

VOICE_CHANNEL = "the-booth"
WELCOME_CHANNEL = "read-this-first"
GRIND_CHANNEL = "the-grinder"
SHOWCASE_CHANNEL = "fresh-grinds"


@dataclasses.dataclass
class Report:
    """What actually happened, so the command can tell the founder rather than claim success."""
    created: list[str] = dataclasses.field(default_factory=list)
    skipped: list[str] = dataclasses.field(default_factory=list)
    failed: list[str] = dataclasses.field(default_factory=list)
    # Channels on the server that aren't in the plan. Reported, never deleted - see extra_channels.
    extra: list[str] = dataclasses.field(default_factory=list)
    # The channel ids the bot needs in its config, so the founder can paste them in one go.
    channel_ids: dict = dataclasses.field(default_factory=dict)

    def ok(self, label: str) -> None:
        self.created.append(label)

    def already(self, label: str) -> None:
        self.skipped.append(label)

    def error(self, label: str, exc: Exception) -> None:
        # The reason matters more than the exception type — "Missing Permissions" is the answer to
        # 90% of setup failures, and the founder can act on it.
        reason = getattr(exc, "text", None) or str(exc) or exc.__class__.__name__
        self.failed.append(f"{label}: {reason}")
        log.warning("setup step failed: %s", label, exc_info=exc)


def _by_name(items, name: str):
    lowered = name.lower()
    return discord.utils.find(lambda c: c.name.lower() == lowered, items)


def _overwrites_for(guild: discord.Guild, ch: ChannelSpec):
    """The permission overwrites a channel is created with.

    Two things learned the hard way on the first real run:

    1. For an ordinary channel there are NO overwrites, and discord.py wants `MISSING` for that,
       not `None` — passing None raises "overwrites parameter expects a dict" and the channel is
       never created. (Every read-only channel succeeded and every normal one failed, which is
       what pointed at this.)

    2. A read-only channel must still explicitly ALLOW the bot to post. Channel-level overwrites
       beat server-level role permissions, so denying `send_messages` to @everyone also silences
       Grinder — which is how the welcome post failed with "Missing Permissions" in the very
       channel it had just created."""
    if not ch.read_only:
        return discord.utils.MISSING
    return {
        # everyone: read and react, but don't post
        guild.default_role: discord.PermissionOverwrite(
            send_messages=False, add_reactions=True),
        # the bot: must be able to post here, or it can't write the welcome
        guild.me: discord.PermissionOverwrite(
            send_messages=True, embed_links=True, attach_files=True),
    }


async def apply_icon(guild: discord.Guild, report: Report, *, force: bool = False) -> None:
    """Set the server icon to Grinder's mark.

    Skipped by default if the server already has an icon — replacing art the founder chose
    themselves would be presumptuous. `force` (from `/setup refresh_branding:True`) overrides that,
    which is how updated artwork gets onto an already-branded server."""
    if guild.icon is not None and not force:
        report.already("server icon (already set - use /setup refresh_branding:True to replace)")
        return
    data = brand.image_bytes(brand.ICON)
    if data is None:
        report.already("server icon (artwork missing)")
        return
    try:
        await guild.edit(icon=data, reason="Grinder /setup - brand the server")
        report.ok("server icon" + (" (replaced)" if force else ""))
    except Exception as e:  # noqa: BLE001 — one failed step must not abort the rest of setup
        report.error("server icon", e)


async def apply_banner(guild: discord.Guild, report: Report) -> None:
    """Set the banner. Only possible once the server has boost level 2. Reports the reason
    plainly rather than failing silently, because "why is there no banner" is an obvious question."""
    if "BANNER" not in guild.features:
        report.already("banner (needs boost level 2, artwork is ready)")
        return
    data = brand.image_bytes(brand.BANNER)
    if data is None:
        report.already("banner (artwork missing)")
        return
    try:
        await guild.edit(banner=data, reason="Grinder /setup - brand the server")
        report.ok("banner")
    except Exception as e:  # noqa: BLE001
        report.error("banner", e)


async def create_roles(guild: discord.Guild, report: Report) -> None:
    for name, colour, reason in ROLES:
        if _by_name(guild.roles, name) is not None:
            report.already(f"role @{name}")
            continue
        try:
            await guild.create_role(name=name, colour=discord.Colour(colour),
                                    mentionable=True, reason=f"Grinder /setup - {reason}")
            report.ok(f"role @{name}")
        except Exception as e:  # noqa: BLE001
            report.error(f"role @{name}", e)


async def create_channels(guild: discord.Guild, report: Report) -> None:
    """Build the categories and their channels, in order, skipping anything already present."""
    for cat_spec in STRUCTURE:
        category = _by_name(guild.categories, cat_spec.name)
        if category is None:
            try:
                category = await guild.create_category(cat_spec.name,
                                                       reason="Grinder /setup")
                report.ok(f"category {cat_spec.name}")
            except Exception as e:  # noqa: BLE001
                report.error(f"category {cat_spec.name}", e)
                continue  # without the category there is nowhere to put its channels
        else:
            report.already(f"category {cat_spec.name}")

        for ch in cat_spec.channels:
            # Look up by the SAME string we create with (see ChannelSpec.label), otherwise a second
            # run wouldn't recognise the channel and would duplicate it.
            # Search the TEXT or VOICE view specifically. `guild.channels` also contains categories,
            # so looking there made a channel named "welcome" match a leftover "WELCOME" category:
            # /setup reported "#welcome already there" and then failed with "#welcome doesn't exist".
            pool = guild.voice_channels if ch.voice else guild.text_channels
            existing = _by_name(pool, ch.label)
            if existing is not None:
                await _adopt_existing(guild, existing, category, ch, report)
                report.already(f"🔊 {ch.label}" if ch.voice else f"#{ch.label}")
                continue
            try:
                if ch.voice:
                    await guild.create_voice_channel(
                        ch.label, category=category, reason="Grinder /setup")
                    report.ok(f"🔊 {ch.label}")
                else:
                    await guild.create_text_channel(
                        ch.name, category=category, topic=ch.topic or None,
                        overwrites=_overwrites_for(guild, ch), reason="Grinder /setup")
                    report.ok(f"#{ch.name}")
            except Exception as e:  # noqa: BLE001
                report.error(f"#{ch.name}", e)


async def _adopt_existing(guild: discord.Guild, channel, category, ch: ChannelSpec,
                          report: Report) -> None:
    """Bring an EXISTING channel in line with the plan, rather than just stepping over it.

    Two repairs, both learned from real runs:

    1. Move it into the planned category. When the layout was cut from ten channels to four,
       #best-mixes and #feedback stayed under their old SHOWCASE and HANGOUT headers while the new
       GRINDER category sat empty - the server looked untouched even though /setup "succeeded".

    2. Re-allow the bot to post in a read-only channel. One created before the bot-allow fix denies
       `send_messages` to @everyone with no explicit allow for Grinder, so the welcome post fails
       with "Missing Permissions" in a channel the bot itself made."""
    current = getattr(channel, "category", None)
    if category is not None and current is not category:
        try:
            await channel.edit(category=category, reason="Grinder /setup - adopt into the plan")
        except Exception as e:  # noqa: BLE001
            report.error(f"#{ch.label} move into {category.name}", e)

    if ch.voice or not ch.read_only:
        return
    try:
        await channel.set_permissions(
            guild.me, send_messages=True, embed_links=True, attach_files=True,
            reason="Grinder /setup - let the bot post in its own read-only channel")
    except Exception as e:  # noqa: BLE001 — report it; the welcome step will fail loudly anyway
        report.error(f"#{ch.label} bot-post permission", e)


async def apply_renames(guild: discord.Guild, report: Report) -> None:
    """Rename the channels that changed name, keeping every message in them.

    Runs BEFORE create_channels, so the renamed channel is found by its new name and the plan does
    not create an empty duplicate beside it."""
    for old, new in RENAMES:
        if _by_name(guild.text_channels, new) is not None:
            continue                       # already renamed, or the new one exists already
        existing = _by_name(guild.text_channels, old)
        if existing is None:
            continue
        try:
            await existing.edit(name=new, reason="Grinder /setup - the new layout")
            report.ok(f"#{old} renamed to #{new}")
        except Exception as e:  # noqa: BLE001
            report.error(f"rename #{old}", e)


async def delete_retired(guild: discord.Guild, report: Report) -> None:
    """Remove the channels the new layout drops - but ONLY if they are empty.

    The emptiness check is not a formality. A channel can hold conversation, and losing that to a
    config change would be indefensible, so the destructive step refuses on anything with a human
    message in it and reports why. The founder can then delete it themselves having actually seen
    what is in there.
    """
    for name in RETIRED:
        ch = _by_name(guild.text_channels, name)
        if ch is None:
            continue
        try:
            human = [m async for m in ch.history(limit=50) if not m.author.bot]
            if human:
                report.already(f"#{name} kept - it has {len(human)} real messages in it")
                continue
            await ch.delete(reason="Grinder /setup - folded into #requests")
            report.ok(f"#{name} deleted (was empty)")
        except Exception as e:  # noqa: BLE001
            report.error(f"delete #{name}", e)

    for name in RETIRED_VOICE:
        ch = _by_name(guild.voice_channels, name)
        if ch is None:
            continue
        if ch.members:
            report.already(f"🔊 {name} kept - there are people in it")
            continue
        try:
            await ch.delete(reason="Grinder /setup - one voice room, not two")
            report.ok(f"🔊 {name} deleted")
        except Exception as e:  # noqa: BLE001
            report.error(f"delete 🔊 {name}", e)


async def delete_empty_categories(guild: discord.Guild, report: Report) -> None:
    """Remove old category headers that no longer hold anything.

    Moving every channel into the new headers leaves the old ones behind as empty labels. Nothing
    is lost by deleting a category with no channels in it, and three dead headers at the top of the
    sidebar is exactly the "half-finished" look this restructure exists to fix. A category that
    still holds ANY channel is left completely alone."""
    planned = {cat.name.lower() for cat in STRUCTURE}
    for cat in list(guild.categories):
        if cat.name.lower() in planned:
            continue
        if getattr(cat, "channels", None):
            report.already(f"category {cat.name} kept - it still has channels in it")
            continue
        try:
            await cat.delete(reason="Grinder /setup - empty leftover header")
            report.ok(f"empty category {cat.name} deleted")
        except Exception as e:  # noqa: BLE001
            report.error(f"delete category {cat.name}", e)


async def delete_retired_roles(guild: discord.Guild, report: Report) -> None:
    for name in RETIRED_ROLES:
        role = _by_name(guild.roles, name)
        if role is None:
            continue
        try:
            await role.delete(reason="Grinder /setup - opt-in role with no way to opt in")
            report.ok(f"@{name} removed")
        except Exception as e:  # noqa: BLE001
            report.error(f"remove @{name}", e)


def extra_channels(guild: discord.Guild) -> list[str]:
    """Channels on the server that AREN'T in the plan.

    `/setup` only ever creates, never deletes, so shrinking STRUCTURE leaves the old channels
    behind. Deleting them automatically is not on: a channel can hold conversation, and losing that
    to a config change would be indefensible. So they get REPORTED, and the founder deletes the ones
    they actually want gone - two clicks each, and no chance of losing something that mattered."""
    planned = {ch.label.lower() for cat in STRUCTURE for ch in cat.channels}
    planned |= {ch.name.lower() for cat in STRUCTURE for ch in cat.channels}
    out = []
    # Ask for text and voice explicitly rather than filtering categories out of guild.channels:
    # that view includes categories, and relying on an isinstance check to exclude them is how the
    # "welcome" channel ended up matching the "WELCOME" category.
    for c in guild.text_channels:
        if c.name.lower() not in planned:
            out.append(f"#{c.name}")
    for c in guild.voice_channels:
        if c.name.lower() not in planned:
            out.append(f"🔊 {c.name}")
    return sorted(out)


async def upload_emojis(guild: discord.Guild, report: Report) -> None:
    """Upload the six brand emojis. Skips any the server already has by that name."""
    have = {e.name.lower() for e in guild.emojis}
    for name, path in brand.emoji_files():
        if name.lower() in have:
            report.already(f":{name}:")
            continue
        data = brand.image_bytes(path)
        if data is None:
            report.error(f":{name}:", FileNotFoundError(path.name))
            continue
        try:
            await guild.create_custom_emoji(name=name, image=data, reason="Grinder /setup")
            report.ok(f":{name}:")
        except Exception as e:  # noqa: BLE001 — a full emoji slot list is a normal, reportable outcome
            report.error(f":{name}:", e)


def welcome_embeds(guild: discord.Guild) -> list[discord.Embed]:
    """The #read-this-first post. Should take 30 seconds to read, and no longer."""
    intro = discord.Embed(
        title="you're in. here's the whole thing.",
        description=(
            "Grinder mashes two songs together.\n"
            "You pick a beat. You pick a vocal. It figures out how to make them one track.\n\n"
            "Sometimes it's incredible. Sometimes it's a war crime.\n"
            "That's the fun part."),
        color=brand.PRIMARY)
    intro.set_image(url="attachment://logo.png")

    how = discord.Embed(title="how to do it", color=brand.PRIMARY)
    how.add_field(
        name="the four steps",
        value=("1. Go to #the-grinder\n"
               "2. Type `/grind`\n"
               "3. Pick a beat and a vocal. Want something longer? Hit **➕ Add another** and "
               "stack up to 5 pairs before you build anything.\n"
               "4. Hit **Grind it** and find out what you've done"),
        inline=False)
    how.add_field(
        name="then what",
        value=("React to it. 🔥 if it goes hard, 💀 if it's a disaster, 😐 if it's mid.\n"
               "🔁 **Again** gives you the same songs mixed a different way.\n"
               "📌 sends it to #fresh-grinds if it deserves to live."),
        inline=False)
    how.add_field(
        name="the good part",
        value=("Jump into 🔊 The Booth and grind while people are in there. Everyone hears it at "
               "the same second. Ten people finding out together whether a Bollywood vocal "
               "survives a techno beat is a better time than doing it alone."),
        inline=False)
    how.set_footer(text=f"{guild.name} · that's it. go break something.")
    return [intro, how]


# The pinned message for each channel, so a newcomer landing anywhere knows what the room is for.
# Plain ASCII punctuation throughout: no em dashes, no en dashes (founder rule).
CHANNEL_COPY: dict[str, tuple[str, str]] = {
    "rules": ("the rules", (
        "there aren't many.\n\n"
        "**1.** Grind whatever you want. There are no bad ideas here, only bad grinds, and those "
        "are funny too.\n"
        "**2.** Don't be a dick. That's the actual rule.\n"
        "**3.** No slurs, no harassment, no weird stuff about minors. Instant ban, no "
        "conversation.\n"
        "**4.** Don't spam the grinder. Let other people have a turn.\n"
        "**5.** If something's broken, say so in #requests. If it's brilliant, say so louder.\n\n"
        "that's it. go make something cursed.")),
    "announcements": ("this is where we post what's new.", (
        "New features, Booth sessions, things we fixed, things we broke.\n\n"
        "Turn on notifications for this one if you want to know when we're running a live "
        "session.")),
    "the-grinder": ("this is where it happens.", (
        "Type `/grind` right here.\n\n"
        "Everyone grinds in this channel, on purpose. You'll see what other people are throwing "
        "together, which is the fastest way to learn what works, and the fastest way to find out "
        "that the thing you thought would never work absolutely works.\n\n"
        "React to other people's grinds. 🔥 💀 😐\n"
        "Steal their ideas. That's allowed. Encouraged, actually.\n\n"
        "**🔊 The Booth is right there.** Grind while you're in it and everyone in the room hears "
        "it live.")),
    "fresh-grinds": ("the hall of fame.", (
        "Hit 📌 on any grind in #the-grinder and it lands here.\n\n"
        "This is the good stuff. And the legendary disasters, those count too.\n\n"
        "Scroll it when you need ideas.")),
    "general": ("no agenda here.", (
        "Talk about music, talk about nothing, drop a track you're obsessed with, argue about "
        "whether the last grind was genius or a hate crime.\n\n"
        "If you're new, say hi. Someone will say it back.")),
    "requests": ("tell us what you want.", (
        "Three kinds of post:\n\n"
        "🐛  **broken** - something didn't work. Tell us what you did.\n"
        "🎵  **missing** - a song, artist, or genre you want in the hopper.\n"
        "💡  **wild** - a feature you want. Ask for anything. Seriously.\n\n"
        "We read all of it. We build a lot of it.\n"
        "The stuff in here is where most of the good ideas come from.")),
}


async def _post_once(channel, report: Report, label: str, embed: discord.Embed,
                     files=None, pin: bool = False) -> None:
    """Post into a channel only if nothing is there yet, so re-running /setup never spams it."""
    try:
        async for _ in channel.history(limit=1):
            report.already(f"{label} (#{channel.name} isn't empty)")
            return
    except Exception as e:  # noqa: BLE001 - can't read history => don't risk double-posting
        report.error(label, e)
        return
    try:
        msg = await channel.send(embed=embed, files=files or [])
        if pin:
            try:
                await msg.pin()
            except discord.HTTPException:
                pass          # pinning is a nicety; the post is useful either way
        report.ok(label)
    except Exception as e:  # noqa: BLE001
        report.error(label, e)


async def post_welcome(guild: discord.Guild, report: Report) -> None:
    """Post (once) into the welcome channel. Skipped if it already has messages, so re-running
    /setup never spams it."""
    channel = _by_name(guild.text_channels, WELCOME_CHANNEL)
    if channel is None:
        report.error("welcome post", RuntimeError(f"#{WELCOME_CHANNEL} doesn't exist"))
        return
    try:
        async for _ in channel.history(limit=1):
            report.already(f"welcome post (#{WELCOME_CHANNEL} isn't empty)")
            return
    except Exception as e:  # noqa: BLE001
        report.error("welcome post", e)
        return
    logo = brand.image_bytes(brand.LOGO)
    files = [discord.File(brand.LOGO, filename="logo.png")] if logo else []
    try:
        msg = await channel.send(embeds=welcome_embeds(guild), files=files)
        try:
            await msg.pin()
        except discord.HTTPException:
            pass
        report.ok(f"welcome post in #{WELCOME_CHANNEL}")
    except Exception as e:  # noqa: BLE001
        report.error("welcome post", e)


async def post_channel_copy(guild: discord.Guild, report: Report) -> None:
    """Pin the "what is this room for" message in each channel that has one."""
    for name, (title, body) in CHANNEL_COPY.items():
        channel = _by_name(guild.text_channels, name)
        if channel is None:
            continue
        embed = discord.Embed(title=title, description=body, color=brand.PRIMARY)
        await _post_once(channel, report, f"pinned post in #{name}", embed, pin=True)


async def run(guild: discord.Guild, *, refresh_branding: bool = False) -> Report:
    """Build the whole community. Order matters: channels before the welcome post (it needs
    #welcome), and the icon first so the founder sees something change immediately.

    `refresh_branding` re-applies the icon (and banner) over existing art — the way to push updated
    artwork onto a server that is already branded."""
    report = Report()
    await apply_icon(guild, report, force=refresh_branding)
    await apply_banner(guild, report)
    await create_roles(guild, report)
    await delete_retired_roles(guild, report)
    # Renames run BEFORE creates so a renamed channel is found by its new name; deletes run AFTER,
    # so a channel is only ever removed once its replacement definitely exists.
    await apply_renames(guild, report)
    await create_channels(guild, report)
    await delete_retired(guild, report)
    await delete_empty_categories(guild, report)
    await upload_emojis(guild, report)
    await post_welcome(guild, report)
    await post_channel_copy(guild, report)
    report.extra = extra_channels(guild)
    report.channel_ids = channel_ids(guild)
    return report


def channel_ids(guild: discord.Guild) -> dict[str, int]:
    """The ids the bot needs in its config: the booth, the grind channel, the showcase.

    Reported rather than written to `.env` by the bot: the env file holds the token, and a program
    that rewrites its own secrets file is a bad idea however careful it is."""
    out: dict[str, int] = {}
    # Look up by ChannelSpec.label, the SAME string the channel was created with. Using the slug
    # here found nothing for the voice channel: it is created as "The Booth", whose lowercase form
    # is "the booth" with a space, not "the-booth". That is the create/lookup mismatch that
    # previously made every /setup run add another voice channel.
    specs = {ch.name: ch for cat in STRUCTURE for ch in cat.channels}
    for key, name in (("GRINDER_BOOTH_CHANNEL_ID", VOICE_CHANNEL),
                      ("GRINDER_MAIN_CHANNEL_ID", GRIND_CHANNEL),
                      ("GRINDER_SHOWCASE_CHANNEL_ID", SHOWCASE_CHANNEL)):
        spec = specs.get(name)
        if spec is None:
            continue
        pool = guild.voice_channels if spec.voice else guild.text_channels
        ch = _by_name(pool, spec.label)
        if ch is not None:
            out[key] = ch.id
    return out


def report_embed(report: Report, guild_name: str) -> discord.Embed:
    """Turn the report into something readable, and honest about what didn't work."""
    colour = brand.FAIL if report.failed else brand.PRIMARY
    e = discord.Embed(
        title="Server setup" + (" with problems" if report.failed else " complete"),
        description=f"**{guild_name}** is ready." if not report.failed else
                    f"Built most of **{guild_name}**, but some steps failed. See below.",
        color=colour)

    def block(items: list[str], limit: int = 18) -> str:
        if not items:
            return "-"
        shown = items[:limit]
        # never silently truncate — say how many were left out
        extra = len(items) - len(shown)
        text = "\n".join(f"• {i}" for i in shown)
        return text + (f"\n• …and {extra} more" if extra else "")

    if report.created:
        e.add_field(name=f"Created ({len(report.created)})", value=block(report.created), inline=False)
    if report.skipped:
        e.add_field(name=f"Already there ({len(report.skipped)})", value=block(report.skipped), inline=False)
    if report.extra:
        e.add_field(
            name=f"Not in the plan ({len(report.extra)})",
            value=block(report.extra) + "\n\nDelete any you don't want: right-click the channel, "
                                        "Delete Channel. Grinder won't delete them for you, in case "
                                        "there's conversation in one.",
            inline=False)
    if report.failed:
        e.add_field(name=f"Failed ({len(report.failed)})", value=block(report.failed), inline=False)
        e.set_footer(text="Most failures are a missing permission. Re-running /setup is safe: "
                          "it skips whatever already exists.")
    else:
        e.set_footer(text="Re-running /setup is safe: it skips whatever already exists.")
    return e
