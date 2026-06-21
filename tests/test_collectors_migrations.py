# tests/test_collectors_migrations.py
from __future__ import annotations

import sys
import unittest
from pathlib import Path


class AlembicCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.migrations import ALEMBIC

        self.assertEqual(ALEMBIC.collector_id, "alembic-migrations")
        self.assertEqual(ALEMBIC.tool, "alembic")
        self.assertEqual(ALEMBIC.category, "migrations")
        self.assertTrue(ALEMBIC.deterministic)
        self.assertIn("*.py", ALEMBIC.file_patterns)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.migrations import ALEMBIC

        cmd = ALEMBIC.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "alembic")
        self.assertIn("upgrade", cmd)
        self.assertIn("head", cmd)
        self.assertIn("--sql", cmd)

    def test_build_cmd_custom_revision(self) -> None:
        from story_automator.core.collectors.migrations import ALEMBIC

        profile = {"rules": {"migrations": {"alembic_revision": "abc123"}}}
        cmd = ALEMBIC.build_cmd("/tmp/checkout", profile)
        self.assertIn("abc123", cmd)
        self.assertNotIn("head", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.migrations import ALEMBIC

        self.assertIsNotNone(ALEMBIC.tool_version_cmd)
        self.assertIn("alembic", ALEMBIC.tool_version_cmd)


class MigrationLintCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.migrations import MIGRATION_LINT

        self.assertEqual(MIGRATION_LINT.collector_id, "migration-lint-migrations")
        self.assertEqual(MIGRATION_LINT.tool, "python3")
        self.assertEqual(MIGRATION_LINT.category, "migrations")
        self.assertTrue(MIGRATION_LINT.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.migrations import MIGRATION_LINT

        cmd = MIGRATION_LINT.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("migration_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        self.assertEqual(cmd[3], "alembic/versions")

    def test_build_cmd_custom_dir(self) -> None:
        from story_automator.core.collectors.migrations import MIGRATION_LINT

        profile = {"rules": {"migrations": {"migrations_dir": "db/migrations"}}}
        cmd = MIGRATION_LINT.build_cmd("/tmp/checkout", profile)
        self.assertEqual(cmd[3], "db/migrations")

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.migrations import MIGRATION_LINT

        cmd = MIGRATION_LINT.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class MigrationsCollectorListTests(unittest.TestCase):
    def test_two_collectors(self) -> None:
        from story_automator.core.collectors.migrations import COLLECTORS

        self.assertEqual(len(COLLECTORS), 2)

    def test_all_migrations_category(self) -> None:
        from story_automator.core.collectors.migrations import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "migrations")

    def test_expected_ids(self) -> None:
        from story_automator.core.collectors.migrations import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {"alembic-migrations", "migration-lint-migrations"})

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.migrations import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
