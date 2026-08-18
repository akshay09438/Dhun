"""Session-wide test isolation: the suite must never be able to reach the real data folder.

WHY THIS FILE EXISTS, with the measurement that caused it (2026-08-13). The founder's real
`services/api/data` went from **39 evictable renders / 1.21 GB to zero** across one full-suite run,
free disk landing just under `storage._TARGET_FREE_GB` (3.0) - `storage.sweep()`'s exact signature -
with no API server running. It is the most likely explanation for the founder-made mix that
"vanished" on 2026-08-12 and was recorded against the disk janitor.

THE MECHANISM, and why per-test isolation could never have fixed it:
  * `app.config.Settings` is a FROZEN dataclass and every module does `from app.config import
    settings`, so they share one instance. A test redirects it per module, per test, with
    `monkeypatch.setattr(mod, "settings", dataclasses.replace(...))`.
  * `monkeypatch` undoes that at teardown, restoring the REAL settings object.
  * But renders do not run on the test's thread. `renderq` hands them to daemon workers
    (`renderq.py:211`), and `maybe_sweep()` runs inside the job (`mix.py:469`, `set.py:240`).
  * So a render still going when its test ends reads the restored, REAL `settings.data_dir` and
    sweeps the founder's actual mixes.

No individual test was written wrongly. The protection was scoped to the wrong LIFETIME. Redirecting
once for the whole session fixes it at the root: a per-test teardown now restores to this session's
throwaway folder, so a late thread can only ever find a temp directory.

Guarded by `tests/test_data_dir_isolation.py`, which fails if this file is removed or weakened.
"""

from __future__ import annotations

import atexit
import dataclasses
import os
import shutil
import tempfile
from pathlib import Path

import app.config as _config

# The real folder, captured BEFORE the redirect below - it is what we are protecting.
_REAL_DATA_DIR = _config.settings.data_dir

# ONE throwaway folder for the whole session, created before any test module is imported.
_SESSION_DATA_DIR = Path(tempfile.mkdtemp(prefix="promptdj-test-data-"))


def _redirect(target: Path) -> None:
    """Point `app.config.settings` AND any module that already captured it at `target`.

    Modules do `from app.config import settings`, which binds the OBJECT, not the module - so
    rebinding `app.config.settings` alone would miss anything imported earlier. conftest is imported
    before the test modules, so in practice the loop finds little; it is here so the guarantee does
    not quietly depend on import order.
    """
    import sys

    _config.settings = dataclasses.replace(_config.settings, data_dir=target)
    for mod in list(sys.modules.values()):
        name = getattr(mod, "__name__", "")
        if name == "app" or name.startswith("app."):
            s = getattr(mod, "settings", None)
            if s is not None and getattr(s, "data_dir", None) == _REAL_DATA_DIR:
                mod.settings = _config.settings


# Files that must NEVER be linked in, however read-only they look.
#
# `upload_spend.json` IS THE PAID-ATTEMPT COUNTER, and linking it made the suite inherit the
# founder's real Replicate spending. `max_paid_upload_attempts` is 40, so the tests started at
# whatever the founder had used and climbed from there: measured 2026-08-18, at a real counter of
# 3 the full suite finished just under the ceiling and was green, and after three more real uploads
# took it to 6 the suite crossed 40 partway through and six upload tests failed with 429 - refused
# for having no imaginary money left, nothing to do with what they were testing. The suite's result
# tracked the founder's bank balance.
#
# The real file was never corrupted, but only because `spend.record_attempt` writes through an
# atomic replace, which breaks the hard link rather than writing through it. The caveat below says
# "nothing in the suite has a reason to overwrite" a linked file; that had quietly stopped being
# true, and this is what makes it true again.
_NEVER_LINK = frozenset({"upload_spend.json"})


def _link_readonly_catalog(src: Path, dst: Path) -> int:
    """HARD-LINK the catalog INPUTS into the session folder, so the real-audio end-to-end tests keep
    running instead of silently turning into skips.

    Without this, `test_effect_pool_e2e.py` (5 tests) and `test_rule3_parked.py` (1) skip on their
    own "real cached audio not present under data/" guard - they would still report green while
    testing nothing, which is the exact hollow-green this project refuses.

    Only files the sweep can NEVER delete are linked: anything ending in `_EVICTABLE_SUFFIXES` (the
    renders) is deliberately left out, so a sweep during a test finds nothing of the founder's to
    take - by construction, not by care.

    Hard links, not copies: the catalog is gigabytes and a link costs nothing. A link is also SAFER
    than a copy here, because `unlink` removes a directory entry and never the file's contents - so
    even a deletion cannot harm the original.

    THE ONE CAVEAT, stated plainly: a hard link shares the file's CONTENTS, so a test that opened
    one of these paths for WRITING would modify the real catalog file. Nothing does today - the
    suite writes analyses and stems under invented 64-hex ids, never a real song's - and only inputs
    are linked, which nothing in the suite has a reason to overwrite.
    """
    from app.storage import _EVICTABLE_SUFFIXES

    linked = 0
    if not src.exists():
        return 0
    for p in src.iterdir():
        if not p.is_file() or p.name.endswith(_EVICTABLE_SUFFIXES):
            continue
        if p.name in _NEVER_LINK:
            continue
        try:
            os.link(p, dst / p.name)
            linked += 1
        except OSError:
            pass  # locked or cross-volume: that file simply is not available to the read-only tests
    return linked


_SESSION_DATA_DIR.mkdir(parents=True, exist_ok=True)
_redirect(_SESSION_DATA_DIR)
_LINKED_CATALOG_FILES = _link_readonly_catalog(_REAL_DATA_DIR, _SESSION_DATA_DIR)


@atexit.register
def _cleanup() -> None:
    """Remove the session folder. Only links and test-made files live here, so this can never
    delete real audio - unlinking a hard link leaves the original untouched."""
    shutil.rmtree(_SESSION_DATA_DIR, ignore_errors=True)
