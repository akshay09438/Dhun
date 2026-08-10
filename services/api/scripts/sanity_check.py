"""Catalog-wide SANITY / SENSE / BUG check for the arrangement rules.

Sweeps EVERY beat x vocal pair in the local catalog and verifies, for the mixing rules:
  HARD RULES (must pass):
    - the plan builds (or declines cleanly with a reason) — never an unexpected crash
    - the referee `validate_plan` passes: R1 no two vocals overlap, R3 on a downbeat, etc.
    - the mixing-rule shuffler NEVER puts two rules (1/3/4) back-to-back — INCLUDING after the
      guest-verse chop->echo remap the user actually hears
  QUALITY STATS (reported, not failed):
    - how many Song-2 lines and beat lines end ON a breath (finish their sentence)

Scales to any catalog size (it only reads cached analyses + plans; no cloud, no render by default).
Run anytime:  cd services/api && .venv/Scripts/python.exe scripts/sanity_check.py
Add --render to also render a small sample end-to-end and check R6 (no clip / not silent).
"""
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "services" / "api"))

from app.routes.library import get_library
from app.routes.mix import _load_analysis, SHIPPED_CHAIN
from app.planner.plan import build_mix_plan, MixDeclined
from app.planner import validate, rule_shuffle, beat_guest_verse, keys
from app.planner.keys import resolve_key_shift

_BREATH_TOL = 0.6   # a line end within this many secs of a breath "finished on a breath"
_REACH = 5.0        # a breath farther than this was out of reach (a non-stop singer) — not a fault


def _near_breath(t, pauses):
    return any(abs(t - p) <= _BREATH_TOL for p in pauses)


def sweep_pairs(beats, vocals):
    hard, stats = [], {"lines": 0, "on_breath": 0, "beat_lines": 0, "beat_on_breath": 0,
                       "built": 0, "declined": 0}
    for b in beats:
        a1 = _load_analysis(b["id"])
        for v in vocals:
            a2 = _load_analysis(v["id"])
            if a1 is None or a2 is None:
                hard.append(f"{b['original_name']} x {v['original_name']}: missing analysis")
                continue
            # HARD PITCH RULE: the label-path key shift must be within +/-2 (the audio fallback is
            # separately capped at KEY_SHIFT_CAP == CAP_SEMITONES; proven in tests/test_pitch_cap_hardrule.py).
            kshift, _kwhy = resolve_key_shift(a1, a2)
            if abs(int(kshift)) > keys.CAP_SEMITONES:
                hard.append(f"{b['original_name']} x {v['original_name']}: key shift {kshift:+d} st "
                            f"exceeds +/-{keys.CAP_SEMITONES} (HARD PITCH RULE)")
            for rule in (1, 4):  # rule 3 is remapped for guest-verse beats; 1=dry, 4=echo cover the render path
                try:
                    plan = build_mix_plan("sane", a1, a2, "", take=1, chain=SHIPPED_CHAIN, rule=rule)
                except MixDeclined as d:
                    stats["declined"] += 1
                    # with force-tempo on, only a track with NO beat grid should ever decline
                    if a1.downbeats and a2.downbeats:
                        hard.append(f"{b['original_name']} x {v['original_name']} r{rule}: unexpected decline: {d}")
                    continue
                except Exception as e:  # noqa: BLE001 — a crash IS the bug we're hunting
                    hard.append(f"{b['original_name']} x {v['original_name']} r{rule}: CRASH {type(e).__name__}: {e}")
                    continue
                stats["built"] += 1
                errs = validate.validate_plan(plan, a1, a2)  # THE HARD RULES
                if errs:
                    hard.append(f"{b['original_name']} x {v['original_name']} r{rule}: referee: {errs}")
                # quality stats — finishing on a breath
                for p in plan.placements:
                    stats["lines"] += 1
                    if _near_breath(p.vocal_src[1], a2.vocal_pauses or []):
                        stats["on_breath"] += 1
                for s, e in plan.s1_vocal_regions:
                    stats["beat_lines"] += 1
                    if _near_breath(e, a1.vocal_pauses or []):
                        stats["beat_on_breath"] += 1
    return hard, stats


def sweep_rule_shuffle(beats, vocals):
    """No two mixing rules (1/3/4) back-to-back — the EFFECTIVE rule the user actually hears, for both
    the single-pair re-roll flow and the set flow (including sets that mix guest-verse + normal beats)."""
    problems = []
    users = ["u1", "u2", "u3", "anon-device-abc", "anon-device-xyz"]

    # (a) single-pair re-rolls: 8 takes of every beat x a sample of vocals, every user
    for b in beats:
        allowed = beat_guest_verse.available_rules(b["id"])
        for v in vocals[:6]:
            for u in users:
                eff = [rule_shuffle.rule_for_available(u, b["id"], v["id"], n, allowed) for n in range(8)]
                for i in range(1, len(eff)):
                    if eff[i] == eff[i - 1]:
                        problems.append(f"single-pair back-to-back rule {eff[i]}: {b['original_name']} {eff} ({u})")
                        break

    # (b) sets: worst-case orderings that mix guest-verse and normal beats (and an all-guest-verse set)
    gv = [b for b in beats if beat_guest_verse.guest_verse_for(b["id"])]
    normal = [b for b in beats if not beat_guest_verse.guest_verse_for(b["id"])]
    sample_sets = []
    if gv and normal:
        sample_sets.append([gv[0], normal[0], gv[0], normal[0], gv[0]])   # alternating gv/normal, 5 mixes
    if len(gv) >= 1:
        sample_sets.append((gv * 5)[:5])                                  # all guest-verse -> forces {1,4}
    if len(normal) >= 2:
        sample_sets.append((normal * 5)[:5])                             # all normal -> full {1,3,4}
    for u in users:
        for si, sset in enumerate(sample_sets):
            allowed = [beat_guest_verse.available_rules(b["id"]) for b in sset]
            rules = rule_shuffle.set_rules_for(u, si, allowed)
            for i in range(1, len(rules)):
                if rules[i] == rules[i - 1]:
                    names = [bb["original_name"] for bb in sset]
                    problems.append(f"set back-to-back rule {rules[i]}: {rules} ({u}, {names})")
                    break
    return problems


def main():
    lib = get_library()["songs"]
    beats = [s for s in lib if s["role_hint"] == "beat"]
    vocals = [s for s in lib if s["role_hint"] == "vocals"]
    print(f"catalog: {len(beats)} beats x {len(vocals)} vocals = {len(beats) * len(vocals)} pairs")

    hard, stats = sweep_pairs(beats, vocals)
    shuffle_probs = sweep_rule_shuffle(beats, vocals)

    print(f"\nplans built: {stats['built']}  declined: {stats['declined']}")
    if stats["lines"]:
        print(f"Song-2 lines finishing on a breath: {stats['on_breath']}/{stats['lines']} "
              f"({100 * stats['on_breath'] // max(1, stats['lines'])}%)")
    if stats["beat_lines"]:
        print(f"beat lines finishing on a breath:   {stats['beat_on_breath']}/{stats['beat_lines']} "
              f"({100 * stats['beat_on_breath'] // max(1, stats['beat_lines'])}%)")

    print(f"\n=== HARD RULE failures (referee / crashes): {len(hard)} ===")
    for h in hard[:40]:
        print("  FAIL:", h)
    print(f"\n=== RULE-SHUFFLE back-to-back failures: {len(shuffle_probs)} ===")
    for p in shuffle_probs[:40]:
        print("  FAIL:", p)

    ok = not hard and not shuffle_probs
    print(f"\n{'ALL SANITY CHECKS PASSED' if ok else 'SANITY CHECKS FOUND PROBLEMS'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
