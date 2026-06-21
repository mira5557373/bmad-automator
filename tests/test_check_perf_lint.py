# tests/test_check_perf_lint.py
from __future__ import annotations

import os
import tempfile
import unittest


class PerfLintUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.perf_lint_check import main

        self.assertEqual(main([]), 2)


class ScanNPlusOneTests(unittest.TestCase):
    def test_lazy_load_in_loop_detected(self) -> None:
        from story_automator.core.checks.perf_lint_check import scan_for_n_plus_one

        content = (
            "for user in users:\n"
            "    orders = user.orders.all()\n"
        )
        findings = scan_for_n_plus_one(content, "app.py")
        self.assertEqual(len(findings), 1)
        self.assertIn("N+1", findings[0])

    def test_no_lazy_load_passes(self) -> None:
        from story_automator.core.checks.perf_lint_check import scan_for_n_plus_one

        content = (
            "users = db.query(User).options(joinedload(User.orders)).all()\n"
        )
        findings = scan_for_n_plus_one(content, "app.py")
        self.assertEqual(findings, [])

    def test_selectin_outside_loop_passes(self) -> None:
        from story_automator.core.checks.perf_lint_check import scan_for_n_plus_one

        content = "result = item.children.all()\n"
        findings = scan_for_n_plus_one(content, "app.py")
        self.assertEqual(findings, [])


class ScanUnboundedTests(unittest.TestCase):
    def test_select_without_limit_detected(self) -> None:
        from story_automator.core.checks.perf_lint_check import scan_for_unbounded

        content = 'db.execute("SELECT * FROM users")\n'
        findings = scan_for_unbounded(content, "query.py")
        self.assertEqual(len(findings), 1)
        self.assertIn("unbounded", findings[0].lower())

    def test_select_with_limit_passes(self) -> None:
        from story_automator.core.checks.perf_lint_check import scan_for_unbounded

        content = 'db.execute("SELECT * FROM users LIMIT 100")\n'
        findings = scan_for_unbounded(content, "query.py")
        self.assertEqual(findings, [])

    def test_find_all_without_limit_detected(self) -> None:
        from story_automator.core.checks.perf_lint_check import scan_for_unbounded

        content = "results = repo.find_all()\n"
        findings = scan_for_unbounded(content, "service.py")
        self.assertEqual(len(findings), 1)

    def test_count_query_passes(self) -> None:
        from story_automator.core.checks.perf_lint_check import scan_for_unbounded

        content = 'db.execute("SELECT COUNT(*) FROM users")\n'
        findings = scan_for_unbounded(content, "query.py")
        self.assertEqual(findings, [])


class ScanDirectoryTests(unittest.TestCase):
    def test_scans_python_files(self) -> None:
        from story_automator.core.checks.perf_lint_check import scan_directory

        checkout = tempfile.mkdtemp()
        try:
            src = os.path.join(checkout, "src")
            os.makedirs(src)
            with open(os.path.join(src, "bad.py"), "w") as f:
                f.write(
                    "for u in users:\n"
                    "    orders = u.orders.all()\n"
                )
            findings = scan_directory(checkout, [".py"])
            self.assertTrue(len(findings) >= 1)
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_no_files_returns_empty(self) -> None:
        from story_automator.core.checks.perf_lint_check import scan_directory

        checkout = tempfile.mkdtemp()
        try:
            findings = scan_directory(checkout, [".py"])
            self.assertEqual(findings, [])
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)
