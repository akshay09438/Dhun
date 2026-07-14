# Ground truth — hand-marked drops & hooks (Task 2)

The founder's ear is the reference we measure the app against. This folder holds the marks.

## The 1-hour session

1. **Open** [`scripts/mark_drops.html`](../mark_drops.html) in a browser (just double-click it — nothing installs, nothing leaves your computer).
2. Click **"Choose your song folder…"** and point it at `services/api/data` (the folder that holds the song files). It lists the real songs (the six catalog songs show by name; anything else shows by a short code).
3. For each song: press **Play**, then tap **D** at every real drop. Mark the one **hook** (the memorable line) with **H** at its start and **H** again at its end. `Space` = play/pause, `U` = undo, `N` = next song.
4. Click **⬇ Export CSV** → save it, then drop it in here as `drops_hooks.csv` (or hand it to Claude — the tool autosaves your progress in the browser too, so you can stop and resume).

Do **Der Lagi first** — marking its hook restores a stable Father Ocean × Der Lagi tuning baseline (Task 1 moved it).

## Then measure

```
python scripts/measure_drops.py --csv scripts/ground_truth/drops_hooks.csv
```

Reports, for the shipped `energy_drops` rule (energy ≥ 0.6 AND a rise ≥ 0.15 over 4 bars):

- **Precision** — of the drops the app finds, how many are real.
- **Recall** — of the real drops, how many the app finds.
- **Offset** — when it's right, how many bars off.

Zero cloud — it reads only the local cached analyses.

## CSV shape

`song_id,song_name,kind,t_start,t_end` — one `drop` row per drop (`t_start` only), one `hook` row per song (`t_start`,`t_end`). That's the whole schema; it's a plain CSV on purpose.
