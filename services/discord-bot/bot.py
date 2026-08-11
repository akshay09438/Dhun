"""Prompt-DJ Discord bot (demo).

A convenience-first front-end to the Prompt-DJ mix engine, modelled on how people already
"get" Midjourney: type one slash command, pick your two songs from an autocomplete list, and
the finished mix comes back in the channel as a playable clip with buttons (Another take /
Play in voice). No web screen, no manual steps.

It talks to the local engine over HTTP (see api_client). It never touches audio or the mixing
logic itself, so every bit of mix quality lives in one place (the engine).

Setup + run: services/discord-bot/README.md.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
import tempfile
import uuid
from pathlib import Path

import discord
from discord import app_commands

import brand
import media
import server_setup
import showcase
import store
import voice_player
from booth import booth
from api_client import EngineError, PromptDJClient, Song
from botconfig import load_config
import ui
from helpers import match_songs, safe_filename, select_option_specs

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("promptdj.discord")

CFG = load_config()
BOT_NAME = "Grinder"       # the beta Discord bot's name (Prompt-DJ is the product)
VIOLET = ui.ACCENT         # the Grinder purple, sampled from the artwork — defined in brand.py
MAX_TAKES = 5              # matches the web app's MAX_GENERATIONS_PER_SESSION


# --------------------------------------------------------------------------------------
# The client — loads the catalog once for autocomplete, syncs the /mix command.
# --------------------------------------------------------------------------------------
class PromptDJBot(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.default())  # slash cmds need no privileged intents
        self.tree = app_commands.CommandTree(self)
        self.api = PromptDJClient(CFG.api_base)
        self.songs: list[Song] = []
        self.beats: list[Song] = []
        self.vocals: list[Song] = []
        # Guilds whose slash commands are already registered, so a reconnect doesn't re-sync them.
        self._synced_guilds: set[int] = set()

    async def setup_hook(self) -> None:
        await self.refresh_catalog()
        try:
            if CFG.guild_id:
                guild = discord.Object(id=CFG.guild_id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)   # appears INSTANTLY in that server
                # Remember it, so on_ready doesn't immediately sync the same guild a second time.
                self._synced_guilds.add(CFG.guild_id)
                log.info("commands synced to configured guild %s", CFG.guild_id)
            else:
                await self.tree.sync()              # global — can take up to ~1h to appear
                log.info("commands synced globally (may take up to 1h to appear)")
        except discord.Forbidden:
            # 50001 Missing Access: the bot lacks the applications.commands scope in that
            # guild (added without the "slash commands" permission), or DISCORD_GUILD_ID points
            # at a server it isn't in. Don't crash — fall back to a global sync so the bot still
            # comes online, and log what to fix.
            log.warning("Guild command sync was REFUSED (Missing Access, 50001). Re-invite the "
                        "bot with the applications.commands scope, or fix DISCORD_GUILD_ID. "
                        "Falling back to a GLOBAL sync for now (can take up to ~1h to appear).")
            try:
                await self.tree.sync()
            except Exception as e:  # noqa: BLE001
                log.warning("Global command sync also failed: %s", e)
        except Exception as e:  # noqa: BLE001
            log.warning("Command sync failed (%s); the bot will still run.", e)

    async def refresh_catalog(self) -> None:
        try:
            self.songs = await self.api.library()
        except Exception as e:  # noqa: BLE001 — a catalog failure shouldn't stop the bot from starting
            log.warning("could not load catalog from %s: %s", CFG.api_base, e)
            self.songs = []
        self.beats = [s for s in self.songs if s.role_hint == "beat"] or self.songs
        self.vocals = [s for s in self.songs if s.role_hint == "vocals"] or self.songs
        log.info("catalog: %d songs (%d beats, %d vocals)",
                 len(self.songs), len(self.beats), len(self.vocals))

    async def on_ready(self) -> None:
        log.info("logged in as %s (id %s)", self.user, getattr(self.user, "id", "?"))
        await self._apply_brand()
        guilds = list(self.guilds)
        # Say which servers Grinder is in. Silence here used to be ambiguous — "no guilds" and
        # "already synced" looked identical in the log, which hid whether /setup would appear.
        log.info("in %d server(s): %s", len(guilds),
                 ", ".join(f"{g.name} ({g.id})" for g in guilds) or "none")
        await self.sync_to_guilds(guilds)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Sync commands the moment Grinder is invited somewhere new.

        Without this, a brand-new server shows NO slash commands: `setup_hook` can only sync to the
        one guild in DISCORD_GUILD_ID, and a global sync can take up to an hour to propagate. Since
        the whole point of `/setup` is to run it in a server you just created, "wait an hour" would
        make the command useless exactly when it's needed."""
        log.info("joined guild %s (%s)", guild.name, guild.id)
        await self.sync_to_guilds([guild])

    async def sync_to_guilds(self, guilds) -> None:
        """Copy the global commands into each guild so they appear instantly. `on_ready` fires again
        on every reconnect, so already-synced guilds are remembered and skipped — re-syncing on each
        reconnect would burn through Discord's command-update rate limit for no gain."""
        for guild in guilds:
            if guild.id in self._synced_guilds:
                continue
            try:
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                self._synced_guilds.add(guild.id)
                log.info("commands synced to guild %s", guild.id)
            except Exception as e:  # noqa: BLE001 — one guild refusing must not affect the others
                log.warning("couldn't sync commands to guild %s: %s", guild.id, e)

    async def _apply_brand(self) -> None:
        """Put the Grinder mark on the bot itself, and remember its URL for the cards.

        Uploads when the bot has no avatar OR when the shipped artwork has CHANGED since the last
        upload (tracked by a local fingerprint — Discord re-encodes uploads, so comparing bytes
        against its copy never works). That way new art applies itself on the next start, while an
        unchanged one doesn't burn Discord's avatar rate limit, which is strict. Never fatal — a bot
        that can't set its picture must still make mixes."""
        user = self.user
        if user is None:
            return
        try:
            if user.avatar is None or brand.avatar_needs_upload():
                data = brand.image_bytes(brand.ICON)
                if data is not None:
                    await user.edit(avatar=data)
                    brand.mark_avatar_applied()
                    log.info("brand: avatar uploaded from %s (%s)",
                             brand.ICON.name, brand.icon_fingerprint())
            else:
                log.info("brand: avatar already up to date")
            url = str(user.display_avatar.url) if user.display_avatar else None
            # Log it: this is the ONLY way to check from outside what picture Discord actually holds
            # for the bot, and it distinguishes the bot's avatar from the separate Application icon
            # shown in the slash-command picker (which the API cannot change).
            log.info("brand: bot avatar url = %s", url)
            ui.set_avatar_url(url)
        except Exception:  # noqa: BLE001 — branding is cosmetic; never let it stop the bot
            log.warning("brand: couldn't set the avatar (continuing)", exc_info=True)


bot = PromptDJBot()


def _now() -> str:
    """UTC, timezone-aware. The engine learned this lesson the hard way: a naive stamp
    means a different instant on a cloud box than on this machine, with nothing in the row
    to tell them apart."""
    return datetime.now(timezone.utc).isoformat()


def _name_of(song_id: str) -> str:
    for s in bot.songs:
        if s.id == song_id:
            return s.name
    return "song"


def _error_embed(msg: str) -> discord.Embed:
    return ui.error_embed(msg)


# --------------------------------------------------------------------------------------
# A grind's lifecycle: a "grinding..." card that becomes the finished audio + buttons.
#
# ONE class covers both shapes. A grind starts as a single pair and GROWS through the ➕ button
# into a "long grind" of up to five. That is deliberate: nobody opens Discord meaning to build a
# five-track set - they make one, it goes hard, and THEN they want more. There is no /set command
# any more, because the button catches that impulse at the moment it appears.
#
# NOTHING on a card evaluates the grind. See the rule at the top of ui.py.
# --------------------------------------------------------------------------------------
MAX_PAIRS_PER_GRIND = 5            # the core rule, one constant, matches the engine's set cap
CLIP_SIZE_LIMIT_BYTES = 9_000_000  # Discord's non-Nitro upload limit, with headroom


class GrindContext:
    """Owns one grind card from submit to finished, through however many pairs it grows to."""

    def __init__(self, interaction: discord.Interaction, pairs: list[tuple[str, str]],
                 *, generation: int = 0) -> None:
        self.interaction = interaction
        self.pairs = pairs                       # [(beat_id, vocal_id), ...]
        self.generation = generation
        self.owner_id = interaction.user.id      # only the owner may append or re-roll
        self.user_id = str(interaction.user.id)
        self.user_name = getattr(interaction.user, "display_name", None) or interaction.user.name
        self.message: discord.Message | None = None
        self.audio_path: Path | None = None      # the WAV, kept for The Booth
        self.done = False                        # ✅ Done pressed, or the cap reached
        self.number: int | None = None
        self.duration: float = 0.0

    # -- naming -------------------------------------------------------------------------
    def named_pairs(self) -> list[tuple[str, str]]:
        return [(_name_of(a), _name_of(b)) for a, b in self.pairs]

    def _store_pairs(self) -> list:
        return [[a, b, _name_of(a), _name_of(b)] for a, b in self.pairs]

    def label(self) -> str:
        named = self.named_pairs()
        if len(named) == 1:
            return f"{named[0][0]} x {named[0][1]}"
        return f"long grind, {len(named)} tracks"

    # -- the card -----------------------------------------------------------------------
    def _submit_embed(self) -> discord.Embed:
        beat, vocals = self.named_pairs()[-1]
        return ui.submit_embed(user=self.interaction.user, beat=beat, vocals=vocals)

    async def _post_submit_card(self, *, first: bool) -> None:
        """State 1, posted BEFORE any rendering starts. The grind number is claimed here so the
        number on the 'grinding...' card is the number the finished grind keeps."""
        e = self._submit_embed()
        if first:
            self.number = store.new_grind(
                user_id=self.owner_id, user_name=self.user_name,
                pairs=self._store_pairs(), created_at=_now(),
                guild_id=getattr(self.interaction.guild, "id", None),
                channel_id=getattr(self.interaction.channel, "id", None))
            self.message = await self.interaction.followup.send(embed=e)
            store.attach_message(self.number, self.message.id)
        elif self.message is not None:
            await self.message.edit(embed=e, view=None, attachments=[])

    # -- rendering ----------------------------------------------------------------------
    async def _render(self) -> tuple[Path, float] | None:
        """Ask the engine for the audio. One pair goes through the mix route; two or more go
        through the set route, which joins them on the beat. Returns (wav, seconds) or None.

        Appending re-runs the JOIN, not the individual mixes - each mix is cached by its own
        content id, so only the seam work is repeated. That is why ➕ stays quick after the first.
        """
        stem = Path(tempfile.gettempdir()) / f"grind_{uuid.uuid4().hex[:10]}"
        wav = stem.with_suffix(".wav")
        try:
            if len(self.pairs) == 1:
                a, b = self.pairs[0]
                mix_id = await bot.api.start_mix(a, b, self.user_id, self.generation,
                                                 user_name=self.user_name)
                res = await bot.api.wait_for_mix(mix_id)
                if res.status != "ready":
                    await self._fail(res.message or "That pair did not come out. Try another.")
                    return None
                await bot.api.fetch_audio(mix_id, wav)
                store.set_pairs(self.number, self._store_pairs(), ref_id=mix_id)
            else:
                set_id = await bot.api.start_set(self.pairs, self.user_id, set_index=0,
                                                 user_name=self.user_name)
                res = await bot.api.wait_for_set(set_id)
                if res.status != "ready":
                    await self._fail(res.message or "That did not come out. Try another pair.")
                    return None
                await bot.api.fetch_set_audio(set_id, wav)
                store.set_pairs(self.number, self._store_pairs(), ref_id=set_id)
        except EngineError as e:
            await self._fail(str(e))
            return None
        except Exception as e:  # noqa: BLE001
            log.exception("grind render failed")
            await self._fail(f"Something broke on the way back: {e}")
            return None
        return wav, ui.wav_duration(wav)

    async def _attach(self, wav: Path) -> discord.File | None:
        """Transcode at the best bitrate that still fits Discord's limit, so a long grind always
        attaches something audible rather than nothing."""
        mp3 = wav.with_suffix(".mp3")
        for br in ("160k", "128k", "96k", "64k"):
            await media.to_mp3(wav, mp3, bitrate=br)
            if mp3.stat().st_size <= CLIP_SIZE_LIMIT_BYTES:
                return discord.File(str(mp3), filename=f"grind-{self.number}.mp3")
        return None

    async def run(self, *, first: bool, just_landed: bool = False) -> None:
        await self._post_submit_card(first=first)
        rendered = await self._render()
        if rendered is None:
            return
        wav, secs = rendered
        self.audio_path = wav
        self.duration = secs

        clip = await self._attach(wav)
        embed = ui.grind_embed(number=self.number, user=self.interaction.user,
                               pairs=self.named_pairs(), total_secs=secs,
                               just_landed=just_landed)
        if clip is None:
            embed.add_field(
                name="Too long to attach",
                value="Play it in 🔊 The Booth, or hit ✅ Done and start a fresh one.",
                inline=False)
        if self.message is None:
            return
        await self.message.edit(embed=embed,
                                attachments=[clip] if clip else [],
                                view=GrindView(self))
        await _seed_reactions(self.message)
        await booth.on_grind_finished(self)

    async def _fail(self, msg: str) -> None:
        if self.message is not None:
            await self.message.edit(embed=ui.error_embed(msg), view=None, attachments=[])


async def _seed_reactions(message: discord.Message) -> None:
    """Put 🔥 💀 😐 on the card so reacting is one tap rather than a search.

    Reactions rather than buttons on purpose: a Discord view stops responding after its timeout,
    so buttons would go dead on yesterday's grinds - and yesterday's grinds are exactly the ones
    a newcomer scrolls. A reaction keeps working forever and survives a bot restart."""
    for emoji in ui.REACTIONS:
        try:
            await message.add_reaction(emoji)
        except discord.HTTPException:
            pass          # a missing permission must never break the card itself


# --------------------------------------------------------------------------------------
# The picker that ➕ Keep going opens.
# --------------------------------------------------------------------------------------
class AddPairView(discord.ui.View):
    """Pick one more beat + vocal to stitch onto the end of an existing grind."""

    def __init__(self, ctx: GrindContext) -> None:
        super().__init__(timeout=300)
        self.ctx = ctx
        self.sel_beat: str | None = None
        self.sel_vocal: str | None = None

        self.beat_select = discord.ui.Select(placeholder="Pick a beat...", row=0,
                                             options=self._opts(bot.beats, None))
        self.beat_select.callback = self._on_beat
        self.vocal_select = discord.ui.Select(placeholder="Pick a vocal...", row=1,
                                              options=self._opts(bot.vocals, None))
        self.vocal_select.callback = self._on_vocal
        self.add_item(self.beat_select)
        self.add_item(self.vocal_select)

    @staticmethod
    def _opts(songs, selected_id):
        return [discord.SelectOption(label=lbl, value=val, default=dflt)
                for lbl, val, dflt in select_option_specs(songs, selected_id)]

    def _refresh(self) -> None:
        self.beat_select.options = self._opts(bot.beats, self.sel_beat)
        self.vocal_select.options = self._opts(bot.vocals, self.sel_vocal)

    def embed(self) -> discord.Embed:
        b = _name_of(self.sel_beat) if self.sel_beat else "-"
        v = _name_of(self.sel_vocal) if self.sel_vocal else "-"
        return discord.Embed(
            title="➕  What goes on the end?",
            description=f"🥁  {b}\n🎤  {v}\n\nPick both, then hit **Stitch it on**.",
            color=ui.ACCENT)

    async def _on_beat(self, interaction: discord.Interaction) -> None:
        self.sel_beat = self.beat_select.values[0]
        self._refresh()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def _on_vocal(self, interaction: discord.Interaction) -> None:
        self.sel_vocal = self.vocal_select.values[0]
        self._refresh()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Stitch it on", emoji="➕",
                       style=discord.ButtonStyle.primary, row=2)
    async def stitch(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not (self.sel_beat and self.sel_vocal):
            await interaction.response.send_message("Pick a beat and a vocal first.",
                                                    ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=discord.Embed(description="Stitching it on...", color=ui.ACCENT), view=self)
        self.ctx.pairs.append((self.sel_beat, self.sel_vocal))
        if len(self.ctx.pairs) >= MAX_PAIRS_PER_GRIND:
            self.ctx.done = True
        await self.ctx.run(first=False, just_landed=True)
        self.stop()


# --------------------------------------------------------------------------------------
# The buttons under a finished grind.
# --------------------------------------------------------------------------------------
class GrindView(discord.ui.View):
    def __init__(self, ctx: GrindContext) -> None:
        super().__init__(timeout=1800)
        self.ctx = ctx
        # At the cap, or once they have said they are finished, ➕ goes away and the grind settles
        # into its final shape. Anyone can still react and anyone can still pin it.
        if ctx.done or len(ctx.pairs) >= MAX_PAIRS_PER_GRIND:
            self.remove_item(self.keep_going)
            self.remove_item(self.finish)
        else:
            self.remove_item(self.again)

    async def _owner_only(self, interaction: discord.Interaction) -> bool:
        """Anyone may react to and pin a grind. Only its owner may change it - otherwise a busy
        channel turns every grind into a free-for-all."""
        if interaction.user.id == self.ctx.owner_id:
            return True
        await interaction.response.send_message(
            "That is someone else's grind. React to it, pin it, or start your own with `/grind`.",
            ephemeral=True)
        return False

    @discord.ui.button(label="Keep going", emoji="➕",
                       style=discord.ButtonStyle.primary, custom_id="keep_going")
    async def keep_going(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._owner_only(interaction):
            return
        view = AddPairView(self.ctx)
        await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)

    @discord.ui.button(label="Done", emoji="✅",
                       style=discord.ButtonStyle.secondary, custom_id="finish")
    async def finish(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._owner_only(interaction):
            return
        self.ctx.done = True
        await interaction.response.edit_message(view=GrindView(self.ctx))

    @discord.ui.button(label="Again", emoji="🔁",
                       style=discord.ButtonStyle.secondary, custom_id="again")
    async def again(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._owner_only(interaction):
            return
        await interaction.response.defer()
        self.ctx.generation += 1
        await self.ctx.run(first=False)

    @discord.ui.button(label="Pin it", emoji="📌",
                       style=discord.ButtonStyle.secondary, custom_id="pin_it")
    async def pin_it(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(await showcase.pin(self.ctx, interaction), ephemeral=True)


# --------------------------------------------------------------------------------------
# The commands. Three, on purpose: nobody explores slash-command parameters, they click buttons.
# Everything else lives on the card.
# --------------------------------------------------------------------------------------
async def _beat_ac(interaction: discord.Interaction, current: str):
    if not bot.songs:                      # self-heal if the engine wasn't ready at startup
        await bot.refresh_catalog()
    return [app_commands.Choice(name=s.name[:100], value=s.id)
            for s in match_songs(bot.beats, current)]


async def _vocal_ac(interaction: discord.Interaction, current: str):
    if not bot.songs:
        await bot.refresh_catalog()
    return [app_commands.Choice(name=s.name[:100], value=s.id)
            for s in match_songs(bot.vocals, current)]


@bot.tree.command(name="grind", description="Throw two songs in the grinder and find out.")
@app_commands.describe(beat="The song you want the beat from",
                       vocal="The song you want the singing from")
@app_commands.autocomplete(beat=_beat_ac, vocal=_vocal_ac)
async def grind_cmd(interaction: discord.Interaction, beat: str, vocal: str) -> None:
    await interaction.response.defer(thinking=True)
    if not bot.songs:
        await bot.refresh_catalog()
    await GrindContext(interaction, [(beat, vocal)]).run(first=True)


@bot.tree.command(name="mygrinds", description="Everything you have made.")
async def mygrinds_cmd(interaction: discord.Interaction) -> None:
    rows = []
    for r in store.recent_for_user(interaction.user.id, limit=10):
        pairs = json.loads(r["pairs"])
        label = (f"{pairs[0][2]} x {pairs[0][3]}" if len(pairs) == 1
                 else f"long grind, {len(pairs)} tracks")
        url = None
        if r["guild_id"] and r["channel_id"] and r["message_id"]:
            url = (f"https://discord.com/channels/{r['guild_id']}"
                   f"/{r['channel_id']}/{r['message_id']}")
        rows.append((r["number"], label, url))
    await interaction.response.send_message(
        embed=ui.mygrinds_embed(user=interaction.user,
                                total=store.count_for_user(interaction.user.id), rows=rows),
        ephemeral=True)


# --------------------------------------------------------------------------------------
# Reactions - the actual product signal.
#
# RAW events, not the cooked ones: the cooked handler only fires for messages the bot happens to
# have cached, so a reaction on yesterday's grind (exactly the ones a newcomer scrolls) would be
# silently dropped after any restart. Raw events always fire.
# --------------------------------------------------------------------------------------
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
    if payload.user_id == getattr(bot.user, "id", None):
        return                                   # the bot seeding 🔥 💀 😐 is not a vote
    emoji = str(payload.emoji)
    if emoji not in ui.REACTIONS:
        return
    row = store.by_message(payload.message_id)
    if row is None:
        return
    store.add_reaction(grind_number=row["number"], user_id=payload.user_id,
                       emoji=emoji, when=_now())
    log.info("reaction: %s on grind #%s by %s", emoji, row["number"], payload.user_id)


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent) -> None:
    emoji = str(payload.emoji)
    if emoji not in ui.REACTIONS:
        return
    row = store.by_message(payload.message_id)
    if row is None:
        return
    # A changed mind must not be counted twice, so a removal really removes.
    store.remove_reaction(grind_number=row["number"], user_id=payload.user_id, emoji=emoji)


@bot.event
async def on_voice_state_update(member, before, after) -> None:
    await booth.on_voice_state_update(member, before, after)


@bot.tree.command(name="help", description="What Grinder does and how to use it.")
async def help_cmd(interaction: discord.Interaction) -> None:
    # The wordmark rides along as an attachment; the embed references it as attachment://logo.png.
    logo = brand.image_bytes(brand.LOGO)
    files = [discord.File(brand.LOGO, filename="logo.png")] if logo else []
    await interaction.response.send_message(embed=ui.help_embed(), files=files, ephemeral=True)


@bot.tree.command(name="setup", description="Set up this server: channels, roles, emojis and branding.")
@app_commands.describe(
    refresh_branding="Replace the server icon with Grinder's current artwork (default: leave it alone).")
@app_commands.checks.has_permissions(manage_guild=True)
async def setup_cmd(interaction: discord.Interaction, refresh_branding: bool = False) -> None:
    """Build the community inside a server the founder already created and owns.

    Gated on Manage Server so a random member can't restructure the place. Deferred because a full
    run makes a dozen API calls (categories, channels, roles, six emoji uploads) and will comfortably
    exceed Discord's 3-second reply window."""
    if interaction.guild is None:
        await interaction.response.send_message(
            embed=ui.error_embed("Run this inside a server, not in a DM."), ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    try:
        report = await server_setup.run(interaction.guild, refresh_branding=refresh_branding)
    except Exception as e:  # noqa: BLE001 — report the failure rather than a silent timeout
        log.exception("setup failed outright")
        await interaction.followup.send(
            embed=ui.error_embed(f"Setup couldn't run: {e}"))
        return
    await interaction.followup.send(
        embed=server_setup.report_embed(report, interaction.guild.name))


@setup_cmd.error
async def setup_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    """Turn the permission check's failure into a plain sentence instead of Discord's raw error."""
    if isinstance(error, app_commands.MissingPermissions):
        msg = "You need the **Manage Server** permission to run setup."
    else:
        msg = f"Setup couldn't start: {error}"
    send = (interaction.followup.send if interaction.response.is_done()
            else interaction.response.send_message)
    await send(embed=ui.error_embed(msg), ephemeral=True)


def main() -> None:
    bot.run(CFG.token, log_handler=None)


if __name__ == "__main__":
    main()
