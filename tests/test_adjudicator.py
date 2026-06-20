from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

from story_automator.core.adjudicator import (
    resolve_timeout,
    run_collector_with_timeout,
)
from story_automator.core.product_profile import (
    DEFAULT_TIMEOUT_FALLBACK,
    DEFAULT_TIMEOUTS,
)
from story_automator.core.trust_boundary import TrustBoundaryError


class ResolveTimeoutTests(unittest.TestCase):
    def test_profile_timeout_takes_precedence(self) -> None:
        profile = {"timeouts": {"security": 999}}
        self.assertEqual(resolve_timeout(profile, "security"), 999)

    def test_default_timeout_for_known_category(self) -> None:
        profile: dict = {}
        self.assertEqual(
            resolve_timeout(profile, "security"),
            DEFAULT_TIMEOUTS["security"],
        )

    def test_fallback_for_unknown_category(self) -> None:
        profile: dict = {}
        self.assertEqual(
            resolve_timeout(profile, "unknown_cat"),
            DEFAULT_TIMEOUT_FALLBACK,
        )

    def test_empty_timeouts_uses_defaults(self) -> None:
        profile = {"timeouts": {}}
        self.assertEqual(
            resolve_timeout(profile, "correctness"),
            DEFAULT_TIMEOUTS["correctness"],
        )


class RunCollectorTests(unittest.TestCase):
    def test_successful_collector(self) -> None:
        record = run_collector_with_timeout(
            [sys.executable, "-c", "print('ok')"],
            collector="test",
            tool="python",
            category="correctness",
            timeout_s=10,
        )
        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["exit_code"], 0)
        self.assertGreater(record["duration_ms"], 0)

    def test_failing_collector(self) -> None:
        record = run_collector_with_timeout(
            [sys.executable, "-c", "import sys; print('fail'); sys.exit(1)"],
            collector="test",
            tool="python",
            category="correctness",
            timeout_s=10,
        )
        self.assertEqual(record["status"], "violation")
        self.assertEqual(record["exit_code"], 1)
        self.assertIn("fail", record["findings"])

    def test_timeout_produces_timeout_evidence(self) -> None:
        record = run_collector_with_timeout(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            collector="test",
            tool="slow-tool",
            category="security",
            timeout_s=1,
        )
        self.assertEqual(record["status"], "timeout")
        self.assertEqual(record["findings"], ["TIMEOUT: slow-tool exceeded 1s"])
        self.assertEqual(record["exit_code"], -1)

    def test_missing_binary_produces_error(self) -> None:
        record = run_collector_with_timeout(
            ["nonexistent-binary-12345"],
            collector="test",
            tool="missing",
            category="security",
            timeout_s=10,
        )
        self.assertEqual(record["status"], "error")
        self.assertEqual(record["exit_code"], 127)
        self.assertTrue(any("not found" in f for f in record["findings"]))

    def test_empty_cmd_produces_error(self) -> None:
        record = run_collector_with_timeout(
            [],
            collector="test",
            tool="empty",
            category="correctness",
            timeout_s=10,
        )
        self.assertEqual(record["status"], "error")
        self.assertEqual(record["exit_code"], 127)

    def test_evidence_has_schema_version(self) -> None:
        record = run_collector_with_timeout(
            [sys.executable, "-c", "pass"],
            collector="test",
            tool="python",
            category="correctness",
            timeout_s=10,
        )
        self.assertEqual(record["schema_version"], 1)


class CollectorTrustBoundaryTests(unittest.TestCase):
    def test_raises_in_child_session(self) -> None:
        with patch.dict("os.environ", {"STORY_AUTOMATOR_CHILD": "true"}):
            with self.assertRaises(TrustBoundaryError):
                run_collector_with_timeout(
                    [sys.executable, "-c", "print('ok')"],
                    collector="test",
                    tool="python",
                    category="correctness",
                    timeout_s=10,
                )

    def test_runs_normally_on_host(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("STORY_AUTOMATOR_CHILD", None)
            record = run_collector_with_timeout(
                [sys.executable, "-c", "print('ok')"],
                collector="test",
                tool="python",
                category="correctness",
                timeout_s=10,
            )
            self.assertEqual(record["status"], "ok")


if __name__ == "__main__":
    unittest.main()
