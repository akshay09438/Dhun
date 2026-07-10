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
}


def hook_for(song_id: str) -> tuple[float, float] | None:
    """The signature-hook slice to land on the drop for this vocal song, or None (fall back)."""
    return HOOKS.get(song_id)
