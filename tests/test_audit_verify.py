from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class VerifyMissingFileTests(unittest.TestCase):
    KEY = b"\x55" * 32

    def test_returns_true_zero_when_file_does_not_exist(self) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            self.assertFalse(p.exists())
            log = AuditLog(path=p, key=self.KEY)
            self.assertEqual(log.verify(), (True, 0))

    def test_verify_does_not_create_the_file_as_side_effect(self) -> None:
        from story_automator.core.audit import AuditLog

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audit.jsonl"
            log = AuditLog(path=p, key=self.KEY)
            log.verify()
            self.assertFalse(
                p.exists(),
                "verify() must not create the audit log file (REQ-09)",
            )


if __name__ == "__main__":
    unittest.main()
