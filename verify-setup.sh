#!/usr/bin/env bash
# verify-setup.sh — confirms tooling is ready BEFORE any milestone work.
# sw doctor will warn on "workflow.json not found" until `sw init` runs in this worktree.
# That's expected here — the diagnostic is whether sw is callable + claude reachable.
export PATH="/c/Program Files/GitHub CLI:$PATH"
status=0

echo "[1/7] sw callable"
if command -v sw >/dev/null && sw --version >/dev/null 2>&1; then
  echo "  $(sw --version)"
else
  echo "  FAIL: sw not on PATH"; status=1
fi

echo "[2/7] claude reachable"
if command -v claude >/dev/null && claude --version >/dev/null 2>&1; then
  echo "  $(claude --version)"
else
  echo "  FAIL: claude not on PATH"; status=1
fi

echo "[3/7] convergence_gate hook importable"
hookout=$(echo "{}" | python -m superpower_workflow.hooks.convergence_gate 2>&1)
hookexit=$?
if [ $hookexit -eq 0 ]; then
  echo "  OK (exit 0)"
else
  echo "  FAIL: hook exit $hookexit, output: $hookout"; status=1
fi

echo "[4/7] git remotes"
git remote -v | sed 's/^/  /'

echo "[5/7] git identity (worktree-local)"
echo "  name=$(git config --local --get user.name)"
echo "  email=$(git config --local --get user.email)"

echo "[6/7] gh auth"
gh auth status 2>&1 | sed 's/^/  /' | head -8

echo "[7/7] Stop hook registered in ~/.claude/settings.json"
if grep -q "convergence_gate" /c/Users/Administrator/.claude/settings.json; then
  echo "  OK"
else
  echo "  FAIL: hook not in settings.json"; status=1
fi

echo ""
if [ $status -eq 0 ]; then
  echo "verify-setup: PASS"
else
  echo "verify-setup: FAIL"
fi
exit $status
