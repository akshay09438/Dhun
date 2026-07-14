"""Silent set-order scoring (feature 5 — the moat piece).

Given the mixes in a set, compute the order the app WOULD recommend — harmonic (camelot key
compatibility between adjacent mixes' beats) + an energy arc (build to a late peak, then resolve at the
end) — and LOG it against the order the user actually chose. Pure DATA COLLECTION:

  * it changes NOTHING the user experiences — the set is still built in the user's order;
  * it gates nothing and is background-only (the caller wraps it so a failure can never break a render);
  * zero cloud — it reads already-cached analyses and does arithmetic only.

The scoring is intentionally simple and will be refined FROM the data this collects; it is not a schema.
"""
from __future__ import annotations

import csv
from itertools import permutations
from pathlib import Path

from app.planner.fence import camelot_fit


def _key_adjacency(keys: list[str], order: list[int]) -> float:
    """Fraction of adjacent transitions in `order` whose beat keys are camelot-compatible (0..1).
    A single-beat set is all-compatible (1.0), so the energy arc decides — which is correct."""
    if len(order) < 2:
        return 1.0
    ok = sum(1 for a, b in zip(order, order[1:])
             if keys[a] and keys[b] and camelot_fit(keys[a], keys[b]))
    return ok / (len(order) - 1)


def _energy_arc(energies: list[float], order: list[int]) -> float:
    """How well the ordered energies match an ideal build-to-a-late-peak-then-resolve arc (0..1):
    a triangular template peaking ~80% through, scored by 1 - mean-squared-error to it."""
    n = len(order)
    if n < 2:
        return 1.0
    seq = [energies[i] for i in order]
    lo, hi = min(seq), max(seq)
    rng = (hi - lo) or 1.0
    norm = [(e - lo) / rng for e in seq]
    peak_at = 0.8 * (n - 1)  # ideal peak ~80% through the set, then resolve down
    template = [1.0 - abs(i - peak_at) / (n - 1) for i in range(n)]
    mse = sum((norm[i] - template[i]) ** 2 for i in range(n)) / n
    return max(0.0, 1.0 - mse)


def score_ordering(keys: list[str], energies: list[float], order: list[int],
                   w_key: float = 0.5, w_energy: float = 0.5) -> float:
    """Composite: harmonic adjacency + energy arc. Higher is better."""
    return w_key * _key_adjacency(keys, order) + w_energy * _energy_arc(energies, order)


def recommend_order(keys: list[str], energies: list[float]) -> tuple[list[int], float]:
    """Rank EVERY ordering and return (best order as indices, its score). N is small (a few mixes),
    so brute-force permutations are trivially fast."""
    idx = list(range(len(keys)))
    if len(idx) <= 1:
        return idx, 1.0
    best = max(permutations(idx), key=lambda o: score_ordering(keys, energies, list(o)))
    return list(best), score_ordering(keys, energies, list(best))


def log_set_pick(csv_path, mix_names: list[str], keys: list[str], energies: list[float],
                 user_order: list[int], when: str = "") -> dict:
    """Compute the app's recommended order, compare to the user's, and APPEND one row to a CSV.
    Returns the record (for tests/inspection). `user_order`/`app_order` are 0-indexed positions into
    `mix_names`. Data only — nothing here affects the rendered set."""
    app_order, app_score = recommend_order(keys, energies)
    user_score = score_ordering(keys, energies, user_order)
    rec = {
        "when": when,
        "n": len(mix_names),
        "mixes": " | ".join(mix_names),
        "user_order": ",".join(str(i) for i in user_order),
        "app_order": ",".join(str(i) for i in app_order),
        "match": user_order == app_order,
        "user_score": round(user_score, 4),
        "app_score": round(app_score, 4),
        "delta_app_minus_user": round(app_score - user_score, 4),
    }
    p = Path(csv_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists()
    with p.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rec.keys()))
        if new:
            w.writeheader()
        w.writerow(rec)
    return rec
