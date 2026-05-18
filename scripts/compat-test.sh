#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/bmad-story-automator-compat.XXXXXX")"
PACK_TARBALL=""

cleanup() {
  if [ -n "$PACK_TARBALL" ] && [ -f "$PACK_TARBALL" ]; then
    rm -f "$PACK_TARBALL"
  fi
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

assert_file() {
  local path="$1"
  [ -f "$path" ] || {
    echo "Missing file: $path" >&2
    exit 1
  }
}

assert_contains() {
  local needle="$1"
  local path="$2"
  grep -Fq "$needle" "$path" || {
    echo "Missing content in $path: $needle" >&2
    exit 1
  }
}

assert_not_contains() {
  local needle="$1"
  local path="$2"
  if grep -Fq "$needle" "$path"; then
    echo "Unexpected content in $path: $needle" >&2
    exit 1
  fi
}

make_skill() {
  local root="$1"
  local name="$2"
  mkdir -p "$root/.claude/skills/$name"
  printf -- '---\nname: %s\n---\n\nFollow ./workflow.md.\n' "$name" >"$root/.claude/skills/$name/SKILL.md"
  printf '# %s\n' "$name" >"$root/.claude/skills/$name/workflow.md"
}

make_project() {
  local root="$1"
  local manifest="$root/_bmad/_config/manifest.yaml"
  mkdir -p "$root/_bmad/_config" "$root/.claude/commands"
  make_skill "$root" bmad-create-story
  make_skill "$root" bmad-dev-story
  make_skill "$root" bmad-retrospective
  make_skill "$root" bmad-qa-generate-e2e-tests
  cat >"$manifest" <<'EOF'
installation:
  version: 6.6.0
  installDate: 2026-05-17T00:00:00.000Z
  lastUpdated: 2026-05-17T00:00:00.000Z
modules:
  - name: core
    version: 6.6.0
    source: built-in
  - name: baut
    version: v1.14.2
    installDate: 2026-05-17T00:00:00.000Z
    lastUpdated: 2026-05-17T00:00:00.000Z
    source: external
    npmPackage: bmad-story-automator
    repoUrl: https://github.com/bmad-code-org/bmad-automator
    channel: stable
    sha: 593f338532ea730b5c1a2dd86681e87b5b4f04dd
  - name: bmm
    version: 6.6.0
    source: built-in
ides:
  - claude-code
EOF
  printf 'team config untouched\n' >"$root/_bmad/config.toml"
  printf 'user config untouched\n' >"$root/_bmad/config.user.toml"
}

pack_fixture_tarball() {
  PACK_TARBALL="$(cd "$ROOT_DIR" && npm pack --silent)"
  PACK_TARBALL="$ROOT_DIR/$PACK_TARBALL"
  assert_file "$PACK_TARBALL"
}

run_legacy_baut_manifest_migration_case() {
  local root="$TMP_DIR/legacy-baut-manifest-migration"
  local manifest="$root/_bmad/_config/manifest.yaml"
  local install_log="$root/install.log"

  make_project "$root"
  npx --yes --package "file:$PACK_TARBALL" bmad-story-automator "$root" >"$install_log" 2>&1

  assert_file "$manifest.bak"
  assert_contains "name: baut" "$manifest.bak"
  assert_contains "name: core" "$manifest"
  assert_contains "name: bmm" "$manifest"
  assert_not_contains "name: baut" "$manifest"
  assert_contains "team config untouched" "$root/_bmad/config.toml"
  assert_contains "user config untouched" "$root/_bmad/config.user.toml"
  assert_contains "Migrated legacy baut manifest entry: _bmad/_config/manifest.yaml" "$install_log"
  assert_file "$root/.claude/skills/bmad-story-automator/SKILL.md"
  assert_file "$root/.claude/skills/bmad-story-automator-review/SKILL.md"
}

pack_fixture_tarball
run_legacy_baut_manifest_migration_case

echo "compat ok"
