#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from smoke_prep.config import repo_root
from smoke_prep.package_contracts import assert_package_contract
from smoke_prep.process import SmokeError


def main() -> int:
    try:
        identity = assert_package_contract(repo_root())
    except (OSError, subprocess.CalledProcessError, ValueError, SmokeError) as exc:
        print(f"package contract failed: {exc}", file=sys.stderr)
        return 1

    print("package contract ok")
    print(json.dumps(identity, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
