"""Burn-in runner: re-execute a test command N times to detect flaky tests.

Standalone script invoked by the burn-in-test-quality collector.
Runs the supplied test command N times, tracks per-run exit codes,
and optionally parses JUnit XML for per-test flakiness.
Exit 0 = no flaky, exit 1 = flaky or all-fail, exit 2 = usage.

Stdout includes a BURN_IN_RESULT: JSON line with metrics.
Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET


def _parse_junit_tests(xml_path: str) -> dict[str, str]:
    """Parse JUnit XML, return {test_name: 'pass'|'fail'|'error'|'skip'}."""
    results: dict[str, str] = {}
    try:
        tree = ET.parse(xml_path)
    except (ET.ParseError, OSError):
        return results
    for tc in tree.iter("testcase"):
        name = tc.get("classname", "") + "." + tc.get("name", "")
        if tc.find("failure") is not None or tc.find("error") is not None:
            results[name] = "fail"
        elif tc.find("skipped") is not None:
            results[name] = "skip"
        else:
            results[name] = "pass"
    return results


def _find_junit_xmls(checkout: str) -> list[str]:
    """Find JUnit XML files in common locations."""
    patterns = [
        os.path.join(checkout, "**", "junit*.xml"),
        os.path.join(checkout, "**", "results*.xml"),
        os.path.join(checkout, "**", "TEST-*.xml"),
    ]
    found: list[str] = []
    for pat in patterns:
        found.extend(glob.glob(pat, recursive=True))
    return sorted(set(found))


def _detect_flaky_tests(
    per_run_tests: list[dict[str, str]],
) -> list[dict[str, int]]:
    """Identify tests with mixed pass/fail across runs."""
    all_tests: set[str] = set()
    for run in per_run_tests:
        all_tests.update(run.keys())
    flaky: list[dict[str, int]] = []
    for test in sorted(all_tests):
        pass_count = sum(1 for run in per_run_tests if run.get(test) == "pass")
        fail_count = sum(
            1 for run in per_run_tests
            if run.get(test) in ("fail", "error")
        )
        if pass_count > 0 and fail_count > 0:
            flaky.append({"name": test, "pass_count": pass_count, "fail_count": fail_count})
    return flaky


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 3 or "--" not in args:
        print("usage: burn_in_check.py <checkout> <n_runs> [--timeout <secs>] -- <test_command...>")
        return 2

    sep = args.index("--")
    positional = args[:sep]
    checkout = positional[0]
    try:
        n_runs = int(positional[1])
    except ValueError:
        print(f"invalid n_runs: {positional[1]}")
        return 2
    if n_runs < 1:
        print(f"n_runs must be >= 1; got {n_runs}")
        return 2

    per_run_timeout = 300
    if "--timeout" in positional:
        ti = positional.index("--timeout")
        if ti + 1 < len(positional):
            try:
                per_run_timeout = int(positional[ti + 1])
            except ValueError:
                print(f"invalid timeout: {positional[ti + 1]}")
                return 2

    test_cmd = args[sep + 1:]
    if not test_cmd:
        print("test command is empty")
        return 2

    passed_runs = 0
    failed_runs = 0
    per_run_tests: list[dict[str, str]] = []

    for run_idx in range(n_runs):
        try:
            proc = subprocess.run(
                test_cmd, cwd=checkout,
                capture_output=True, text=True, errors="replace",
                timeout=per_run_timeout,
            )
        except FileNotFoundError:
            print(f"test command not found: {test_cmd[0]}")
            return 2
        except subprocess.TimeoutExpired:
            failed_runs += 1
            per_run_tests.append({})
            print(f"run {run_idx + 1}/{n_runs}: TIMEOUT")
            continue

        if proc.returncode == 0:
            passed_runs += 1
            print(f"run {run_idx + 1}/{n_runs}: PASS")
        else:
            failed_runs += 1
            print(f"run {run_idx + 1}/{n_runs}: FAIL (exit {proc.returncode})")

        junit_files = _find_junit_xmls(checkout)
        run_tests: dict[str, str] = {}
        for jf in junit_files:
            run_tests.update(_parse_junit_tests(jf))
        per_run_tests.append(run_tests)

    has_junit_data = any(bool(run) for run in per_run_tests)
    flaky_tests: list[dict[str, int]] = []
    if has_junit_data:
        flaky_tests = _detect_flaky_tests(per_run_tests)

    suite_flaky = passed_runs > 0 and failed_runs > 0

    result = {
        "total_runs": n_runs,
        "passed_runs": passed_runs,
        "failed_runs": failed_runs,
        "flaky": bool(flaky_tests) or suite_flaky,
        "flaky_count": len(flaky_tests),
        "flaky_tests": flaky_tests,
    }
    print(f"BURN_IN_RESULT: {json.dumps(result)}")

    if result["flaky"] or failed_runs == n_runs:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
