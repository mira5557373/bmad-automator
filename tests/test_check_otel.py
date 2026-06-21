# tests/test_check_otel.py
from __future__ import annotations

import os
import tempfile
import unittest


class OtelCheckUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.otel_check import main

        self.assertEqual(main([]), 2)


class CheckOtelWiringTests(unittest.TestCase):
    def test_all_signals_present(self) -> None:
        from story_automator.core.checks.otel_check import check_otel_wiring

        checkout = tempfile.mkdtemp()
        try:
            src = os.path.join(checkout, "src")
            os.makedirs(src)
            with open(os.path.join(src, "telemetry.py"), "w") as f:
                f.write(
                    "from opentelemetry import trace\n"
                    "from opentelemetry import metrics\n"
                    "import logging\n"
                    "tracer = trace.get_tracer(__name__)\n"
                    "meter = metrics.get_meter(__name__)\n"
                    "logger = logging.getLogger(__name__)\n"
                )
            missing = check_otel_wiring(checkout, ["traces", "metrics", "logs"])
            self.assertEqual(missing, [])
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_missing_traces(self) -> None:
        from story_automator.core.checks.otel_check import check_otel_wiring

        checkout = tempfile.mkdtemp()
        try:
            src = os.path.join(checkout, "src")
            os.makedirs(src)
            with open(os.path.join(src, "app.py"), "w") as f:
                f.write("import logging\nlogger = logging.getLogger(__name__)\n")
            missing = check_otel_wiring(checkout, ["traces", "metrics", "logs"])
            self.assertTrue(any("traces" in m for m in missing))
            self.assertTrue(any("metrics" in m for m in missing))
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_empty_checkout_reports_all_missing(self) -> None:
        from story_automator.core.checks.otel_check import check_otel_wiring

        checkout = tempfile.mkdtemp()
        try:
            missing = check_otel_wiring(checkout, ["traces", "metrics", "logs"])
            self.assertEqual(len(missing), 3)
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_typescript_otel_detected(self) -> None:
        from story_automator.core.checks.otel_check import check_otel_wiring

        checkout = tempfile.mkdtemp()
        try:
            src = os.path.join(checkout, "src")
            os.makedirs(src)
            with open(os.path.join(src, "tracing.ts"), "w") as f:
                f.write(
                    "import { trace } from '@opentelemetry/api';\n"
                    "import { metrics } from '@opentelemetry/api';\n"
                    "import { logs } from '@opentelemetry/api';\n"
                )
            missing = check_otel_wiring(checkout, ["traces", "metrics", "logs"])
            self.assertEqual(missing, [])
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)
