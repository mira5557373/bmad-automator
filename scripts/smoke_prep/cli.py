from __future__ import annotations

import argparse
import subprocess
import sys

from .automator import (
    install_bmad,
    install_project_automator,
    pack_project_automator,
    smoke_env,
    verify_layout,
)
from .config import repo_root
from .gunz import prepare_gunz
from .process import SmokeError, ensure_tool
from .report import write_next_steps
from .workspace import reset_dir, resolve_workspace


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare the pinned gunz BMAD project for Story Automator smoke testing.",
    )
    parser.add_argument(
        "--workspace",
        default=".smoke",
        help="Repo-relative ignored workspace for clone, npm cache, and reports.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the smoke workspace before preparing it.",
    )
    parser.add_argument(
        "--skip-bmad-install",
        action="store_true",
        help="Skip BMAD core/BMM install; useful after a previous successful run.",
    )
    parser.add_argument(
        "--skip-automator-install",
        action="store_true",
        help="Skip installing the project-local automator into the smoke repo.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = repo_root()

    try:
        ensure_tool("git")
        workspace = resolve_workspace(root, args.workspace)
        gunz_dir = workspace / "gunz"
        ensure_tool("node")
        ensure_tool("npm")
        ensure_tool("npx")

        if args.reset:
            reset_dir(workspace)
        workspace.mkdir(parents=True, exist_ok=True)

        env = smoke_env(workspace)
        prepare_gunz(workspace, gunz_dir)
        if not args.skip_bmad_install:
            install_bmad(gunz_dir, env)
        if not args.skip_automator_install:
            tarball = pack_project_automator(root, workspace, env)
            install_project_automator(gunz_dir, tarball, env)
        verify_layout(gunz_dir)
        next_steps = write_next_steps(workspace, gunz_dir)

    except (OSError, subprocess.CalledProcessError, SmokeError) as exc:
        print(f"smoke prep failed: {exc}", file=sys.stderr)
        return 1

    print("")
    print("smoke prep ok")
    print(f"workspace: {workspace}")
    print(f"project: {gunz_dir}")
    print(f"next steps: {next_steps}")
    return 0
