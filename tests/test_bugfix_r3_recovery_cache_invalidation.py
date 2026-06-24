"""Round-3 fix — recovery rename must invalidate evidence cache.

Pins the behavior promoted from the cache-staleness finding: when
``_recover_from_crash_locked`` atomically relocates an orphan evidence
bundle into ``_bmad/gate/cleanup/`` (line 379) — or when
``_quarantine_corrupted_marker`` relocates it into
``_bmad/gate/quarantine/`` (line 195) — the in-process
``cached_load_evidence_bundle`` cache must be invalidated for that
``gate_id`` so subsequent reads do not silently serve pre-rename
records.

The contract from ``evidence_cache.py:11-17`` states ``persist`` is the
single source of cache invalidation, but a recovery rename moves the
bundle out from under any cache entry warmed before the rename — that
violates the invariant unless we mirror the invalidation hook at both
recovery rename sites.

Pre-fix reproducer (would fail on the unfixed code):

1. Persist 1 record for ``g1abcdef`` via ``persist_evidence_record``.
2. Warm the cache via ``cached_load_evidence_bundle`` (returns 1
   record, primes ``_CACHE``).
3. Write a legacy marker (no pid → recovery treats as dead) pointing at
   ``g1abcdef`` and call ``recover_from_crash`` — the orphan evidence
   dir is atomically renamed into ``_bmad/gate/cleanup/``.
4. ``load_evidence_bundle`` returns ``[]`` (disk truth).
5. PRE-FIX: ``cached_load_evidence_bundle`` STILL returns the 1-record
   stale bundle because the rename never invalidated the cache.
6. POST-FIX: ``cached_load_evidence_bundle`` returns ``[]`` — matches
   the disk.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_automator.core.evidence_cache import (
    cached_load_evidence_bundle,
    invalidate_all_evidence_cache,
)
from story_automator.core.evidence_io import (
    load_evidence_bundle,
    persist_evidence_record,
)
from story_automator.core.gate_orchestrator import recover_from_crash
from story_automator.core.gate_schema import make_evidence_record


def _seed_record(
    project_root: Path,
    gate_id: str,
    *,
    tool: str = "ruff",
    collector: str = "ruff",
) -> None:
    """Persist a minimal evidence record so the bundle is non-empty."""
    rec = make_evidence_record(
        category="correctness",
        collector=collector,
        tool=tool,
        status="ok",
    )
    persist_evidence_record(project_root, gate_id, rec)


class RecoveryCacheInvalidationTests(unittest.TestCase):
    """Pin: recovery rename invalidates the in-process evidence cache."""

    def setUp(self) -> None:
        # Fresh cache so the per-key generation counter starts at zero
        # and the assertions below are independent of test ordering.
        invalidate_all_evidence_cache()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(invalidate_all_evidence_cache)
        self.root = Path(self._tmp.name)

    def _write_dead_marker(self, gate_id: str) -> None:
        """Write a legacy marker (no pid → recovery treats it as dead)."""
        marker_path = (
            self.root / "_bmad" / "gate" / "gate-in-progress.json"
        )
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(
            json.dumps({
                "gate_id": gate_id,
                "commit_sha": "deadbeef",
                "started_at": "2026-06-22T12:00:00Z",
            }) + "\n",
            encoding="utf-8",
        )

    def test_recovery_rename_invalidates_warm_cache(self) -> None:
        gate_id = "g1abcdef"
        # 1) Persist a record so the bundle is non-empty.
        _seed_record(self.root, gate_id)
        # 2) Warm the cache (now contains 1-record list for gate_id).
        warm = cached_load_evidence_bundle(self.root, gate_id)
        self.assertEqual(len(warm), 1)
        # 3) Legacy dead marker → recover_from_crash will atomically
        #    rename the orphan evidence dir into _bmad/gate/cleanup/.
        self._write_dead_marker(gate_id)
        result = recover_from_crash(self.root)
        self.assertTrue(result["recovered"])
        self.assertEqual(result["gate_id"], gate_id)
        # 4) Disk truth: evidence dir is gone (or empty).
        self.assertEqual(load_evidence_bundle(self.root, gate_id), [])
        # 5) Cache truth: MUST agree with disk after recovery.
        # PRE-FIX this returned the 1-record stale bundle silently.
        cached_after = cached_load_evidence_bundle(self.root, gate_id)
        self.assertEqual(
            cached_after, [],
            "cached_load_evidence_bundle must return [] after recovery "
            "rename — recovery rename must mirror persist's invalidation "
            "hook so the cache cannot serve pre-rename records",
        )

    def test_quarantine_rename_invalidates_warm_cache(self) -> None:
        gate_id = "g2bcdef0"
        # 1) Persist + warm.
        _seed_record(self.root, gate_id)
        warm = cached_load_evidence_bundle(self.root, gate_id)
        self.assertEqual(len(warm), 1)
        # 2) Corrupt the marker but keep the gate_id salvageable from
        #    raw bytes so the targeted-quarantine branch fires (the
        #    code path that calls evidence_dir.rename at line 195).
        marker_path = (
            self.root / "_bmad" / "gate" / "gate-in-progress.json"
        )
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        # Trailing garbage after a valid-looking gate_id fragment so
        # best_effort_extract_gate_id finds the gate_id but
        # read_gate_marker still raises GateMarkerCorruptedError.
        marker_path.write_bytes(
            (
                '{"gate_id":"' + gate_id + '",not-json-after-this'
            ).encode("utf-8")
        )
        # 3) Recovery enters the quarantine path → evidence_dir is
        #    renamed into _bmad/gate/quarantine/<ts>/evidence/<gate_id>.
        result = recover_from_crash(self.root)
        self.assertFalse(result["recovered"])
        self.assertTrue(result["quarantined"])
        # 4) Disk: bundle is empty (the dir moved into quarantine).
        self.assertEqual(load_evidence_bundle(self.root, gate_id), [])
        # 5) Cache must mirror disk — pre-fix would return the stale
        # 1-record bundle.
        cached_after = cached_load_evidence_bundle(self.root, gate_id)
        self.assertEqual(
            cached_after, [],
            "cached_load_evidence_bundle must return [] after the "
            "quarantine rename — the cache contract requires "
            "invalidation on any event that mutates the bundle "
            "from this process",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
