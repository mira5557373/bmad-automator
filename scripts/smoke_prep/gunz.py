from __future__ import annotations

from pathlib import Path

from .config import BRANCH, PINNED_COMMIT, REPO_URL
from .process import SmokeError, run, step


def prepare_gunz(workspace: Path, gunz_dir: Path) -> None:
    step("Prepare pinned gunz smoke repo")
    if gunz_dir.exists():
        print(f"reuse existing clone: {gunz_dir}")
    else:
        run(
            [
                "git",
                "clone",
                "--single-branch",
                "--branch",
                BRANCH,
                REPO_URL,
                str(gunz_dir),
            ],
            cwd=workspace,
        )

    run(
        ["git", "fetch", "origin", f"refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}"],
        cwd=gunz_dir,
    )
    ancestry = run(
        ["git", "merge-base", "--is-ancestor", PINNED_COMMIT, f"origin/{BRANCH}"],
        cwd=gunz_dir,
        check=False,
    )
    if ancestry.returncode != 0:
        raise SmokeError(f"pinned commit {PINNED_COMMIT} is not on origin/{BRANCH}")

    run(["git", "checkout", PINNED_COMMIT], cwd=gunz_dir)
    actual = run(["git", "rev-parse", "HEAD"], cwd=gunz_dir, capture=True)
    if actual.stdout.strip() != PINNED_COMMIT:
        raise SmokeError(
            f"gunz HEAD mismatch: expected {PINNED_COMMIT}, got {actual.stdout.strip()}"
        )
