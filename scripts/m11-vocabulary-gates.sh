#!/bin/sh
# M11 changelog vocabulary gates — portable across Windows git-bash, WSL Ubuntu, and Linux CI.
# Exits 0 only if every M11 doc-gate passes.

set -eu

REPO_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$REPO_ROOT"

fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
pass() { printf 'PASS: %s\n' "$1"; }

# Gate 1 — REQ-12 vocabulary-coverage: dated-heading count == tagged-heading count.
DATED=$(grep -hE '^##+ [0-9]{6}' docs/changelog/*.md | wc -l | tr -d ' ')
TAGGED=$(grep -hE '^##+ [0-9]{6}.*\[(FULL|LITE|SKELETON|DEFERRED)\]' docs/changelog/*.md | wc -l | tr -d ' ')
[ "$DATED" = "$TAGGED" ] || fail "REQ-12 vocabulary-coverage: dated=$DATED tagged=$TAGGED"
pass "REQ-12 vocabulary-coverage (dated=$DATED tagged=$TAGGED)"

# Gate 2 — Closed-vocabulary: any bracketed uppercase 3..9-letter token on a dated heading
# must be a member of {FULL, LITE, SKELETON, DEFERRED}.
EXTRA=$(grep -hE '^##+ [0-9]{6}' docs/changelog/*.md \
  | grep -oE '\[[A-Z]{3,9}\]' \
  | sort -u \
  | grep -vE '^\[(FULL|LITE|SKELETON|DEFERRED)\]$' || true)
[ -z "$EXTRA" ] || fail "Closed-vocabulary: foreign tokens on dated headings: $EXTRA"
pass "Closed-vocabulary (only allowed tokens present)"

# Gate 3 — REQ-09 sub-heading isolation: any tagged heading must also be a dated heading.
NONDATED_TAGGED=$(grep -hE '^##+' docs/changelog/*.md \
  | grep -E '\[(FULL|LITE|SKELETON|DEFERRED)\]' \
  | grep -vE '^##+ [0-9]{6}' || true)
[ -z "$NONDATED_TAGGED" ] || fail "REQ-09 sub-heading isolation: non-dated heading carries a tag: $NONDATED_TAGGED"
pass "REQ-09 sub-heading isolation (only dated headings tagged)"

# Gate 4 — REQ-13 contributor-guide vocabulary: each tag string must appear at
# least once as fenced inline code in CONTRIBUTING.md.
MISSING=""
for TAG in FULL LITE SKELETON DEFERRED; do
  if ! grep -qF "\`$TAG\`" CONTRIBUTING.md; then
    MISSING="$MISSING $TAG"
  fi
done
[ -z "$MISSING" ] || fail "REQ-13 contributor-guide: missing inline-code tags:$MISSING"
pass "REQ-13 contributor-guide (all four tags present as inline code)"
