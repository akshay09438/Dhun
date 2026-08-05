"""Manual cache-eviction sweep for the Prompt-DJ data dir.

Frees ONLY regenerable render outputs (see app.storage._EVICTABLE_SUFFIXES) — never the catalog
(sources / stems / analyses / manifest / approved config / listening folders). Dry-run by DEFAULT
(reports what WOULD be freed, deletes nothing); pass --apply to actually delete.

Usage:
  services/api/.venv/Scripts/python.exe scripts/evict_cache.py                # dry-run report
  services/api/.venv/Scripts/python.exe scripts/evict_cache.py --apply        # delete to the default target
  services/api/.venv/Scripts/python.exe scripts/evict_cache.py --apply --target=5   # free up to 5 GB
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "services" / "api"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.config import settings          # noqa: E402
from app.storage import sweep, _free_gb  # noqa: E402

apply = "--apply" in sys.argv
target = next((float(a.split("=")[1]) for a in sys.argv if a.startswith("--target=")), 3.0)

print(f"data dir: {settings.data_dir}")
print(f"free now: {_free_gb(settings.data_dir):.2f} GB   target: {target} GB")
rep = sweep(target_free_gb=target, dry_run=not apply)
mode = "APPLIED" if apply else "DRY-RUN"
print(f"\n{mode}: {rep['evicted']} of {rep['candidates']} regenerable renders "
      f"({rep['freed_gb']} GB) -> free after: {rep['free_gb_after']} GB")
for f in rep["files"][:25]:
    print("   -", f)
if rep["evicted"] > 25:
    print(f"   ... and {rep['evicted'] - 25} more")
if not apply and rep["evicted"]:
    print("\nre-run with --apply to delete.")
