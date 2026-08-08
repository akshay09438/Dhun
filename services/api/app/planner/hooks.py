"""Per-song HOOK markers for the curated catalog — the signature line to land on the drop.

The app can't hear audio, so *which* vocal slice is "the hook" (the recognizable payoff a DJ drops
on) is a per-song judgment, not something the loudness/energy math can find (it kept grabbing the
wrong bit). For the small curated catalog we mark it ONCE — the slice is read off the song's own
section map (which chorus holds the hook) plus knowledge of the song, then confirmed by ear — keyed
by the song's content id. A song with no entry is NOT guessed at: the planner uses its vocal regions
as-is (song order) and never lands the loudest slice on the drop as a fake hook — a low-confidence
guess measured ~28s off is worse than admitting we don't know (Task 1, 2026-07-10).

Each value is (start_secs, end_secs): the sung stretch that contains the hook. The planner lands it
on the strongest anchor (the drop) and uses the other vocal parts for the setup entries.
"""
from __future__ import annotations

HOOKS: dict[str, tuple[float, float]] = {
    # Dil Ye Bekarar Kyun Hai (Players) — "Dil ye bekaraar kyun hai" starts at 42.0s
    # (founder-confirmed by ear 2026-07-10; the section boundary at 35.5 landed mid-phrase on "…kyun ye…").
    "73431441fb8cae90e084ca78b18c213fe7c58d7a51cfa39b786c9eceac0a9e5e": (42.0, 56.9),
    # Jee Karda (Badlapur) — "Jee karda!" — first chorus section (55.0-68.7)
    "2294a71524d7b0041a8f1c01f198a1e2ac4af4d1d1d39a6ac6f6ea695d7a6195": (55.0, 68.7),
    # Maula Mere Maula (Anwar) — "Aankhein teri kitni haseen" — verse after the opening refrain
    # (28.9-51.9). Founder-confirmed by ear (2026-07-10).
    "6608cb4849db314c28a26843adcb94558afebe833020af010a7d8cb8f69d7fcb": (28.9, 51.9),
    # --- The five SHIPPED catalog vocal donors — founder-marked by ear via scripts/mark_drops.html
    #     (2026-07-11, drops_hooks_marks.csv). Before this they were hookless (Task 1 removed the
    #     loudest-slice guess), so every catalog vocal mix ran the no-guess path; with these each
    #     donor's real hook now lands on the drop. Der Lagi's specifically UN-MOVES the tuning
    #     baseline Task 1 shifted (see implementation-plan.md drift log, 37th entry). ---
    # Der Lagi Lekin (ZNMD) — the memorable sung stretch (marked FIRST, to reset the baseline).
    "bbab7b9f875f071f8e3b53aa73e64c02b3f39730d0a1feec48af6b54de501430": (18.74, 51.11),
    # Don't Start Now (Dua Lipa) — the "don't show up, don't come out…" hook.
    "c0c6ab91a06e24367e84874da81d4abc285779f50e8f1aeacf70a655cabceb0b": (51.51, 66.19),
    # Tujhe Bhula Diya (Anjaana Anjaani) — the title-line chorus.
    "fedc95c90aff7c957f398f302a6a3ed4c7dbf48d7a6667c8294e0b4030355e20": (58.69, 81.47),
    # With You (AP Dhillon) — the hook stretch.
    "ae132f3a444f5121d75097a44110a0323365e6dc4a8d0736a924c00b2ac210c1": (53.25, 84.25),
    # Tere Bina — the memorable line (declined from the one-tempo SET by 3.2, but still a valid
    #     stand-alone vocal donor for a single mix, so it gets its hook too).
    "6ad6903592cd668502c5f4546618aec807c6eadb974fa6437fef7180fbffddc2": (63.48, 90.13),
    # --- The seven NEW Bollywood/Punjabi vocal donors (added 2026-07-15). Placed as a first pass from
    #     the analysis (first chorus that lines up with a vocal region, on a sung onset) + song
    #     knowledge, then FOUNDER-EAR-CONFIRMED 2026-07-15: five accepted as-is, two moved (Nadan
    #     Parinde and Jugni Ji) to the founder's marks. ---
    # Nadan Parinde (Rockstar) — "Nadaan parinde, ghar aaja" — founder-marked 1:35–2:05 (moved from 2:55).
    "84e4ea36d2f3cb34f7e1beb4ce1bace077083994e700b7cc73347e2f5b5438f3": (95.0, 125.0),
    # Uff Teri Ada (Karthik Calling Karthik) — "Uff teri ada…" — first chorus (1:22); founder-confirmed.
    "5c3ce60868f97c5657d32cc14a028b349fab07bfdf984c40f401790fd1c82375": (82.0, 105.0),
    # Jugni Ji — "Jugni ji…" — founder-marked 0:09–0:29 (moved from 0:50).
    "cb3e96493087255ef535db47d04388f51d2de27e20c6cb13dd626092778aae43": (9.0, 29.0),
    # Wari Jawa (Vaari Jaavan) — "Vaari jaavan…" — chorus on the 1:05 vocal onset (skips the 0:53–1:05 gap).
    "0bcbcd12d965a7d03f314424670768ed9074c18f6f2af961fb05d77c803f3d7b": (65.0, 82.0),
    # Tere Bin — title hook — first chorus section (1:00), inside the 0:20–2:48 vocal run.
    "84ff0d8b12455dc66e971874b64ae3b816d622f7fc947cfba12cca77fe6eea88": (60.0, 80.0),
    # Mera Yaar (Bhaag Milkha Bhaag) — "Mera yaar…" — first chorus (0:57), in the 0:41–1:20 vocal run.
    "b07a768b3409725988f2d08e2445b46f787e86a3da1233d987999f5ecb2d77c3": (57.0, 77.0),
    # Khuda Jaane (Bachna Ae Haseeno) — "Khuda jaane ke main fida hoon…" — first chorus (0:59), 0:12–1:24 vocal run.
    "457d170c17dea1fc8644c479788efff6c1bfc5b5c4b3fa5897e43a6c0e5ce751": (59.0, 84.0),
    # --- Three vocal-heavy EDM beats (Wake Me Up / Faded / Lean On), founder-marked by ear
    #     2026-08-08 via scripts/mark_drops.html. Uploaded AS BEATS, so hook_for (called for the Song-2
    #     vocal only) leaves these inert until one is used as a vocal donor — captured now as ground
    #     truth for the catalog. ---
    # Wake Me Up (Avicii) — hook line.
    "e6722353c4251a3f9af0a76ab620b22f61fa6e385846ae67073debafa6acf1ad": (38.78, 69.81),
    # Faded (Alan Walker) — hook line.
    "f61ea8edc6c56a0a1da0de64d26768618e6007262fbca7738d8571ccfa92c7fa": (31.66, 54.17),
    # Lean On (Major Lazer & DJ Snake) — hook line.
    "ed2c86b75c81961842d7ea6509d0d962efd1798c49e45bed01395db0d49bcc46": (49.03, 68.65),
    # Closer (The Chainsmokers ft. Halsey) — founder-marked hook 0:51-1:10 (2026-08-08).
    "3f260b5cadb5a20ca475f50553f4d8512ed2764ba9f4d7988f9c1e0111d25f4e": (51.0, 70.0),
}


def hook_for(song_id: str) -> tuple[float, float] | None:
    """The signature-hook slice to land on the drop for this vocal song, or None (fall back)."""
    return HOOKS.get(song_id)
