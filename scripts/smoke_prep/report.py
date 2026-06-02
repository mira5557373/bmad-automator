from __future__ import annotations

import shlex
from pathlib import Path

from .config import BMAD_METHOD_NPM_SPEC, BRANCH, PINNED_COMMIT, REPO_URL


def write_next_steps(workspace: Path, gunz_dir: Path) -> Path:
    next_steps = workspace / "SMOKE_NEXT_STEPS.md"
    helper = (
        gunz_dir
        / ".claude"
        / "skills"
        / "bmad-story-automator"
        / "scripts"
        / "story-automator"
    )
    quoted_gunz_dir = shlex.quote(str(gunz_dir))
    quoted_helper = shlex.quote(str(helper))
    next_steps.write_text(
        "\n".join(
            [
                "# Story Automator Smoke",
                "",
                "Prepared project:",
                "",
                f"```text\n{gunz_dir}\n```",
                "",
                "Pinned source:",
                "",
                f"- repo: `{REPO_URL}`",
                f"- branch: `{BRANCH}`",
                f"- commit: `{PINNED_COMMIT}`",
                f"- deterministic input manifest: `{workspace / 'SMOKE_INPUTS.json'}`",
                "",
                "Installed pieces:",
                "",
                f"- BMAD core and BMM via `{BMAD_METHOD_NPM_SPEC}`",
                "- project-local `bmad-story-automator` packed from this checkout",
                "",
                "Manual smoke start:",
                "",
                "```bash",
                f"cd {quoted_gunz_dir}",
                "claude",
                "```",
                "",
                "Then ask Claude Code:",
                "",
                "```text",
                "Use the bmad-story-automator skill. Run the smoke test in this repo.",
                "```",
                "",
                "Helper sanity check:",
                "",
                "```bash",
                f"{quoted_helper} --help",
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return next_steps
