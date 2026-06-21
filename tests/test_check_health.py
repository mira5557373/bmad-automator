# tests/test_check_health.py
from __future__ import annotations

import os
import tempfile
import unittest


class HealthCheckUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.health_check import main

        self.assertEqual(main([]), 2)


class CheckHealthEndpointsTests(unittest.TestCase):
    def test_both_endpoints_present(self) -> None:
        from story_automator.core.checks.health_check import check_health_endpoints

        checkout = tempfile.mkdtemp()
        try:
            src = os.path.join(checkout, "src")
            os.makedirs(src)
            with open(os.path.join(src, "app.py"), "w") as f:
                f.write(
                    '@app.get("/healthz")\n'
                    "def health(): return {'ok': True}\n"
                    '@app.get("/readyz")\n'
                    "def ready(): return {'ok': True}\n"
                )
            missing = check_health_endpoints(checkout, ["/healthz", "/readyz"])
            self.assertEqual(missing, [])
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_missing_readyz(self) -> None:
        from story_automator.core.checks.health_check import check_health_endpoints

        checkout = tempfile.mkdtemp()
        try:
            src = os.path.join(checkout, "src")
            os.makedirs(src)
            with open(os.path.join(src, "app.py"), "w") as f:
                f.write('@app.get("/healthz")\ndef health(): pass\n')
            missing = check_health_endpoints(checkout, ["/healthz", "/readyz"])
            self.assertEqual(len(missing), 1)
            self.assertTrue(any("/readyz" in m for m in missing))
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_empty_checkout_reports_all_missing(self) -> None:
        from story_automator.core.checks.health_check import check_health_endpoints

        checkout = tempfile.mkdtemp()
        try:
            missing = check_health_endpoints(checkout, ["/healthz", "/readyz"])
            self.assertEqual(len(missing), 2)
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_typescript_routes_detected(self) -> None:
        from story_automator.core.checks.health_check import check_health_endpoints

        checkout = tempfile.mkdtemp()
        try:
            src = os.path.join(checkout, "src")
            os.makedirs(src)
            with open(os.path.join(src, "routes.ts"), "w") as f:
                f.write(
                    "app.get('/healthz', (req, res) => res.json({ok: true}));\n"
                    "app.get('/readyz', (req, res) => res.json({ok: true}));\n"
                )
            missing = check_health_endpoints(checkout, ["/healthz", "/readyz"])
            self.assertEqual(missing, [])
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_yaml_k8s_probe_detected(self) -> None:
        from story_automator.core.checks.health_check import check_health_endpoints

        checkout = tempfile.mkdtemp()
        try:
            k8s = os.path.join(checkout, "k8s")
            os.makedirs(k8s)
            with open(os.path.join(k8s, "deployment.yaml"), "w") as f:
                f.write(
                    "livenessProbe:\n"
                    "  httpGet:\n"
                    "    path: /healthz\n"
                    "readinessProbe:\n"
                    "  httpGet:\n"
                    "    path: /readyz\n"
                )
            missing = check_health_endpoints(checkout, ["/healthz", "/readyz"])
            self.assertEqual(missing, [])
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)
