"""Backend anomaly reporting.

When a mix is built from imperfect or unexpected inputs, the app STILL generates the music — a far-apart
vocal is forced onto the beat, a shaky beat grid falls back to safer moves, an untrusted key is measured
from the audio. That resilience is deliberate. But those degraded conditions used to be invisible: on a
real user upload (where analysis is often "off" or unspecified) the operator had no way to see that a mix
came out of a fallback, or why.

This module turns each such condition into a structured **anomaly** — a plain-language "what was
unexpected" plus "what to do about it" — that the mix pipeline logs on the backend. It never blocks or
changes the mix; it only reports. (Founder rule 2026-08-07, point 2.)

Pure and side-effect-free: `scan(...)` inspects facts the pipeline already computed and returns the
anomalies; the caller logs them. See test_anomaly.py.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Anomaly:
    code: str        # a stable machine tag, e.g. "forced_tempo"
    detail: str      # plain-language: what was unexpected
    action: str      # plain-language: what to do about it
    severity: str = "info"  # "info" (worth noting) | "warn" (a human should probably look)


def scan(*, grid_health: dict[str, dict], tempo_forced: bool,
         vocal_stretch: float, key_why: str, beat_vocal_coverage: float = 0.0,
         beat_bpm: float = 0.0, vocal_bpm: float = 0.0) -> list[Anomaly]:
    """The anomalies for one mix, from facts the pipeline already has. Empty when nothing was off."""
    out: list[Anomaly] = []

    # HALF-TIME PAIRING. best_stretch folds octaves, so a pair that is ~2x apart (e.g. Silence 143 x
    # Panda 72) passes as "compatible" with almost NO stretch and locks perfectly on the beat — the
    # maths is right, but one song's pulse is twice the other's, so the beat can feel like it is
    # racing under a slow vocal (founder ear-report 2026-08-10). Report only: the mix is still made
    # (never-refuse) and nothing about it changes; this flags WHY it may feel off.
    if beat_bpm > 0 and vocal_bpm > 0:
        r = beat_bpm / vocal_bpm
        folded = min((abs(r - 1.0), "straight"), (abs(r / 2 - 1.0), "vocal_half"),
                     (abs(r * 2 - 1.0), "vocal_double"))[1]
        if folded != "straight":
            faster, slower = ("Song 1's beat", "Song 2's vocal") if folded == "vocal_half" \
                else ("Song 2's vocal", "Song 1's beat")
            out.append(Anomaly(
                "half_time_pair",
                f"half-time pairing: {round(beat_bpm)} BPM beat vs {round(vocal_bpm)} BPM vocal "
                f"(~2x apart) — matched by octave-fold, so it is exactly on-beat, but {faster} pulses "
                f"twice as often as {slower}.",
                "Expected to be technically correct; if it feels frantic, prefer a partner within "
                "~15% of this song's tempo rather than a half/double-time one.",
                "warn",
            ))

    # The beat's OWN vocal reads as covering ~the whole track. A real beat rarely sings the whole song,
    # so this usually means the vocal separator mis-heard instrumental bleed/pads as singing (a false
    # read). We only FLAG it — we never auto-silence the beat from this number (a human decides via the
    # hand-list). If the beat truly has no vocal, mark it music-only; if it does sing, its read is wrong.
    if beat_vocal_coverage >= 0.9:
        out.append(Anomaly(
            "suspicious_beat_vocal",
            f"Song 1's own vocal reads as ~{round(beat_vocal_coverage * 100)}% of the track — likely a "
            f"false read (a beat rarely sings the whole song; the separator may have caught instrumental "
            f"bleed).",
            "If Song 1 has no real lyrics, mark it music-only; if it does sing, re-scan its vocal "
            "separation. (Never auto-silenced from this number.)",
            "warn",
        ))

    # A large forced stretch: we never decline for tempo, but a big stretch is where a warble would
    # come from, so flag how big it was.
    if tempo_forced:
        pct = round(abs(vocal_stretch - 1.0) * 100)
        out.append(Anomaly(
            "forced_tempo",
            f"Song 2 was stretched ~{pct}% to lock onto Song 1's beat (never-decline forced match).",
            "Expected for far-apart pairs; if it warbles, prefer a closer-tempo partner for this song.",
            "warn",
        ))

    # A shaky beat grid: every on-beat move trusts the downbeats, so a low-confidence grid is the usual
    # source of an off-beat feel. Report per track.
    for tag, gh in (grid_health or {}).items():
        if isinstance(gh, dict) and gh.get("ok") is False:
            reason = gh.get("reason") or "the beat grid looks irregular"
            out.append(Anomaly(
                "low_grid_confidence",
                f"{tag}: low-confidence beat grid ({reason}).",
                "Re-check this song's analysis; a bad grid can make on-beat moves feel off.",
                "warn",
            ))

    # The detected key label couldn't be trusted, so the shift was measured from the audio instead.
    if key_why and key_why.startswith("chroma-empirical"):
        out.append(Anomaly(
            "key_measured",
            f"Key label untrusted — the pitch shift was measured from the audio ({key_why}).",
            "Fine to ship; if many songs hit this, the key detector may need an ear-check.",
            "info",
        ))

    return out


def format_line(mix_id: str, a: Anomaly) -> str:
    """A single, greppable backend log line for one anomaly."""
    return f"anomaly mix={mix_id} code={a.code} severity={a.severity} :: {a.detail} -> {a.action}"
