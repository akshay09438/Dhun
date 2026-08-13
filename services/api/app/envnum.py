"""Reading a positive number out of the environment, once, for everyone who needs one.

Extracted from `janitor.py` (2026-08-13) when `storage.py` needed the same behaviour for its
render-age window. Two copies of "parse a float, fall back loudly on rubbish" is the kind of
near-duplicate that drifts: one copy learns to reject zero and the other does not, and the two
knobs then behave differently for no reason a reader can see.

Always resolved at CALL time by the caller, never as a default argument — a default argument is
bound once at import, which silently freezes the value and makes the knob a decoration.
"""

from __future__ import annotations

import logging
import math
import os

log = logging.getLogger(__name__)


def env_float(name: str, default: float) -> float:
    """The positive, FINITE float in `name`, or `default` if it is unset, unparseable, or neither.

    Never raises: a mistyped environment variable must not stop the engine starting. It says what
    it ignored and what it used instead, because a silently ignored setting is worse than no
    setting — the operator believes it took effect.

    `math.isfinite` is load-bearing, not belt-and-braces. `float("nan")` parses, and **every**
    comparison against NaN is False — so a bare `val <= 0` guard waves it through as "positive",
    and every downstream `x < threshold` then reads False as well. Found by adversarial review
    2026-08-13: with NaN here, `storage.sweep_old`'s age check silently matched EVERY file,
    including a render being written that second, straight through the in-flight floor that is
    supposed to be unbreachable. `float("inf")` parses too, and would put `interval_secs()` into an
    `asyncio.sleep(inf)` the janitor never wakes from. Both must die at the door: this value ends up
    deciding what gets deleted.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        val = float(raw)
    except ValueError:
        log.warning("%s=%r is not a number — using the default %.1f", name, raw, default)
        return default
    if not math.isfinite(val) or val <= 0:
        log.warning("%s=%r must be a positive, finite number — using the default %.1f",
                    name, raw, default)
        return default
    return val
