from __future__ import annotations

import os
from pathlib import Path

from .package_contracts import pack_project
from .process import SmokeError, run, step


def install_bmad(gunz_dir: Path, env: dict[str, str], bmad_method_spec: str) -> None:
    step("Install BMAD core and BMM")
    run(
        [
            "npx",
            "--yes",
            bmad_method_spec,
            "install",
            "--tools",
            "claude-code",
            "--action",
            "install",
            "--modules",
            "core,bmm",
            "--yes",
            "--directory",
            str(gunz_dir),
        ],
        cwd=gunz_dir,
        env=env,
    )


def pack_project_automator(root: Path, workspace: Path, env: dict[str, str]) -> dict:
    step("Pack project-local automator")
    pack_dir = workspace / "packages"
    return pack_project(root, pack_dir, env)


def install_project_automator(
    gunz_dir: Path,
    package_identity: dict,
    env: dict[str, str],
) -> None:
    step("Install project-local automator into smoke project")
    run(
        [
            "npx",
            "--yes",
            "--package",
            f"file:{package_identity['tarball']}",
            "bmad-story-automator",
            str(gunz_dir),
        ],
        cwd=gunz_dir,
        env=env,
    )


def verify_layout(gunz_dir: Path) -> None:
    step("Verify smoke project layout")
    helper = (
        gunz_dir
        / ".claude"
        / "skills"
        / "bmad-story-automator"
        / "scripts"
        / "story-automator"
    )
    required = [
        gunz_dir / "_bmad" / "_config" / "manifest.yaml",
        gunz_dir / ".claude" / "skills" / "bmad-create-story" / "SKILL.md",
        gunz_dir / ".claude" / "skills" / "bmad-dev-story" / "SKILL.md",
        gunz_dir / ".claude" / "skills" / "bmad-retrospective" / "SKILL.md",
        gunz_dir / ".claude" / "skills" / "bmad-story-automator" / "SKILL.md",
        gunz_dir / ".claude" / "skills" / "bmad-story-automator-review" / "SKILL.md",
        helper,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SmokeError("missing expected smoke files:\n" + "\n".join(missing))

    run([str(helper), "--help"], cwd=gunz_dir)


def smoke_env(workspace: Path) -> dict[str, str]:
    env = os.environ.copy()
    home = workspace / "home"
    npm_cache = workspace / "npm-cache"
    home.mkdir(parents=True, exist_ok=True)
    npm_cache.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)
    env["NPM_CONFIG_CACHE"] = str(npm_cache)
    return env
