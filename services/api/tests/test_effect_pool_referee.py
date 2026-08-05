"""Acceptance tests for the effect-pool REFEREE rule (validate._pool_violations) and the
'one vocabulary, three readers' cross-check.

Independent of the implementation: uses real Placement models and asserts the R1 tail rule
directly on the named referee helper. The vocabulary cross-check guards the three independent
copies (engine / referee / planner) against silent drift AND against all three drifting
together away from the human-approved vocabulary.

Criteria covered here:
  4 R1 TAIL RULE — reject a tail-extender (throw/freeze) on a non-final placement; accept it on the
    final (max-anchor) placement; reject unknown space/width names; pass when space/width are None.
  7 VOCABULARY AGREEMENT — render.py, validate.py, plan.py agree, and match the approved sets.
"""

import sys
from pathlib import Path

from app.models import Placement
from app.planner import validate

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def _pl(anchor, space=None, width=None):
    return Placement(anchor=anchor, vocal_src=(0.0, 4.0), space=space, width=width)


def _has_tail_violation(violations):
    return any("tail-extending" in v for v in violations)


def _has_unknown_violation(violations):
    return any("unknown" in v for v in violations)


# ---------------------------------------------------------------- Criterion 4: R1 tail rule
def test_tail_extender_on_a_non_final_placement_is_rejected():
    """AC4: a tail-extender (throw/freeze) on a NON-final placement is rejected — its tail would ring
    over the next vocal (R1). Final placement is the LATEST anchor; here the throw sits on the earlier
    one, which is illegal."""
    for tail in ("throw", "freeze"):
        placements = [_pl(8.0, space=tail), _pl(40.0)]  # tail on the EARLIER (non-final) placement
        v = validate._pool_violations(placements)
        assert _has_tail_violation(v), f"'{tail}' on a non-final placement was not rejected: {v}"


def test_tail_extender_on_the_final_placement_is_accepted():
    """AC4: the SAME tail-extender on the FINAL (max-anchor) placement is legal — nothing follows it."""
    for tail in ("throw", "freeze"):
        placements = [_pl(8.0), _pl(40.0, space=tail)]  # tail on the LATEST anchor
        v = validate._pool_violations(placements)
        assert not _has_tail_violation(v), f"'{tail}' on the final placement was wrongly rejected: {v}"


def test_final_is_derived_by_max_anchor_not_list_order():
    """AC4 (sharper): 'final' is the MAX anchor, re-derived independently — not the last list element.
    A tail-extender on the max-anchor placement is legal even when that placement is listed FIRST."""
    for tail in ("throw", "freeze"):
        placements = [_pl(50.0, space=tail), _pl(10.0), _pl(30.0)]  # max anchor is listed first
        v = validate._pool_violations(placements)
        assert not _has_tail_violation(v), f"max-anchor '{tail}' listed first was wrongly rejected: {v}"
        # ...and putting it on a non-max anchor that happens to be LAST in the list is still illegal
        placements2 = [_pl(50.0), _pl(30.0), _pl(10.0, space=tail)]  # tail on the smallest anchor (listed last)
        assert _has_tail_violation(validate._pool_violations(placements2))


def test_length_preserving_reverb_is_legal_on_any_placement():
    """AC4 control: a length-preserving reverb (room/hall/plate/predelay) is legal on ANY placement,
    interior or final — only the tail-extenders are final-only."""
    for sp in ("room", "hall", "plate", "predelay"):
        placements = [_pl(8.0, space=sp), _pl(40.0, space=sp)]
        assert validate._pool_violations(placements) == [], f"reverb '{sp}' on interior wrongly rejected"


def test_unknown_space_and_width_names_are_rejected():
    """AC4: an unknown space or width name is rejected loudly (the engine would silently render
    nothing) — mirroring the _KNOWN_FX fail-loud rule."""
    assert _has_unknown_violation(validate._pool_violations([_pl(8.0, space="cathedral")]))
    assert _has_unknown_violation(validate._pool_violations([_pl(8.0, width="triple")]))
    assert _has_unknown_violation(validate._pool_violations([_pl(8.0, space="ROOM")]))  # case-sensitive


def test_double_is_the_only_legal_width():
    """AC4 control: width='double' is legal; anything else is unknown."""
    assert validate._pool_violations([_pl(8.0, width="double")]) == []


def test_no_space_or_width_passes_cleanly():
    """AC4: with space/width None on every placement there are NO pool checks — the pre-pool
    behaviour. An empty placement list is also clean."""
    assert validate._pool_violations([_pl(8.0), _pl(40.0)]) == []
    assert validate._pool_violations([]) == []


def test_a_full_legal_take_is_clean():
    """AC4 integration: a realistic take — interior reverb everywhere + a final tail-extender + the
    doubler — passes the referee with no violations."""
    placements = [_pl(8.0, space="hall", width="double"),
                  _pl(24.0, space="hall", width="double"),
                  _pl(48.0, space="freeze", width="double")]  # tail-extender on the final only
    assert validate._pool_violations(placements) == []


# ---------------------------------------------------------------- Criterion 7: vocabulary agreement
def test_three_readers_agree_on_the_vocabulary():
    """AC7: the engine (render.py), the referee (validate.py) and the planner (plan.py) each keep
    their OWN copy of the SPACE / tail-extender / WIDTH vocabulary. This cross-check asserts all three
    AGREE — the 'one list, three readers' guard against silent drift (the classic hole where the
    planner emits an effect the engine or referee has never heard of)."""
    from app.planner import plan
    from workers import render

    render_lp = set(render._POOL_SPACE_LENGTH_PRESERVING)
    render_tail = set(render._POOL_SPACE_TAIL_EXTENDING)
    render_width = set(render._POOL_WIDTH)

    validate_lp = set(validate._POOL_SPACE_LENGTH_PRESERVING)
    validate_tail = set(validate._POOL_SPACE_TAIL_EXTENDING)
    validate_width = set(validate._POOL_WIDTH)

    plan_lp = set(plan._POOL_SPACE_INTERIOR)
    plan_tail = set(plan._POOL_SPACE_FINAL)
    plan_width = set(plan._POOL_WIDTH)

    assert render_lp == validate_lp == plan_lp, (
        f"length-preserving spaces disagree: render={render_lp} validate={validate_lp} plan={plan_lp}")
    assert render_tail == validate_tail == plan_tail, (
        f"tail-extenders disagree: render={render_tail} validate={validate_tail} plan={plan_tail}")
    assert render_width == validate_width == plan_width, (
        f"widths disagree: render={render_width} validate={validate_width} plan={plan_width}")
    # the planner's tail SET helper must match its own FINAL list, too
    assert set(plan._POOL_SPACE_TAIL) == plan_tail


def test_vocabulary_matches_the_approved_sets():
    """AC7 (the anchor): a cross-check between three copies passes vacuously if all three drift TOGETHER
    away from the spec. Pin the vocabulary to the human-approved sets so a coordinated rename/removal is
    still caught: SPACE reverbs = {room,hall,plate,predelay}, tail-extenders = {throw,freeze},
    WIDTH = {double}."""
    from workers import render

    assert set(render._POOL_SPACE_LENGTH_PRESERVING) == {"room", "hall", "plate", "predelay"}
    assert set(render._POOL_SPACE_TAIL_EXTENDING) == {"throw", "freeze"}
    assert set(render._POOL_WIDTH) == {"double"}
    # the referee's combined SPACE set is the union of the two (no stray extra names)
    assert set(validate._POOL_SPACE) == {"room", "hall", "plate", "predelay", "throw", "freeze"}
