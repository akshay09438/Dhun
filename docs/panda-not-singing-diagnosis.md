# "Panda wasn't being sung" — what the evidence says

_2026-08-12. Founder report: they made Father Ocean × Panda and Panda's vocal was not being sung in
the remix. Read-only diagnosis. Nothing in the engine was changed. Every number below says how it
was obtained._

---

## Where it got to

**It is not a planning failure — the plan puts Panda in the mix for 40% of what you heard.** What I
could not finish is the last step: proving whether the vocal survived into the finished audio. The
file needed for that measurement was deleted off the disk by tonight's catalog sweep before I got to
it. The probe is written and the mix is exactly reproducible, so that step is about a minute of work
next session.

---

## What was measured

### 1. The mix is 474.7s long; you heard a 219.6s crop of it

Read from the plan and the files: `mix.wav` is 474.7s, `bestparts.wav` is 219.6s. The app crops every
mix to its highlight, which is why you never hear the whole thing.

**Which 219.6 seconds:** roughly **221.5s → 441.1s** — the second half.

⚠️ **Low confidence on that specific window.** I found it by matching the loudness shape of the clip
against the full mix; the best match scored 0.68 and the runner-up 0.65. That gap is too small to
call it settled. The crop offsets are not recorded anywhere, which is itself worth fixing — right
now nothing in the system can say which part of a mix a person actually heard.

### 2. The plan places Panda's vocal three times, and two of them are inside what you heard

Read straight from the mix plan:

|                | Where in the mix | Length | Inside the crop?                |
| -------------- | ---------------- | ------ | ------------------------------- |
| Panda vocal #1 | 62.8 – 115.7s    | 52.9s  | **no** — before the crop starts |
| Panda vocal #2 | 235.3 – 269.7s   | 34.4s  | **yes, all of it**              |
| Panda vocal #3 | 376.5 – 429.4s   | 52.9s  | **yes, all of it**              |

**87.4 seconds of Panda inside a 220-second clip — 40% of what you heard was supposed to be him.**

For comparison, Father Ocean's own vocal appears for only 6.3s in that window. So the plan is not
quietly favouring the beat song either.

**This rules out the two easiest explanations:** the arrangement didn't forget Panda, and the crop
didn't land on a Panda-free stretch.

### 3. The engine already flagged this pair as awkward

From its own event log for that mix, recorded at the time:

> `half_time_pair`: 122 BPM beat vs 72 BPM vocal (~2x apart) — matched by octave-fold, so it is
> exactly on-beat, but Song 1's beat pulses twice as often as Song 2's vocal.

The mix shipped as **amber**, not green. The engine knew this pair was a stretch and said so.

Panda's vocal was also compressed to **85% of its original length** (`vocal_stretch: 0.85`) and
pitched down one semitone. That is a 15% stretch — exactly the recorded warble threshold.

---

## The two suspects, and why I did not pick one

**Suspect A — the vocal is there but too quiet to make out.** There is a known, _parked_ issue from
2026-08-08: vocals sit roughly 6–8 dB under the beat because nothing adds makeup gain after the vocal
chain. On a dense house beat, a rap vocal 8 dB down and stretched 15% could easily read as texture
rather than as someone singing.

**Suspect B — the vocal did not make it into the render.** Something in the chain dropped or
collapsed it between the plan and the file.

**These need opposite fixes**, which is why guessing is worse than waiting:

- If it is A, the fix is a constant post-chain vocal boost — a change to the **vocal chain**, which
  is a handle-with-care file and needs your explicit yes.
- If it is B, it is a bug in the render path and a boost would do nothing.

**A first attempt at telling them apart failed for a reason worth recording.** I compared how much of
the mix's energy sits in the vocal frequency band during Panda's placements versus elsewhere. The
answer came out _backwards_ — less vocal-band energy during the vocal sections. That is not evidence
of anything: the arrangement's own energy arc (filtered, mid-heavy intro; full-range drop) swamps the
measurement. **Reporting that as a finding would have been wrong**, so it is recorded here as a
discarded method rather than a result.

---

## The measurement that would settle it, and why it did not run

The right test: take Panda's actual vocal stem, apply the same slice and the same 1.176× stretch the
plan used, and check whether the finished mix's loudness in the vocal band **follows that vocal's
phrasing at exactly the planned spot and nowhere else.** A vocal buried 10 dB under a beat still
moves the envelope; a vocal that never made it into the render does not.

The probe is written (`scratchpad/panda_probe.py` — it searches 150–330s so the true spot has to beat
180 wrong ones, and prints how far the real offset stands out from the crowd).

**It could not run: `…5953abb4….mix.wav` was gone by the time I reached it** — swept off the disk
during tonight's catalog sweep, which deletes each render as soon as it is judged.

**This costs almost nothing to recover.** A mix's id is a hash of its inputs, so re-running Father
Ocean × Panda regenerates a byte-identical file. Re-render, run the probe, get a verdict. About a
minute, on an idle machine.

---

## Recommendation

1. **Re-render that pair and run the probe first.** Do not touch the vocal chain until the answer is
   known — a loudness fix applied to a render-path bug changes nothing and adds a change to defend.
2. **If it is a loudness problem, treat it as the general one it is.** The parked note says vocals sit
   6–8 dB down on _every_ mix. Panda is just where it became obvious, because a half-time rap over a
   dense house beat is the least forgiving case in the catalog. Fixing it for Panda alone would be
   fixing the wrong thing.
3. **Record the crop offsets.** Nothing currently stores which slice of a mix was delivered, which is
   why establishing "what did they actually hear" took a signal-matching exercise with a weak result.
   Two numbers written next to the mix would have answered it instantly.

## Explicitly not done

- **No fix was applied.** The likely fix touches the vocal chain — a handle-with-care surface — and
  under an unattended run those are never self-applied.
- **No conclusion about whether Panda is audible.** That is the whole open question; the plan-level
  evidence above is real, the audio-level evidence is not yet in.
