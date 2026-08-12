"""Does a REAL MIX play through the REAL playback function? The gap the tone probe left open.

WHY THIS EXISTS. `voice_probe.py` proved the voice PATH works on this machine: it connected to a
room and streamed a generated 440 Hz tone. That was the right thing to prove first - a synthetic
tone measures the voice path and nothing else, so a decode problem cannot masquerade as a voice
problem.

But it left three things untested, and all three sit between "voice works" and "a listening room
works":

  1. It called `channel.connect()` + `vc.play(...)` by hand. The Booth does NOT do that - it calls
     `voice_player.play_in`, which additionally handles an existing voice client, moves rooms, and
     stops whatever is already playing. That function has never run against Discord.
  2. It played a generated tone. A real mix is a long 48 kHz stereo WAV off disk, decoded by
     ffmpeg. Different code, different failure modes.
  3. It never exercised `on_finished`. `play_in` hands discord.py an `after=` callback that fires
     on a WORKER THREAD and hops back to the event loop via `run_coroutine_threadsafe`. That hop is
     what makes the room play the NEXT grind instead of going quiet forever with the bot sitting in
     it. It is also the single most race-prone line in the file, and it has never fired for real.

So: take a real finished mix, cut a short excerpt (so this takes seconds, not four minutes), and
push it through `play_in` exactly as `booth.py:127` does - callback and all.

READ-ONLY toward the community: posts nothing, messages nobody, changes no server setting. It
joins a listening room, plays a few seconds of real music, and leaves.

Run:  services/discord-bot/.venv-x64/Scripts/python.exe scripts/booth_playback_probe.py
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discord                                                    # noqa: E402
import voice_player                                               # noqa: E402
from botconfig import load_config                                 # noqa: E402

CFG = load_config()
EXCERPT_SECONDS = 12.0
TIMEOUT = 120.0
DATA_DIR = Path(__file__).resolve().parents[3] / "services" / "api" / "data"


def _newest_real_mix() -> Path | None:
    """The most recent finished mix. Prefers `.bestparts.wav` - that is what a grind actually
    ships to a room, so it is the file whose decode we care about."""
    candidates = sorted(DATA_DIR.glob("*.bestparts.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        candidates = sorted(DATA_DIR.glob("*.mix.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _excerpt(src: Path, dst: Path) -> Path:
    """A short slice of the real mix, taken 30s in so it lands in actual music rather than a
    fade-in. Re-encoded by ffmpeg, which is the same decoder discord.py will use."""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", "30", "-t", str(EXCERPT_SECONDS),
         "-i", str(src), str(dst)],
        check=True,
    )
    return dst


def _report(ok: bool, headline: str, detail: str = "") -> None:
    print(f"\n{'=' * 74}\n{'WORKS' if ok else 'DOES NOT WORK'}: {headline}\n{'=' * 74}")
    if detail:
        print(detail)


async def main() -> int:
    print(f"voice_supported(): {voice_player.voice_supported()}")
    reason = voice_player.voice_unavailable_reason()
    if reason:
        _report(False, "the voice gate says no before we even connect", reason)
        return 1

    src = _newest_real_mix()
    if src is None:
        _report(False, "no finished mix on disk to play", f"looked in {DATA_DIR}")
        return 1
    print(f"real mix: {src.name}  ({src.stat().st_size / 1e6:.1f} MB)")

    clip = _excerpt(src, Path(tempfile.gettempdir()) / "booth_probe_excerpt.wav")
    print(f"excerpt:  {EXCERPT_SECONDS:.0f}s cut from 0:30")

    intents = discord.Intents.default()
    intents.voice_states = True
    client = discord.Client(intents=intents)
    outcome: dict = {"ok": False, "headline": "never reached the room", "detail": ""}

    @client.event
    async def on_ready() -> None:
        vc = None
        try:
            room = None
            for guild in client.guilds:
                for ch in guild.voice_channels:
                    cat_id = getattr(getattr(ch, "category", None), "id", None)
                    if not CFG.rooms_category_id or cat_id == CFG.rooms_category_id:
                        room = ch
                        break
                if room:
                    break
            if room is None:
                outcome.update(headline="no listening room found to test in")
                return

            # THE POINT OF THIS PROBE: the same call booth.py makes, callback and all.
            finished = asyncio.Event()

            async def _on_finished() -> None:
                # If this never runs, a room plays one grind and then goes silent forever.
                finished.set()

            print(f"joining #{room.name} in {room.guild.name} ...")
            await asyncio.wait_for(
                voice_player.play_in(room, clip, on_finished=_on_finished), timeout=45
            )
            vc = room.guild.voice_client
            print(f"play_in returned. encryption mode: {getattr(vc, 'mode', '?')}")
            print(f"is_playing(): {vc.is_playing() if vc else '?'}")

            await asyncio.wait_for(finished.wait(), timeout=EXCERPT_SECONDS + 30)
            print("on_finished FIRED - the room would advance to the next grind")

            await vc.disconnect(force=True)
            outcome.update(
                ok=True,
                headline="a real mix played through the real playback function, and the finish callback fired",
                detail=(f"room: #{room.name}\nmix:  {src.name}\n"
                        f"path: voice_player.play_in (the same call as booth.py:127)\n"
                        f"mode: {getattr(vc, 'mode', '?')}"),
            )
        except asyncio.TimeoutError:
            outcome.update(
                headline="timed out - audio started but the finish callback never fired"
                         if vc is not None else "timed out before playback started",
                detail="If playback started but on_finished never ran, the bug is the "
                       "run_coroutine_threadsafe hop in voice_player.play_in - a room would play "
                       "one grind and then stay silent with the bot still sitting in it.",
            )
        except Exception as e:  # noqa: BLE001 - capturing whatever it is IS the job
            outcome.update(headline=f"{type(e).__name__}: {e}", detail=traceback.format_exc())
        finally:
            try:
                if vc is not None and vc.is_connected():
                    await vc.disconnect(force=True)
            except Exception:  # noqa: BLE001 - best effort; never mask the real outcome
                pass
            await client.close()

    try:
        await asyncio.wait_for(client.start(CFG.token), timeout=TIMEOUT)
    except asyncio.TimeoutError:
        outcome.update(headline="timed out - never finished")
    except Exception as e:  # noqa: BLE001
        outcome.update(headline=f"login failed: {type(e).__name__}: {e}")
    finally:
        if not client.is_closed():
            await client.close()

    _report(outcome["ok"], outcome["headline"], outcome["detail"])
    return 0 if outcome["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
