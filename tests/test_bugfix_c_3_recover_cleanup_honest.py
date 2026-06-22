"""Round-3 fix C-3 — _recover_from_crash_locked partial-rmtree honesty (Lens M).

Pins the behavior promoted from finding M-2: when ``shutil.rmtree``
fails partway through cleaning an orphan evidence dir, the recovery
function must surface ``cleanup_failed=True`` and a ``cleanup_error``
string rather than silently swallowing the OSError and clearing the
marker.

The pre-fix code did::

    try:
        shutil.rmtree(evidence_dir)
    except OSError:
        pass
    clear_gate_marker(project_root)

The operator saw a "successful" recovery (no marker, recovered=True)
even though half-deleted evidence was left on disk with no audit
signal.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_automator.core.gate_orchestrator import recover_from_crash


class RecoverCleanupHonestyTests(unittest.TestCase):
    """Pin Fix C-3: rmtree OSError must NOT be silently swallowed."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # Write a healthy marker pointing at a gate_id with no verdict.
        marker_path = self.root / "_bmad" / "gate" / "gate-in-progress.json"
        marker_path.parent.mkdir(parents=True)
        marker_path.write_text(
            json.dumps({
                "gate_id": "orphan-gate",
                "commit_sha": "abc123",
                "started_at": "2026-06-22T12:00:00Z",
                # Intentionally omit pid so the liveness check
                # falls through to "legacy marker == dead" branch.
            }) + "\n",
            encoding="utf-8",
        )
        # Place an orphan evidence dir under that gate_id.
        evidence_dir = (
            self.root / "_bmad" / "gate" / "evidence" / "orphan-gate"
        )
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "leftover.json").write_text(
            '{"v": 1}', encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_rmtree_failure_surfaces_cleanup_error(self) -> None:
        # Patch shutil.rmtree (the module-level binding inside
        # gate_orchestrator) so the orphan cleanup raises OSError.
        with mock.patch(
            "story_automator.core.gate_orchestrator.shutil.rmtree",
            side_effect=OSError("simulated permission denied during rmtree"),
        ):
            result = recover_from_crash(self.root)

        # Recovery semantics: the marker had no live PID, so legacy
        # behaviour is "recovered=True". Preserve that.
        self.assertTrue(result["recovered"])
        # The critical new field: operator-visible cleanup error.
        self.assertTrue(
            result.get("cleanup_failed", False),
            "cleanup_failed must surface when rmtree raised",
        )
        self.assertIn("cleanup_error", result)
        self.assertIn("permission denied", result["cleanup_error"])
        # The marker MUST still be cleared regardless — the audit
        # contract is that recovery never leaves a stale marker.
        self.assertFalse(
            (self.root / "_bmad" / "gate" / "gate-in-progress.json").exists()
        )

    def test_rmtree_success_does_not_emit_cleanup_failed(self) -> None:
        # Happy path: rmtree succeeds; the result must NOT include
        # ``cleanup_failed`` (omitted field, not False) so the new
        # surface is strictly additive and existing callers reading
        # via ``result.get('cleanup_failed', False)`` keep working.
        result = recover_from_crash(self.root)
        self.assertTrue(result["recovered"])
        self.assertNotIn(
            "cleanup_failed", result,
            "cleanup_failed must be absent on successful cleanup",
        )
        self.assertNotIn("cleanup_error", result)
        # Evidence dir is gone, marker is gone.
        self.assertFalse(
            (self.root / "_bmad" / "gate" / "evidence" / "orphan-gate").exists()
        )
        self.assertFalse(
            (self.root / "_bmad" / "gate" / "gate-in-progress.json").exists()
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
