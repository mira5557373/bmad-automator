#!/usr/bin/env python3
from __future__ import annotations

import sys
from subprocess import CalledProcessError

from smoke_prep.inputs import smoke_inputs
from smoke_prep.process import SmokeError


def main() -> int:
    try:
        inputs = smoke_inputs()
    except (CalledProcessError, OSError, ValueError, SmokeError) as exc:
        print(f"smoke input determinism failed: {exc}", file=sys.stderr)
        return 1

    gunz = inputs["gunz"]
    bmad = inputs["bmadMethod"]
    print("smoke input determinism ok")
    print(f"- repo: {gunz['repo']}")
    print(f"- branch: {gunz['branch']}")
    print(f"- commit: {gunz['commit']}")
    print(f"- bmad method npm spec: {bmad['spec']}")
    print(f"- bmad method resolved version: {bmad['resolvedVersion']}")
    print(f"- bmad method install spec: {bmad['installSpec']}")
    print(f"- bmad method integrity: {bmad['integrity']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
