from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class SmokeError(RuntimeError):
    pass


def step(name: str) -> None:
    print(f"\n==> {name}", flush=True)


def run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    print(f"+ ({cwd}) {' '.join(args)}", flush=True)
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        check=check,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


def ensure_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise SmokeError(f"missing required tool: {name}")
