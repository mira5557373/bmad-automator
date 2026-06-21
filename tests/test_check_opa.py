from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch


class OpaCheckUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.opa_check import main

        self.assertEqual(main([]), 2)


class RunOpaCompileTests(unittest.TestCase):
    def test_no_policy_dir_returns_pass(self) -> None:
        from story_automator.core.checks.opa_check import run_opa_compile

        checkout = tempfile.mkdtemp()
        try:
            ok, msg = run_opa_compile(checkout, "policy")
            self.assertTrue(ok)
            self.assertIn("no policy", msg.lower())
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    @patch("subprocess.run")
    def test_compile_success(self, mock_run: MagicMock) -> None:
        from story_automator.core.checks.opa_check import run_opa_compile

        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        checkout = tempfile.mkdtemp()
        try:
            policy_dir = os.path.join(checkout, "policy")
            os.makedirs(policy_dir)
            with open(os.path.join(policy_dir, "main.rego"), "w") as f:
                f.write("package main\n")
            ok, msg = run_opa_compile(checkout, "policy")
            self.assertTrue(ok)
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    @patch("subprocess.run")
    def test_compile_failure(self, mock_run: MagicMock) -> None:
        from story_automator.core.checks.opa_check import run_opa_compile

        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error: parse error",
        )
        checkout = tempfile.mkdtemp()
        try:
            policy_dir = os.path.join(checkout, "policy")
            os.makedirs(policy_dir)
            with open(os.path.join(policy_dir, "main.rego"), "w") as f:
                f.write("package main\n")
            ok, msg = run_opa_compile(checkout, "policy")
            self.assertFalse(ok)
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)


class RunOpaTestTests(unittest.TestCase):
    def test_no_test_files_returns_pass(self) -> None:
        from story_automator.core.checks.opa_check import run_opa_test

        checkout = tempfile.mkdtemp()
        try:
            policy_dir = os.path.join(checkout, "policy")
            os.makedirs(policy_dir)
            with open(os.path.join(policy_dir, "main.rego"), "w") as f:
                f.write("package main\n")
            ok, msg = run_opa_test(checkout, "policy")
            self.assertTrue(ok)
            self.assertIn("no test", msg.lower())
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    @patch("subprocess.run")
    def test_test_success(self, mock_run: MagicMock) -> None:
        from story_automator.core.checks.opa_check import run_opa_test

        mock_run.return_value = MagicMock(returncode=0, stdout="PASS: 5/5", stderr="")
        checkout = tempfile.mkdtemp()
        try:
            policy_dir = os.path.join(checkout, "policy")
            os.makedirs(policy_dir)
            with open(os.path.join(policy_dir, "main_test.rego"), "w") as f:
                f.write("package main\ntest_allow { allow }\n")
            ok, msg = run_opa_test(checkout, "policy")
            self.assertTrue(ok)
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)
