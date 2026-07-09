# How Prompt-DJ Makes a Mix — the master recipe

_The single, plain-English rulebook for how the app turns two songs into a DJ mix. Every rule the app follows, in order, plus what's still open and what we've tried. Read this to understand how a mix is made without opening the code. Kept current as the logic changes._

**Last updated:** 2026-07-10

---

## The big idea

- **Song 1 = the beat** (the instrumental / house track). **Song 2 = the vocal** (the Bollywood song).
- The app lays **Song 2's vocal over Song 1's beat**, like a DJ making a mashup.
- A **"brain"** plans the whole arrangement as a recipe (a list of instructions); a separate **engine** performs that recipe on the actual audio. **The brain never touches the audio itself** — it only writes the plan. This is what keeps the app safe and predictable.

---

## Step 1 — Match the tempo (so they lock together)

- The two songs are almost never the same speed, so one has to bend to the other.
- **Protect the beat.** The beat (Song 1) is the anchor — speeding or slowing it too much kills its drive. So the beat moves the **minimum** (a small nudge, capped), and the **vocal does most of the stretching** to meet it.
- Whether the vocal ends up faster or slower depends on which song was quicker to start with.
- **If two songs are too far apart to blend** (past the safe stretch limit), the app **refuses the pair** rather than ship something that sounds bad.
- Close-tempo pairs aren't touched at all — they play at their natural speed.

## Step 2 — Decide WHERE the vocal goes (the arc)

- The vocal doesn't play the whole time and doesn't clump in one place. It's **spread across the song like an arc**: a moment early, a moment in the middle, and a **strong entry saved for near the end** — with **beat-only stretches** in between so the mix breathes.
- Vocal entries land on the beat song's **drops** (the big energy moments) wherever possible.

## Step 3 — Put the RIGHT part of the vocal on each spot

- **The drop gets the HOOK** — the song's signature line (e.g. _"Jee karda," "Dil ye bekaraar kyun hai," "Aankhein teri kitni haseen"_), not whatever is merely loudest.
- **The other spots get the setup** — different, other parts of the song (a verse, another section), never the hook twice, so the mix has variety and builds _toward_ the hook.
- **How the hook is found:** the app can't hear the songs, so for each curated song the hook's exact spot is **marked once** (read off the song's chorus/verse structure + knowledge of the song, then **confirmed by ear**) and locked in. A song with no mark falls back to the loudest part.

## Step 4 — Lock the vocal to the beat

- The vocal is re-timed **bar by bar** so it stays exactly on the beat for the whole placement and never drifts off-time — even over a long song.

## Step 5 — The hand-off (when the beat song also sings)

- Some beat songs have their own vocal. Rather than hard-muting it, the app lets the **beat's vocal fade out naturally** while the **Bollywood vocal comes in underneath** — a smooth hand-off, never a hard cut. The beat's voice tapers off on its own, and the Bollywood one takes over.
- **Only one lead voice at a time** — the two never talk over each other (a hard rule; see the guardrails).

## Step 6 — Produce the drops (make them feel made, not assembled)

Around each big drop, the app performs the beat like a DJ would:

- **Build-up:** a multi-bar filter+volume climb leading into the drop, so you feel it coming.
- **Drop to just the beat:** just before the drop, the bass and melody recede so the drums drive alone — a held breath.
- **Bass pull-and-slam:** the bass fades down through the build and **slams back in on the drop**.
- **Beat-up:** once per mix, the melody ducks so the drums+bass drive for a few bars ("the beat takes over").
- **Breakdown:** once per mix, the drums+bass fade to a low simmer, the melody holds, then the beat kicks back in.
- **Echo throws:** the vocal's last words echo out into the space after a line, on the drops.
- Every one of these lands **on the beat**, and a continuous element is only ever **lowered, never hard-cut** (except the slam at the drop, which the song earns).

## Step 7 — The guardrails (never broken)

- **One lead vocal at a time** — never two voices competing.
- **Never clips** — the finished audio is volume-checked so it can't distort.
- **Never goes fully silent** mid-song — a continuous part is lowered, not killed.
- **Everything lands on the beat.**
- **Play it safe on a shaky read:** if the app isn't confident about a song's beat/structure, it does **fewer, simpler moves** rather than risk an embarrassing one.

---

## What's still OPEN (identified, not built yet)

- **Vocal "play" / production** — roughening or energizing the vocal to match the beat (e.g. a soft, sweet vocal made harsher to sit on a punchy beat), and keeping more energy going **outside the drop** so the mix doesn't feel plain. This is the founder's biggest current note.
- **Cleaner setup parts** — the non-drop entries still draw from coarse "loud chunks," not clean verses.
- **Which beat suits which vocal** — some pairs just don't work (e.g. Jee Karda × Anchor Point). Right now that's the founder's ear, not a written rule.

## Lessons — what we tried and decided

- **Hook-on-drop:** BUILT + founder-confirmed. The drop plays the signature line.
- **Natural hand-off (not muting the beat's vocal):** CONFIRMED correct — the fade-underneath is more musical than a hard mute.
- **Vocal chops** (stuttering the hook on the drop): BUILT then **PARKED** — it re-fired the vocal's first split-second, which was sometimes a breath, so the drop went dead. Revive only if it grabs a punchy syllable.
- **Phrasing** (snapping every change to a fixed 8/4-bar grid): TRIED then **REVERTED** — the grid was counted from the song's start, but real songs' phrasing is offset by the intro, so it pulled vocals **off** the real drop. Lesson: if revisited, anchor the grid to the music, never to bar zero.

## Where the finer details live

- **The code** — the arrangement "brain" (`services/api/app/planner/`) and the engine (`workers/render.py`).
- **The DJ Judgment Handbook** and the **House × Bollywood recipe** (`docs/reference/`, `docs/house-bollywood-recipe.md`) — the original judgment rules.
- **The technical spec** (how it's built) and the **implementation plan's drift log** (every change + why), where new learnings are recorded.
