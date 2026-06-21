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
    """Parse syft JSON output into a flat list of {name, license, locations}.

    Emits one entry per license per artifact. If an artifact has multiple licenses,
    each license gets its own package entry with the same name and locations.
    """
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
        locs = art.get("locations") or []
        loc_paths = [loc.get("path", "") for loc in locs if isinstance(loc, dict)]

        # Extract all license values from license list.
        lics = []
        for lic_entry in licenses:
            if isinstance(lic_entry, dict) and lic_entry.get("value"):
                lics.append(lic_entry["value"])

        # If no licenses found, emit one entry with empty license.
        if not lics:
            lics = [""]

        # Emit one package entry per license.
        for license_val in lics:
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
