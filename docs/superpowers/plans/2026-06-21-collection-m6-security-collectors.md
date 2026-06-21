# Security Collectors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 11 evidence collectors across 4 new categories (security, license, compliance, supply_chain) to the collector framework, completing spec §6.2 module 3 and §8 module 3.

**Architecture:** Each category becomes a new Python module under `core/collectors/` following the exact pattern established by M5 (correctness.py, static.py, docs.py, process.py). Collectors are frozen `CollectorConfig` dataclasses with `build_cmd` callables that return subprocess argument lists. Two new check scripts (license_check.py, sbom_check.py) under `core/checks/` handle multi-step validations that need profile-rule interpretation. All collectors register via `register_core_collectors()`. M5 has 14 collectors; M6 brings the total to 25.

**Tech Stack:** Python 3.11+ stdlib only (no new deps), `CollectorConfig` from M4 framework, `presence_check.py` reuse for provenance, profile `rules` dict for per-category configuration.

## Global Constraints

- No Python imports beyond stdlib + `filelock` + `psutil` (CLAUDE.md hard rule)
- 500 LOC soft limit per module
- Check scripts are standalone (no `story_automator` imports, stdlib only)
- Collectors use the same `CollectorConfig` frozen dataclass from `collector_config.py`
- All collectors are `deterministic=True` (subprocess tools produce repeatable output)
- Profile rules are opaque dicts consumed by `build_cmd`/check scripts, not validated at the profile level
- Conventional Commits, `Generated-By:` trailer on every commit
- Test runner: `python -m pytest tests/ -v`
- Lint: `ruff check .`

## File Structure

**New files (4 collector modules):**
- `skills/bmad-story-automator/src/story_automator/core/collectors/security.py` — 4 collectors: semgrep, trivy, osv, gitleaks
- `skills/bmad-story-automator/src/story_automator/core/collectors/license.py` — 1 collector: license-check (uses check script)
- `skills/bmad-story-automator/src/story_automator/core/collectors/compliance.py` — 2 collectors: compliance-rules (semgrep), conftest (OPA/Rego policies)
- `skills/bmad-story-automator/src/story_automator/core/collectors/supply_chain.py` — 4 collectors: sbom, cosign, provenance, trivy-sbom

**New files (2 check scripts):**
- `skills/bmad-story-automator/src/story_automator/core/checks/license_check.py` — runs syft, validates forbidden licenses + boundary rules
- `skills/bmad-story-automator/src/story_automator/core/checks/sbom_check.py` — runs syft, validates SBOM generation

**New files (6 test files):**
- `tests/test_collectors_security.py`
- `tests/test_collectors_license.py`
- `tests/test_collectors_compliance.py`
- `tests/test_collectors_supply_chain.py`
- `tests/test_check_license.py`
- `tests/test_check_sbom.py`

**Modified files:**
- `skills/bmad-story-automator/src/story_automator/core/collectors/__init__.py` — import + register new categories

---

### Task 1: Security collectors — semgrep + trivy

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/security.py`
- Create: `tests/test_collectors_security.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `story_automator.core.collector_config`
- Produces: `SEMGREP: CollectorConfig`, `TRIVY_VULN: CollectorConfig`, `COLLECTORS: list[CollectorConfig]` (partial — extended in Task 2)

- [ ] **Step 1: Write failing tests for semgrep collector**

```python
# tests/test_collectors_security.py
from __future__ import annotations

import unittest


class SemgrepCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.security import SEMGREP

        self.assertEqual(SEMGREP.collector_id, "semgrep-security")
        self.assertEqual(SEMGREP.tool, "semgrep")
        self.assertEqual(SEMGREP.category, "security")
        self.assertTrue(SEMGREP.deterministic)
        self.assertIn("*.py", SEMGREP.file_patterns)
        self.assertIn("*.ts", SEMGREP.file_patterns)
        self.assertIn("*.js", SEMGREP.file_patterns)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.security import SEMGREP

        cmd = SEMGREP.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "semgrep")
        self.assertIn("scan", cmd)
        self.assertIn("--error", cmd)

    def test_build_cmd_custom_config(self) -> None:
        from story_automator.core.collectors.security import SEMGREP

        profile = {"rules": {"security": {"semgrep_config": "p/owasp-top-ten"}}}
        cmd = SEMGREP.build_cmd("/tmp/checkout", profile)
        self.assertIn("--config=p/owasp-top-ten", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.security import SEMGREP

        self.assertIsNotNone(SEMGREP.tool_version_cmd)
        self.assertIn("semgrep", SEMGREP.tool_version_cmd)


class TrivyVulnCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.security import TRIVY_VULN

        self.assertEqual(TRIVY_VULN.collector_id, "trivy-vuln-security")
        self.assertEqual(TRIVY_VULN.tool, "trivy")
        self.assertEqual(TRIVY_VULN.category, "security")
        self.assertTrue(TRIVY_VULN.deterministic)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.security import TRIVY_VULN

        cmd = TRIVY_VULN.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "trivy")
        self.assertIn("fs", cmd)
        self.assertIn("--exit-code", cmd)
        self.assertIn("1", cmd)
        self.assertIn("--scanners", cmd)
        self.assertIn("vuln", cmd)
        self.assertIn(".", cmd)

    def test_build_cmd_custom_severity(self) -> None:
        from story_automator.core.collectors.security import TRIVY_VULN

        profile = {"rules": {"security": {"trivy_severity": "CRITICAL"}}}
        cmd = TRIVY_VULN.build_cmd("/tmp/checkout", profile)
        self.assertIn("--severity", cmd)
        self.assertIn("CRITICAL", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.security import TRIVY_VULN

        self.assertIsNotNone(TRIVY_VULN.tool_version_cmd)
        self.assertIn("trivy", TRIVY_VULN.tool_version_cmd)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_collectors_security.py -v`
Expected: `ModuleNotFoundError` — `security` module does not exist yet.

- [ ] **Step 3: Implement semgrep + trivy collectors**

```python
# skills/bmad-story-automator/src/story_automator/core/collectors/security.py
"""Security-category evidence collectors (§6.2).

PASS rule: SAST 0 high+, deps 0 critical-unwaived, 0 secrets.
Collectors: semgrep-security, trivy-vuln-security, osv-security, gitleaks-security.
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _semgrep_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("security") or {}
    config = rules.get("semgrep_config", "auto")
    return ["semgrep", "scan", f"--config={config}", "--error"]


def _trivy_vuln_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("security") or {}
    severity = rules.get("trivy_severity", "HIGH,CRITICAL")
    return [
        "trivy", "fs",
        "--exit-code", "1",
        "--severity", severity,
        "--scanners", "vuln",
        ".",
    ]


SEMGREP = CollectorConfig(
    collector_id="semgrep-security",
    tool="semgrep",
    category="security",
    build_cmd=_semgrep_cmd,
    tool_version_cmd=("semgrep", "--version"),
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx", "*.js", "*.jsx", "*.yaml", "*.yml"}),
)

TRIVY_VULN = CollectorConfig(
    collector_id="trivy-vuln-security",
    tool="trivy",
    category="security",
    build_cmd=_trivy_vuln_cmd,
    tool_version_cmd=("trivy", "--version"),
    file_patterns=frozenset({"*.lock", "*.txt", "*.toml", "*.cfg", "package.json"}),
)

COLLECTORS: list[CollectorConfig] = [SEMGREP, TRIVY_VULN]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_collectors_security.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_collectors_security.py skills/bmad-story-automator/src/story_automator/core/collectors/security.py
git commit -m "feat(collector): add semgrep + trivy security collectors" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 2: Security collectors — osv + gitleaks + module tests

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/collectors/security.py`
- Modify: `tests/test_collectors_security.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `story_automator.core.collector_config`
- Produces: `OSV: CollectorConfig`, `GITLEAKS: CollectorConfig`; `COLLECTORS` list grows to 4 items

- [ ] **Step 1: Write failing tests for osv + gitleaks + module-level**

Append to `tests/test_collectors_security.py`:

```python
class OsvCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.security import OSV

        self.assertEqual(OSV.collector_id, "osv-security")
        self.assertEqual(OSV.tool, "osv-scanner")
        self.assertEqual(OSV.category, "security")
        self.assertTrue(OSV.deterministic)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.security import OSV

        cmd = OSV.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "osv-scanner")
        self.assertIn("scan", cmd)
        self.assertIn("--recursive", cmd)
        self.assertIn(".", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.security import OSV

        self.assertIsNotNone(OSV.tool_version_cmd)
        self.assertIn("osv-scanner", OSV.tool_version_cmd)


class GitleaksCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.security import GITLEAKS

        self.assertEqual(GITLEAKS.collector_id, "gitleaks-security")
        self.assertEqual(GITLEAKS.tool, "gitleaks")
        self.assertEqual(GITLEAKS.category, "security")
        self.assertTrue(GITLEAKS.deterministic)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.security import GITLEAKS

        cmd = GITLEAKS.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "gitleaks")
        self.assertIn("detect", cmd)
        self.assertIn("--source", cmd)
        self.assertIn(".", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.security import GITLEAKS

        self.assertIsNotNone(GITLEAKS.tool_version_cmd)
        self.assertIn("gitleaks", GITLEAKS.tool_version_cmd)


class SecurityCollectorListTests(unittest.TestCase):
    def test_four_collectors(self) -> None:
        from story_automator.core.collectors.security import COLLECTORS

        self.assertEqual(len(COLLECTORS), 4)

    def test_all_expected_ids(self) -> None:
        from story_automator.core.collectors.security import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {
            "semgrep-security", "trivy-vuln-security",
            "osv-security", "gitleaks-security",
        })

    def test_all_security_category(self) -> None:
        from story_automator.core.collectors.security import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "security")

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.security import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `python -m pytest tests/test_collectors_security.py::OsvCollectorTests -v`
Expected: `ImportError` — `OSV` not defined yet.

- [ ] **Step 3: Add osv + gitleaks to security.py**

Add these functions and configs to `security.py`, before the `COLLECTORS` list:

```python
def _osv_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["osv-scanner", "scan", "--recursive", "."]


def _gitleaks_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["gitleaks", "detect", "--source", ".", "--no-banner"]


OSV = CollectorConfig(
    collector_id="osv-security",
    tool="osv-scanner",
    category="security",
    build_cmd=_osv_cmd,
    tool_version_cmd=("osv-scanner", "--version"),
    file_patterns=frozenset({"*.lock", "*.txt", "*.toml", "*.cfg", "package.json"}),
)

GITLEAKS = CollectorConfig(
    collector_id="gitleaks-security",
    tool="gitleaks",
    category="security",
    build_cmd=_gitleaks_cmd,
    tool_version_cmd=("gitleaks", "version"),
    file_patterns=frozenset(),
)
```

Update the `COLLECTORS` list:

```python
COLLECTORS: list[CollectorConfig] = [SEMGREP, TRIVY_VULN, OSV, GITLEAKS]
```

- [ ] **Step 4: Run all security tests to verify they pass**

Run: `python -m pytest tests/test_collectors_security.py -v`
Expected: All 19 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_collectors_security.py skills/bmad-story-automator/src/story_automator/core/collectors/security.py
git commit -m "feat(collector): add osv + gitleaks security collectors" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 3: License check script

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/checks/license_check.py`
- Create: `tests/test_check_license.py`

**Interfaces:**
- Consumes: nothing (standalone script, stdlib only)
- Produces: `main(argv) -> int` entry point. CLI: `license_check.py <checkout> <forbidden_json> <boundary_json>`. Exit 0 = clean, 1 = violations, 2 = usage error. Writes violations as `FORBIDDEN: <pkg> <license>` or `BOUNDARY: <pkg> <license> not allowed in <dir>` lines to stdout.

- [ ] **Step 1: Write failing tests for license check script**

```python
# tests/test_check_license.py
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = str(
    Path(__file__).resolve().parent.parent
    / "skills" / "bmad-story-automator" / "src"
    / "story_automator" / "core" / "checks" / "license_check.py"
)


class LicenseCheckUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.license_check import main

        self.assertEqual(main([]), 2)

    def test_one_arg_returns_2(self) -> None:
        from story_automator.core.checks.license_check import main

        self.assertEqual(main(["/tmp"]), 2)

    def test_two_args_returns_2(self) -> None:
        from story_automator.core.checks.license_check import main

        self.assertEqual(main(["/tmp", "[]"]), 2)

    def test_invalid_forbidden_json_returns_2(self) -> None:
        from story_automator.core.checks.license_check import main

        self.assertEqual(main(["/tmp", "not-json", "{}"]), 2)


class LicenseCheckForbiddenTests(unittest.TestCase):
    def test_no_forbidden_returns_0(self) -> None:
        from story_automator.core.checks.license_check import check_licenses

        packages = [{"name": "flask", "license": "BSD-3-Clause"}]
        violations = check_licenses(packages, [], {})
        self.assertEqual(violations, [])

    def test_forbidden_license_detected(self) -> None:
        from story_automator.core.checks.license_check import check_licenses

        packages = [
            {"name": "good-pkg", "license": "MIT"},
            {"name": "bad-pkg", "license": "BSL-1.1"},
        ]
        violations = check_licenses(packages, ["BSL-1.1"], {})
        self.assertEqual(len(violations), 1)
        self.assertIn("bad-pkg", violations[0])
        self.assertIn("BSL-1.1", violations[0])

    def test_forbidden_case_insensitive(self) -> None:
        from story_automator.core.checks.license_check import check_licenses

        packages = [{"name": "pkg", "license": "sspl-1.0"}]
        violations = check_licenses(packages, ["SSPL-1.0"], {})
        self.assertEqual(len(violations), 1)


class LicenseCheckBoundaryTests(unittest.TestCase):
    def test_boundary_violation_detected(self) -> None:
        from story_automator.core.checks.license_check import check_licenses

        packages = [{"name": "odoo-core", "license": "AGPL-3.0", "locations": ["/src/api/main.py"]}]
        boundary = {"AGPL-3.0": ["odoo-pod"]}
        violations = check_licenses(packages, [], boundary)
        self.assertEqual(len(violations), 1)
        self.assertIn("BOUNDARY", violations[0])

    def test_boundary_allowed_location(self) -> None:
        from story_automator.core.checks.license_check import check_licenses

        packages = [{"name": "odoo-core", "license": "AGPL-3.0", "locations": ["/src/odoo-pod/addon.py"]}]
        boundary = {"AGPL-3.0": ["odoo-pod"]}
        violations = check_licenses(packages, [], boundary)
        self.assertEqual(violations, [])

    def test_no_boundary_rules_no_violations(self) -> None:
        from story_automator.core.checks.license_check import check_licenses

        packages = [{"name": "pkg", "license": "AGPL-3.0", "locations": ["/src/api.py"]}]
        violations = check_licenses(packages, [], {})
        self.assertEqual(violations, [])


class ParseSyftOutputTests(unittest.TestCase):
    def test_parse_json_output(self) -> None:
        from story_automator.core.checks.license_check import parse_syft_output

        syft_json = json.dumps({
            "artifacts": [
                {"name": "flask", "version": "2.0", "licenses": [{"value": "BSD-3-Clause"}], "locations": [{"path": "/app/x.py"}]},
                {"name": "requests", "version": "2.28", "licenses": [{"value": "Apache-2.0"}], "locations": []},
            ]
        })
        packages = parse_syft_output(syft_json)
        self.assertEqual(len(packages), 2)
        self.assertEqual(packages[0]["name"], "flask")
        self.assertEqual(packages[0]["license"], "BSD-3-Clause")
        self.assertEqual(packages[1]["name"], "requests")
        self.assertEqual(packages[1]["license"], "Apache-2.0")

    def test_parse_empty_output(self) -> None:
        from story_automator.core.checks.license_check import parse_syft_output

        packages = parse_syft_output("{}")
        self.assertEqual(packages, [])

    def test_parse_invalid_json(self) -> None:
        from story_automator.core.checks.license_check import parse_syft_output

        packages = parse_syft_output("not json")
        self.assertEqual(packages, [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_check_license.py -v`
Expected: `ModuleNotFoundError` — `license_check` module does not exist yet.

- [ ] **Step 3: Implement license check script**

```python
# skills/bmad-story-automator/src/story_automator/core/checks/license_check.py
"""Validate licenses against forbidden list and boundary rules.

Standalone script invoked by the license-check collector.
Exit 0 = clean, exit 1 = violations, exit 2 = usage error.
Prints FORBIDDEN: or BOUNDARY: lines for each violation.

Runs syft internally to extract package license data,
then checks against profile-provided forbidden and boundary rules.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import subprocess
import sys


def parse_syft_output(raw: str) -> list[dict]:
    """Parse syft JSON output into a flat list of {name, license, locations}."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    artifacts = data.get("artifacts") or []
    packages: list[dict] = []
    for art in artifacts:
        if not isinstance(art, dict):
            continue
        name = art.get("name", "")
        licenses = art.get("licenses") or []
        first_lic = licenses[0] if licenses else {}
        license_val = first_lic.get("value", "") if isinstance(first_lic, dict) else ""
        locs = art.get("locations") or []
        loc_paths = [loc.get("path", "") for loc in locs if isinstance(loc, dict)]
        packages.append({
            "name": name,
            "license": license_val,
            "locations": loc_paths,
        })
    return packages


def check_licenses(
    packages: list[dict],
    forbidden: list[str],
    boundary: dict[str, list[str]],
) -> list[str]:
    """Check packages against forbidden list and boundary rules.

    Returns list of violation strings (empty = clean).
    """
    violations: list[str] = []
    forbidden_lower = {f.lower() for f in forbidden}
    for pkg in packages:
        lic = pkg.get("license", "")
        name = pkg.get("name", "")
        if lic.lower() in forbidden_lower:
            violations.append(f"FORBIDDEN: {name} uses {lic}")
        allowed_dirs = boundary.get(lic, boundary.get(lic.upper(), []))
        if not allowed_dirs:
            continue
        locations = pkg.get("locations") or []
        for loc in locations:
            if not any(allowed in loc for allowed in allowed_dirs):
                violations.append(
                    f"BOUNDARY: {name} ({lic}) at {loc} "
                    f"not in allowed dirs {allowed_dirs}"
                )
    return violations


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 3:
        print("usage: license_check.py <checkout> <forbidden_json> <boundary_json>")
        return 2
    checkout = args[0]
    try:
        forbidden: list[str] = json.loads(args[1])
    except (json.JSONDecodeError, TypeError):
        print(f"invalid forbidden list: {args[1]}")
        return 2
    try:
        boundary: dict[str, list[str]] = json.loads(args[2])
    except (json.JSONDecodeError, TypeError):
        print(f"invalid boundary rules: {args[2]}")
        return 2
    try:
        result = subprocess.run(
            ["syft", "packages", "-o", "json", checkout],
            capture_output=True, text=True, timeout=120,
        )
    except FileNotFoundError:
        print("syft not found")
        return 1
    except subprocess.TimeoutExpired:
        print("syft timed out")
        return 1
    if result.returncode != 0:
        print(f"syft exited {result.returncode}")
        for line in result.stderr.splitlines()[:5]:
            print(line)
        return 1
    packages = parse_syft_output(result.stdout)
    violations = check_licenses(packages, forbidden, boundary)
    for v in violations:
        print(v)
    if violations:
        print(f"{len(violations)} license violation(s) found")
        return 1
    print(f"{len(packages)} package(s) scanned, no license violations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_check_license.py -v`
Expected: All 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_check_license.py skills/bmad-story-automator/src/story_automator/core/checks/license_check.py
git commit -m "feat(collector): add license check script" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 4: License collector module

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/license.py`
- Create: `tests/test_collectors_license.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `story_automator.core.collector_config`; `license_check.py` from `core/checks/`
- Produces: `LICENSE_CHECK: CollectorConfig`, `COLLECTORS: list[CollectorConfig]` (1 item)

- [ ] **Step 1: Write failing tests for license collector**

```python
# tests/test_collectors_license.py
from __future__ import annotations

import json
import sys
import unittest


class LicenseCheckCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.license import LICENSE_CHECK

        self.assertEqual(LICENSE_CHECK.collector_id, "license-check-license")
        self.assertEqual(LICENSE_CHECK.tool, "python3")
        self.assertEqual(LICENSE_CHECK.category, "license")
        self.assertTrue(LICENSE_CHECK.deterministic)

    def test_build_cmd_default_rules(self) -> None:
        from story_automator.core.collectors.license import LICENSE_CHECK

        cmd = LICENSE_CHECK.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("license_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        forbidden = json.loads(cmd[3])
        self.assertEqual(forbidden, [])
        boundary = json.loads(cmd[4])
        self.assertEqual(boundary, {})

    def test_build_cmd_with_profile_rules(self) -> None:
        from story_automator.core.collectors.license import LICENSE_CHECK

        profile = {
            "rules": {
                "license": {
                    "forbidden": ["BSL-1.1", "SSPL-1.0"],
                    "boundary": {"AGPL-3.0": ["odoo-pod"]},
                },
            },
        }
        cmd = LICENSE_CHECK.build_cmd("/tmp/checkout", profile)
        forbidden = json.loads(cmd[3])
        self.assertEqual(forbidden, ["BSL-1.1", "SSPL-1.0"])
        boundary = json.loads(cmd[4])
        self.assertEqual(boundary, {"AGPL-3.0": ["odoo-pod"]})

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.license import LICENSE_CHECK

        cmd = LICENSE_CHECK.build_cmd("/tmp/checkout", {})
        from pathlib import Path

        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class LicenseCollectorListTests(unittest.TestCase):
    def test_one_collector(self) -> None:
        from story_automator.core.collectors.license import COLLECTORS

        self.assertEqual(len(COLLECTORS), 1)

    def test_all_license_category(self) -> None:
        from story_automator.core.collectors.license import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "license")

    def test_expected_id(self) -> None:
        from story_automator.core.collectors.license import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {"license-check-license"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_collectors_license.py -v`
Expected: `ModuleNotFoundError` — `license` module does not exist yet.

- [ ] **Step 3: Implement license collector module**

```python
# skills/bmad-story-automator/src/story_automator/core/collectors/license.py
"""License-category evidence collectors (§6.2).

PASS rule: 0 forbidden licenses + boundary-aware (AGPL only in Odoo pod).
Collectors: license-check-license.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"


def _license_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("license") or {}
    forbidden = json.dumps(rules.get("forbidden", []))
    boundary = json.dumps(rules.get("boundary", {}))
    return [
        sys.executable,
        str(_CHECKS_DIR / "license_check.py"),
        checkout,
        forbidden,
        boundary,
    ]


LICENSE_CHECK = CollectorConfig(
    collector_id="license-check-license",
    tool="python3",
    category="license",
    build_cmd=_license_cmd,
    file_patterns=frozenset({"*.lock", "*.txt", "*.toml", "*.cfg", "package.json"}),
)

COLLECTORS: list[CollectorConfig] = [LICENSE_CHECK]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_collectors_license.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_collectors_license.py skills/bmad-story-automator/src/story_automator/core/collectors/license.py
git commit -m "feat(collector): add license collector module" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 5: Compliance collector module

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/compliance.py`
- Create: `tests/test_collectors_compliance.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `story_automator.core.collector_config`
- Produces: `COMPLIANCE_RULES: CollectorConfig`, `CONFTEST: CollectorConfig`, `COLLECTORS: list[CollectorConfig]` (2 items)

- [ ] **Step 1: Write failing tests for compliance collectors**

```python
# tests/test_collectors_compliance.py
from __future__ import annotations

import unittest


class ComplianceRulesCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.compliance import COMPLIANCE_RULES

        self.assertEqual(COMPLIANCE_RULES.collector_id, "compliance-rules-compliance")
        self.assertEqual(COMPLIANCE_RULES.tool, "semgrep")
        self.assertEqual(COMPLIANCE_RULES.category, "compliance")
        self.assertTrue(COMPLIANCE_RULES.deterministic)
        self.assertIn("*.py", COMPLIANCE_RULES.file_patterns)
        self.assertIn("*.ts", COMPLIANCE_RULES.file_patterns)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.compliance import COMPLIANCE_RULES

        cmd = COMPLIANCE_RULES.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "semgrep")
        self.assertIn("scan", cmd)
        self.assertIn("--error", cmd)
        self.assertIn("--config=auto", cmd)

    def test_build_cmd_custom_rulepack(self) -> None:
        from story_automator.core.collectors.compliance import COMPLIANCE_RULES

        profile = {"rules": {"compliance": {"rulepack_dir": "semgrep/compliance"}}}
        cmd = COMPLIANCE_RULES.build_cmd("/tmp/checkout", profile)
        self.assertIn("--config=semgrep/compliance", cmd)
        self.assertNotIn("--config=auto", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.compliance import COMPLIANCE_RULES

        self.assertIsNotNone(COMPLIANCE_RULES.tool_version_cmd)
        self.assertIn("semgrep", COMPLIANCE_RULES.tool_version_cmd)


class ConftestCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.compliance import CONFTEST

        self.assertEqual(CONFTEST.collector_id, "conftest-compliance")
        self.assertEqual(CONFTEST.tool, "conftest")
        self.assertEqual(CONFTEST.category, "compliance")
        self.assertTrue(CONFTEST.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.compliance import CONFTEST

        cmd = CONFTEST.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "conftest")
        self.assertIn("test", cmd)
        self.assertIn("--policy", cmd)
        self.assertIn("policy", cmd)

    def test_build_cmd_custom_policy_dir(self) -> None:
        from story_automator.core.collectors.compliance import CONFTEST

        profile = {"rules": {"compliance": {"conftest_policy_dir": "opa/compliance"}}}
        cmd = CONFTEST.build_cmd("/tmp/checkout", profile)
        self.assertIn("opa/compliance", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.compliance import CONFTEST

        self.assertIsNotNone(CONFTEST.tool_version_cmd)
        self.assertIn("conftest", CONFTEST.tool_version_cmd)


class ComplianceCollectorListTests(unittest.TestCase):
    def test_two_collectors(self) -> None:
        from story_automator.core.collectors.compliance import COLLECTORS

        self.assertEqual(len(COLLECTORS), 2)

    def test_all_compliance_category(self) -> None:
        from story_automator.core.collectors.compliance import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "compliance")

    def test_expected_ids(self) -> None:
        from story_automator.core.collectors.compliance import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {"compliance-rules-compliance", "conftest-compliance"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_collectors_compliance.py -v`
Expected: `ModuleNotFoundError` — `compliance` module does not exist yet.

- [ ] **Step 3: Implement compliance collector module**

```python
# skills/bmad-story-automator/src/story_automator/core/collectors/compliance.py
"""Compliance-category evidence collectors (§6.2).

PASS rule: compliance rulepack checks pass (PII-redaction, residency,
audit-envelope, consent-receipt present and correct).
Collectors: compliance-rules-compliance, conftest-compliance.
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _compliance_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("compliance") or {}
    rulepack = rules.get("rulepack_dir", "")
    config = rulepack if rulepack else "auto"
    return ["semgrep", "scan", f"--config={config}", "--error"]


def _conftest_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("compliance") or {}
    policy_dir = rules.get("conftest_policy_dir", "policy")
    return ["conftest", "test", "--policy", policy_dir, "."]


COMPLIANCE_RULES = CollectorConfig(
    collector_id="compliance-rules-compliance",
    tool="semgrep",
    category="compliance",
    build_cmd=_compliance_cmd,
    tool_version_cmd=("semgrep", "--version"),
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx", "*.js", "*.jsx", "*.yaml", "*.yml"}),
)

CONFTEST = CollectorConfig(
    collector_id="conftest-compliance",
    tool="conftest",
    category="compliance",
    build_cmd=_conftest_cmd,
    tool_version_cmd=("conftest", "--version"),
    file_patterns=frozenset({"*.yaml", "*.yml", "*.json", "*.tf", "*.hcl"}),
)

COLLECTORS: list[CollectorConfig] = [COMPLIANCE_RULES, CONFTEST]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_collectors_compliance.py -v`
Expected: All 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_collectors_compliance.py skills/bmad-story-automator/src/story_automator/core/collectors/compliance.py
git commit -m "feat(collector): add compliance collector module" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 6: SBOM check script

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/checks/sbom_check.py`
- Create: `tests/test_check_sbom.py`

**Interfaces:**
- Consumes: nothing (standalone script, stdlib only)
- Produces: `main(argv) -> int` entry point. CLI: `sbom_check.py <checkout> [format]`. Exit 0 = valid SBOM generated, 1 = error/invalid, 2 = usage error. Writes `SBOM: <n> packages found` on success.

- [ ] **Step 1: Write failing tests for SBOM check script**

```python
# tests/test_check_sbom.py
from __future__ import annotations

import json
import unittest


class SbomCheckUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.sbom_check import main

        self.assertEqual(main([]), 2)


class ValidateSbomTests(unittest.TestCase):
    def test_valid_spdx_json(self) -> None:
        from story_automator.core.checks.sbom_check import validate_sbom

        sbom = json.dumps({
            "spdxVersion": "SPDX-2.3",
            "name": "test",
            "packages": [
                {"name": "flask", "versionInfo": "2.0"},
            ],
        })
        ok, msg = validate_sbom(sbom, "spdx-json")
        self.assertTrue(ok)
        self.assertIn("1", msg)

    def test_valid_cyclonedx_json(self) -> None:
        from story_automator.core.checks.sbom_check import validate_sbom

        sbom = json.dumps({
            "bomFormat": "CycloneDX",
            "specVersion": "1.4",
            "components": [
                {"name": "requests", "version": "2.28"},
            ],
        })
        ok, msg = validate_sbom(sbom, "cyclonedx-json")
        self.assertTrue(ok)
        self.assertIn("1", msg)

    def test_empty_json_fails(self) -> None:
        from story_automator.core.checks.sbom_check import validate_sbom

        ok, msg = validate_sbom("{}", "spdx-json")
        self.assertFalse(ok)

    def test_invalid_json_fails(self) -> None:
        from story_automator.core.checks.sbom_check import validate_sbom

        ok, msg = validate_sbom("not json", "spdx-json")
        self.assertFalse(ok)

    def test_empty_packages_fails(self) -> None:
        from story_automator.core.checks.sbom_check import validate_sbom

        sbom = json.dumps({
            "spdxVersion": "SPDX-2.3",
            "name": "test",
            "packages": [],
        })
        ok, msg = validate_sbom(sbom, "spdx-json")
        self.assertFalse(ok)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_check_sbom.py -v`
Expected: `ModuleNotFoundError` — `sbom_check` module does not exist yet.

- [ ] **Step 3: Implement SBOM check script**

```python
# skills/bmad-story-automator/src/story_automator/core/checks/sbom_check.py
"""Validate SBOM generation via syft.

Standalone script invoked by the sbom-supply_chain collector.
Exit 0 = valid SBOM generated, exit 1 = error/invalid, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import subprocess
import sys


def validate_sbom(raw: str, fmt: str) -> tuple[bool, str]:
    """Validate SBOM content. Returns (ok, message)."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return False, "SBOM is not valid JSON"
    if not isinstance(data, dict):
        return False, "SBOM root must be a JSON object"
    if fmt == "spdx-json":
        if "spdxVersion" not in data:
            return False, "missing spdxVersion field"
        pkgs = data.get("packages") or []
        if not pkgs:
            return False, "SBOM contains no packages"
        return True, f"SBOM: {len(pkgs)} package(s) found (SPDX)"
    if fmt == "cyclonedx-json":
        if "bomFormat" not in data:
            return False, "missing bomFormat field"
        components = data.get("components") or []
        if not components:
            return False, "SBOM contains no components"
        return True, f"SBOM: {len(components)} component(s) found (CycloneDX)"
    return False, f"unknown SBOM format: {fmt}"


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: sbom_check.py <checkout> [format]")
        return 2
    checkout = args[0]
    fmt = args[1] if len(args) > 1 else "spdx-json"
    try:
        result = subprocess.run(
            ["syft", "packages", "-o", fmt, checkout],
            capture_output=True, text=True, timeout=120,
        )
    except FileNotFoundError:
        print("syft not found")
        return 1
    except subprocess.TimeoutExpired:
        print("syft timed out")
        return 1
    if result.returncode != 0:
        print(f"syft exited {result.returncode}")
        for line in result.stderr.splitlines()[:5]:
            print(line)
        return 1
    ok, msg = validate_sbom(result.stdout, fmt)
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_check_sbom.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_check_sbom.py skills/bmad-story-automator/src/story_automator/core/checks/sbom_check.py
git commit -m "feat(collector): add SBOM check script" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 7: Supply chain collector module

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/supply_chain.py`
- Create: `tests/test_collectors_supply_chain.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `story_automator.core.collector_config`; `sbom_check.py` and `presence_check.py` from `core/checks/`
- Produces: `SBOM: CollectorConfig`, `COSIGN: CollectorConfig`, `PROVENANCE: CollectorConfig`, `TRIVY_SBOM: CollectorConfig`, `COLLECTORS: list[CollectorConfig]` (4 items)

- [ ] **Step 1: Write failing tests for supply chain collectors**

```python
# tests/test_collectors_supply_chain.py
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


class SbomCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.supply_chain import SBOM

        self.assertEqual(SBOM.collector_id, "sbom-supply_chain")
        self.assertEqual(SBOM.tool, "python3")
        self.assertEqual(SBOM.category, "supply_chain")
        self.assertTrue(SBOM.deterministic)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.supply_chain import SBOM

        cmd = SBOM.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("sbom_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")

    def test_build_cmd_custom_format(self) -> None:
        from story_automator.core.collectors.supply_chain import SBOM

        profile = {"rules": {"supply_chain": {"sbom_format": "cyclonedx-json"}}}
        cmd = SBOM.build_cmd("/tmp/checkout", profile)
        self.assertIn("cyclonedx-json", cmd)

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.supply_chain import SBOM

        cmd = SBOM.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class CosignCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.supply_chain import COSIGN

        self.assertEqual(COSIGN.collector_id, "cosign-supply_chain")
        self.assertEqual(COSIGN.tool, "cosign")
        self.assertEqual(COSIGN.category, "supply_chain")
        self.assertTrue(COSIGN.deterministic)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.supply_chain import COSIGN

        cmd = COSIGN.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "cosign")
        self.assertIn("verify-blob", cmd)

    def test_build_cmd_custom_bundle(self) -> None:
        from story_automator.core.collectors.supply_chain import COSIGN

        profile = {"rules": {"supply_chain": {"cosign_bundle": "my.bundle"}}}
        cmd = COSIGN.build_cmd("/tmp/checkout", profile)
        self.assertIn("my.bundle", cmd)

    def test_build_cmd_custom_artifact(self) -> None:
        from story_automator.core.collectors.supply_chain import COSIGN

        profile = {"rules": {"supply_chain": {"cosign_artifact": "my-sbom.spdx.json"}}}
        cmd = COSIGN.build_cmd("/tmp/checkout", profile)
        self.assertIn("my-sbom.spdx.json", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.supply_chain import COSIGN

        self.assertIsNotNone(COSIGN.tool_version_cmd)
        self.assertIn("cosign", COSIGN.tool_version_cmd)


class ProvenanceCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.supply_chain import PROVENANCE

        self.assertEqual(PROVENANCE.collector_id, "provenance-supply_chain")
        self.assertEqual(PROVENANCE.tool, "python3")
        self.assertEqual(PROVENANCE.category, "supply_chain")
        self.assertTrue(PROVENANCE.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.supply_chain import PROVENANCE

        cmd = PROVENANCE.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("presence_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        files = json.loads(cmd[3])
        self.assertIsInstance(files, list)
        self.assertTrue(len(files) > 0)

    def test_build_cmd_custom_files(self) -> None:
        from story_automator.core.collectors.supply_chain import PROVENANCE

        profile = {"rules": {"supply_chain": {"provenance_files": ["custom.jsonl"]}}}
        cmd = PROVENANCE.build_cmd("/tmp/checkout", profile)
        files = json.loads(cmd[3])
        self.assertEqual(files, ["custom.jsonl"])

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.supply_chain import PROVENANCE

        cmd = PROVENANCE.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class TrivySbomCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.supply_chain import TRIVY_SBOM

        self.assertEqual(TRIVY_SBOM.collector_id, "trivy-sbom-supply_chain")
        self.assertEqual(TRIVY_SBOM.tool, "trivy")
        self.assertEqual(TRIVY_SBOM.category, "supply_chain")
        self.assertTrue(TRIVY_SBOM.deterministic)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.supply_chain import TRIVY_SBOM

        cmd = TRIVY_SBOM.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "trivy")
        self.assertIn("sbom", cmd)
        self.assertIn("--exit-code", cmd)
        self.assertIn("1", cmd)

    def test_build_cmd_custom_severity(self) -> None:
        from story_automator.core.collectors.supply_chain import TRIVY_SBOM

        profile = {"rules": {"supply_chain": {"trivy_severity": "CRITICAL"}}}
        cmd = TRIVY_SBOM.build_cmd("/tmp/checkout", profile)
        self.assertIn("CRITICAL", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.supply_chain import TRIVY_SBOM

        self.assertIsNotNone(TRIVY_SBOM.tool_version_cmd)
        self.assertIn("trivy", TRIVY_SBOM.tool_version_cmd)


class SupplyChainCollectorListTests(unittest.TestCase):
    def test_four_collectors(self) -> None:
        from story_automator.core.collectors.supply_chain import COLLECTORS

        self.assertEqual(len(COLLECTORS), 4)

    def test_all_expected_ids(self) -> None:
        from story_automator.core.collectors.supply_chain import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {
            "sbom-supply_chain", "cosign-supply_chain",
            "provenance-supply_chain", "trivy-sbom-supply_chain",
        })

    def test_all_supply_chain_category(self) -> None:
        from story_automator.core.collectors.supply_chain import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "supply_chain")

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.supply_chain import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_collectors_supply_chain.py -v`
Expected: `ModuleNotFoundError` — `supply_chain` module does not exist yet.

- [ ] **Step 3: Implement supply chain collector module**

```python
# skills/bmad-story-automator/src/story_automator/core/collectors/supply_chain.py
"""Supply-chain-category evidence collectors (§6.2).

PASS rule: SBOM emitted, deps signed/pinned, provenance present.
Collectors: sbom-supply_chain, cosign-supply_chain, provenance-supply_chain,
            trivy-sbom-supply_chain.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"

_DEFAULT_PROVENANCE_FILES = [
    ".slsa/provenance.json",
    "provenance.intoto.jsonl",
]


def _sbom_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("supply_chain") or {}
    fmt = rules.get("sbom_format", "spdx-json")
    return [
        sys.executable,
        str(_CHECKS_DIR / "sbom_check.py"),
        checkout,
        fmt,
    ]


def _cosign_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("supply_chain") or {}
    bundle = rules.get("cosign_bundle", "cosign.bundle")
    artifact = rules.get("cosign_artifact", "sbom.json")
    return ["cosign", "verify-blob", "--bundle", bundle, artifact]


def _provenance_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("supply_chain") or {}
    files = rules.get("provenance_files", _DEFAULT_PROVENANCE_FILES)
    return [
        sys.executable,
        str(_CHECKS_DIR / "presence_check.py"),
        checkout,
        json.dumps(files),
    ]


def _trivy_sbom_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("supply_chain") or {}
    severity = rules.get("trivy_severity", "HIGH,CRITICAL")
    return [
        "trivy", "sbom",
        "--exit-code", "1",
        "--severity", severity,
        ".",
    ]


SBOM = CollectorConfig(
    collector_id="sbom-supply_chain",
    tool="python3",
    category="supply_chain",
    build_cmd=_sbom_cmd,
    file_patterns=frozenset({"*.lock", "*.txt", "*.toml", "*.cfg", "package.json"}),
)

COSIGN = CollectorConfig(
    collector_id="cosign-supply_chain",
    tool="cosign",
    category="supply_chain",
    build_cmd=_cosign_cmd,
    tool_version_cmd=("cosign", "version"),
    file_patterns=frozenset(),
)

PROVENANCE = CollectorConfig(
    collector_id="provenance-supply_chain",
    tool="python3",
    category="supply_chain",
    build_cmd=_provenance_cmd,
    file_patterns=frozenset(),
)

TRIVY_SBOM = CollectorConfig(
    collector_id="trivy-sbom-supply_chain",
    tool="trivy",
    category="supply_chain",
    build_cmd=_trivy_sbom_cmd,
    tool_version_cmd=("trivy", "--version"),
    file_patterns=frozenset(),
)

COLLECTORS: list[CollectorConfig] = [SBOM, COSIGN, PROVENANCE, TRIVY_SBOM]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_collectors_supply_chain.py -v`
Expected: All 22 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_collectors_supply_chain.py skills/bmad-story-automator/src/story_automator/core/collectors/supply_chain.py
git commit -m "feat(collector): add supply chain collector module with trivy-sbom" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 8: Registration wiring + whole-registry tests

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/collectors/__init__.py`
- Modify: `tests/test_collector_registry.py` (add security-category coverage)

**Interfaces:**
- Consumes: `COLLECTORS` lists from security, license, compliance, supply_chain modules
- Produces: `register_core_collectors(registry)` now registers all 25 collectors (14 from M5 + 11 from M6). `CORE_COLLECTOR_IDS` frozenset updated.

- [ ] **Step 1: Write failing test for expanded registry**

Add to `tests/test_collector_registry.py` (or create a new section at the bottom):

```python
# Append to tests/test_collector_registry.py

class SecurityCategoryRegistrationTests(unittest.TestCase):
    def test_register_includes_security_collectors(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        security = reg.get_for_category("security")
        ids = {c.collector_id for c in security}
        self.assertEqual(ids, {
            "semgrep-security", "trivy-vuln-security",
            "osv-security", "gitleaks-security",
        })

    def test_register_includes_license_collectors(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        license_colls = reg.get_for_category("license")
        ids = {c.collector_id for c in license_colls}
        self.assertEqual(ids, {"license-check-license"})

    def test_register_includes_compliance_collectors(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        compliance = reg.get_for_category("compliance")
        ids = {c.collector_id for c in compliance}
        self.assertEqual(ids, {"compliance-rules-compliance", "conftest-compliance"})

    def test_register_includes_supply_chain_collectors(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        sc = reg.get_for_category("supply_chain")
        ids = {c.collector_id for c in sc}
        self.assertEqual(ids, {
            "sbom-supply_chain", "cosign-supply_chain",
            "provenance-supply_chain", "trivy-sbom-supply_chain",
        })

    def test_total_collector_count(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        self.assertEqual(len(reg.all_collectors()), 25)

    def test_all_categories_present(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        cats = reg.all_categories()
        for expected in ("security", "license", "compliance", "supply_chain"):
            self.assertIn(expected, cats)

    def test_core_collector_ids_frozenset(self) -> None:
        from story_automator.core.collectors import CORE_COLLECTOR_IDS

        self.assertEqual(len(CORE_COLLECTOR_IDS), 25)
        self.assertIn("semgrep-security", CORE_COLLECTOR_IDS)
        self.assertIn("license-check-license", CORE_COLLECTOR_IDS)
        self.assertIn("compliance-rules-compliance", CORE_COLLECTOR_IDS)
        self.assertIn("conftest-compliance", CORE_COLLECTOR_IDS)
        self.assertIn("sbom-supply_chain", CORE_COLLECTOR_IDS)
        self.assertIn("trivy-sbom-supply_chain", CORE_COLLECTOR_IDS)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_collector_registry.py::SecurityCategoryRegistrationTests -v`
Expected: FAIL — security collectors not registered yet (new categories missing from `_ALL`).

- [ ] **Step 3: Update __init__.py to register new categories**

Replace the contents of `skills/bmad-story-automator/src/story_automator/core/collectors/__init__.py`:

```python
"""Core evidence collector registration (§6.2, §8 module 3).

Registers all built-in collectors for correctness, static, docs, process,
security, license, compliance, supply_chain.
"""

from __future__ import annotations

from ..collector_registry import CollectorRegistry
from .compliance import COLLECTORS as _COMPLIANCE
from .correctness import COLLECTORS as _CORRECTNESS
from .docs import COLLECTORS as _DOCS
from .license import COLLECTORS as _LICENSE
from .process import COLLECTORS as _PROCESS
from .security import COLLECTORS as _SECURITY
from .static import COLLECTORS as _STATIC
from .supply_chain import COLLECTORS as _SUPPLY_CHAIN

__all__ = ["register_core_collectors", "CORE_COLLECTOR_IDS"]

_ALL = (
    _COMPLIANCE + _CORRECTNESS + _DOCS + _LICENSE
    + _PROCESS + _SECURITY + _STATIC + _SUPPLY_CHAIN
)

CORE_COLLECTOR_IDS: frozenset[str] = frozenset(c.collector_id for c in _ALL)


def register_core_collectors(registry: CollectorRegistry) -> None:
    """Register all built-in collectors into the given registry."""
    for config in _ALL:
        registry.register(config)
```

- [ ] **Step 4: Run all registry tests to verify they pass**

Run: `python -m pytest tests/test_collector_registry.py -v`
Expected: All tests PASS including the new `SecurityCategoryRegistrationTests`.

- [ ] **Step 5: Verify no existing tests broke**

Run: `python -m pytest tests/test_collectors_correctness.py tests/test_collectors_static.py tests/test_collectors_docs.py tests/test_collectors_process.py -v`
Expected: All existing collector tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/collectors/__init__.py tests/test_collector_registry.py
git commit -m "feat(collector): register security collectors in core registry" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 9: Pipeline integration tests

**Files:**
- Modify: `tests/test_collector_integration.py`

**Interfaces:**
- Consumes: `CollectorRegistry`, `run_gate_collectors`, `register_core_collectors`, verdict functions
- Produces: integration tests proving security/license/compliance/supply_chain collectors work through the full gate pipeline

- [ ] **Step 1: Write integration tests for security categories**

Append to `tests/test_collector_integration.py`:

```python
class SecurityCategoryPipelineTests(unittest.TestCase):
    """Pipeline tests with security, license, compliance, supply_chain categories."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-sec-integration-")
        self.project_root = Path(self.tmpdir) / "project"
        self.project_root.mkdir()
        self.base_sha = _init_repo(self.project_root)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.project_root), "worktree", "prune"],
            capture_output=True,
        )
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _security_profile(self) -> dict[str, Any]:
        return {
            "categories": {
                "code": ["security", "license", "compliance", "supply_chain"],
                "system": [],
            },
            "categories_na": [],
            "rules": {
                "security": {},
                "license": {"forbidden": ["BSL-1.1"], "boundary": {}},
                "compliance": {},
                "supply_chain": {},
            },
            "timeouts": {},
        }

    def _security_registry(self) -> CollectorRegistry:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="semgrep-security",
            tool="python3",
            category="security",
            build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="license-check-license",
            tool="python3",
            category="license",
            build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="compliance-rules-compliance",
            tool="python3",
            category="compliance",
            build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="sbom-supply_chain",
            tool="python3",
            category="supply_chain",
            build_cmd=_ok_cmd,
        ))
        return reg

    def test_all_security_categories_pass(self) -> None:
        profile = self._security_profile()
        reg = self._security_registry()
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-sec-pass", self.base_sha,
                profile, reg,
            )
        self.assertEqual(len(outcomes), 4)
        for outcome in outcomes:
            self.assertEqual(outcome.evidence["status"], "ok")
        records = load_evidence_bundle(self.project_root, "gate-sec-pass")
        verdicts = {
            r["category"]: verdict_for_collector_status(r["status"])
            for r in records
        }
        self.assertEqual(aggregate_verdicts(verdicts), "PASS")

    def test_security_fail_propagates(self) -> None:
        profile = self._security_profile()
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="semgrep-security",
            tool="python3",
            category="security",
            build_cmd=_fail_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="license-check-license",
            tool="python3",
            category="license",
            build_cmd=_ok_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-sec-fail", self.base_sha,
                profile, reg,
            )
        records = load_evidence_bundle(self.project_root, "gate-sec-fail")
        verdicts = {
            r["category"]: verdict_for_collector_status(r["status"])
            for r in records
        }
        self.assertEqual(verdicts["security"], "FAIL")
        self.assertEqual(verdicts["license"], "PASS")
        self.assertEqual(aggregate_verdicts(verdicts), "FAIL")

    def test_kill_switch_security_tool(self) -> None:
        profile = self._security_profile()
        profile["rules"]["security"]["disabled_tools"] = ["python3"]
        reg = self._security_registry()
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-sec-kill", self.base_sha,
                profile, reg,
            )
        run_cats = {o.config.category for o in outcomes}
        self.assertNotIn("security", run_cats)
        self.assertIn("license", run_cats)

    def test_categories_na_excludes_compliance(self) -> None:
        profile = self._security_profile()
        profile["categories_na"] = ["compliance"]
        reg = self._security_registry()
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-sec-na", self.base_sha,
                profile, reg,
            )
        run_cats = {o.config.category for o in outcomes}
        self.assertNotIn("compliance", run_cats)
        self.assertIn("security", run_cats)
```

- [ ] **Step 2: Run integration tests to verify they pass**

Run: `python -m pytest tests/test_collector_integration.py -v`
Expected: All tests PASS (existing + new `SecurityCategoryPipelineTests`).

- [ ] **Step 3: Commit**

```bash
git add tests/test_collector_integration.py
git commit -m "test(collector): add security category pipeline integration tests" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 10: Quality gates

**Files:** All files from Tasks 1-9

**Interfaces:** None (validation only)

- [ ] **Step 1: Run ruff on all new/modified files**

Run: `ruff check skills/bmad-story-automator/src/story_automator/core/collectors/security.py skills/bmad-story-automator/src/story_automator/core/collectors/license.py skills/bmad-story-automator/src/story_automator/core/collectors/compliance.py skills/bmad-story-automator/src/story_automator/core/collectors/supply_chain.py skills/bmad-story-automator/src/story_automator/core/checks/license_check.py skills/bmad-story-automator/src/story_automator/core/checks/sbom_check.py`
Expected: No errors.

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All tests PASS (existing 87+ test files + 6 new test files).

- [ ] **Step 3: Verify LOC limits**

Run: `wc -l skills/bmad-story-automator/src/story_automator/core/collectors/security.py skills/bmad-story-automator/src/story_automator/core/collectors/license.py skills/bmad-story-automator/src/story_automator/core/collectors/compliance.py skills/bmad-story-automator/src/story_automator/core/collectors/supply_chain.py skills/bmad-story-automator/src/story_automator/core/checks/license_check.py skills/bmad-story-automator/src/story_automator/core/checks/sbom_check.py`
Expected: All files under 500 LOC.

- [ ] **Step 4: Verify collector count**

Run: `python -c "from story_automator.core.collectors import CORE_COLLECTOR_IDS; print(f'{len(CORE_COLLECTOR_IDS)} collectors registered'); assert len(CORE_COLLECTOR_IDS) == 25"`
Expected: `25 collectors registered`

- [ ] **Step 5: Fix any issues found, commit**

If ruff or tests flagged issues, fix them and commit:

```bash
git add -A
git commit -m "fix(collector): quality gate fixes for collection-m6-security-collectors" --trailer "Generated-By: claude-opus-4-6"
```
