# tests/test_check_migration.py
from __future__ import annotations

import os
import tempfile
import unittest


class MigrationCheckUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.migration_check import main

        self.assertEqual(main([]), 2)


class CheckReversibilityTests(unittest.TestCase):
    def test_has_downgrade_passes(self) -> None:
        from story_automator.core.checks.migration_check import check_reversibility

        content = (
            "def upgrade():\n"
            "    op.create_table('users')\n"
            "\n"
            "def downgrade():\n"
            "    op.drop_table('users')\n"
        )
        issues = check_reversibility(content, "001_create_users.py")
        self.assertEqual(issues, [])

    def test_missing_downgrade_fails(self) -> None:
        from story_automator.core.checks.migration_check import check_reversibility

        content = (
            "def upgrade():\n"
            "    op.create_table('users')\n"
        )
        issues = check_reversibility(content, "001_create_users.py")
        self.assertEqual(len(issues), 1)
        self.assertIn("downgrade", issues[0].lower())

    def test_empty_downgrade_fails(self) -> None:
        from story_automator.core.checks.migration_check import check_reversibility

        content = (
            "def upgrade():\n"
            "    op.create_table('users')\n"
            "\n"
            "def downgrade():\n"
            "    pass\n"
        )
        issues = check_reversibility(content, "001_create_users.py")
        self.assertEqual(len(issues), 1)
        self.assertIn("empty", issues[0].lower())


class CheckAdvisoryLockTests(unittest.TestCase):
    def test_data_migration_with_lock_passes(self) -> None:
        from story_automator.core.checks.migration_check import check_advisory_lock

        content = (
            "def upgrade():\n"
            "    op.execute('SELECT pg_advisory_lock(1234)')\n"
            "    op.execute('UPDATE users SET active = true')\n"
            "    op.execute('SELECT pg_advisory_unlock(1234)')\n"
        )
        issues = check_advisory_lock(content, "002_data_migration.py")
        self.assertEqual(issues, [])

    def test_data_migration_without_lock_fails(self) -> None:
        from story_automator.core.checks.migration_check import check_advisory_lock

        content = (
            "def upgrade():\n"
            "    op.execute('UPDATE users SET active = true')\n"
        )
        issues = check_advisory_lock(content, "002_data_migration.py")
        self.assertEqual(len(issues), 1)
        self.assertIn("advisory", issues[0].lower())

    def test_schema_only_migration_passes(self) -> None:
        from story_automator.core.checks.migration_check import check_advisory_lock

        content = (
            "def upgrade():\n"
            "    op.add_column('users', sa.Column('name', sa.String))\n"
        )
        issues = check_advisory_lock(content, "003_add_column.py")
        self.assertEqual(issues, [])


class ScanMigrationsTests(unittest.TestCase):
    def test_no_dir_returns_empty(self) -> None:
        from story_automator.core.checks.migration_check import scan_migrations

        issues = scan_migrations("/nonexistent", "alembic/versions")
        self.assertEqual(issues, [])

    def test_scans_migration_files(self) -> None:
        from story_automator.core.checks.migration_check import scan_migrations

        checkout = tempfile.mkdtemp()
        try:
            mig_dir = os.path.join(checkout, "alembic", "versions")
            os.makedirs(mig_dir)
            with open(os.path.join(mig_dir, "001_init.py"), "w") as f:
                f.write("def upgrade():\n    op.create_table('x')\n")
            issues = scan_migrations(checkout, "alembic/versions")
            self.assertTrue(len(issues) >= 1)
            self.assertTrue(any("downgrade" in i.lower() for i in issues))
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)
