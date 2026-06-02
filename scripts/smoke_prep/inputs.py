from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .config import BMAD_METHOD_NPM_SPEC, BRANCH, PINNED_COMMIT, REPO_URL
from .process import SmokeError


FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _resolve_bmad_method(env: dict[str, str] | None = None) -> dict[str, str]:
    result = subprocess.run(
        [
            "npm",
            "view",
            BMAD_METHOD_NPM_SPEC,
            "version",
            "dist.integrity",
            "--json",
        ],
        env=env,
        text=True,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    metadata = json.loads(result.stdout)
    version = metadata.get("version")
    integrity = metadata.get("dist", {}).get("integrity") or metadata.get(
        "dist.integrity"
    )
    if not version or not integrity:
        raise SmokeError(
            f"missing npm identity for {BMAD_METHOD_NPM_SPEC}: {result.stdout.strip()}"
        )
    return {
        "spec": BMAD_METHOD_NPM_SPEC,
        "resolvedVersion": version,
        "installSpec": f"bmad-method@{version}",
        "integrity": integrity,
    }


def smoke_inputs(env: dict[str, str] | None = None) -> dict:
    if not REPO_URL.startswith("https://github.com/"):
        raise SmokeError(f"unexpected smoke repo URL: {REPO_URL}")
    if not BRANCH:
        raise SmokeError("missing smoke repo branch")
    if not FULL_SHA_RE.match(PINNED_COMMIT):
        raise SmokeError(f"smoke repo commit is not a full SHA: {PINNED_COMMIT}")
    if BMAD_METHOD_NPM_SPEC != "bmad-method@next":
        raise SmokeError(
            "BMAD Method installer input changed; update Phase 01 input contract "
            f"before accepting: {BMAD_METHOD_NPM_SPEC}"
        )
    return {
        "gunz": {
            "repo": REPO_URL,
            "branch": BRANCH,
            "commit": PINNED_COMMIT,
        },
        "bmadMethod": _resolve_bmad_method(env),
    }


def write_smoke_inputs(workspace: Path, inputs: dict) -> Path:
    path = workspace / "SMOKE_INPUTS.json"
    path.write_text(
        json.dumps(inputs, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
