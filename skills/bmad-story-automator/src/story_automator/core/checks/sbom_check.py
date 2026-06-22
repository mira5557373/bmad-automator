"""Validate SBOM generation via syft.

Standalone script invoked by the sbom-supply_chain collector.
Exit 0 = valid SBOM generated, exit 1 = error/invalid, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

# D-04: import the trust-boundary scrub helper for subprocess env hygiene.
try:
    from story_automator.core.audit import scrub_env_for_subprocess
except ImportError:  # pragma: no cover - defensive fallback
    def scrub_env_for_subprocess(env=None):  # type: ignore[no-redef]
        src = dict(os.environ if env is None else env)
        src.pop("BMAD_AUDIT_KEY", None)
        return src


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
            env=scrub_env_for_subprocess(),
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
