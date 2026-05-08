#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Usage: ./install.sh <bmad-project-root>

Installs the portable skill bundle into:
  .claude/skills/bmad-story-automator
  .claude/skills/bmad-story-automator-review

The Python helper runtime is already self-contained inside:
  .claude/skills/bmad-story-automator/scripts/story-automator
EOF
}

err() {
  echo "Error: $*" >&2
  exit 1
}

warn() {
  echo "Warn: $*" >&2
}

resolve_abs_dir() {
  local input="$1"
  [ -d "$input" ] || err "Directory not found: $input"
  cd "$input" >/dev/null 2>&1 && pwd
}

skill_file() {
  local skill_name="$1"
  printf '.claude/skills/%s/SKILL.md\n' "$skill_name"
}

backup_if_exists() {
  local path="$1"
  if [ -e "$path" ]; then
    local backup="${path}.backup-$(date -u +%Y%m%dT%H%M%SZ)"
    mv "$path" "$backup"
    echo "Backup: ${backup#$TARGET_ROOT/}"
  fi
}

backup_legacy_story_automator_installs() {
  local legacy_path
  local legacy_paths=(
    "$TARGET_ROOT/_bmad/bmm/4-implementation/bmad-story-automator"
    "$TARGET_ROOT/_bmad/bmm/4-implementation/story-automator"
    "$TARGET_ROOT/_bmad/bmm/4-implementation/story-automator-py"
    "$TARGET_ROOT/_bmad/bmm/4-implementation/bmad-story-automator-review"
    "$TARGET_ROOT/_bmad/bmm/4-implementation/story-automator-review"
    "$TARGET_ROOT/_bmad/bmm/workflows/4-implementation/bmad-story-automator"
    "$TARGET_ROOT/_bmad/bmm/workflows/4-implementation/story-automator"
    "$TARGET_ROOT/_bmad/bmm/workflows/4-implementation/bmad-story-automator-review"
    "$TARGET_ROOT/_bmad/bmm/workflows/4-implementation/story-automator-review"
  )

  for legacy_path in "${legacy_paths[@]}"; do
    backup_if_exists "$legacy_path"
  done
}

wrapper_points_to_skill_tree() {
  local shim="$1"
  grep -Eq '\.claude/skills/' "$shim"
}

wrapper_points_to_legacy_target() {
  local shim="$1"
  grep -Eq '_bmad/bmm/(4-implementation|workflows/4-implementation)|_bmad/tea/|/bmad-bmm-|/bmad-tea-' "$shim"
}

remove_obsolete_command_shim_if_legacy() {
  local shim="$1"
  [ -f "$shim" ] || return 0
  if wrapper_points_to_skill_tree "$shim"; then
    return 0
  fi
  if wrapper_points_to_legacy_target "$shim"; then
    rm -f "$shim"
    echo "Removed obsolete command shim: ${shim#$TARGET_ROOT/}"
  fi
}

cleanup_obsolete_command_shims() {
  local command_dir="$TARGET_ROOT/.claude/commands"
  local shim

  rm -f "$command_dir/bmad-bmm-story-automator-py.md"

  for shim in \
    "$command_dir/bmad-bmm-story-automator.md" \
    "$command_dir/bmad-bmm-story-automator-review.md" \
    "$command_dir/bmad-bmm-create-story.md" \
    "$command_dir/bmad-bmm-dev-story.md" \
    "$command_dir/bmad-bmm-retrospective.md" \
    "$command_dir/bmad-bmm-qa-generate-e2e-tests.md" \
    "$command_dir/bmad-tea-testarch-automate.md"; do
    remove_obsolete_command_shim_if_legacy "$shim"
  done
}

resolve_workflow_path() {
  local candidate
  for candidate in "$@"; do
    if [ -f "$TARGET_ROOT/$candidate" ]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

resolve_required_skill() {
  local skill_name="$1"
  local skill_path
  skill_path="$(skill_file "$skill_name")"
  [ -f "$TARGET_ROOT/$skill_path" ] || err "Required skill file missing: $skill_path"
  printf '%s\n' "$skill_path"
}

resolve_optional_skill() {
  local skill_name="$1"
  local skill_path

  skill_path="$(skill_file "$skill_name")"
  if [ -f "$TARGET_ROOT/$skill_path" ]; then
    printf '%s\n' "$skill_path"
    return 0
  fi

  if resolve_workflow_path \
    ".claude/skills/$skill_name/workflow.md" \
    ".claude/skills/$skill_name/workflow.yaml" >/dev/null; then
    warn "Optional skill incomplete: missing .claude/skills/$skill_name/SKILL.md. Story-automator still installs, but run with 'Skip Automate' enabled unless you fix that skill."
  fi
  return 1
}

if [ $# -ne 1 ]; then
  usage
  exit 1
fi

TARGET_ROOT="$(resolve_abs_dir "$1")"
TARGET_BMAD="$TARGET_ROOT/_bmad"
TARGET_SKILLS="$TARGET_ROOT/.claude/skills"
TARGET_STORY="$TARGET_SKILLS/bmad-story-automator"
TARGET_STORY_REVIEW="$TARGET_SKILLS/bmad-story-automator-review"
CREATE_STORY_SKILL="$(skill_file "bmad-create-story")"
DEV_STORY_SKILL="$(skill_file "bmad-dev-story")"
RETROSPECTIVE_SKILL="$(skill_file "bmad-retrospective")"
OPTIONAL_AUTOMATE_SKILL="$(skill_file "bmad-qa-generate-e2e-tests")"
SKILL_SOURCE_ROOT="$SCRIPT_DIR/skills"
STORY_SOURCE="$SKILL_SOURCE_ROOT/bmad-story-automator"
STORY_REVIEW_SOURCE="$SKILL_SOURCE_ROOT/bmad-story-automator-review"

[ -d "$TARGET_BMAD" ] || err "Target is not a BMAD project: missing $TARGET_BMAD"
[ -d "$SKILL_SOURCE_ROOT" ] || err "Missing skills root: $SKILL_SOURCE_ROOT"
[ -d "$STORY_SOURCE" ] || err "Missing story-automator skill: $STORY_SOURCE"
[ -d "$STORY_REVIEW_SOURCE" ] || err "Missing story-automator-review skill: $STORY_REVIEW_SOURCE"
[ -f "$STORY_SOURCE/SKILL.md" ] || err "Missing story-automator SKILL.md: $STORY_SOURCE/SKILL.md"
[ -f "$STORY_SOURCE/scripts/story-automator" ] || err "Missing runtime helper: $STORY_SOURCE/scripts/story-automator"
[ -d "$STORY_SOURCE/src/story_automator" ] || err "Missing runtime package dir: $STORY_SOURCE/src/story_automator"
[ -f "$STORY_SOURCE/pyproject.toml" ] || err "Missing runtime pyproject: $STORY_SOURCE/pyproject.toml"
[ -f "$STORY_REVIEW_SOURCE/SKILL.md" ] || err "Missing review SKILL.md: $STORY_REVIEW_SOURCE/SKILL.md"

CREATE_STORY_PATH="$(resolve_required_skill "bmad-create-story")"
DEV_STORY_PATH="$(resolve_required_skill "bmad-dev-story")"
RETROSPECTIVE_PATH="$(resolve_required_skill "bmad-retrospective")"

OPTIONAL_AUTOMATE_PATH=""
if ! OPTIONAL_AUTOMATE_PATH="$(resolve_optional_skill "bmad-qa-generate-e2e-tests")"; then
  if [ ! -f "$TARGET_ROOT/$OPTIONAL_AUTOMATE_SKILL" ]; then
    warn "Optional skill not found: .claude/skills/bmad-qa-generate-e2e-tests. Story-automator still installs, but run with 'Skip Automate' enabled unless you install that skill."
  fi
fi

backup_if_exists "$TARGET_STORY"
backup_if_exists "$TARGET_STORY_REVIEW"
backup_legacy_story_automator_installs

mkdir -p "$TARGET_STORY" "$TARGET_STORY_REVIEW"
cp -a "$STORY_SOURCE"/. "$TARGET_STORY"/
cp -a "$STORY_REVIEW_SOURCE"/. "$TARGET_STORY_REVIEW"/
chmod +x "$TARGET_STORY/scripts/story-automator"

cleanup_obsolete_command_shims

echo "Installed story-automator skill into: $TARGET_STORY"
echo "Installed story-automator-review skill into: $TARGET_STORY_REVIEW"
echo "Runtime helper: $TARGET_STORY/scripts/story-automator"
echo "Verified dependency skills:"
echo "  create-story: $CREATE_STORY_PATH"
echo "  dev-story: $DEV_STORY_PATH"
echo "  retrospective: $RETROSPECTIVE_PATH"
if [ -n "$OPTIONAL_AUTOMATE_PATH" ]; then
  echo "  qa-generate-e2e-tests: $OPTIONAL_AUTOMATE_PATH"
fi
echo "Claude command wrappers are not generated; invoke the bmad-story-automator skill directly."
