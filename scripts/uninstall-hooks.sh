#!/usr/bin/env bash
# Uninstall: clear the project-local core.hooksPath setting.
#
# Use this if you've deleted .githooks/ or want to revert to default
# git hooks. The project-local config is removed; global git config is
# never touched.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

if git config --get core.hooksPath >/dev/null 2>&1; then
  PRIOR="$(git config --get core.hooksPath)"
  git config --unset core.hooksPath
  echo "Uninstalled: core.hooksPath (was '$PRIOR')"
else
  echo "No project-local core.hooksPath was set; nothing to do."
fi
