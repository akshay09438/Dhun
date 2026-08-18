# Parked tests — not run, not deleted, not forgotten

A test in here is **finished and correct on its own** but could not be left in the suite. Parking
rather than deleting is the house rule: a deleted test is a decision nobody can find again.

Each entry says what it proves, why it is parked, and exactly how to put it back.

---

## `drop_saved_for_a_song_already_here.py`

**Parked 2026-08-18, on the founder's call, after ~40 minutes and ten full-suite runs.**

### What it proves

The fix in `app/routes/songs.py` that saves a drop typed for a song the app already has.
`POST /songs/add` returns as soon as it recognises a song — which is why a duplicate costs nobody
a slot or a penny — but it returned *before* `main_drop` was ever written, so the answer to "where
does the drop hit?" was binned in silence.

**Both tests are red without the fix and green with it**, verified by stashing the change and
re-running. Run them and they pass:

```
services/api/.venv/Scripts/python.exe -m pytest services/api/tests/parked/drop_saved_for_a_song_already_here.py -q
```

### Why it is parked

**Adding this file to the suite makes one or two UNRELATED tests fail** — usually
`test_upload_security.py::test_a_song_can_never_be_stored_with_no_name` with a 429, sometimes a
different test entirely. It is reproducible, not random. The suite is green the moment this file
is not collected, checked twice.

### What was ruled out (so nobody repeats it)

- **Leaked ingest threads or reservations.** Measured directly after the file runs: no live
  `ingest-` threads, `_RESERVED` empty, the slot semaphore back at its full value.
- **A shared test account.** Changed to its own uploader id. No effect.
- **The manifest cache key.** `uploads._stamp()` is `(mtime, size)` with **no path in it**, so two
  different data dirs with same-sized manifests written in one clock tick can collide. Adding the
  path took failures 2 → 1 but did not clear them, so it was **reverted** — a real latent weakness,
  but not this cause, and shipping an unrelated speculative change on a wrong hypothesis is worse
  than leaving it. **Worth fixing on its own merits, separately.**
- **Identical fixture audio.** The other upload test files build their audio with the same
  generator, seed and tempo, so this file's song was *byte-identical* to theirs and shared a
  `song_id`. Given its own seed and tempo. No effect.
- **The paid-attempt budget.** The 429 comes from `spend.BudgetSpent` on paper, but instrumenting
  `spend.check_budget` never caught it raising. The real 429 source is still unidentified.
- **Machine load.** Plausible at first — the failures moved between runs — but the control run
  (same load, this file excluded) is green, which kills it.

### The one thing NOT tried

Moving these two tests **into an existing upload test file** rather than adding a new file. A new
file being the trigger is the one variable never removed. That is the first thing to try.

### The cost of leaving it parked

The fix is live and works, but nothing in the suite guards it. A future change to that branch could
silently undo it and no test would notice.
