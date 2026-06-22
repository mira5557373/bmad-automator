"""Round-3 fix C-1 — _quarantine_corrupted_marker truthful mkdir failure (Lens M).

Pins the behavior promoted from finding M-1: when the quarantine root
``mkdir`` fails, the returned dict must NOT claim ``quarantined=True``.
Instead it surfaces ``quarantined=False`` plus a ``quarantine_error``
string so the operator can investigate.

The audit-floor MarkerCorruptionInvariant asserts that
``quarantined=True`` IMPLIES the evidence has been moved. The old code
violated that implication on mkdir failure by returning quarantined=True
even when no rename ever ran.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_automator.core.gate_orchestrator import recover_from_crash


class QuarantineMkdirHonestyTests(unittest.TestCase):
    """Pin Fix C-1 behavior: lying about quarantine success is forbidden."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        marker = self.root / "_bmad" / "gate" / "gate-in-progress.json"
        marker.parent.mkdir(parents=True)
        # Marker with a recognizable gate_id but invalid JSON tail.
        marker.write_text(
            '{"gate_id": "broken-gate", "commit_sha": "x", invalid}',
            encoding="utf-8",
        )
        # Place a stub evidence dir under the salvageable gate_id.
        evidence_dir = self.root / "_bmad" / "gate" / "evidence" / "broken-gate"
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "stub.json").write_text(
            '{"v": 1}', encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_mkdir_failure_returns_quarantined_false_with_error(self) -> None:
        # Patch Path.mkdir on the quarantine root path so the inner mkdir
        # call raises. We use a side_effect that fails only when the path
        # contains "quarantine" — every other mkdir (setup, marker parent)
        # was already done in setUp via real fs ops.
        real_mkdir = Path.mkdir

        def selective_mkdir(self_path: Path, *args: object, **kwargs: object) -> None:
            if "quarantine" in str(self_path):
                raise OSError("simulated disk full during quarantine")
            return real_mkdir(self_path, *args, **kwargs)

        with mock.patch.object(Path, "mkdir", new=selective_mkdir):
            result = recover_from_crash(self.root)

        # Recovery status unchanged: marker corruption keeps recovered=False.
        self.assertFalse(result["recovered"])
        # The critical assertion: quarantined MUST be False when mkdir failed.
        self.assertFalse(
            result.get("quarantined", True),
            "quarantined=True is a lie when mkdir failed and nothing moved",
        )
        # The operator-visible error string must be present.
        self.assertIn("quarantine_error", result)
        self.assertIn("disk full", result["quarantine_error"])
        # The corruption_reason field is still emitted for audit chaining.
        self.assertIn("corruption_reason", result)

    def test_mkdir_success_still_reports_quarantined_true(self) -> None:
        # No injection — the happy path must keep returning quarantined=True
        # to preserve the audit-floor invariant.
        result = recover_from_crash(self.root)
        self.assertFalse(result["recovered"])
        self.assertTrue(result["quarantined"])
        self.assertIn("quarantine_dir", result)
        # The original evidence file MUST have been moved to quarantine.
        original = (
            self.root / "_bmad" / "gate" / "evidence" / "broken-gate" / "stub.json"
        )
        self.assertFalse(
            original.exists(),
            "happy-path quarantine must actually move evidence",
        )


if __name__ == "__main__":  # pragma: no cover — unittest entry point
    unittest.main()
