"""Prompt-DJ Discord bot (demo).

A convenience-first front-end to the Prompt-DJ mix engine, modelled on how people already
"get" Midjourney: type one slash command, pick your two songs from an autocomplete list, and
the finished mix comes back in the channel as a playable clip with buttons (Another take /
Play in voice). No web screen, no manual steps.

It talks to the local engine over HTTP (see api_client) — it never touches audio or the mixing
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

import media
import voice_player
from api_client import EngineError, PromptDJClient, Song
from botconfig import load_config
from helpers import match_songs, safe_filename, style_label

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("promptdj.discord")

CFG = load_config()
BOT_NAME = "Grinder"       # the beta Discord bot's name (Prompt-DJ is the product)
VIOLET = 0x8A2BE2          # the app's "Electric Violet" accent
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

    async def setup_hook(self) -> None:
        await self.refresh_catalog()
        if CFG.guild_id:
            guild = discord.Object(id=CFG.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)   # appears INSTANTLY in that server
            log.info("commands synced to guild %s", CFG.guild_id)
        else:
            await self.tree.sync()              # global — can take up to ~1h to appear
            log.info("commands synced globally (may take up to 1h to appear)")

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


bot = PromptDJBot()


def _name_of(song_id: str) -> str:
    for s in bot.songs:
        if s.id == song_id:
            return s.name
    return "song"


def _error_embed(msg: str) -> discord.Embed:
    return discord.Embed(title="😕 Couldn't make that mix", description=msg, color=0xB00020)


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
        self.name1 = _name_of(song1_id)
        self.name2 = _name_of(song2_id)
        self.message: discord.Message | None = None
        self.audio_path: Path | None = None   # the WAV, kept for voice playback

    def _cooking_embed(self) -> discord.Embed:
        return discord.Embed(
            title="🎧 Cooking your mix…",
            description=(f"**{self.name1}**  ·  the beat\n**{self.name2}**  ·  the vocals\n\n"
                         f"Take {self.generation + 1} — this is quick if we've mixed this pair before, "
                         f"or up to a minute the first time."),
            color=VIOLET)

    async def run(self, *, first: bool) -> None:
        cooking = self._cooking_embed()
        if first:
            self.message = await self.interaction.followup.send(embed=cooking)
        elif self.message is not None:
            await self.message.edit(embed=cooking, view=None, attachments=[])

        try:
            mix_id = await bot.api.start_mix(self.song1_id, self.song2_id,
                                             self.user_id, self.generation)
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
        embed = discord.Embed(
            title=f"🎛️ {name}",
            description=f"**{self.name1}** · beat   ×   **{self.name2}** · vocals",
            color=VIOLET)
        embed.add_field(name="Mix style", value=style_label(res.rule, res.notes), inline=True)
        embed.add_field(name="Take", value=f"{self.generation + 1} of {MAX_TAKES}", inline=True)
        embed.set_footer(text=f"{BOT_NAME} · tap 🔄 for another take, 🔊 to play in voice")
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

    @discord.ui.button(label="Another take", emoji="🔄",
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
            await interaction.followup.send("Give it a second — the mix is still arriving.", ephemeral=True)
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
    return [app_commands.Choice(name=s.name[:100], value=s.id)
            for s in match_songs(bot.beats, current)]


async def _vocal_ac(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=s.name[:100], value=s.id)
            for s in match_songs(bot.vocals, current)]


@bot.tree.command(name="mix", description="Make a DJ mix — Song 1's beat + Song 2's vocals.")
@app_commands.describe(beat="Song 1 — its beat drives the mix",
                       vocals="Song 2 — its vocals ride on top")
@app_commands.autocomplete(beat=_beat_ac, vocals=_vocal_ac)
async def mix_cmd(interaction: discord.Interaction, beat: str, vocals: str) -> None:
    await interaction.response.defer(thinking=True)
    if not bot.songs:
        await bot.refresh_catalog()
    ctx = MixContext(interaction, song1_id=beat, song2_id=vocals, generation=0)
    await ctx.run(first=True)


@bot.tree.command(name="songs", description="List the songs you can mix.")
async def songs_cmd(interaction: discord.Interaction) -> None:
    if not bot.songs:
        await bot.refresh_catalog()
    beats = "\n".join(f"• {s.name}" for s in bot.beats) or "—"
    vocals = "\n".join(f"• {s.name}" for s in bot.vocals) or "—"
    embed = discord.Embed(title=f"🎵 {BOT_NAME} — song library", color=VIOLET)
    embed.add_field(name="Beats (Song 1)", value=beats[:1024], inline=True)
    embed.add_field(name="Vocals (Song 2)", value=vocals[:1024], inline=True)
    embed.set_footer(text="Use /mix and start typing a name — it autocompletes.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


def main() -> None:
    bot.run(CFG.token, log_handler=None)


if __name__ == "__main__":
    main()
