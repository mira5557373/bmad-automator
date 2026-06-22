#!/usr/bin/env bash
# One-shot installer: point this repo's git hooks at .githooks/.
#
# Runs once per clone; idempotent. Captures any prior core.hooksPath
# so devs who had a custom hookspath can restore it later (gap B-L7).
#
# Uninstall via scripts/uninstall-hooks.sh.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

if [ ! -x ".githooks/pre-commit" ]; then
  echo "Error: .githooks/pre-commit not found or not executable." >&2
  exit 1
fi

PRIOR_HOOKS_PATH="$(git config --get core.hooksPath || true)"
if [ -n "$PRIOR_HOOKS_PATH" ] && [ "$PRIOR_HOOKS_PATH" != ".githooks" ]; then
  echo "Note: prior core.hooksPath was '$PRIOR_HOOKS_PATH'; restore later with:" >&2
  echo "  git config core.hooksPath $PRIOR_HOOKS_PATH" >&2
fi

git config core.hooksPath .githooks
echo "Installed: core.hooksPath = .githooks"
echo "Skip a single commit with: git commit --no-verify"
echo "Skip ad-hoc with:          BMAD_SKIP_PRECOMMIT=1 git commit ..."
echo "Uninstall with:            scripts/uninstall-hooks.sh"
