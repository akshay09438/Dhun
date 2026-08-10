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

import logging
import tempfile
import uuid
from pathlib import Path

import discord
from discord import app_commands

import brand
import media
import server_setup
import voice_player
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


def _name_of(song_id: str) -> str:
    for s in bot.songs:
        if s.id == song_id:
            return s.name
    return "song"


def _error_embed(msg: str) -> discord.Embed:
    return ui.error_embed(msg)


# --------------------------------------------------------------------------------------
# One mix's lifecycle: a "cooking…" message that becomes the finished clip + buttons.
# --------------------------------------------------------------------------------------
class MixContext:
    def __init__(self, interaction: discord.Interaction, song1_id: str, song2_id: str,
                 generation: int = 0) -> None:
        self.interaction = interaction
        self.song1_id = song1_id
        self.song2_id = song2_id
        self.generation = generation
        self.user_id = str(interaction.user.id)
        # The name the operator would actually recognise in their own server (a nickname if the
        # member set one, otherwise the account name). Sent for the ops dashboard only.
        self.user_name = getattr(interaction.user, "display_name", None) or interaction.user.name
        self.name1 = _name_of(song1_id)
        self.name2 = _name_of(song2_id)
        self.message: discord.Message | None = None
        self.audio_path: Path | None = None   # the WAV, kept for voice playback

    def _cooking_embed(self) -> discord.Embed:
        return ui.cooking_embed(self.name1, self.name2)

    async def run(self, *, first: bool) -> None:
        cooking = self._cooking_embed()
        if first:
            self.message = await self.interaction.followup.send(embed=cooking)
        elif self.message is not None:
            await self.message.edit(embed=cooking, view=None, attachments=[])

        try:
            mix_id = await bot.api.start_mix(self.song1_id, self.song2_id,
                                             self.user_id, self.generation,
                                             user_name=self.user_name)
        except EngineError as e:
            await self._fail(str(e))
            return

        async def on_progress(elapsed: float) -> None:
            if elapsed and int(elapsed) % 10 == 0 and self.message is not None:
                cooking.set_footer(text=f"still mixing… {int(elapsed)}s")
                try:
                    await self.message.edit(embed=cooking)
                except discord.HTTPException:
                    pass

        res = await bot.api.wait_for_mix(mix_id, on_progress=on_progress)
        if res.status != "ready":
            await self._fail(res.message or "Couldn't build this mix. Try another pair.")
            return

        # Fetch the finished audio, keep the WAV for voice, post an MP3 clip everyone can play.
        stem = Path(tempfile.gettempdir()) / f"promptdj_{mix_id[:12]}_{uuid.uuid4().hex[:6]}"
        wav, mp3 = stem.with_suffix(".wav"), stem.with_suffix(".mp3")
        try:
            await bot.api.fetch_audio(mix_id, wav)
            self.audio_path = wav
            await media.to_mp3(wav, mp3)
        except Exception as e:  # noqa: BLE001
            log.exception("audio fetch/transcode failed")
            await self._fail(f"The mix rendered, but sending it failed: {e}")
            return

        name = await bot.api.mix_name(self.name1, self.name2) or f"{self.name1} × {self.name2}"
        embed = ui.now_playing_embed(
            name=name, beat=self.name1, vocals=self.name2,
            total_secs=ui.wav_duration(wav), user=self.interaction.user)
        clip = discord.File(str(mp3), filename=f"{safe_filename(name)}.mp3")
        if self.message is not None:
            await self.message.edit(embed=embed, attachments=[clip], view=MixView(self))

    async def _fail(self, msg: str) -> None:
        if self.message is not None:
            await self.message.edit(embed=_error_embed(msg), view=None, attachments=[])


# --------------------------------------------------------------------------------------
# The buttons under a finished mix.
# --------------------------------------------------------------------------------------
class MixView(discord.ui.View):
    def __init__(self, ctx: MixContext) -> None:
        super().__init__(timeout=1800)
        self.ctx = ctx
        for item in self.children:                       # disable "Another take" at the cap
            if getattr(item, "custom_id", None) == "another_take" and ctx.generation + 1 >= MAX_TAKES:
                item.disabled = True

    @discord.ui.button(label="Regenerate", emoji="🔄",
                       style=discord.ButtonStyle.primary, custom_id="another_take")
    async def another(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        self.ctx.generation += 1
        await self.ctx.run(first=False)

    @discord.ui.button(label="Play in voice", emoji="🔊",
                       style=discord.ButtonStyle.secondary, custom_id="play_voice")
    async def play_voice(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        if self.ctx.audio_path is None:
            await interaction.followup.send("Give it a second, the mix is still arriving.", ephemeral=True)
            return
        msg = await voice_player.play_in_channel(interaction, self.ctx.audio_path)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="Leave voice", emoji="⏹️",
                       style=discord.ButtonStyle.secondary, custom_id="leave_voice")
    async def leave_voice(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        msg = await voice_player.leave(interaction)
        await interaction.followup.send(msg, ephemeral=True)


# --------------------------------------------------------------------------------------
# The commands.
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


@bot.tree.command(name="mix", description="Make a mashup: one song's beat, another song's vocals.")
@app_commands.describe(beat="The song you want the beat from",
                       vocals="The song you want the singing from")
@app_commands.autocomplete(beat=_beat_ac, vocals=_vocal_ac)
async def mix_cmd(interaction: discord.Interaction, beat: str, vocals: str) -> None:
    await interaction.response.defer(thinking=True)
    if not bot.songs:
        await bot.refresh_catalog()
    ctx = MixContext(interaction, song1_id=beat, song2_id=vocals, generation=0)
    await ctx.run(first=True)


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


@bot.tree.command(name="songs", description="See every song you can pick.")
async def songs_cmd(interaction: discord.Interaction) -> None:
    if not bot.songs:
        await bot.refresh_catalog()
    beats = "\n".join(f"• {s.name}" for s in bot.beats) or "-"
    vocals = "\n".join(f"• {s.name}" for s in bot.vocals) or "-"
    embed = discord.Embed(title=f"🎵 {BOT_NAME} song library", color=VIOLET)
    embed.add_field(name="Beats (Song 1)", value=beats[:1024], inline=True)
    embed.add_field(name="Vocals (Song 2)", value=vocals[:1024], inline=True)
    embed.set_footer(text="Use /mix and start typing a name. It autocompletes.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# --------------------------------------------------------------------------------------
# /set — a continuous back-to-back set of 2–5 mixes.
# --------------------------------------------------------------------------------------
MAX_MIXES_PER_SET = 5
SET_SIZE_LIMIT_BYTES = 9_000_000   # keep set clips under Discord's non-Nitro upload limit


def _mmss(seconds: float) -> str:
    s = int(seconds or 0)
    return f"{s // 60}:{s % 60:02d}"


def _member_line(m: dict) -> str:
    idx = m.get("index", "?")
    n1, n2 = _name_of(m.get("song1_id", "")), _name_of(m.get("song2_id", ""))
    if not m.get("kept", True):
        return f"~~Set {idx}: {n1} × {n2}~~ skipped ({m.get('reason', 'couldn’t be mixed')})"
    seam = m.get("seam_at")
    when = f" · joins at {_mmss(seam)}" if seam else ""
    return f"**Set {idx}:** {n1} × {n2}{when}"


class SetView(discord.ui.View):
    def __init__(self, ctx: "SetContext") -> None:
        super().__init__(timeout=1800)
        self.ctx = ctx

    @discord.ui.button(label="Play in voice", emoji="🔊",
                       style=discord.ButtonStyle.secondary, custom_id="set_play")
    async def play_voice(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        if self.ctx.audio_path is None:
            await interaction.followup.send("Give it a second, the set is still arriving.", ephemeral=True)
            return
        await interaction.followup.send(
            await voice_player.play_in_channel(interaction, self.ctx.audio_path), ephemeral=True)

    @discord.ui.button(label="Leave voice", emoji="⏹️",
                       style=discord.ButtonStyle.secondary, custom_id="set_leave")
    async def leave_voice(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(await voice_player.leave(interaction), ephemeral=True)


class SetContext:
    def __init__(self, interaction: discord.Interaction, pairs: list[tuple[str, str]]) -> None:
        self.interaction = interaction
        self.pairs = pairs                       # list[(beat_id, vocals_id)]
        self.user_id = str(interaction.user.id)
        self.user_name = getattr(interaction.user, "display_name", None) or interaction.user.name
        self.message: discord.Message | None = None
        self.audio_path: Path | None = None

    def _building_embed(self) -> discord.Embed:
        lines = "\n".join(f"{i}. {_name_of(a)} × {_name_of(b)}"
                          for i, (a, b) in enumerate(self.pairs, 1))
        return ui.building_embed(lines, len(self.pairs))

    async def _fit_mp3(self, wav: Path, mp3: Path) -> None:
        """Transcode at the highest bitrate that still fits Discord's upload limit, so even a
        long set always attaches something audible."""
        for br in ("160k", "128k", "96k", "64k"):
            await media.to_mp3(wav, mp3, bitrate=br)
            if mp3.stat().st_size <= SET_SIZE_LIMIT_BYTES:
                return

    async def run(self) -> None:
        building = self._building_embed()
        self.message = await self.interaction.followup.send(embed=building)
        try:
            set_id = await bot.api.start_set(self.pairs, self.user_id, set_index=0,
                                             user_name=self.user_name)
        except EngineError as e:
            await self.message.edit(embed=_error_embed(str(e)))
            return

        async def on_progress(elapsed: float) -> None:
            if elapsed and int(elapsed) % 15 == 0 and self.message is not None:
                building.set_footer(text=f"still building… {int(elapsed)}s")
                try:
                    await self.message.edit(embed=building)
                except discord.HTTPException:
                    pass

        res = await bot.api.wait_for_set(set_id, on_progress=on_progress)
        if res.status != "ready":
            await self.message.edit(embed=_error_embed(res.message or "Couldn't build this set."))
            return

        stem = Path(tempfile.gettempdir()) / f"promptdj_set_{set_id[:12]}_{uuid.uuid4().hex[:6]}"
        wav, mp3 = stem.with_suffix(".wav"), stem.with_suffix(".mp3")
        try:
            await bot.api.fetch_set_audio(set_id, wav)
            self.audio_path = wav
            await self._fit_mp3(wav, mp3)
        except Exception as e:  # noqa: BLE001
            log.exception("set fetch/transcode failed")
            await self.message.edit(embed=_error_embed(f"The set rendered, but sending it failed: {e}"))
            return

        members = res.members or []
        kept = [m for m in members if m.get("kept", True)]
        lines = "\n".join(_member_line(m) for m in members) or "-"
        embed = ui.set_lineup_embed(lines, res.duration or 0, len(kept), self.interaction.user)

        size = mp3.stat().st_size if mp3.exists() else 0
        if 0 < size <= SET_SIZE_LIMIT_BYTES:
            f = discord.File(str(mp3), filename="grinder-set.mp3")
            await self.message.edit(embed=embed, attachments=[f], view=SetView(self))
        else:
            embed.add_field(
                name="Heads up",
                value="This set is a bit long to attach here. Tap 🔊 **Play in voice**, or build a shorter set.",
                inline=False)
            await self.message.edit(embed=embed, view=SetView(self))


class SetBuilderView(discord.ui.View):
    """A step-by-step set builder: pick a beat + a vocal from dropdowns, ➕ Add mix, repeat
    (2–5), then ✅ Build set. Far more convenient than one command with ten fields — and since
    the catalog is small, dropdowns fit (no typing)."""

    def __init__(self) -> None:
        super().__init__(timeout=600)
        self.pairs: list[tuple[str, str]] = []
        self.sel_beat: str | None = None
        self.sel_vocal: str | None = None
        self.message: discord.Message | None = None

        self.beat_select = discord.ui.Select(
            placeholder="1) Pick a beat…", min_values=1, max_values=1, row=0,
            options=self._opts(bot.beats, None))
        self.beat_select.callback = self._on_beat
        self.vocal_select = discord.ui.Select(
            placeholder="2) Pick a vocal…", min_values=1, max_values=1, row=1,
            options=self._opts(bot.vocals, None))
        self.vocal_select.callback = self._on_vocal
        self.add_item(self.beat_select)
        self.add_item(self.vocal_select)

    @staticmethod
    def _opts(songs, selected_id):
        return [discord.SelectOption(label=lbl, value=val, default=dflt)
                for lbl, val, dflt in select_option_specs(songs, selected_id)]

    def _refresh_selects(self) -> None:
        """Rebuild both dropdowns so the picked song shows as selected, not the placeholder."""
        self.beat_select.options = self._opts(bot.beats, self.sel_beat)
        self.vocal_select.options = self._opts(bot.vocals, self.sel_vocal)

    def embed(self) -> discord.Embed:
        lineup = ("\n".join(f"{i}. **{_name_of(a)}** × **{_name_of(b)}**"
                            for i, (a, b) in enumerate(self.pairs, 1))
                  if self.pairs else "_No mixes yet._")
        picking = ""
        if self.sel_beat or self.sel_vocal:
            b = _name_of(self.sel_beat) if self.sel_beat else "-"
            v = _name_of(self.sel_vocal) if self.sel_vocal else "-"
            picking = f"\n\n**Selecting:** {b} × {v}  → tap ➕ Add mix"
        e = discord.Embed(
            title="🎚️ Build a DJ set",
            description=f"**Line-up ({len(self.pairs)}/{MAX_MIXES_PER_SET}):**\n{lineup}{picking}",
            color=VIOLET)
        e.set_footer(text="Pick a beat and a vocal, then ➕ Add mix. Repeat up to 5, then ✅ Build set.")
        return e

    async def _on_beat(self, interaction: discord.Interaction) -> None:
        self.sel_beat = self.beat_select.values[0]
        self._refresh_selects()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def _on_vocal(self, interaction: discord.Interaction) -> None:
        self.sel_vocal = self.vocal_select.values[0]
        self._refresh_selects()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Add mix", emoji="➕", style=discord.ButtonStyle.secondary, row=2)
    async def add_mix(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not (self.sel_beat and self.sel_vocal):
            await interaction.response.send_message("Pick a beat *and* a vocal first.", ephemeral=True)
            return
        if len(self.pairs) >= MAX_MIXES_PER_SET:
            await interaction.response.send_message(
                f"A set holds up to {MAX_MIXES_PER_SET} mixes.", ephemeral=True)
            return
        self.pairs.append((self.sel_beat, self.sel_vocal))
        self.sel_beat = self.sel_vocal = None
        self._refresh_selects()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Remove last", emoji="↩️", style=discord.ButtonStyle.secondary, row=2)
    async def remove_last(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.pairs:
            self.pairs.pop()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Build set", emoji="✅", style=discord.ButtonStyle.primary, row=2)
    async def build(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if len(self.pairs) < 2:
            await interaction.response.send_message("Add at least **2** mixes first.", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)   # freeze the builder
        await SetContext(interaction, list(self.pairs)).run()
        self.stop()


@bot.tree.command(name="set", description="Join 2 to 5 mixes into one continuous set.")
async def set_cmd(interaction: discord.Interaction) -> None:
    if not bot.songs:
        await bot.refresh_catalog()
    if not bot.beats or not bot.vocals:
        await interaction.response.send_message(
            "The song library isn't loaded yet. Make sure the engine is running, then try again.",
            ephemeral=True)
        return
    view = SetBuilderView()
    await interaction.response.send_message(embed=view.embed(), view=view)
    view.message = await interaction.original_response()


def main() -> None:
    bot.run(CFG.token, log_handler=None)


if __name__ == "__main__":
    main()
