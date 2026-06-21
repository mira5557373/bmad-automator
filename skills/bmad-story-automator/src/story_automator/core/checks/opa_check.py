"""Run OPA constitution compile and test.

Standalone script invoked by the opa-agentic collector.
Exit 0 = both pass, exit 1 = failures, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import os
import subprocess
import sys

_OPA_TIMEOUT = 120


def _has_rego_files(policy_path: str) -> bool:
    """Check if any .rego files exist in the policy directory."""
    if not os.path.isdir(policy_path):
        return False
    for root, _dirs, files in os.walk(policy_path):
        for f in files:
            if f.endswith(".rego"):
                return True
    return False


def _has_test_files(policy_path: str) -> bool:
    """Check if any *_test.rego files exist."""
    if not os.path.isdir(policy_path):
        return False
    for root, _dirs, files in os.walk(policy_path):
        for f in files:
            if f.endswith("_test.rego"):
                return True
    return False


def run_opa_compile(
    checkout: str, policy_dir: str,
) -> tuple[bool, str]:
    """Run opa compile on the policy directory."""
    policy_path = os.path.join(checkout, policy_dir)
    if not _has_rego_files(policy_path):
        return True, "no policy directory or rego files found — N/A"
    try:
        result = subprocess.run(
            ["opa", "compile", policy_path],
            capture_output=True, text=True,
            timeout=_OPA_TIMEOUT, cwd=checkout,
        )
    except FileNotFoundError:
        return False, "opa not found in PATH"
    except subprocess.TimeoutExpired:
        return False, "opa compile timed out"
    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "").strip()[:200]
        return False, f"opa compile failed: {msg}"
    return True, "opa compile passed"


def run_opa_test(
    checkout: str, policy_dir: str,
) -> tuple[bool, str]:
    """Run opa test on the policy directory (if test rules exist)."""
    policy_path = os.path.join(checkout, policy_dir)
    if not _has_test_files(policy_path):
        return True, "no test rules found — skipping opa test"
    try:
        result = subprocess.run(
            ["opa", "test", policy_path, "-v"],
            capture_output=True, text=True,
            timeout=_OPA_TIMEOUT, cwd=checkout,
        )
    except FileNotFoundError:
        return False, "opa not found in PATH"
    except subprocess.TimeoutExpired:
        return False, "opa test timed out"
    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "").strip()[:200]
        return False, f"opa test failed: {msg}"
    return True, f"opa test passed: {(result.stdout or '').strip()[:100]}"


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: opa_check.py <checkout> [policy_dir]")
        return 2
    checkout = args[0]
    policy_dir = args[1] if len(args) > 1 else "policy"
    compile_ok, compile_msg = run_opa_compile(checkout, policy_dir)
    print(compile_msg)
    if not compile_ok:
        return 1
    test_ok, test_msg = run_opa_test(checkout, policy_dir)
    print(test_msg)
    if not test_ok:
        return 1
    print("OPA constitution checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
