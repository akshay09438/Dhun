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
    # True for channels only the bot and staff should post in (#read-me, #announcements). Everyone
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
    CategorySpec("WELCOME", (
        ChannelSpec("read-me", "What Grinder is and how to make your first mix.", read_only=True),
        ChannelSpec("announcements", "New songs, new features, session times.", read_only=True),
    )),
    CategorySpec("GRINDER", (
        ChannelSpec("make-a-mix", "Use /mix here. Pick a beat, pick a vocal, get a mashup."),
        ChannelSpec("the-booth", voice=True, display="The Booth"),
        ChannelSpec("now-playing", "What's playing in The Booth right now."),
    )),
    CategorySpec("SHOWCASE", (
        ChannelSpec("i-made-this", "Post a mix you're proud of. React 🔥 to the ones you'd play."),
        ChannelSpec("requests", "A song you wish was in the library? Name it here."),
    )),
    CategorySpec("HANGOUT", (
        ChannelSpec("general", "Anything goes."),
        ChannelSpec("feedback", "Something broken, confusing, or missing? Tell us here."),
    )),
)

# Roles worth having on day one. Deliberately only two — an empty server with fifteen roles looks
# abandoned, not organised.
ROLES: tuple[tuple[str, int, str], ...] = (
    ("Resident DJ", brand.PRIMARY, "Shared a mix people liked."),
    ("Session Crew", brand.PINK, "Pinged when a listening session starts in The Booth."),
)

VOICE_CHANNEL = "the-booth"


@dataclasses.dataclass
class Report:
    """What actually happened, so the command can tell the founder rather than claim success."""
    created: list[str] = dataclasses.field(default_factory=list)
    skipped: list[str] = dataclasses.field(default_factory=list)
    failed: list[str] = dataclasses.field(default_factory=list)

    def ok(self, label: str) -> None:
        self.created.append(label)

    def already(self, label: str) -> None:
        self.skipped.append(label)

    def error(self, label: str, exc: Exception) -> None:
        # The reason matters more than the exception type — "Missing Permissions" is the answer to
        # 90% of setup failures, and the founder can act on it.
        reason = getattr(exc, "text", None) or str(exc) or exc.__class__.__name__
        self.failed.append(f"{label} — {reason}")
        log.warning("setup step failed: %s", label, exc_info=exc)


def _by_name(items, name: str):
    lowered = name.lower()
    return discord.utils.find(lambda c: c.name.lower() == lowered, items)


async def apply_icon(guild: discord.Guild, report: Report) -> None:
    """Set the server icon to the G mark. Skipped if the server already has any icon — replacing
    art the founder chose themselves would be presumptuous."""
    if guild.icon is not None:
        report.already("server icon (one is already set)")
        return
    data = brand.image_bytes(brand.ICON)
    if data is None:
        report.already("server icon (artwork missing)")
        return
    try:
        await guild.edit(icon=data, reason="Grinder /setup — brand the server")
        report.ok("server icon")
    except Exception as e:  # noqa: BLE001 — one failed step must not abort the rest of setup
        report.error("server icon", e)


async def apply_banner(guild: discord.Guild, report: Report) -> None:
    """Set the banner — only possible once the server has boost level 2. Reports the reason
    plainly rather than failing silently, because "why is there no banner" is an obvious question."""
    if "BANNER" not in guild.features:
        report.already("banner (needs boost level 2 — artwork is ready)")
        return
    data = brand.image_bytes(brand.BANNER)
    if data is None:
        report.already("banner (artwork missing)")
        return
    try:
        await guild.edit(banner=data, reason="Grinder /setup — brand the server")
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
                                    mentionable=True, reason=f"Grinder /setup — {reason}")
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
                report.already(f"🔊 {ch.label}" if ch.voice else f"#{ch.label}")
                continue
            try:
                if ch.voice:
                    await guild.create_voice_channel(
                        ch.label, category=category, reason="Grinder /setup")
                    report.ok(f"🔊 {ch.label}")
                else:
                    overwrites = None
                    if ch.read_only:
                        # Everyone can read, only staff/bot can post.
                        overwrites = {
                            guild.default_role: discord.PermissionOverwrite(
                                send_messages=False, add_reactions=True),
                        }
                    await guild.create_text_channel(
                        ch.name, category=category, topic=ch.topic or None,
                        overwrites=overwrites, reason="Grinder /setup")
                    report.ok(f"#{ch.name}")
            except Exception as e:  # noqa: BLE001
                report.error(f"#{ch.name}", e)


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
    """The #read-me post: what this is, how to start, and what the reactions mean."""
    intro = discord.Embed(
        title="Welcome to Grinder",
        description=(
            "Grinder makes a **DJ mashup** out of two songs: one song's **beat**, another song's "
            "**vocals**. You don't need to know how to DJ — you just pick two songs."),
        color=brand.PRIMARY)
    intro.set_image(url="attachment://logo.png")

    how = discord.Embed(title="Making your first mix", color=brand.PRIMARY)
    how.add_field(
        name="1 · Go to #make-a-mix",
        value="Type **`/mix`**. Start typing a song name and it'll autocomplete.",
        inline=False)
    how.add_field(
        name="2 · Pick a beat, then a vocal",
        value="The first song gives the rhythm. The second gives the singing.",
        inline=False)
    how.add_field(
        name="3 · Listen, then push it further",
        value=("**Another take** gives you a different version of the same pair. "
               "**Play in voice** makes Grinder join your voice channel and play it out loud."),
        inline=False)
    how.add_field(
        name="Other commands",
        value="**`/set`** builds a continuous set of up to 5 mixes · "
              "**`/songs`** lists the library · **`/help`** explains everything",
        inline=False)

    house = discord.Embed(title="How we use this place", color=brand.PINK)
    house.add_field(
        name="#i-made-this",
        value="Post mixes you'd actually play. React 🔥 to the good ones — that's how we find out "
              "what's working.",
        inline=False)
    house.add_field(
        name="#requests",
        value="Want a song that isn't in the library? Say so here.",
        inline=False)
    house.add_field(
        name="🔊 The Booth",
        value="Where mixes get played out loud. Grab **@Session Crew** to be pinged when one starts.",
        inline=False)
    house.set_footer(text=f"{guild.name} · powered by Prompt-DJ")
    return [intro, how, house]


async def post_welcome(guild: discord.Guild, report: Report) -> None:
    """Post (once) into #read-me. Skipped if the channel already has messages, so re-running
    /setup never spams the channel."""
    channel = _by_name(guild.text_channels, "read-me")
    if channel is None:
        report.error("welcome post", RuntimeError("#read-me doesn't exist"))
        return
    try:
        async for _ in channel.history(limit=1):
            report.already("welcome post (#read-me isn't empty)")
            return
    except Exception as e:  # noqa: BLE001 — can't read history => don't risk double-posting
        report.error("welcome post", e)
        return

    logo = brand.image_bytes(brand.LOGO)
    files = [discord.File(brand.LOGO, filename="logo.png")] if logo else []
    try:
        await channel.send(embeds=welcome_embeds(guild), files=files)
        report.ok("welcome post in #read-me")
    except Exception as e:  # noqa: BLE001
        report.error("welcome post", e)


async def run(guild: discord.Guild) -> Report:
    """Build the whole community. Order matters: channels before the welcome post (it needs
    #read-me), and the icon first so the founder sees something change immediately."""
    report = Report()
    await apply_icon(guild, report)
    await apply_banner(guild, report)
    await create_roles(guild, report)
    await create_channels(guild, report)
    await upload_emojis(guild, report)
    await post_welcome(guild, report)
    return report


def report_embed(report: Report, guild_name: str) -> discord.Embed:
    """Turn the report into something readable — and honest about what didn't work."""
    colour = brand.FAIL if report.failed else brand.PRIMARY
    e = discord.Embed(
        title="Server setup" + (" — with problems" if report.failed else " complete"),
        description=f"**{guild_name}** is ready." if not report.failed else
                    f"Built most of **{guild_name}**, but some steps failed — see below.",
        color=colour)

    def block(items: list[str], limit: int = 18) -> str:
        if not items:
            return "—"
        shown = items[:limit]
        # never silently truncate — say how many were left out
        extra = len(items) - len(shown)
        text = "\n".join(f"• {i}" for i in shown)
        return text + (f"\n• …and {extra} more" if extra else "")

    if report.created:
        e.add_field(name=f"Created ({len(report.created)})", value=block(report.created), inline=False)
    if report.skipped:
        e.add_field(name=f"Already there ({len(report.skipped)})", value=block(report.skipped), inline=False)
    if report.failed:
        e.add_field(name=f"Failed ({len(report.failed)})", value=block(report.failed), inline=False)
        e.set_footer(text="Most failures are a missing permission. Re-running /setup is safe — "
                          "it skips whatever already exists.")
    else:
        e.set_footer(text="Re-running /setup is safe — it skips whatever already exists.")
    return e
