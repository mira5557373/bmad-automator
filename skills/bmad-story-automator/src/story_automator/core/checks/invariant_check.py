"""Run DG/ADR invariant checks from the invariant registry.

Standalone script invoked by the invariant collectors.
Exit 0 = all pass (or no rules to check), exit 1 = violations, exit 2 = usage error.

Filters the registry by check_type, then runs the matching tool (semgrep or
conftest) with the collected rule files.

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


def filter_registry(
    registry: list[dict], check_type: str,
) -> list[dict]:
    """Return checkable entries matching the given check_type."""
    return [
        e for e in registry
        if isinstance(e, dict)
        and e.get("checkable") == "yes"
        and e.get("check_type") == check_type
        and e.get("rule_file")
    ]


def build_semgrep_cmd(entries: list[dict]) -> list[str]:
    """Build a semgrep command from invariant entries."""
    config_args = [f"--config={e['rule_file']}" for e in entries]
    return ["semgrep", "scan"] + config_args + ["--error"]


def build_conftest_cmd(entries: list[dict]) -> list[str]:
    """Build a conftest command from invariant entries."""
    policy_args: list[str] = []
    for e in entries:
        policy_args.extend(["--policy", e["rule_file"]])
    return ["conftest", "test"] + policy_args + ["."]


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 3:
        print(
            "usage: invariant_check.py <checkout> <check_type> <registry_json>"
        )
        return 2
    checkout = args[0]
    check_type = args[1]
    if check_type not in ("semgrep", "conftest"):
        print(f"unsupported check type: {check_type}")
        return 2
    try:
        registry: list[dict] = json.loads(args[2])
    except (json.JSONDecodeError, TypeError):
        print(f"invalid registry JSON: {args[2][:80]}")
        return 2
    if not isinstance(registry, list):
        print("registry must be a JSON array")
        return 2
    entries = filter_registry(registry, check_type)
    if not entries:
        print(f"no {check_type} invariants to check")
        return 0
    if check_type == "semgrep":
        cmd = build_semgrep_cmd(entries)
    else:
        cmd = build_conftest_cmd(entries)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, cwd=checkout,
            env=scrub_env_for_subprocess(),
        )
    except FileNotFoundError:
        print(f"{check_type} not found")
        return 1
    except subprocess.TimeoutExpired:
        print(f"{check_type} timed out")
        return 1
    if result.stdout:
        print(result.stdout.rstrip())
    if result.returncode != 0:
        if result.stderr:
            for line in result.stderr.splitlines()[:5]:
                print(line)
        ids = [e["id"] for e in entries if "id" in e]
        print(f"invariant violations: {', '.join(ids)}")
        return 1
    ids = [e["id"] for e in entries if "id" in e]
    print(f"{len(entries)} {check_type} invariant(s) passed: {', '.join(ids)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
