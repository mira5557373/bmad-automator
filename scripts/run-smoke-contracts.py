#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


TEST_MODULES = [
    "tests.test_runtime_helper_contracts",
    "tests.test_orchestrator_parse",
    "tests.test_success_verifiers",
    "tests.test_tmux_runtime",
    "tests.test_state_validation",
    "tests.test_runtime_policy",
    "tests.test_state_policy_metadata",
    "tests.test_runtime_layout",
    "tests.test_agent_config_model",
]

ENVIRONMENT_SKIP_REASONS = {"tmux not available"}


def unexpected_skips(skipped: list[tuple[object, str]]) -> list[tuple[object, str]]:
    return [(test, reason) for test, reason in skipped if str(reason) not in ENVIRONMENT_SKIP_REASONS]


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    suite = unittest.defaultTestLoader.loadTestsFromNames(TEST_MODULES)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if result.skipped:
        unexpected = unexpected_skips(result.skipped)
        if unexpected:
            print(f"smoke:contracts got {len(unexpected)} unexpected skipped tests", file=sys.stderr)
            for test, reason in unexpected:
                print(f"- {test}: {reason}", file=sys.stderr)
            return 1
        print(f"smoke:contracts skipped {len(result.skipped)} allowed environment-dependent tests", file=sys.stderr)
        for test, reason in result.skipped:
            print(f"- {test}: {reason}", file=sys.stderr)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
