"""K-5: quarantine-then-rmtree-outside-lock + crash-resilient janitor.

Extracted from :mod:`evidence_io` to keep the parent module under the
CLAUDE.md 500-LOC soft limit (Conventions / shared invariant #5). The
parent's K-2 evidence-cache split (see :mod:`evidence_cache`) shaved a
small amount of LOC but later commits (J-03 marker liveness, K-5
quarantine janitor, gate-marker contract enforcement) grew the parent
back over the soft cap. The K-5 cleanup helpers here share zero state
with the persist/load core, making this the cheapest cut.

``_bmad/gate/cleanup/`` is the staging ground for orphan evidence dirs
that ``_recover_from_crash_locked`` has renamed under the gate lock but
not yet ``shutil.rmtree``-d. The path is intentionally a sibling of
``evidence/`` (NOT a child) so listing ``evidence/`` for Merkle
reverification never sees in-flight quarantined bundles, and so a
misbehaving rmtree in cleanup can't damage live evidence.

Because rename inside the gate lock is O(1) but rmtree can take seconds
on large bundles, deferring the rmtree to outside the lock unblocks
concurrent ``run_production_gate`` callers (bug K-5). The janitor exists
to mop up cleanup subdirs orphaned by a crash between rename and rmtree.

Public surface is re-exported by :mod:`evidence_io` so existing callers
keep working without import changes.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .utils import ensure_dir


_GATE_CLEANUP_DIRNAME = "cleanup"


def get_gate_cleanup_root(project_root: str | Path) -> Path:
    """Return the K-5 cleanup root, creating it lazily if missing.

    The cleanup root is ``<project_root>/_bmad/gate/cleanup/``. It is the
    single staging ground for orphan evidence dirs being held for an
    outside-lock ``shutil.rmtree``. Living inside ``_bmad/gate/`` (same
    filesystem as ``evidence/``) means ``os.rename`` from
    ``evidence/<gate_id>/`` into here can never fail with EXDEV.

    Idempotent — safe to call on a fresh project root.
    """
    path = Path(project_root) / "_bmad" / "gate" / _GATE_CLEANUP_DIRNAME
    ensure_dir(path)
    return path


def run_cleanup_janitor(project_root: str | Path) -> dict[str, Any]:
    """Best-effort rmtree of every subdir under the K-5 cleanup root.

    Designed to run on ``run_production_gate`` startup BEFORE the gate
    lock is acquired — the subdirs here are by construction unreferenced
    (anything that needed them has already renamed them out of the live
    tree), so the janitor cannot race the gate lifecycle.

    Idempotent and resilient:
    - Missing cleanup root => no-op, returns ``swept=0``.
    - Per-subdir ``try/except OSError`` so one corrupted subdir (e.g.
      Windows read-only file, partial rmtree from a concurrent
      crashed process) does not block sweeping the others.

    Returns a small descriptor ``{"swept": int, "failed": list[str]}``
    primarily for tests; callers in production typically ignore the
    return value because failures are non-fatal.
    """
    root = Path(project_root) / "_bmad" / "gate" / _GATE_CLEANUP_DIRNAME
    if not root.is_dir():
        return {"swept": 0, "failed": []}
    swept = 0
    failed: list[str] = []
    try:
        children = list(root.iterdir())
    except OSError:
        # Cleanup root unreadable - surface via empty success rather than
        # raising; the next startup will retry.
        return {"swept": 0, "failed": []}
    for child in children:
        if not child.is_dir():
            # Stray file in the cleanup root - best-effort unlink so we
            # don't accumulate noise. Failures are non-fatal.
            try:
                child.unlink()
            except OSError:
                failed.append(str(child))
            continue
        try:
            shutil.rmtree(child)
            swept += 1
        except OSError:
            # Corrupted subdir, permission denied, in-progress rmtree by
            # another process - skip and move on.
            failed.append(str(child))
    return {"swept": swept, "failed": failed}
