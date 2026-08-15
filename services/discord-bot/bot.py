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
import logging.handlers
from datetime import datetime, timezone
import tempfile
import uuid
from pathlib import Path

import discord
from discord import app_commands

import brand
import editbudget
import media
import server_setup
import door
import showcase
import speakers as speakers_mod
import store
import voice_player
import voices as voices_mod
from booth import booth
from api_client import EngineError, PromptDJClient, Song
from botconfig import load_config
import ui
from helpers import match_songs, safe_filename, select_option_specs

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("promptdj.discord")

# WRITE OUR OWN LOG, rather than relying on the launcher to redirect the console.
#
# For two days there was no log at all: the .bat threw everything at a console window and nowhere
# else, so once it was minimised nobody could answer "is Grinder up?" or "what just broke?". On
# 2026-08-14 that cost a wrong diagnosis - a perfectly healthy bot was killed and debugged, because
# the only other signal available (`Member.status`) reads `offline` for EVERYONE without the
# privileged presences intent. Doing it here rather than in the shell also avoids PowerShell
# wrapping every stderr line in a NativeCommandError and writing the file as UTF-16.
try:
    _LOGDIR = Path(__file__).resolve().parent / "logs"
    _LOGDIR.mkdir(exist_ok=True)
    _fh = logging.handlers.RotatingFileHandler(       # rotate: an unbounded log on a full disk is a bug
        _LOGDIR / "grinder.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(_fh)
    log.info("logging to %s", _LOGDIR / "grinder.log")
except OSError:                                       # a log we cannot write must never stop the bot
    log.warning("could not open the log file; console only")

CFG = load_config()
BOT_NAME = "Grinder"       # the beta Discord bot's name (Prompt-DJ is the product)
VIOLET = ui.ACCENT         # the Grinder purple, sampled from the artwork — defined in brand.py
MAX_TAKES = 5              # matches the web app's MAX_GENERATIONS_PER_SESSION

# WHICH VOCALS A PERSON SEES. "Bollywood" rather than "Hindi" because three of the fourteen are
# Punjabi (AP Dhillon, Jugni Ji, Wari Jawa) - Bollywood is both more honest and the word a global
# audience already knows. Beats are NEVER filtered; they are instrumental beds.
LANGUAGES = {"english": "English", "bollywood": "Bollywood"}
DEFAULT_LANGUAGE = "english"


# --------------------------------------------------------------------------------------
# The client — loads the catalog once for autocomplete, syncs the /mix command.
# --------------------------------------------------------------------------------------
class PromptDJBot(discord.Client):
    def __init__(self) -> None:
        # MEMBERS is privileged and is requested for exactly one reason: `on_member_join`, which is
        # what makes a vouch link work - somebody the founder invited personally has to be let
        # straight in, and the bot cannot notice an arrival it is never told about. It also gives
        # the booth a real member list instead of an empty cache.
        # If it is ever turned off in the Developer Portal the bot will refuse to start with a
        # clear error, which is better than silently never letting a vouched friend in.
        _intents = discord.Intents.default()
        _intents.members = True
        super().__init__(intents=_intents)
        self.tree = app_commands.CommandTree(self)
        self.api = PromptDJClient(CFG.api_base)
        self.songs: list[Song] = []
        self.beats: list[Song] = []
        self.vocals: list[Song] = []
        # Guilds whose slash commands are already registered, so a reconnect doesn't re-sync them.
        self._synced_guilds: set[int] = set()

    async def setup_hook(self) -> None:
        # PERSISTENT VIEWS, re-registered on every start. The lobby button sits in a channel for
        # weeks and the founder reads a pool of application cards that has been building for days;
        # without this both go dead after a restart, and a dead "Ask to join" button reads to a
        # newcomer as a community that does not work.
        self.add_view(door.DoorView())
        self.add_view(door.ReviewView())
        await self.refresh_catalog()
        await self.bring_extra_voices_online()
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
        # FEATURED FIRST. A Discord select menu holds 25 options and `select_option_specs` takes the
        # first 25 in list order, so with 63 beats and 59 English vocals most of the catalog was
        # unreachable and WHICH 25 showed was an accident of manifest order. Sorting featured to the
        # front makes the curated 25 (scripts/set_featured.py) the ones that fit. Stable sort, so
        # everything else keeps its order behind them and nothing is dropped - the engine and the
        # web app still see the whole catalog.
        def curated_first(pool):
            return sorted(pool, key=lambda s: not getattr(s, "featured", False))

        self.beats = curated_first([s for s in self.songs if s.role_hint == "beat"]) or self.songs
        self.vocals = curated_first([s for s in self.songs if s.role_hint == "vocals"]) or self.songs
        log.info("catalog: %d songs (%d beats, %d vocals; %d featured)",
                 len(self.songs), len(self.beats), len(self.vocals),
                 sum(1 for s in self.songs if getattr(s, "featured", False)))

    async def on_ready(self) -> None:
        log.info("logged in as %s (id %s)", self.user, getattr(self.user, "id", "?"))
        await self._clear_stale_voice()
        await self._apply_brand()
        guilds = list(self.guilds)
        # Say which servers Grinder is in. Silence here used to be ambiguous — "no guilds" and
        # "already synced" looked identical in the log, which hid whether /setup would appear.
        log.info("in %d server(s): %s", len(guilds),
                 ", ".join(f"{g.name} ({g.id})" for g in guilds) or "none")
        for g in guilds:
            booth.check_config(g)     # say so loudly if a configured channel has been deleted
            # The vouch feature works by spotting which invite's count changed, so it needs a
            # BEFORE picture. Without this the very first join after a restart is unattributable
            # and a vouched friend would be sent to the lobby like a stranger.
            await door.remember_invites(g)
            # Say it LOUDLY at startup if approvals cannot actually grant the role. Otherwise the
            # first anybody knows is a person who was approved and still cannot see the server.
            ok, why = door.can_grant_member(g)
            if door.is_open() and not ok:
                log.error("THE DOOR CANNOT LET ANYBODY IN: %s. Approvals will be recorded and the "
                          "person will still see nothing.", why)
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

    async def bring_extra_voices_online(self) -> None:
        """Log in the extra Grinder identities, so more than one room can have sound at once.

        A bot application holds ONE voice connection per SERVER, so a single Grinder means one room
        with music and every other one silent - and worse, it WALKS OUT of a busy room to serve one
        person next door. Extra identities are free and are the only fix; see voices.py.

        ZERO CONFIGURED IS THE DEFAULT AND CHANGES NOTHING. With no GRINDER_ROOM_TOKENS the box holds
        exactly one voice - this bot - and every decision the booth makes is the one it made before
        any of this existed. Nothing changes for the founder until they choose to paste a token.

        Runs in `setup_hook` rather than `on_ready` deliberately: on_ready fires again on every
        reconnect, and logging the extras in again each time would burn Discord's identify budget for
        no gain."""
        pool = speakers_mod.SpeakerPool(CFG.room_tokens, main_token=CFG.token)
        if len(pool):
            await speakers_mod.bring_online(
                pool,
                lambda: discord.Client(intents=discord.Intents.default()),
                on_ready=self._set_up_extra_voice)
        booth.voices = voices_mod.VoiceBox(pool, main_client=self)
        # The single most useful line the founder can read at startup. Discovering this limit from a
        # room that stayed quiet all night is how the whole feature came to be needed.
        log.info(voices_mod.describe(booth.voices))

    async def _set_up_extra_voice(self, speaker) -> None:
        """Give a freshly logged-in extra the same face as the main Grinder, and clear any voice
        session it left behind.

        THE FOUNDER'S CALL: an identical twin. Somebody in the second room just sees Grinder, and
        never learns there are two - so the picture is applied here, from code, rather than being one
        more thing to do by hand in the Developer Portal.

        Each identity keeps its OWN record of what it last uploaded, because Discord's avatar rate
        limit is strict and counted per bot."""
        await self._clear_stale_voice(speaker.client)
        user = getattr(speaker.client, "user", None)
        if user is None:
            return
        slot = f"avatar-{user.id}"
        if getattr(user, "avatar", None) is not None and not brand.slot_needs_upload(slot):
            log.info("brand: extra voice #%d already wears the disc", speaker.index)
            return
        data = brand.image_bytes(brand.ICON)
        if data is None:
            return
        await user.edit(avatar=data)
        brand.mark_slot_applied(slot)
        log.info("brand: extra voice #%d avatar uploaded from %s (%s)",
                 speaker.index, brand.ICON.name, brand.icon_fingerprint())

    async def _clear_stale_voice(self, client=None) -> None:
        """Tell Discord we are not in any voice channel, before we try to join one.

        THE BUG THIS FIXES, observed 2026-08-11: kill the bot while it is connected to voice and
        Discord keeps the old voice session alive server-side. The next run's handshake completes
        and finds the media endpoint, then the voice websocket dies - five times over, every time,
        because it is colliding with a session belonging to a process that no longer exists. From
        the outside it looks exactly like "voice is broken".

        A bot that has just logged in is, by definition, not in a call. Saying so explicitly costs
        one gateway message and clears any leftover. Safe to run always: if there is nothing stale,
        it is a no-op.

        `client` lets an EXTRA identity be cleared too. Each one holds its own voice session, so each
        one can leave its own zombie behind - and a stale session on the second Grinder presents as
        "the second room never plays", which is indistinguishable from the feature not working."""
        for guild in (client or self).guilds:
            try:
                await guild.change_voice_state(channel=None)
            except Exception:  # noqa: BLE001 - never let housekeeping stop the bot starting
                log.debug("could not clear voice state in %s", guild.id, exc_info=True)

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
            await self._apply_profile_banner(user)
            await self._apply_app_icon()
            url = str(user.display_avatar.url) if user.display_avatar else None
            # Log it: this is the ONLY way to check from outside what picture Discord actually holds
            # for the bot. NOTE (corrected 2026-08-12): this line used to end "...the separate
            # Application icon shown in the slash-command picker (which the API cannot change)".
            # It can — discord.py 2.7.1's AppInfo.edit takes an icon — and it is now set below.
            log.info("brand: bot avatar url = %s", url)
            ui.set_avatar_url(url)
        except Exception:  # noqa: BLE001 — branding is cosmetic; never let it stop the bot
            log.warning("brand: couldn't set the avatar (continuing)", exc_info=True)

    async def _apply_app_icon(self) -> None:
        """Set the APPLICATION icon - a different picture from the bot's avatar.

        The avatar is what you see beside a message. This is what the Developer Portal lists, what
        the slash-command picker shows, and what the App Directory would use. Setting one does NOT
        set the other, which is why the portal still showed the old disc after the avatar had
        already changed (founder-reported 2026-08-12).

        Its own fingerprint file, so it uploads once per artwork change rather than on every start.
        Never fatal: a bot that cannot set a picture must still make mixes."""
        if not brand.app_icon_needs_upload():
            log.info("brand: application icon already up to date")
            return
        data = brand.image_bytes(brand.ICON)
        if data is None:
            return
        try:
            info = await self.application_info()
            await info.edit(icon=data, reason="Grinder - keep the portal icon in step with the art")
            brand.mark_app_icon_applied()
            log.info("brand: application icon uploaded from %s (%s)",
                     brand.ICON.name, brand.icon_fingerprint())
        except Exception:  # noqa: BLE001 - cosmetic; the avatar already succeeded above
            log.warning("brand: couldn't set the application icon (continuing)", exc_info=True)

    async def _apply_profile_banner(self, user) -> None:
        """Set the strip behind the bot's picture on its profile card.

        Separate from the avatar's try/except on purpose: banner support is newer than the avatar's
        and a server-side refusal here must not swallow the avatar's own success log. Kept quiet
        about failure for the same reason as the avatar — a bot that can't set a picture must still
        make mixes.

        NOT the same thing as the SERVER banner (`brand.BANNER`), which needs boost level 2. This
        one is the bot's own profile and has no such gate.
        """
        data = brand.image_bytes(brand.REMIX_BANNER)
        if data is None:
            log.info("brand: no profile banner shipped (%s missing)", brand.REMIX_BANNER.name)
            return
        if user.banner is not None and not brand.art_needs_upload(brand.REMIX_BANNER):
            log.info("brand: profile banner already up to date")
            return
        try:
            await user.edit(banner=data)
            brand.mark_art_applied(brand.REMIX_BANNER)
            log.info("brand: profile banner uploaded from %s (%s)",
                     brand.REMIX_BANNER.name, brand.art_fingerprint(brand.REMIX_BANNER))
        except Exception:  # noqa: BLE001
            log.warning("brand: couldn't set the profile banner (continuing)", exc_info=True)


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
        self.number: int | None = None
        self.duration: float = 0.0
        # Track boundaries inside a SET, filled in when one renders. Empty for a single mix, which
        # has nothing to skip between.
        self.seams: list[float] = []
        self.ref_id: str | None = None       # engine mix_id / set_id, so seams can be looked up
        self._last_line: str | None = None       # the live "what's happening" line, so we only edit on a change

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
    def _submit_embed(self, *, stage: str | None = None, position: int | None = None,
                      eta_secs: int | None = None) -> discord.Embed:
        beat, vocals = self.named_pairs()[-1]
        return ui.submit_embed(user=self.interaction.user, beat=beat, vocals=vocals,
                               stage=stage, position=position, eta_secs=eta_secs)

    async def _on_progress(self, _elapsed: float, res) -> None:
        """Move the card while the engine works.

        Only edits when the LINE ACTUALLY CHANGES. Discord rate-limits message edits, and
        re-sending an identical embed every two seconds would spend that budget saying nothing -
        so a grind that sits in one stage for twenty seconds costs exactly one edit."""
        if self.message is None:
            return
        line = ui.waiting_line(stage=getattr(res, "stage", None),
                               position=getattr(res, "queue_position", None),
                               eta_secs=getattr(res, "queue_eta_secs", None))
        if line == self._last_line:
            return

        # Each card is already polite on its own - but politeness per card is not politeness per
        # CHANNEL, and Discord rate-limits edits per channel. Ten cards moving in #get-shit-done
        # know nothing about each other, so they share one budget here. A skipped progress edit
        # costs nothing: the next tick is two seconds away and knows more. The FINAL edit that
        # delivers the mix bypasses this entirely - see run().
        channel = getattr(self.message, "channel", None)
        if not editbudget.budget.allow(getattr(channel, "id", 0)):
            return          # deliberately do NOT record _last_line: the next tick retries

        self._last_line = line
        try:
            await self.message.edit(embed=self._submit_embed(
                stage=getattr(res, "stage", None),
                position=getattr(res, "queue_position", None),
                eta_secs=getattr(res, "queue_eta_secs", None)))
        except discord.HTTPException:
            pass       # a card that will not update is not worth failing a grind over

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
                res = await bot.api.wait_for_mix(mix_id, on_progress=self._on_progress)
                if res.status != "ready":
                    await self._fail(res.message or "That pair did not come out. Try another.")
                    return None
                await bot.api.fetch_audio(mix_id, wav)
                store.set_pairs(self.number, self._store_pairs(), ref_id=mix_id)
            else:
                # A FRESH ordinal per build. The engine seeds a set's rule order from
                # (user_id, set_index), so this is what stops every set this person builds coming
                # out in the same style order - and what makes 🔁 Again a genuinely new take
                # instead of a cache hit on the identical file. See store.next_set_index.
                set_id = await bot.api.start_set(self.pairs, self.user_id,
                                                 set_index=store.next_set_index(self.owner_id),
                                                 user_name=self.user_name)
                res = await bot.api.wait_for_set(set_id, on_progress=self._on_progress)
                if res.status != "ready":
                    await self._fail(res.message or "That did not come out. Try another pair.")
                    return None
                await bot.api.fetch_set_audio(set_id, wav)
                store.set_pairs(self.number, self._store_pairs(), ref_id=set_id)
                self.ref_id = set_id
                # A set is ONE continuous file. `seam_at` is where each member's crossfade begins,
                # which is what a listener hears as "the next track" - so /skip can move BETWEEN
                # the five instead of only abandoning all of them. Some members legitimately have
                # no seam (no crossfade was created), so the Nones are dropped rather than faked.
                self.seams = [m.get("seam_at") for m in (res.members or [])
                              if isinstance(m, dict) and m.get("seam_at")]
                if self.seams:
                    store.set_seams(self.number, self.seams)
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

    async def run(self, *, first: bool) -> None:
        await self._post_submit_card(first=first)
        rendered = await self._render()
        if rendered is None:
            return
        wav, secs = rendered
        self.audio_path = wav
        self.duration = secs

        clip = await self._attach(wav)
        embed = ui.grind_embed(number=self.number, user=self.interaction.user,
                               pairs=self.named_pairs(), total_secs=secs)
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
        # Remember where the audio lives so it can be re-sent later straight off disk -
        # no re-render, no download, no new file. If the janitor sweeps it, it simply drops out
        # of rotation.
        try:
            store.set_audio_path(self.number, str(wav))
        except Exception:  # noqa: BLE001 - never fail a finished grind over bookkeeping
            log.warning("could not record the audio path for grind #%s", self.number, exc_info=True)
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
# The buttons under a finished grind.
#
# THERE IS NO "ADD ANOTHER PAIR" HERE, deliberately (founder, 2026-08-11). There used to be, and
# it was a lie: the engine cannot stitch a new pair onto something that already exists. Pressing it
# rebuilt the entire set from scratch and swapped the audio out - which, if the grind was playing
# in The Booth at the time, replaced the thing people were listening to.
#
# So the model is honest instead: you choose every pair UP FRONT in the picker, the bot stitches
# them, and what comes back is the finished set. A grind is done when it arrives.
# --------------------------------------------------------------------------------------
class GrindView(discord.ui.View):
    def __init__(self, ctx: GrindContext) -> None:
        super().__init__(timeout=1800)
        self.ctx = ctx

    async def _owner_only(self, interaction: discord.Interaction) -> bool:
        """Anyone may react to and pin a grind. Only its owner may re-roll it."""
        if interaction.user.id == self.ctx.owner_id:
            return True
        await interaction.response.send_message(
            "That is someone else's grind. React to it, pin it, or start your own with `/grind`.",
            ephemeral=True)
        return False

    @discord.ui.button(label="Again", emoji="🔁",
                       style=discord.ButtonStyle.primary, custom_id="again")
    async def again(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Re-roll the same line-up. Every pair stays; what changes is how they are mixed."""
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
# The picker `/grind` opens: beat, vocal, and a + to stack another pair BEFORE building.
#
# Why this exists as well as the + on a finished card (founder, 2026-08-11): stacking pairs
# up front is how you sketch a set on the go, deciding the whole shape before hearing any of
# it. The + on the finished card catches the other impulse - you heard one, it went hard, now
# you want more. Both are real; they happen at different moments.
# --------------------------------------------------------------------------------------
class GrindBuilderView(discord.ui.View):
    def __init__(self, user_id: int) -> None:
        super().__init__(timeout=600)
        self.owner_id = user_id
        self.pairs: list[tuple[str, str]] = []
        self.sel_beat: str | None = None
        self.sel_vocal: str | None = None
        # WHICH VOCALS ARE SHOWN. The catalog is 14 Bollywood vocals to 4 English ones, so a
        # listener who does not know Hindi opened the picker and met a wall of unfamiliar names.
        # Defaults to English (founder's call) and is a TOGGLE, not a one-time setting - nothing
        # is hidden forever, and the cross-language pairs that make the best mixes stay one tap
        # away. Beats are never filtered: they are instrumental and belong to neither audience.
        self.language = DEFAULT_LANGUAGE

        self.beat_select = discord.ui.Select(placeholder="Pick a beat...", row=1,
                                             options=self._opts(bot.beats, None))
        self.beat_select.callback = self._on_beat
        self.vocal_select = discord.ui.Select(placeholder="Pick a vocal...", row=2,
                                              options=self._opts(self._vocals(), None))
        self.vocal_select.callback = self._on_vocal
        self.add_item(self.beat_select)
        self.add_item(self.vocal_select)
        self.lang_select = discord.ui.Select(placeholder="Vocals: English", row=0, options=[
            discord.SelectOption(label=LANGUAGES[k], value=k, default=(k == self.language))
            for k in LANGUAGES])
        self.lang_select.callback = self._on_language
        self.add_item(self.lang_select)
        # Consistent from birth: everything starts greyed out because nothing is picked yet.
        # Done here rather than at the call site so no future caller can forget it and ship a
        # picker whose buttons all look available before they can do anything.
        self.sync_buttons()

    @staticmethod
    def _opts(songs, selected_id):
        return [discord.SelectOption(label=lbl, value=val, default=dflt)
                for lbl, val, dflt in select_option_specs(songs, selected_id)]

    def _vocals(self):
        """The vocals this person should see. Falls back to the whole list if a language somehow
        matches nothing, because an empty dropdown is worse than an unfiltered one."""
        # getattr, not s.language: the bot talks to the engine over HTTP, and an engine that
        # predates the language field simply will not send one. A missing tag must mean "unknown",
        # never a crashed picker.
        picked = [s for s in bot.vocals if (getattr(s, "language", "") or "") == self.language]
        return picked or bot.vocals

    def set_language(self, lang: str) -> None:
        """Switch which vocals are shown. Deliberately PURE of Discord so it can be tested without
        faking an interaction - the callback below does the plumbing, this does the thinking."""
        self.language = lang if lang in LANGUAGES else DEFAULT_LANGUAGE
        # A vocal chosen in the OTHER language is dropped. Leaving it selected would show a picker
        # whose own choice is missing from its list, and Grind it would build something the person
        # can no longer see.
        if self.sel_vocal and self.sel_vocal not in {s.id for s in self._vocals()}:
            self.sel_vocal = None
        self.lang_select.placeholder = f"Vocals: {LANGUAGES[self.language]}"
        self._refresh_options()
        self.sync_buttons()

    async def _on_language(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        self.set_language(self.lang_select.values[0])
        await interaction.response.edit_message(embed=self.embed(), view=self)

    def _refresh_options(self) -> None:
        # NOT _refresh: discord.ui.View owns that name and calls it with the message components.
        self.beat_select.options = self._opts(bot.beats, self.sel_beat)
        self.vocal_select.options = self._opts(self._vocals(), self.sel_vocal)
        for o in self.lang_select.options:
            o.default = (o.value == self.language)

    def _staged(self) -> list[tuple[str, str]]:
        """Everything that would be built right now, including a pair that is picked but not yet
        added. Hitting Grind it with a pair sitting in the dropdowns should just work rather than
        silently dropping it."""
        out = list(self.pairs)
        if self.sel_beat and self.sel_vocal:
            out.append((self.sel_beat, self.sel_vocal))
        return out

    def sync_buttons(self) -> None:
        """Grey out anything that cannot do its job yet.

        This is the instruction. A newcomer looking at three equally-available buttons has to guess
        the order of operations; a greyed-out button tells them without a word. Add is dead until a
        pair is picked, Remove is dead with nothing stacked, and Grind is dead with nothing to grind.
        """
        picked = bool(self.sel_beat and self.sel_vocal)
        room = len(self.pairs) < MAX_PAIRS_PER_GRIND
        for item in self.children:
            label = getattr(item, "label", None)
            if label == "Add another pair":
                item.disabled = not (picked and room)
            elif label == "Remove the last one":
                item.disabled = not self.pairs
            elif label == "Grind it":
                item.disabled = not self._staged()

    def embed(self) -> discord.Embed:
        """Say what will HAPPEN, not what the buttons are called.

        The first version described its own mechanics ("nothing stacked yet", "Add another to stack
        more") and never once said that several pairs come back as a single continuous set. Nobody
        can guess an outcome, so it goes on the screen, and it changes as the set grows.
        """
        staged = self._staged()
        lines = [f"`{i}`  **{_name_of(a)}**  ✕  **{_name_of(b)}**"
                 for i, (a, b) in enumerate(self.pairs, 1)]
        if self.sel_beat and self.sel_vocal:
            lines.append(f"`{len(self.pairs) + 1}`  **{_name_of(self.sel_beat)}**  ✕  "
                         f"**{_name_of(self.sel_vocal)}**")
        elif self.sel_beat or self.sel_vocal:
            b = f"**{_name_of(self.sel_beat)}**" if self.sel_beat else "_still need a beat_"
            v = f"**{_name_of(self.sel_vocal)}**" if self.sel_vocal else "_still need a vocal_"
            lines.append(f"　　{b}  ✕  {v}")

        if not staged:
            body = ("Pick a **beat** and a **vocal** below. That makes one track.\n\n"
                    "Want a longer one? Add up to 5 pairs and they play **back to back as one "
                    "continuous set**.")
        elif len(staged) == 1:
            body = ("\n".join(lines) + "\n\n"
                    "**Grind it** makes just this one.\n"
                    "**Add another pair** and they play back to back as one continuous set.")
        else:
            body = ("\n".join(lines) + "\n\n"
                    f"These {len(staged)} play **back to back as one continuous set**.  "
                    f"{len(staged)} of {MAX_PAIRS_PER_GRIND}.")

        return discord.Embed(title="⚙️  What are we grinding?", description=body, color=ui.ACCENT)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "That is someone else's. Type `/grind` to start your own.", ephemeral=True)
        return False

    async def _on_beat(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        self.sel_beat = self.beat_select.values[0]
        self._refresh_options()
        self.sync_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def _on_vocal(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        self.sel_vocal = self.vocal_select.values[0]
        self._refresh_options()
        self.sync_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Add another pair", emoji="➕",
                       style=discord.ButtonStyle.secondary, row=3)
    async def add_another(self, interaction: discord.Interaction,
                          button: discord.ui.Button) -> None:
        if not await self._guard(interaction):
            return
        if not (self.sel_beat and self.sel_vocal):
            await interaction.response.send_message("Pick a beat and a vocal first.",
                                                    ephemeral=True)
            return
        if len(self.pairs) >= MAX_PAIRS_PER_GRIND:
            await interaction.response.send_message(
                f"That is the limit, {MAX_PAIRS_PER_GRIND}. Hit **Grind it**.", ephemeral=True)
            return
        self.pairs.append((self.sel_beat, self.sel_vocal))
        self.sel_beat = self.sel_vocal = None
        self._refresh_options()
        self.sync_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Remove the last one", emoji="↩️",
                       style=discord.ButtonStyle.secondary, row=3)
    async def undo(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._guard(interaction):
            return
        if self.pairs:
            self.pairs.pop()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Grind it", emoji="⚙️",
                       style=discord.ButtonStyle.primary, row=3)
    async def go(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._guard(interaction):
            return
        pairs = self._staged()
        if not pairs:
            await interaction.response.send_message("Pick a beat and a vocal first.",
                                                    ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)      # freeze the picker
        await GrindContext(interaction, pairs[:MAX_PAIRS_PER_GRIND]).run(first=True)
        self.stop()


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


def _is_showcase(channel) -> bool:
    """The pinned-mixes wall (`#best-mixes`). Identified by its configured id, never by name."""
    return (CFG.fresh_grinds_channel_id is not None
            and getattr(channel, "id", None) == CFG.fresh_grinds_channel_id)


def _grinding_allowed_here(interaction: discord.Interaction) -> str | None:
    """None if `/grind` may run here, otherwise the sentence to send back.

    Grinding is confined to the grind category on purpose (founder, 2026-08-11). The whole point is
    that generation happens in public, in the same few channels, where people scroll past what
    everyone else is throwing together. Allowed anywhere, it scatters across the server and nobody
    sees anyone else's - at which point being in a server buys you nothing over using the app alone.

    Sitting in one of the listening rooms also counts, because Discord treats a voice channel's
    built-in chat as its own channel and somebody in a room should not have to leave it to grind.
    """
    if not CFG.grind_category_id:
        return None                     # not configured: allow everywhere rather than block everything

    # ...EXCEPT the showcase. #best-mixes shares the grind category but is the opposite kind of room:
    # a wall of finished work people scroll, not a workbench. Grinding into it buries the showcase
    # under half-built attempts, which is the one thing it exists not to be. Founder, 2026-08-14:
    # /grind belongs in #get-shit-done and the listening rooms. Keyed off the configured showcase id,
    # never a channel name, so renaming the room cannot quietly re-open it.

    channel = interaction.channel
    cat_id = getattr(getattr(channel, "category", None), "id", None) \
        or getattr(channel, "category_id", None)
    if cat_id == CFG.grind_category_id and not _is_showcase(channel):
        return None
    if booth.room_of(interaction.user) is not None:
        return None                     # they are in a listening room; let them grind from there

    guild = interaction.guild
    allowed = []
    if guild is not None:
        allowed = [f"<#{c.id}>" for c in guild.text_channels
                   if (getattr(getattr(c, "category", None), "id", None)
                       or getattr(c, "category_id", None)) == CFG.grind_category_id
                   and not _is_showcase(c)]
    where = " or ".join(allowed) if allowed else "the grind channels"
    return (f"Not here. Everyone grinds in {where}, out in the open, so you can see what other "
            f"people are throwing together.\n"
            f"You can also grind from inside a listening room while the music is on.")


@bot.tree.command(name="grind", description="Throw two songs in the grinder and find out.")
async def grind_cmd(interaction: discord.Interaction) -> None:
    """No options at all, on purpose. `/grind` used to offer `beat` and `vocal` as optional fields,
    and a first-timer reading two blanks cannot tell that leaving them empty is the right move -
    they look like something you have to fill in. Type it, press enter, the picker opens."""
    # WHO, before WHERE. The door is the founder's rule that only approved people use the bot, and
    # channel permissions alone cannot carry it: one wrongly-set overwrite, or simply no grind
    # category configured, and an unapproved person can grind from the lobby.
    blocked = door.blocked_reason(interaction)
    if blocked is not None:
        await interaction.response.send_message(blocked, ephemeral=True)
        return
    where = _grinding_allowed_here(interaction)
    if where is not None:
        await interaction.response.send_message(where, ephemeral=True)
        return
    if not bot.songs:
        await bot.refresh_catalog()
    if not bot.beats or not bot.vocals:
        await interaction.response.send_message(
            "The song library has not loaded. Make sure the engine is running, then try again.",
            ephemeral=True)
        return
    view = GrindBuilderView(interaction.user.id)
    await interaction.response.send_message(embed=view.embed(), view=view)


# HIDDEN, not merely refused. The check inside runs only AFTER somebody picks the command, so an
# ordinary member still saw it sitting in the picker and learned the server has a back door - the
# founder spotted exactly that from a test account on 2026-08-14. `default_permissions` makes
# DISCORD hide it from anyone without Manage Server, which is the same treatment /setup already has.
# The in-body check STAYS: default_permissions is a display rule a server admin can override, so it
# is the wrong thing to trust on its own.
@bot.tree.command(name="invitefriend",
                  description="A one-use link that lets somebody in without the form.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def invitefriend_cmd(interaction: discord.Interaction) -> None:
    """For people the founder already knows. Their friend clicks the link and is in - no
    lobby, no five questions, no waiting.

    Single use, because a vouch is for one named person; a link that keeps working is a hole
    in the door that widens every time it is forwarded."""
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(
            "That one is for whoever runs the server.", ephemeral=True)
        return
    if not door.is_open():
        await interaction.response.send_message(
            "The door is not switched on, so there is nothing to skip - anybody with an "
            "ordinary invite can already get in.", ephemeral=True)
        return
    # The link is made against the channel the friend will LAND IN and stay in, not against the
    # lobby. Pointing it at the lobby was the 2026-08-15 bug: they landed in #the-door, the bot
    # granted @Member, @Member is denied the lobby, and their client went on reopening a channel
    # that had vanished from their sidebar. `arrival_channel` answers this by permission, so it can
    # never pick a room they are about to lose; None means it could not be answered, and the old
    # behaviour stands.
    channel = (door.arrival_channel(interaction.guild)
               or interaction.guild.get_channel(CFG.door_channel_id)
               or interaction.channel)
    await interaction.response.defer(ephemeral=True)   # creating an invite is an API call
    url = await door.create_vouch_invite(channel, interaction.user.id)
    if url is None:
        await interaction.followup.send(
            "I could not make an invite. I need the Create Invite permission on that "
            "channel.", ephemeral=True)
        return
    await interaction.followup.send(
        f"Send this to your friend. One use, good for a week, and they walk straight in "
        f"without the form:{chr(10)}{url}", ephemeral=True)


@bot.tree.command(name="applications",
                  description="Read who is waiting to join. Add a word to narrow it down.")
@app_commands.default_permissions(manage_guild=True)   # hidden from members — see /invitefriend
@app_commands.guild_only()
@app_commands.describe(contains="Only show applications mentioning this word, e.g. suno")
async def applications_cmd(interaction: discord.Interaction, contains: str = "") -> None:
    """The POOL, not a feed. The founder is choosing the first fifty, so the applications have to
    be readable side by side - a card that arrives, is decided and scrolls away is
    first-come-first-served wearing a review flow.

    `contains` is a plain substring search over the answers. It is a filing cabinet, never a
    judgement: Grinder does not rank, score or recommend an applicant."""
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(
            "That one is for whoever runs the server.", ephemeral=True)
        return
    rows = store.pending_applications(contains or None)
    # Real members, not form approvals - free arrivals under `door.OPEN_BELOW` and vouched friends
    # are seats too, and counting only the form would report "2 of 50" with 30 people in the room.
    taken = door.community_count(interaction.guild)
    if not rows:
        note = (f"Nobody waiting who mentions {contains!r}." if contains
                else "Nobody is waiting.")
        await interaction.response.send_message(
            f"{note}  ({taken} of {door.MEMBER_CAP} seats taken)", ephemeral=True)
        return
    shown = rows[:5]      # five embeds is Discord's per-message limit
    embeds = [door.application_embed(
        user_name=r["user_name"] or str(r["user_id"]), user_id=r["user_id"],
        answers=json.loads(r["answers"]), taken=taken) for r in shown]
    more = ("" if len(rows) <= len(shown)
            else f"\nShowing {len(shown)} of {len(rows)}. Narrow it with a word.")
    await interaction.response.send_message(
        f"{len(rows)} waiting  ({taken} of {door.MEMBER_CAP} seats taken){more}",
        embeds=embeds, ephemeral=True)


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


@bot.tree.command(name="play", description="Start the music in your listening room, or pick up where you stopped.")
async def play_cmd(interaction: discord.Interaction) -> None:
    """The command that was missing. Before this, the ONLY way to get Grinder into a room was to
    finish a grind while sitting in one - somebody who just wanted music had nothing to type.

    DEFER FIRST. Discord kills an interaction that has not been acknowledged within 3 SECONDS, and
    /play may have to open a voice connection (a real handshake, seconds) and ask the engine for a
    set's boundaries. Observed live on 2026-08-12: "The application did not respond", while /skip
    beside it succeeded - because /skip runs when the bot is ALREADY connected and never pays that
    cost."""
    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send(await booth.play(interaction.user), ephemeral=True)


@bot.tree.command(name="skip", description="Skip to the next track in your listening room.")
async def skip_cmd(interaction: discord.Interaction) -> None:
    """ANYONE IN THE ROOM MAY SKIP (founder decision 2026-08-12).

    Deliberately not owner-only: a bad mix whose owner has wandered off would otherwise hold the
    room hostage for three minutes. Deliberately not a skip-vote either - fair in a big room,
    faintly silly when there are two people in it, and this is a validation-scale community where
    social pressure works better than machinery.

    Ephemeral, so skipping does not litter the channel with notices. Deferred for the same reason
    as /play: a seek re-opens the audio stream and may first ask the engine for the set's
    boundaries, which can outrun Discord's 3-second acknowledgement window.
    """
    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send(await booth.skip(interaction.user), ephemeral=True)


@bot.tree.command(name="stop", description="Stop the music in your listening room.")
async def stop_cmd(interaction: discord.Interaction) -> None:
    """Stop means stop: the room falls quiet and stays quiet. Nothing starts it again by itself -
    the next /grind, or /play to pick up exactly where you stopped."""
    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send(
        await booth.stop_playback(interaction.user), ephemeral=True)


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
async def on_member_join(member: discord.Member) -> None:
    """Somebody arrived. If the founder vouched for them, they skip the form entirely.

    Everybody else is deliberately left alone - they land in the lobby and see the door, which
    is what the gate is for. This handler only ever ADDS access, never removes it.

    Never fatal: a vouch that cannot be worked out sends somebody to the lobby, which is the
    safe direction to be wrong in - a stranger let in by mistake is the failure that matters."""
    try:
        await door.on_member_join(member)
    except Exception:  # noqa: BLE001 - an arrival must never crash the bot
        log.warning("could not check whether %s was vouched for", member, exc_info=True)


@bot.event
async def on_voice_state_update(member, before, after) -> None:
    await booth.on_voice_state_update(member, before, after)


@bot.tree.command(name="help", description="What Grinder does and how to use it.")
async def help_cmd(interaction: discord.Interaction) -> None:
    """The "Remix anything." banner, not the wordmark disc - the same image #read-this-first uses,
    so a newcomer sees one identity rather than two. Rooms are passed in as real channels so they
    render as live links that survive a rename."""
    name = "remix-banner.jpg"
    files = ([discord.File(brand.REMIX_BANNER, filename=name)]
             if brand.image_bytes(brand.REMIX_BANNER) is not None else [])
    await interaction.response.send_message(
        embed=ui.help_embed(rooms=booth.rooms(interaction.guild),
                            banner_name=name if files else None),
        files=files, ephemeral=True)


async def _lookup_seams(set_id: str) -> list:
    """Where each member of a set starts, straight from the engine.

    THE BUG THIS FIXES: seams only began being WRITTEN on 2026-08-12, so every set made before
    that had none, and /skip on one silently degraded to "stop" - which is exactly what the
    founder hit ("it just pauses"). The engine has always known them, so ask rather than depend on
    when a grind happened to be made. The booth caches the answer back into its own store, so this
    is one call per set, ever.
    """
    res = await bot.api.set_status(set_id)
    return [m.get("seam_at") for m in (res.members or [])
            if isinstance(m, dict) and m.get("seam_at")]


booth.seam_lookup = _lookup_seams


def configured_channel_ids() -> dict:
    """The ids the bot already works from, handed to setup so the copy links to the rooms as the
    founder has named them rather than to the names the plan happens to use."""
    return {"grind": CFG.grinder_channel_id, "showcase": CFG.fresh_grinds_channel_id}


# ADMINS ONLY, AND HIDDEN FROM EVERYONE ELSE (founder-reported 2026-08-12: "remove /setup from the
# user interface, otherwise users will play with it"). `default_permissions` makes Discord itself
# omit the command from the picker for members without the permission - it is not merely a check
# that fires after they run it, so ordinary members never see it exists. `guild_only` because it
# restructures a server and is meaningless in a DM.
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
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
        report = await server_setup.run(interaction.guild, refresh_branding=refresh_branding,
                                        ids=configured_channel_ids())
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
