"""BMAD dev-story TDD loop integration (§8 module 2).

Provides the TDD loop hook that integrates burn-in into the
BMAD dev-story flow: RED (tests fail) -> GREEN (tests pass) ->
REFACTOR (burn-in verifies stability).
Exit 0 = TDD loop completed, exit 1 = TDD loop failed, exit 2 = usage.

Stdout includes a TDD_LOOP_RESULT: JSON line.
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


def _run_phase(
    name: str, cmd: list[str], checkout: str, timeout: int,
) -> dict:
    try:
        proc = subprocess.run(
            cmd, cwd=checkout,
            capture_output=True, text=True, errors="replace",
            timeout=timeout,
            env=scrub_env_for_subprocess(),
        )
        return {
            "phase": name,
            "exit_code": proc.returncode,
            "passed": proc.returncode == 0,
        }
    except FileNotFoundError:
        return {"phase": name, "exit_code": -1, "passed": False, "error": "command not found"}
    except subprocess.TimeoutExpired:
        return {"phase": name, "exit_code": -1, "passed": False, "error": "timeout"}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2:
        print("usage: tdd_loop.py <checkout> <phase> [-- test_command...]")
        print("  phases: red, green, refactor")
        return 2

    checkout = args[0]
    if not os.path.isdir(checkout):
        print(f"checkout directory does not exist: {checkout}")
        return 2
    phase = args[1].lower()
    if phase not in ("red", "green", "refactor"):
        print(f"unknown TDD phase: {phase}; expected red|green|refactor")
        return 2

    test_cmd = ["pytest", "--tb=short", "-q"]
    if "--" in args:
        sep = args.index("--")
        test_cmd = args[sep + 1:]
        if not test_cmd:
            print("test command is empty")
            return 2

    timeout = 300
    result = _run_phase(phase, test_cmd, checkout, timeout)

    if phase == "red":
        result["tdd_valid"] = not result["passed"]
        if result["passed"]:
            result["error"] = "RED phase: tests should FAIL but they PASSED"
    elif phase == "green":
        result["tdd_valid"] = result["passed"]
        if not result["passed"]:
            result["error"] = "GREEN phase: tests should PASS but they FAILED"
    else:
        result["tdd_valid"] = result["passed"]

    print(f"TDD {phase.upper()}: {'valid' if result['tdd_valid'] else 'INVALID'}")
    print(f"TDD_LOOP_RESULT: {json.dumps(result)}")
    return 0 if result["tdd_valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
