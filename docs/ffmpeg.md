# FFmpeg — pinned build & licensing position

_The audio engine shells out to FFmpeg for decode, time-stretch (`atempo`), the vocal-chain
filtergraph (de-ess / high-pass / compress / presence EQ), and pitch (`rubberband`). Two things about
that binary are load-bearing: its **exact version** (the golden-file byte-identity guarantee rests on
it) and its **licence** (GPL vs LGPL). Both are recorded here._

## Pinned version

The golden-file test (`services/api/tests/test_render.py::test_golden_enabled_false_is_byte_identical_to_m6_0`)
proves the disabled render is byte-identical to the `m6.0` baseline. That guarantee only holds against
the **exact FFmpeg build the hash was captured on**. Different versions / build flags / platforms can
produce subtly different audio and silently break the gate.

- **Pinned version:** `8.1.1` (`workers/ffmpeg_pin.py::PINNED_FFMPEG_VERSION`).
- **Full build string** (dev machine, 2026-07-10), captured via `ffmpeg -version`:

```
ffmpeg version 8.1.1-full_build-www.gyan.dev  (gyan.dev Windows full build)
configuration: --enable-gpl --enable-version3 --enable-static ... --enable-librubberband ...
  (GPL build: --enable-gpl + --enable-librubberband present)
```

- **Enforcement:** `test_ffmpeg_is_the_pinned_version` fails loudly if the running FFmpeg's version
  doesn't match the pin — so a binary drift is surfaced as itself, not misread as a code regression.
- **To change FFmpeg:** bump `PINNED_FFMPEG_VERSION` **only** together with a deliberate re-capture of
  the golden hash on the new binary (and confirm the byte change is intended, not a surprise).
- **Prod:** pin the same version wherever prod resolves FFmpeg (Dockerfile / image / lockfile) when
  that environment is stood up.

## Licensing — current position and exit plan

**We ship a GPL FFmpeg build** (`--enable-gpl --enable-librubberband`).

**This is safe while Merry Go is server-side only.** GPL obligations trigger on **distribution**, not
use. Our users receive **audio**, never the binary. We are _users_ of GPL software, not distributors —
the position most web/SaaS companies deliberately occupy. At MVP scale (50–100 users, a server-side
web platform) there is **no exposure** — and this was a deliberate founder decision (2026-07-10): keep
pitch, which is the highest-value Phase-0 feature (it's what makes a Bollywood vocal sit on a house
bed, and what powers Slice 2d's repair of key-clashing pairs). _None of us are lawyers; this is the
engineering position, not legal advice._

**This becomes a real problem the day we ship anything that runs on a customer's machine** — a desktop
app, a mobile app that renders on-device, a Docker image handed to customers, or any move of rendering
onto the user's device. Any of those is **distribution**.

**The exit is small and known.** Only **stage 3 (pitch shift)** depends on GPL: it needs
`librubberband`, which forces `--enable-gpl`, which makes the whole binary GPL. Stages **1, 2, 5, 7**
(de-ess, high-pass, compress, presence EQ) are **core LGPL filters** and survive an LGPL rebuild
untouched. So an LGPL rebuild costs us pitch and nothing else.

**When the day comes:**

1. Swap stage 3 to **Signalsmith Stretch** (MIT, formant-aware — the cleanest option on paper).
   Prototype it before paying for a commercial engine.
2. Rebuild FFmpeg as LGPL (drop `--enable-librubberband` and the other GPL components).
3. Alternatives if Signalsmith doesn't hold up: **Rubber Band commercial licence**, or **zplane
   élastique** (paid, industry standard). **SoundTouch is LGPL but has no formant preservation →
   chipmunk voices → not an option.**
4. **Get legal counsel before that day, not on it.** The swap is a ~two-day job with three months'
   notice, and a crisis with three days'.

The pitch tests carry a `skipif` (no `rubberband` → skip), so the dependency isn't silently cemented
deeper. **Do not raise the GPL question again unless the roadmap adds on-device rendering or a shipped
binary.**
