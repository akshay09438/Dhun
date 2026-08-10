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
    # FOUR channels, one category, on purpose (founder call 2026-08-11, cut down from ten).
    # A near-empty server with ten channels reads as abandoned, not organised - every room looks
    # dead because the few people there are spread across all of them. Start narrow; split a
    # channel only once conversation is genuinely spilling out of it.
    CategorySpec("GRINDER", (
        ChannelSpec("welcome", "What Grinder is and how to make your first mix.", read_only=True),
        # Deliberately NOT read-only. This is the one music room: you run /mix here AND the good
        # ones live here. Splitting "where you make them" from "where the best ones go" needs more
        # people than this server has - until then it would just be two quiet channels.
        ChannelSpec("best-mixes", "Use /mix here, and post the ones worth keeping."),
        ChannelSpec("feedback", "Bugs, song requests, anything at all."),
        ChannelSpec("the-booth", voice=True, display="The Booth"),
    )),
)

# Roles worth having on day one. Deliberately only two — an empty server with fifteen roles looks
# abandoned, not organised.
ROLES: tuple[tuple[str, int, str], ...] = (
    ("Resident DJ", brand.PRIMARY, "Shared a mix people liked."),
    ("Session Crew", brand.PINK, "Pinged when a listening session starts in The Booth."),
)

VOICE_CHANNEL = "the-booth"
WELCOME_CHANNEL = "welcome"


@dataclasses.dataclass
class Report:
    """What actually happened, so the command can tell the founder rather than claim success."""
    created: list[str] = dataclasses.field(default_factory=list)
    skipped: list[str] = dataclasses.field(default_factory=list)
    failed: list[str] = dataclasses.field(default_factory=list)
    # Channels on the server that aren't in the plan. Reported, never deleted - see extra_channels.
    extra: list[str] = dataclasses.field(default_factory=list)

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
            existing = _by_name(guild.channels, ch.label)
            if existing is not None:
                await _repair_read_only(guild, existing, ch, report)
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


async def _repair_read_only(guild: discord.Guild, channel, ch: ChannelSpec,
                            report: Report) -> None:
    """Make sure the bot can post in an EXISTING read-only channel.

    A channel created before the bot-allow fix denies `send_messages` to @everyone with no explicit
    allow for Grinder, so the welcome post fails with "Missing Permissions" in a channel the bot
    itself made. Skipping it on a re-run would leave that broken forever, so the idempotent path
    repairs it rather than just stepping over it."""
    if ch.voice or not ch.read_only:
        return
    try:
        await channel.set_permissions(
            guild.me, send_messages=True, embed_links=True, attach_files=True,
            reason="Grinder /setup - let the bot post in its own read-only channel")
    except Exception as e:  # noqa: BLE001 — report it; the welcome step will fail loudly anyway
        report.error(f"#{ch.label} bot-post permission", e)


def extra_channels(guild: discord.Guild) -> list[str]:
    """Channels on the server that AREN'T in the plan.

    `/setup` only ever creates, never deletes, so shrinking STRUCTURE leaves the old channels
    behind. Deleting them automatically is not on: a channel can hold conversation, and losing that
    to a config change would be indefensible. So they get REPORTED, and the founder deletes the ones
    they actually want gone - two clicks each, and no chance of losing something that mattered."""
    planned = {ch.label.lower() for cat in STRUCTURE for ch in cat.channels}
    planned |= {ch.name.lower() for cat in STRUCTURE for ch in cat.channels}
    out = []
    for c in guild.channels:
        if isinstance(c, discord.CategoryChannel):
            continue
        if c.name.lower() not in planned:
            out.append(("🔊 " if getattr(c, "type", None) == discord.ChannelType.voice else "#")
                       + c.name)
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
    """The #welcome post: what this is, how to start, and what each channel is for.

    Two cards, not three. With four channels there isn't enough to say to justify a third, and a
    long welcome is the fastest way to make a small server feel like homework."""
    intro = discord.Embed(
        title="Welcome to Grinder",
        description=(
            "Grinder makes a **DJ mashup** out of two songs: one song's **beat**, another song's "
            "**vocals**. You don't need to know how to DJ. You just pick two songs."),
        color=brand.PRIMARY)
    intro.set_image(url="attachment://logo.png")

    how = discord.Embed(title="Make your first mix", color=brand.PRIMARY)
    how.add_field(
        name="1. Go to #best-mixes and type /mix",
        value="Start typing a song name and it fills itself in.",
        inline=False)
    how.add_field(
        name="2. Pick a beat, then a vocal",
        value="The first song gives the rhythm. The second gives the singing.",
        inline=False)
    how.add_field(
        name="3. Listen, then push it further",
        value=("**Another take** gives you a different version of the same two songs. "
               "**Play in voice** makes Grinder join 🔊 The Booth and play it out loud."),
        inline=False)
    how.add_field(
        name="The rest of the commands",
        value="**`/set`** joins up to 5 mixes into one continuous set · "
              "**`/songs`** lists everything you can pick · **`/help`** explains it all",
        inline=False)
    how.add_field(
        name="Where things go",
        value=("**#best-mixes** make them here, and post the ones worth keeping. React 🔥 to the "
               "good ones.\n"
               "**#feedback** anything broken, confusing, or a song you wish was in the library.\n"
               "**🔊 The Booth** where mixes get played out loud. Grab **@Session Crew** to be "
               "pinged when a session starts."),
        inline=False)
    how.set_footer(text=f"{guild.name} · powered by Prompt-DJ")
    return [intro, how]


async def post_welcome(guild: discord.Guild, report: Report) -> None:
    """Post (once) into #welcome. Skipped if the channel already has messages, so re-running
    /setup never spams the channel."""
    channel = _by_name(guild.text_channels, WELCOME_CHANNEL)
    if channel is None:
        report.error("welcome post", RuntimeError(f"#{WELCOME_CHANNEL} doesn't exist"))
        return
    try:
        async for _ in channel.history(limit=1):
            report.already(f"welcome post (#{WELCOME_CHANNEL} isn't empty)")
            return
    except Exception as e:  # noqa: BLE001 — can't read history => don't risk double-posting
        report.error("welcome post", e)
        return

    logo = brand.image_bytes(brand.LOGO)
    files = [discord.File(brand.LOGO, filename="logo.png")] if logo else []
    try:
        await channel.send(embeds=welcome_embeds(guild), files=files)
        report.ok(f"welcome post in #{WELCOME_CHANNEL}")
    except Exception as e:  # noqa: BLE001
        report.error("welcome post", e)


async def run(guild: discord.Guild, *, refresh_branding: bool = False) -> Report:
    """Build the whole community. Order matters: channels before the welcome post (it needs
    #welcome), and the icon first so the founder sees something change immediately.

    `refresh_branding` re-applies the icon (and banner) over existing art — the way to push updated
    artwork onto a server that is already branded."""
    report = Report()
    await apply_icon(guild, report, force=refresh_branding)
    await apply_banner(guild, report)
    await create_roles(guild, report)
    await create_channels(guild, report)
    await upload_emojis(guild, report)
    await post_welcome(guild, report)
    report.extra = extra_channels(guild)
    return report


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
