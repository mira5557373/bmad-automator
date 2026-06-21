from __future__ import annotations

import os
import tempfile
import unittest


class HardWaitUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.hard_wait_check import main

        self.assertEqual(main([]), 2)


class ScanForHardWaitsTests(unittest.TestCase):
    def test_time_sleep_detected(self) -> None:
        from story_automator.core.checks.hard_wait_check import scan_for_hard_waits

        content = "import time\ntime.sleep(5)\n"
        findings = scan_for_hard_waits(content, "test_app.py")
        self.assertEqual(len(findings), 1)
        self.assertIn("time.sleep", findings[0])

    def test_set_timeout_detected(self) -> None:
        from story_automator.core.checks.hard_wait_check import scan_for_hard_waits

        content = "await new Promise(r => setTimeout(r, 5000));\n"
        findings = scan_for_hard_waits(content, "test_app.ts")
        self.assertEqual(len(findings), 1)
        self.assertIn("setTimeout", findings[0])

    def test_cy_wait_detected(self) -> None:
        from story_automator.core.checks.hard_wait_check import scan_for_hard_waits

        content = "cy.wait(3000)\n"
        findings = scan_for_hard_waits(content, "test_app.cy.ts")
        self.assertEqual(len(findings), 1)
        self.assertIn("cy.wait", findings[0])

    def test_asyncio_sleep_detected(self) -> None:
        from story_automator.core.checks.hard_wait_check import scan_for_hard_waits

        content = "await asyncio.sleep(10)\n"
        findings = scan_for_hard_waits(content, "test_async.py")
        self.assertEqual(len(findings), 1)

    def test_thread_sleep_detected(self) -> None:
        from story_automator.core.checks.hard_wait_check import scan_for_hard_waits

        content = "Thread.sleep(1000)\n"
        findings = scan_for_hard_waits(content, "Test.java")
        self.assertEqual(len(findings), 1)

    def test_clean_code_passes(self) -> None:
        from story_automator.core.checks.hard_wait_check import scan_for_hard_waits

        content = "def test_something():\n    assert True\n"
        findings = scan_for_hard_waits(content, "test_app.py")
        self.assertEqual(findings, [])

    def test_page_wait_for_selector_ok(self) -> None:
        from story_automator.core.checks.hard_wait_check import scan_for_hard_waits

        content = "await page.waitForSelector('.ready')\n"
        findings = scan_for_hard_waits(content, "test_app.ts")
        self.assertEqual(findings, [])


class ScanTestFilesTests(unittest.TestCase):
    def test_scans_test_directories(self) -> None:
        from story_automator.core.checks.hard_wait_check import scan_test_files

        checkout = tempfile.mkdtemp()
        try:
            tests_dir = os.path.join(checkout, "tests")
            os.makedirs(tests_dir)
            with open(os.path.join(tests_dir, "test_slow.py"), "w") as f:
                f.write("import time\ntime.sleep(30)\n")
            findings = scan_test_files(checkout, [".py"])
            self.assertTrue(len(findings) >= 1)
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_skips_non_test_files(self) -> None:
        from story_automator.core.checks.hard_wait_check import scan_test_files

        checkout = tempfile.mkdtemp()
        try:
            src_dir = os.path.join(checkout, "src")
            os.makedirs(src_dir)
            with open(os.path.join(src_dir, "app.py"), "w") as f:
                f.write("import time\ntime.sleep(1)\n")
            findings = scan_test_files(checkout, [".py"])
            self.assertEqual(findings, [])
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_no_test_dir_returns_empty(self) -> None:
        from story_automator.core.checks.hard_wait_check import scan_test_files

        checkout = tempfile.mkdtemp()
        try:
            findings = scan_test_files(checkout, [".py"])
            self.assertEqual(findings, [])
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)
