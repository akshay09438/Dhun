"""The generated marks layer must ADD, never override.

Founder's instruction, 2026-08-14: _"A similar pattern has to be followed for this. Nothing, no
single thing, has to change."_ The existing catalog sounds right because it runs on hand-marked
drops and hooks that were confirmed by ear. Wiring the remaining ~227 marks out of
`scripts/song_marks.csv` must therefore be purely ADDITIVE: a song that already carries a
hand-marked entry keeps it byte-for-byte, even where the CSV disagrees.

Rather than trust a one-time merge to get that right, precedence is structural: the hand-curated
dicts in `hooks.py` / `main_drops.py` are consulted FIRST and the generated table is only a
fallback. These tests pin that, so regenerating the table can never silently retune a song that
already works.
"""

from __future__ import annotations

from app.planner import hooks, main_drops
from app.planner import marks_generated as gen

# The eight songs whose CSV marks point at a genuinely DIFFERENT part of the song than the value
# already wired and ear-confirmed in the app (measured 2026-08-14: 7s to 50s apart). These are the
# exact values that must survive. If a future regeneration moves any of them, that is the bug this
# file exists to catch.
FROZEN_HOOKS = {
    "6ad6903592cd668502c5f4546618aec807c6eadb974fa6437fef7180fbffddc2": ((63.48, 90.13), "Tere Bina"),
    "84ff0d8b12455dc66e971874b64ae3b816d622f7fc947cfba12cca77fe6eea88": ((60.0, 80.0), "Tere Bin"),
    "ae132f3a444f5121d75097a44110a0323365e6dc4a8d0736a924c00b2ac210c1": ((53.25, 84.25), "With You"),
    "84e4ea36d2f3cb34f7e1beb4ce1bace077083994e700b7cc73347e2f5b5438f3": ((95.0, 125.0), "Nadan Parinde"),
    "f61ea8edc6c56a0a1da0de64d26768618e6007262fbca7738d8571ccfa92c7fa": ((31.66, 54.17), "Faded"),
    "3f260b5cadb5a20ca475f50553f4d8512ed2764ba9f4d7988f9c1e0111d25f4e": ((51.0, 70.0), "Closer"),
    "e6722353c4251a3f9af0a76ab620b22f61fa6e385846ae67073debafa6acf1ad": ((38.78, 69.81), "Wake Me Up"),
    "5c3ce60868f97c5657d32cc14a028b349fab07bfdf984c40f401790fd1c82375": ((82.0, 105.0), "Uff Teri Ada"),
}

FROZEN_DROPS = {
    "f61ea8edc6c56a0a1da0de64d26768618e6007262fbca7738d8571ccfa92c7fa": ([54.65, 76.36], "Faded"),
    "3f260b5cadb5a20ca475f50553f4d8512ed2764ba9f4d7988f9c1e0111d25f4e": ([31.0, 71.0], "Closer"),
    "e6722353c4251a3f9af0a76ab620b22f61fa6e385846ae67073debafa6acf1ad": ([38.31, 93.09], "Wake Me Up"),
}


# --------------------------------------------------------------- the promise: nothing changes
def test_hand_marked_hooks_are_never_overridden_by_the_generated_table():
    for sid, (expected, name) in FROZEN_HOOKS.items():
        assert hooks.hook_for(sid) == expected, (
            f"{name}: hook_for returned {hooks.hook_for(sid)}, expected the hand-marked {expected}. "
            f"The generated table must never win over a hand-marked entry."
        )


def test_hand_marked_drops_are_never_overridden_by_the_generated_table():
    for sid, (expected, name) in FROZEN_DROPS.items():
        assert main_drops.main_drops_for(sid) == expected, (
            f"{name}: main_drops_for returned {main_drops.main_drops_for(sid)}, "
            f"expected the hand-marked {expected}."
        )


def test_no_song_is_in_both_the_hand_table_and_the_generated_table():
    """The generator must SKIP anything already hand-marked, so the two tables cannot drift apart."""
    both_h = set(hooks.HOOKS) & set(gen.GEN_HOOKS)
    both_d = set(main_drops.MAIN_DROPS) & set(gen.GEN_MAIN_DROPS)
    assert not both_h, f"{len(both_h)} song(s) are hand-marked AND generated (hooks): {sorted(both_h)[:3]}"
    assert not both_d, f"{len(both_d)} song(s) are hand-marked AND generated (drops): {sorted(both_d)[:3]}"


# --------------------------------------------------------------- the point: the new marks reach the app
def test_a_generated_hook_is_used_when_the_song_has_no_hand_mark():
    sid = next(s for s in gen.GEN_HOOKS if s not in hooks.HOOKS)
    assert hooks.hook_for(sid) == gen.GEN_HOOKS[sid]


def test_a_generated_drop_is_used_when_the_song_has_no_hand_mark():
    sid = next(s for s in gen.GEN_MAIN_DROPS if s not in main_drops.MAIN_DROPS)
    assert main_drops.main_drops_for(sid) == gen.GEN_MAIN_DROPS[sid]


def test_an_unmarked_song_still_falls_back_cleanly():
    unknown = "0" * 64
    assert hooks.hook_for(unknown) is None      # planner uses vocal regions as-is, never a guess
    assert main_drops.main_drops_for(unknown) == []  # planner keeps automatic energy detection


# --------------------------------------------------------------- the data itself must be sane
def test_every_generated_hook_is_a_valid_forward_slice():
    for sid, (start, end) in gen.GEN_HOOKS.items():
        assert 0.0 <= start < end, f"{sid[:8]}: hook {(start, end)} is not a valid forward slice"


def test_every_generated_drop_is_a_positive_sorted_time():
    for sid, times in gen.GEN_MAIN_DROPS.items():
        assert times, f"{sid[:8]}: empty drop list would silently disable energy detection"
        assert all(t >= 0.0 for t in times), f"{sid[:8]}: negative drop time in {times}"
        assert times == sorted(times), f"{sid[:8]}: drops not sorted: {times}"


def test_every_generated_song_id_is_a_real_content_id():
    for sid in list(gen.GEN_HOOKS) + list(gen.GEN_MAIN_DROPS):
        assert len(sid) == 64 and all(c in "0123456789abcdef" for c in sid), f"bad id: {sid!r}"


def test_the_generated_table_actually_carries_the_bulk_of_the_marks():
    """Guards against a regeneration that silently produces an empty or tiny table."""
    assert len(gen.GEN_HOOKS) >= 90, f"only {len(gen.GEN_HOOKS)} generated hooks - expected ~103"
    assert len(gen.GEN_MAIN_DROPS) >= 110, f"only {len(gen.GEN_MAIN_DROPS)} generated drops - expected ~124"
