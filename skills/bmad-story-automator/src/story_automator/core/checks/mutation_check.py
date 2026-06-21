"""Run mutation testing and check score against threshold.

Standalone script invoked by the mutation collector.
Supports mutmut (Python) and Stryker (JS/TS).
Exit 0 = score >= threshold, exit 1 = below or error, exit 2 = usage.

Stdout includes a MUTATION_RESULT: JSON line with metrics.
Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

VALID_TOOLS = frozenset({"mutmut", "stryker"})

_KILLED_RE = re.compile(r"Killed:\s*(\d+)", re.IGNORECASE)
_SURVIVED_RE = re.compile(r"Survived:\s*(\d+)", re.IGNORECASE)
_TIMEOUT_RE = re.compile(r"Timeout:\s*(\d+)", re.IGNORECASE)


def _parse_mutmut_score(output: str) -> tuple[float, int, int, int]:
    """Parse mutmut results output for mutation score."""
    killed = 0
    survived = 0
    m = _KILLED_RE.search(output)
    if m:
        killed = int(m.group(1))
    m = _SURVIVED_RE.search(output)
    if m:
        survived = int(m.group(1))
    m = _TIMEOUT_RE.search(output)
    timeout_count = int(m.group(1)) if m else 0
    total = killed + survived + timeout_count
    score = (killed / total * 100) if total > 0 else 0.0
    return score, killed, survived, total


def _parse_stryker_score(report: dict) -> tuple[float, int, int, int]:
    """Parse Stryker JSON mutation report."""
    killed = 0
    survived = 0
    total = 0
    for file_data in (report.get("files") or {}).values():
        for mutant in file_data.get("mutants", []):
            total += 1
            status = mutant.get("status", "").lower()
            if status == "killed":
                killed += 1
            elif status == "survived":
                survived += 1
    score = (killed / total * 100) if total > 0 else 0.0
    return score, killed, survived, total


def _run_mutmut(checkout: str, changed_files: str) -> tuple[float, int, int, int]:
    """Run mutmut and parse results."""
    cmd = ["mutmut", "run"]
    if changed_files:
        cmd.extend(["--paths-to-mutate", changed_files])
    try:
        subprocess.run(
            cmd, cwd=checkout, capture_output=True, text=True,
            errors="replace", timeout=600,
        )
    except FileNotFoundError:
        raise
    except subprocess.TimeoutExpired:
        return 0.0, 0, 0, 0

    try:
        result = subprocess.run(
            ["mutmut", "results"], cwd=checkout,
            capture_output=True, text=True, errors="replace", timeout=30,
        )
        return _parse_mutmut_score(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 0.0, 0, 0, 0


def _run_stryker(checkout: str) -> tuple[float, int, int, int]:
    """Run Stryker and parse results."""
    try:
        subprocess.run(
            ["npx", "stryker", "run"], cwd=checkout,
            capture_output=True, text=True, errors="replace", timeout=600,
        )
    except FileNotFoundError:
        raise
    except subprocess.TimeoutExpired:
        return 0.0, 0, 0, 0

    report_path = os.path.join(checkout, "reports", "mutation", "mutation.json")
    if not os.path.isfile(report_path):
        return 0.0, 0, 0, 0
    try:
        with open(report_path, encoding="utf-8", errors="replace") as f:
            report = json.load(f)
        return _parse_stryker_score(report)
    except (json.JSONDecodeError, OSError):
        return 0.0, 0, 0, 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 3:
        print("usage: mutation_check.py <checkout> <tool> <threshold> [changed_files]")
        return 2
    checkout = args[0]
    tool = args[1]
    if tool not in VALID_TOOLS:
        print(f"unsupported mutation tool: {tool}; valid: {sorted(VALID_TOOLS)}")
        return 2
    try:
        threshold = float(args[2])
    except ValueError:
        print(f"invalid threshold: {args[2]}")
        return 2
    changed_files = args[3] if len(args) > 3 else ""

    try:
        if tool == "mutmut":
            score, killed, survived, total = _run_mutmut(checkout, changed_files)
        else:
            score, killed, survived, total = _run_stryker(checkout)
    except FileNotFoundError:
        print(f"mutation tool not found: {tool}")
        result = {
            "tool": tool, "mutation_score": 0.0,
            "mutants_total": 0, "mutants_killed": 0, "mutants_survived": 0,
            "threshold": threshold, "passed": False,
        }
        print(f"MUTATION_RESULT: {json.dumps(result)}")
        return 1

    passed = score >= threshold
    result = {
        "tool": tool, "mutation_score": round(score, 2),
        "mutants_total": total, "mutants_killed": killed,
        "mutants_survived": survived,
        "threshold": threshold, "passed": passed,
    }
    print(f"mutation score: {score:.1f}% (threshold: {threshold}%)")
    print(f"MUTATION_RESULT: {json.dumps(result)}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
