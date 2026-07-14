"""Silent set-order scoring (feature 5). These pin the scoring math and the CSV log; the integration
(build_set writes the set in the USER's order, then logs) is exercised by running build_set — here we
prove the module is pure data (ranks orderings, logs both picks) and touches no audio."""

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]  # tests -> api -> services -> repo
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from workers import set_score  # noqa: E402


def test_recommend_builds_to_a_late_peak_then_resolves():
    # Single-beat set (all one key) -> the energy arc decides. The recommended order should peak late
    # and end below the peak (resolve).
    keys = ["10B"] * 4
    energies = [0.2, 0.9, 0.5, 0.7]
    order, _score = set_score.recommend_order(keys, energies)
    seq = [energies[i] for i in order]
    assert seq[-1] < max(seq)                     # resolves — ends below the peak
    assert seq.index(max(seq)) >= len(seq) - 2    # peak is late (last or second-to-last slot)


def test_key_adjacency_prefers_compatible_neighbours():
    # Flat energy -> key adjacency is the only differentiator. 8A~9A are compatible; 2B clashes with
    # both, so an order that keeps the clash to one transition beats one that clashes on both.
    keys = ["8A", "9A", "2B"]
    energies = [0.5, 0.5, 0.5]
    good = set_score.score_ordering(keys, energies, [0, 1, 2])  # 8A->9A ok, 9A->2B clash
    bad = set_score.score_ordering(keys, energies, [0, 2, 1])   # 8A->2B clash, 2B->9A clash
    assert good > bad


def test_log_appends_both_picks_and_the_difference(tmp_path):
    csv = tmp_path / "set_order_log.csv"
    keys = ["10B"] * 3
    energies = [0.2, 0.9, 0.6]
    rec = set_score.log_set_pick(csv, ["A x a", "B x b", "C x c"], keys, energies, [0, 1, 2], when="t0")
    app_order = set_score.recommend_order(keys, energies)[0]
    assert rec["user_order"] == "0,1,2"
    assert rec["app_order"] == ",".join(str(i) for i in app_order)
    assert rec["match"] == ([0, 1, 2] == app_order)
    assert "delta_app_minus_user" in rec and "user_score" in rec and "app_score" in rec

    lines = csv.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0].startswith("when,n,mixes,user_order,app_order,match")  # header written once
    assert len(lines) == 2                                                  # header + one row
    set_score.log_set_pick(csv, ["A x a", "B x b", "C x c"], keys, energies, [2, 1, 0], when="t1")
    assert len(csv.read_text(encoding="utf-8").strip().splitlines()) == 3   # appended, no 2nd header


def test_empty_and_single_are_safe():
    assert set_score.recommend_order([], []) == ([], 1.0)
    assert set_score.recommend_order(["10B"], [0.5]) == ([0], 1.0)
