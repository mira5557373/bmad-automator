from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .process import SmokeError


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def resolve_workspace(root: Path, workspace_arg: str) -> Path:
    requested = Path(workspace_arg)
    if requested.is_absolute():
        raise SmokeError("--workspace must be a repo-relative ignored path")

    workspace = (root / requested).resolve()
    try:
        relative = workspace.relative_to(root)
    except ValueError as exc:
        raise SmokeError("--workspace must stay inside this repo") from exc

    if relative == Path("."):
        raise SmokeError("--workspace cannot be the repo root")

    check = subprocess.run(
        ["git", "check-ignore", "-q", relative.as_posix()],
        cwd=root,
        check=False,
    )
    if check.returncode != 0:
        raise SmokeError(
            f"--workspace must be gitignored before use: {relative.as_posix()}"
        )

    return workspace
