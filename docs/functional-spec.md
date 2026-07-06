# Prompt-DJ — Functional Spec (V1)

_What the app does, for the user, screen by screen. Approved during discovery on 2026-07-05. This is a living document — kept true to the code. The "how it's built" lives in [technical-spec.md](technical-spec.md); progress lives in [implementation-plan.md](implementation-plan.md)._

## What the app does TODAY (as of 2026-07-06, M1–M3 built; M4 complete)

Upload two songs → each is cleaned to a standard format/volume and playable back. Per song, two on-demand actions: **"Split into parts"** (hear the vocals / drums / bass / other separately — cloud AI, ~30–120s first time, instant after) and **"Analyze track"** (see BPM, the Camelot key, and a colored section-structure timeline — the DJ's read of the song). Once both songs are split and analyzed, **"Make my mix"** produces a **full DJ arrangement** — Song 1's beat running throughout, with Song 2's vocal **weaving in and out across the WHOLE song as an energy arc** (an instrumental intro, then a vocal moment in each third — early, middle, and a strong entry saved for near the end — with beat-only stretches between), tempo-locked, on the beat and click-free, with a real one-bar **beat-breath** and one subtle **filter sweep** before a big entry, and — for contrast — **Song 1's own vocal answering in a gap** so the two songs trade (never two voices at once). The vocal no longer clusters in the middle of a long song; it spans the track and finishes strong. On a song with shaky analysis it automatically plays safer (fewer moves). The mix screen **shows the arrangement** (a two-lane timeline: where each song's vocal is, in distinct colors), and **"Give me another take"** (Regenerate) produces a different valid arrangement; **Download** saves the WAV. (Live steering now plays the **whole mix** — the mix screen's **live player** plays Song 1's beat/bass/melody **and** Song 2's arranged vocal together, and you reshape it live: tap any of the four parts — **Beat · Bass · Melody · Vocals** — or type a command ("take the bass out", "remove the vocals", **"drop everything but the beat"**, "bring it all back"), and it lands **on the next beat** with a smooth fade, replying in DJ language. As the mix plays, the live player also shows **1–3 AI suggestion chips that change with the part of the song** (e.g. "Bring the vocal in", "Drop to just the beat", "Fade it out") — tap one and it happens on the beat; and **"fade away"** fades the whole mix out. The suggestions are worked out **once per mix** by the AI (with a sensible built-in fallback if the AI's unavailable), and your own taps/commands stay predictable (M5 Slices 1–3). In the live player the **Vocals part is Song 2's _continuous_ vocal** (tempo-matched), so you can bring it in/out **anywhere Song 2 sings** — for as long as Song 2's vocal lasts (it's shorter than the mix, so it can't cover the tail). The live player also has a **"Beat up"** energy move — tap it (or type "beat up") and the melody + vocals duck so the drums & bass drive the track (the beat takes over), on the next beat; "bring it all back" restores the full mix. The live player is a steerable _approximation_; the **Download stays the polished master** (it keeps the arranged vocal arc, the filter sweep, and the beat-breath). Still to come: final mastering and short-clip export. **Making a mix is now one click:** drop two songs → **Make my mix** → a "Studying your songs" screen splits and analyzes both automatically (an honest checklist: splitting the parts, finding the beat, planning the arrangement) → the finished mix. The old manual per-song **Split**/**Analyze** buttons are gone. **The whole app now wears its final look — the "Electric Violet" design (grey + one violet accent, Instrument Serif + Space Mono) laid out as four distinct screens (Setup → Generating → Play & Steer → Export) in a console/stage split**, and every mix gets a **playful AI-generated name** (e.g. "Ocean Bina") instead of "Untitled Mix". Still to build: the 14-second shareable clip export and final mastering (M6).) The sections below describe the full V1 target.

## The core value, in one sentence

A person who can't DJ uploads two songs, and gets back a mix that sounds like a real DJ made it — then reshapes it with plain words.

## Who it's for

Casual music fans and creators who can't DJ but want to make good-sounding mashups to share or enjoy. First target slice: people making short mashup clips for TikTok / Reels / for fun.

## The V1 decisions (frozen)

| Decision                | V1 choice                                                                  |
| ----------------------- | -------------------------------------------------------------------------- |
| Who it's for            | Casual creators / fans                                                     |
| Song source             | **Uploads only** ("search any song" is the V2 north star)                  |
| Core loop               | Upload 2 songs → DJ-style mix → steer / regenerate → export                |
| Feature 2               | Lean live commands **+ regenerate**; energy moves only                     |
| Live tempo (BPM) change | **V2 stretch goal** (energy-up is V1; changing song speed live is later)   |
| Music                   | Western + Indian (Indian pairs need extra hand-checking — weaker analysis) |
| Success bar             | ~50 real casual creators clearly feel "I made a real mix by describing it" |

## The two features (frozen scope)

1. **The Mix (offline):** two uploads — Song 1 (beat) + Song 2 (vocals) — become one finished, continuous track with Song 2's vocals arranged _like a DJ_ over Song 1's instrumental (vocals enter on drops/choruses, the beat sometimes drops out for a breath, Song 1's own vocal sometimes kept for contrast, everything on the beat). Not a flat paste.
2. **Instant Changes (live) + Regenerate:** while the mix plays, short typed commands land on the next beat; a Regenerate button produces a different valid take.

---

## Screen 1 — Pick your two songs ✅ built (curated catalog — MVP pivot 2026-07-06)

- **Purpose:** get the raw material in — **from a curated catalog, not uploads** (founder decision 2026-07-06: users kept hitting "tempos too far apart" from misread/incompatible uploads, so the MVP preloads hand-verified songs where **every pairing blends by construction**).
- **On it:** two song slots — "Song 1 → its beat" and "Song 2 → its vocals". Clicking a slot opens a **dropdown of the preloaded songs** (each pre-analyzed, tempo-verified once by us); a song picked in one slot is disabled in the other. Prompt box pre-filled as before.
- **Main action:** pick two songs → **Mix it**.
- **Empty / error:** an empty catalog says "No songs in the library yet"; a failed catalog load says so plainly. No file-type errors anymore — there are no uploads.
- _(The upload flow still exists in the backend — it's how the operator ingests new catalog songs — but users never see it. "Uploads only" from the V1 table is superseded by this pivot for the validation MVP; open uploads may return post-validation, ideally with the tempo-fix control.)_

## Screen 2 — Studying your songs (the wait) ✅ built

- **Purpose:** honest progress while we split stems + analyze (~1 min first time, then cached).
- **On it:** friendly step checklist that ticks off in order — "splitting the vocals, drums & bass… finding the beat, key & structure… planning your arrangement". Reached automatically after **Make my mix**; the user presses nothing else. On any step failure: a plain-language message + a **Start over** button (never a crash or a dead end).
- **Order note (as-built):** stems are split _before_ analysis runs, because the beat/structure read uses the split vocal to find where the singer sings.
- **Edge:** low-confidence song (loose beat, unclear structure, non-Western key) → the planner then picks safer moves (see DJ Handbook Part 9 fallback ladder). _(Surfacing that note on this screen is a later polish.)_

## Screen 3 — Your mix (the heart)

- **Purpose:** play the mix, show what the "DJ" decided, let the user reshape it.
- **On it:** play/pause; a simple timeline showing where Song 2's vocal enters and where the beat drops out (arrangement is visible, not a black box); the prompt/command bar; a **Regenerate ("give me another take")** button; an **Export** button.
- **Main actions:** play/pause; type a live command; regenerate; export.
- **Live command set (V1, lean):** "beat up" (drums/energy up), "take the bass out", "remove / bring back song two's vocals", "drop everything but the beat", "fade away". Each lands on the next beat/bar and answers back in DJ language ("dropping song two's vocal on the next bar").
- **Error / edge:** out-of-scope request ("add a third song", "make it sound like Drake", "change the lyrics", live BPM change) → polite decline that points to what V1 can do; a command with no clean runway → it waits for the next beat or does the closest clean move, and says so.

## Screen 4 — Export / share

- **Purpose:** get the mix out.
- **On it:** download the full mix, and a **short 15–30s clip** (the creator's native unit).

## Global

- No real accounts in V1 (a stub at most).
- Nothing is fetched from outside — only the two uploaded songs' own parts, rearranged on the beat.

---

## Open assumptions (to confirm as we build)

1. Short-clip export as a hero output — keep or cut.
2. "Search any song" is explicitly V2, not V1.
3. ~~Full-length mix is the primary output, clip export secondary.~~ **Resolved 2026-07-06 (discovery):** the **full-length mix is the hero output** (the founder's call). Short-clip export stays a secondary M6 output. This is why full-song arrangement quality (the energy arc) is worth investing in.
4. The ~50-user test uses real casual creators, not friends being nice.
