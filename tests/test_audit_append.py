from __future__ import annotations

import unittest
from dataclasses import fields, is_dataclass
from pathlib import Path


class AuditLogDataclassShapeTests(unittest.TestCase):
    def test_is_kw_only_dataclass(self) -> None:
        from story_automator.core.audit import AuditLog

        self.assertTrue(is_dataclass(AuditLog))

    def test_required_fields_present(self) -> None:
        from story_automator.core.audit import AuditLog

        names = {f.name for f in fields(AuditLog)}
        self.assertIn("path", names)
        self.assertIn("key", names)
        self.assertIn("_lock_path", names)

    def test_path_field_is_kw_only(self) -> None:
        from story_automator.core.audit import AuditLog

        # Positional construction must fail because the dataclass is kw_only.
        with self.assertRaises(TypeError):
            AuditLog(Path("/tmp/x.jsonl"), b"\x00" * 32)  # type: ignore[misc]

    def test_lock_path_derived_from_path(self) -> None:
        from story_automator.core.audit import AuditLog

        log = AuditLog(path=Path("/tmp/audit.jsonl"), key=b"\x00" * 32)
        self.assertEqual(log._lock_path, Path("/tmp/audit.jsonl.lock"))

    def test_lock_path_default_overridable(self) -> None:
        from story_automator.core.audit import AuditLog

        custom = Path("/tmp/override.lock")
        log = AuditLog(
            path=Path("/tmp/audit.jsonl"), key=b"\x00" * 32, _lock_path=custom
        )
        self.assertEqual(log._lock_path, custom)


if __name__ == "__main__":
    unittest.main()
