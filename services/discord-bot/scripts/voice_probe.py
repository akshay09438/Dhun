"""Can Grinder make a sound in a listening room on THIS machine? One straight answer.

WHY THIS EXISTS. Voice has been recorded as "dead on Windows ARM64" since 2026-08-11, which
makes every listening room a silent room - people can join, and nothing will ever play. The
diagnosis at the time was discord.py 2.5.x speaking a retired voice protocol (close code 4017),
and 2.6+ needing `davey`, which has no win-arm64 wheel.

Two things may have changed since, and neither had been tested:
  1. discord.py here is now 2.7.1, not 2.5.x.
  2. `davey` is only strictly required for E2EE voice. Without it discord.py sets
     `has_dave = False` and advertises DAVE protocol version 0; the RuntimeError only fires
     if Discord INSISTS on a version above 0. Whether it insists is a question about
     Discord's servers, and no amount of reading the code answers it.

So this connects for real, plays three seconds of a test tone into a listening room, and prints
what happened. READ-ONLY toward the community: it posts nothing, messages nobody, and changes no
server setting. It joins a voice channel, makes a noise, and leaves.

Run:  services/discord-bot/.venv/Scripts/python.exe scripts/voice_probe.py
"""
from __future__ import annotations

import asyncio
import math
import struct
import sys
import tempfile
import traceback
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discord                                                    # noqa: E402
from botconfig import load_config                                 # noqa: E402

CFG = load_config()
SECONDS = 3.0
TIMEOUT = 90.0


def _tone(path: Path) -> Path:
    """A short 440 Hz tone. Generated rather than reusing a mix, so this measures the voice path
    and nothing else - a decode problem would otherwise look like a voice problem."""
    sr, frames = 48000, []
    for i in range(int(sr * SECONDS)):
        frames.append(struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440.0 * i / sr))))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"".join(frames))
    return path


def _report(ok: bool, headline: str, detail: str = "") -> None:
    print(f"\n{'=' * 74}\n{'WORKS' if ok else 'DOES NOT WORK'}: {headline}\n{'=' * 74}")
    if detail:
        print(detail)


async def main() -> int:
    try:
        import davey  # noqa: F401
        print("davey: present")
    except ImportError:
        print("davey: MISSING (so E2EE voice is unavailable; DAVE version advertised as 0)")
    print(f"discord.py: {discord.__version__}")

    intents = discord.Intents.default()
    intents.voice_states = True
    client = discord.Client(intents=intents)
    outcome: dict = {"ok": False, "headline": "never reached the room", "detail": ""}
    wav = _tone(Path(tempfile.gettempdir()) / "voice_probe.wav")

    @client.event
    async def on_ready() -> None:
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

            print(f"joining #{room.name} in {room.guild.name} ...")
            vc = await asyncio.wait_for(room.connect(), timeout=30)
            print(f"connected. endpoint mode: {getattr(vc, 'mode', '?')}")

            done = asyncio.Event()
            vc.play(discord.FFmpegPCMAudio(str(wav)), after=lambda _e: done.set())
            await asyncio.wait_for(done.wait(), timeout=30)
            print("playback finished with no error")
            await vc.disconnect(force=True)
            outcome.update(ok=True, headline="Grinder connected and played audio into a room",
                           detail=f"room: #{room.name}   discord.py {discord.__version__}   "
                                  f"davey: {'present' if 'davey' in sys.modules else 'missing'}")
        except Exception as e:  # noqa: BLE001 - the whole point is to capture whatever it is
            outcome.update(headline=f"{type(e).__name__}: {e}", detail=traceback.format_exc())
        finally:
            await client.close()

    try:
        await asyncio.wait_for(client.start(CFG.token), timeout=TIMEOUT)
    except asyncio.TimeoutError:
        outcome.update(headline="timed out - the voice handshake never completed")
    except Exception as e:  # noqa: BLE001
        outcome.update(headline=f"login failed: {type(e).__name__}: {e}")
    finally:
        if not client.is_closed():
            await client.close()

    _report(outcome["ok"], outcome["headline"], outcome["detail"])
    return 0 if outcome["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
