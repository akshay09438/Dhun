# Prompt-DJ — Functional Spec (V1)

_What the app does, for the user, screen by screen. Approved during discovery on 2026-07-05. This is a living document — kept true to the code. The "how it's built" lives in [technical-spec.md](technical-spec.md); progress lives in [implementation-plan.md](implementation-plan.md)._

## What the app does TODAY (as of 2026-07-07; M1–M5 built + the curated-catalog MVP pivot)

**MVP pivot (2026-07-07):** users no longer upload — they **pick two songs from a curated dropdown** on the Setup screen (Song 1 = beat, Song 2 = vocals), each pre-analyzed and hand-tempo-verified so pairs blend. The catalog is currently a **single-beat "Father Ocean shelf"**: one beat (**Father Ocean**, 122 BPM / key 10B) + four vocals chosen for **key + tempo** compatibility (**Don't Start Now**, **Der Lagi Lekin**, **Tujhe Bhula Diya**, **With You** — the last two are on-the-edge borderline, pending founder ear-test). Song dropdowns are role-filtered (beats vs vocals) and there is no prompt box. The clean-blend tempo band was widened ±8%→±11% to fit the two Bollywood vocals. Everything below describes the mix/steer engine, which is unchanged by the pivot; the upload route still exists but only for operator ingestion of new catalog songs.

**IN PROGRESS (2026-07-08, on branch `feat/house-bollywood-energy-sync` — NOT yet merged to main):** the **House × Bollywood judgment** — a big upgrade to how the mix is arranged, built and founder-ear-confirmed through Step 2 of a 5-step plan (see [house-bollywood-recipe.md](house-bollywood-recipe.md) + [house-bollywood-build-plan.md](house-bollywood-build-plan.md)). What it changes: (1) **energy-sync** — the Bollywood vocal's most powerful part now lands on the house track's real **DROP** (detected from the energy curve), not just the loudest spot; (2) the **produced drop, founder-confirmed** — a multi-bar filter+volume BUILD climbs into each drop, and (Step 3) it's now a real held-breath-then-hit: the beat audibly **lowers to just the drums** for a couple of bars first (bass and melody gradually recede, never an abrupt cut), then the **bass keeps declining all the way through** the build, only **slamming back in right on the drop** with the vocal — a genuine "before" and "after," never a moment where the music goes silent mid-song (the build itself now also skips any spot where Song 1's own recording has a natural quiet breakdown, rather than blindly building through it); (3) **BOTH vocals trade** — the house track (Father Ocean) is no longer stripped; it LEADS its own substantial sung passages in the gaps and keeps its vocal LICK ringing into each drop, while the Bollywood vocal owns the drops (one lead at a time; the app decides who leads, keeping the real passages and dropping the scraps; the new beat move never plays under Father Ocean's own vocal either); (4) the **natural hand-off** — when they trade, the outgoing vocal's own natural decay rings under the incoming one (no imposed fade), the incoming enters at full; (5) **echo throws** — each sung phrase's last word echoes into its own pause on the drops; (6) **beat-up** — once per mix, in the app's strongest beat-only stretch, the melody audibly ducks (a real decline, never abrupt) so the drums and bass visibly drive for a few bars — "the beat takes over," matching the sound of the live tap-button of the same name, now placed automatically. A prerequisite bug was also fixed: 3 catalog vocals had been analyzed before their vocal was separated, so the app never detected their singing (short, mid-word-cut vocals) — now recomputed. This all lives in the arrangement brain + render engine; the screens/flow below are unchanged. **Still to build:** the breakdown move, using the same mixing-board foundation; then vocal chops + the AI taste layer.

The rest of what the app does: two chosen songs → **Make my mix** → a "Studying your songs" screen splits + analyzes both (instant for catalog songs) → **"Make my mix"** produces a **full DJ arrangement** — Song 1's beat running throughout, with Song 2's vocal **weaving in and out across the WHOLE song as an energy arc** (an instrumental intro, then a vocal moment in each third — early, middle, and a strong entry saved for near the end — with beat-only stretches between), tempo-locked, on the beat and click-free, with a real one-bar **beat-breath** and one subtle **filter sweep** before a big entry, and — for contrast — **Song 1's own vocal answering in a gap** so the two songs trade (never two voices at once). The vocal no longer clusters in the middle of a long song; it spans the track and finishes strong. On a song with shaky analysis it automatically plays safer (fewer moves). The mix screen **shows the arrangement** (a two-lane timeline: where each song's vocal is, in distinct colors), and **"Give me another take"** (Regenerate) produces a different valid arrangement; **Download** saves the WAV. (Live steering now plays the **whole mix** — the mix screen's **live player** plays Song 1's beat/bass/melody **and** Song 2's arranged vocal together, and you reshape it live: tap any of the four parts — **Beat · Bass · Melody · Vocals** — or type a command ("take the bass out", "remove the vocals", **"drop everything but the beat"**, "bring it all back"), and it lands **on the next beat** with a smooth fade, replying in DJ language. As the mix plays, the live player also shows **1–3 AI suggestion chips that change with the part of the song** (e.g. "Bring the vocal in", "Drop to just the beat", "Fade it out") — tap one and it happens on the beat; and **"fade away"** fades the whole mix out. The suggestions are worked out **once per mix** by the AI (with a sensible built-in fallback if the AI's unavailable), and your own taps/commands stay predictable (M5 Slices 1–3). In the live player the **Vocals part is the arranged, per-bar beat-locked vocal** (the same vocal as the Download) — reverted from the earlier "continuous" experiment because it drifted; so the live player now sounds like the finished mix. The transport bar is **click/drag-seekable** and pause/resume keeps its place. The live player also has a **"Beat up"** energy move — tap it (or type "beat up") and the melody + vocals duck so the drums & bass drive the track (the beat takes over), on the next beat; "bring it all back" restores the full mix. The live player is a steerable _approximation_; the **Download stays the polished master** (it keeps the arranged vocal arc, the filter sweep, and the beat-breath). Still to come: final mastering and short-clip export. **Making a mix is now one click:** drop two songs → **Make my mix** → a "Studying your songs" screen splits and analyzes both automatically (an honest checklist: splitting the parts, finding the beat, planning the arrangement) → the finished mix. The old manual per-song **Split**/**Analyze** buttons are gone. **The whole app now wears its final look — the "Electric Violet" design (grey + one violet accent, Instrument Serif + Space Mono) laid out as four distinct screens (Setup → Generating → Play & Steer → Export) in a console/stage split**, and every mix gets a **playful AI-generated name** (e.g. "Ocean Bina") instead of "Untitled Mix". Still to build: the 14-second shareable clip export and final mastering (M6).) The sections below describe the full V1 target.

## The core value, in one sentence

A person who can't DJ picks two songs, and gets back a mix that sounds like a real DJ made it — then reshapes it with plain words.

## Who it's for

Casual music fans and creators who can't DJ but want to make good-sounding mashups to share or enjoy. First target slice: people making short mashup clips for TikTok / Reels / for fun.

## The V1 decisions (frozen)

| Decision                | V1 choice                                                                                                                                             |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Who it's for            | Casual creators / fans                                                                                                                                |
| Song source             | **Curated catalog (pick, don't upload)** — pivoted 2026-07-07; supersedes the earlier "uploads only". ("Search any song" is still the V2 north star.) |
| Core loop               | Pick 2 catalog songs → DJ-style mix → steer / regenerate → export                                                                                     |
| Feature 2               | Lean live commands **+ regenerate**; energy moves only                                                                                                |
| Live tempo (BPM) change | **V2 stretch goal** (energy-up is V1; changing song speed live is later)                                                                              |
| Music                   | Western + Indian (Indian pairs need extra hand-checking — weaker analysis)                                                                            |
| Success bar             | ~50 real casual creators clearly feel "I made a real mix by describing it"                                                                            |

## The two features (frozen scope)

1. **The Mix (offline):** two picked catalog songs — Song 1 (beat) + Song 2 (vocals) — become one finished, continuous track with Song 2's vocals arranged _like a DJ_ over Song 1's instrumental (vocals enter on drops/choruses, the beat sometimes drops out for a breath, Song 1's own vocal sometimes kept for contrast, everything on the beat). Not a flat paste.
2. **Instant Changes (live) + Regenerate:** while the mix plays, short typed commands land on the next beat; a Regenerate button produces a different valid take.

---

## Screen 1 — Pick your two songs ✅ built (curated catalog — MVP pivot 2026-07-06)

- **Purpose:** get the raw material in — **from a curated catalog, not uploads** (founder decision 2026-07-06: users kept hitting "tempos too far apart" from misread/incompatible uploads, so the MVP preloads hand-verified songs where **every pairing blends by construction**).
- **On it:** two song slots — "Song 1 → its beat" and "Song 2 → its vocals". Clicking a slot opens a **dropdown of the preloaded songs for that role only** — Song 1 lists only beat songs, Song 2 only vocal songs (filtered by each catalog entry's `role_hint`). Each song is pre-analyzed and tempo-verified once by us. **No prompt box** (it steered nothing at mix time — live steering happens on the Play screen, so it was removed to keep Setup clean).
- **Main action:** pick two songs → **Mix it**.
- **Wider tempo reach now (movable master, 2026-07-08):** the app no longer needs both songs at nearly the same speed. When a pair is too far apart to force one onto the other, it meets them at a shared tempo — nudging the house track a little (protected: it barely moves, never dragged down) while the guest vocal takes the rest. This unblocked the founder's #1 pair, **Father Ocean × Tere Bina** (~143 vs 122 BPM, previously declined), now in the catalog and mixable.
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
- Nothing is fetched from outside — only the two chosen songs' own parts, rearranged on the beat.

---

## Open assumptions (to confirm as we build)

1. Short-clip export as a hero output — keep or cut.
2. "Search any song" is explicitly V2, not V1.
3. ~~Full-length mix is the primary output, clip export secondary.~~ **Resolved 2026-07-06 (discovery):** the **full-length mix is the hero output** (the founder's call). Short-clip export stays a secondary M6 output. This is why full-song arrangement quality (the energy arc) is worth investing in.
4. The ~50-user test uses real casual creators, not friends being nice.
