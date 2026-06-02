from __future__ import annotations

from pathlib import Path


REPO_URL = "https://github.com/bma-d/gunz.git"
BRANCH = "bmad-smoke-test"
PINNED_COMMIT = "fca6470d329668019dace305b5f0f3c9b62cb113"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]
