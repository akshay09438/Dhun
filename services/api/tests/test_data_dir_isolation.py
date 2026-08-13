"""The test suite must never be able to touch the REAL data folder.

Why this file exists, with the measurement that caused it (2026-08-13): the founder's real
`services/api/data` went from **39 evictable renders / 1.21 GB to zero** across one full-suite run,
free disk landing just under `_TARGET_FREE_GB = 3.0` - `storage.sweep()`'s exact signature - with no
API server running. It is the most likely explanation for the founder-made mix that "vanished" on
2026-08-12 and was recorded against the disk janitor.

THE MECHANISM, and why per-test isolation was never enough:
  * `app.config.Settings` is a FROZEN dataclass, and every module does `from app.config import
    settings`, so they all share one instance. A test redirects it with
    `monkeypatch.setattr(mod, "settings", dataclasses.replace(...))` - per module, per test.
  * `monkeypatch` undoes that at teardown, restoring the REAL settings object.
  * But renders do not run on the test's thread. `renderq` hands them to daemon workers
    (`renderq.py:211`), and `maybe_sweep()` runs inside the job (`mix.py:469`, `set.py:240`).
  * So a job still running when its test ends reads the restored, REAL `settings.data_dir` - and
    sweeps the founder's actual renders. No individual test is written wrongly; the isolation is
    simply scoped to the wrong lifetime.

The fix is in `services/api/conftest.py`: the redirect is applied ONCE for the whole session, before
any test runs, so a per-test `monkeypatch` teardown restores to the session's throwaway folder
rather than to the real one. A late thread can then only ever find a temp directory.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from pathlib import Path

from app import storage
from app.config import Settings

# The real folder, computed the same way `app/config.py` computes its default - deliberately NOT
# read from `settings`, which is the very thing under test.
REAL_DATA_DIR = Path(storage.__file__).resolve().parent.parent / "data"

# Filled in by the thread started in the first test, read by the second. A module global because
# the whole point is to observe what a thread sees AFTER its test has finished and torn down.
_seen: dict[str, Path] = {}
_release = threading.Event()
_thread: threading.Thread | None = None


def test_a_render_thread_outliving_its_test_starts(tmp_path, monkeypatch):
    """Stand in for a queued render: redirect the data dir exactly as every test here does, start
    a worker, and let the test END while that worker is still going."""
    global _thread
    monkeypatch.setattr(
        storage, "settings", dataclasses.replace(storage.settings, data_dir=tmp_path)
    )
    assert storage.settings.data_dir == tmp_path  # the redirect is in force DURING the test

    def late_worker() -> None:
        _release.wait(timeout=30)          # still running when the test below begins
        _seen["data_dir"] = storage.settings.data_dir

    _thread = threading.Thread(target=late_worker, daemon=True)
    _thread.start()
    # test ends here -> monkeypatch tears down -> `storage.settings` is restored


def test_that_thread_can_never_see_the_real_data_folder():
    """THE BUG, stated as the invariant it broke.

    Before the fix this failed with `data_dir` equal to the founder's real `services/api/data`,
    which is the folder `maybe_sweep()` would then have swept."""
    _release.set()
    assert _thread is not None
    _thread.join(timeout=30)
    assert not _thread.is_alive(), "the worker never finished; the test proves nothing"

    seen = _seen.get("data_dir")
    assert seen is not None, "the worker never recorded what it saw"
    assert seen.resolve() != REAL_DATA_DIR.resolve(), (
        f"a render thread outliving its test saw the REAL data folder ({seen}). "
        "maybe_sweep() on that thread deletes the founder's finished mixes."
    )


def test_the_default_settings_object_itself_points_somewhere_disposable():
    """The belt to the braces above. Even code that imports `settings` freshly - or reads it
    before any monkeypatch is applied - must not be aimed at the real folder during a test run."""
    from app.config import settings as fresh

    assert fresh.data_dir.resolve() != REAL_DATA_DIR.resolve(), (
        "app.config.settings still points at the real data folder during the test session"
    )


def test_a_sweep_running_on_a_late_thread_cannot_reach_a_real_render(tmp_path, monkeypatch):
    """The consequence, made concrete: a full pressure sweep with a target it can never reach
    takes everything it is allowed to take. It must find nothing of the founder's.

    Free disk is forced far below the floor so the sweep genuinely runs - this is the exact
    condition that made it fire during a real suite run, when temp WAVs filled the disk."""
    monkeypatch.setattr(storage, "_free_gb", lambda path: 0.1)
    canary = REAL_DATA_DIR / "isolation-canary.mix.wav"
    canary.parent.mkdir(parents=True, exist_ok=True)
    canary.write_bytes(b"x")
    import os
    os.utime(canary, (time.time() - 86400,) * 2)   # old enough to be a candidate
    try:
        storage.sweep(target_free_gb=999.0)        # unreachable target: takes all it may
        assert canary.exists(), (
            "the sweep deleted a file in the REAL data folder during a test run"
        )
    finally:
        canary.unlink(missing_ok=True)
