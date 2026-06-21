"""Run test suite N times and detect flaky tests.

Standalone script invoked by the burn-in-test_quality collector.
Exit 0 = no flaky, 1 = flaky found, 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys

_TEST_RESULT_RE = re.compile(
    r"^(\S+::\S+)\s+(PASSED|FAILED|ERROR)", re.MULTILINE,
)


def parse_test_names(output: str) -> dict[str, bool]:
    """Parse test names and pass/fail status from test runner output."""
    results: dict[str, bool] = {}
    for match in _TEST_RESULT_RE.finditer(output):
        name = match.group(1)
        passed = match.group(2) == "PASSED"
        results[name] = passed
    return results


def run_burn_in(
    checkout: str,
    test_cmd: list[str],
    runs: int,
) -> dict[str, list[bool]]:
    """Run test command N times, collect per-test results."""
    all_results: dict[str, list[bool]] = {}
    for _ in range(runs):
        try:
            proc = subprocess.run(
                test_cmd,
                capture_output=True,
                text=True,
                timeout=600,
                cwd=checkout,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        run_results = parse_test_names(combined)
        for name, passed in run_results.items():
            all_results.setdefault(name, []).append(passed)
    return all_results


def detect_flaky(results: dict[str, list[bool]]) -> list[str]:
    """Return sorted list of test names that flipped between runs."""
    flaky: list[str] = []
    for name, outcomes in results.items():
        if len(outcomes) < 2:
            continue
        if len(set(outcomes)) > 1:
            flaky.append(name)
    return sorted(flaky)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 4:
        print("usage: burn_in_check.py <checkout> <runs> <max_flaky> <test_cmd_json>")
        return 2
    checkout = args[0]
    try:
        runs = int(args[1])
        max_flaky = int(args[2])
    except ValueError:
        print("runs and max_flaky must be integers")
        return 2
    try:
        test_cmd: list[str] = json.loads(args[3])
    except (json.JSONDecodeError, TypeError):
        print(f"invalid test command: {args[3]}")
        return 2
    if not isinstance(test_cmd, list) or not test_cmd:
        print("test_cmd must be a non-empty JSON array")
        return 2
    results = run_burn_in(checkout, test_cmd, runs)
    flaky = detect_flaky(results)
    for name in flaky:
        outcomes = results[name]
        pass_rate = sum(outcomes) / len(outcomes) * 100
        print(f"FLAKY: {name} ({pass_rate:.0f}% pass rate over {len(outcomes)} runs)")
    if len(flaky) > max_flaky:
        print(f"{len(flaky)} flaky test(s) found, max allowed {max_flaky}")
        return 1
    total = len(results)
    print(f"{total} test(s) across {runs} run(s), {len(flaky)} flaky (max {max_flaky})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
