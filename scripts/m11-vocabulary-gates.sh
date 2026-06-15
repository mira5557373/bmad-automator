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

# Gate 5 — REQ-11 ordering preservation: dated-heading line numbers per file
# must match the M1 audit's frozen signature. Format: "file:lineA,lineB,...".
# Files under docs/changelog/ that contain zero dated headings (such as the
# operator-facing audit-trail document added by docs-m2) are excluded from the
# signature so the gate stays stable as adjacent docs are added.
EXPECTED="\
docs/changelog/260401.md:3,26,61,85
docs/changelog/260412.md:3,34
docs/changelog/260413.md:3,27,51,77,104,129,148,168,195,215,250,277,302,330
docs/changelog/260414.md:3
docs/changelog/260415.md:3,33,51
docs/changelog/260506.md:3
docs/changelog/260508.md:3,25,43
docs/changelog/260517.md:3
docs/changelog/260519.md:3
docs/changelog/260615.md:3
docs/changelog/260616.md:3"

ACTUAL=$(for F in docs/changelog/*.md; do
  LINES=$(grep -nE '^##+ [0-9]{6}' "$F" | cut -d: -f1 | tr '\n' ',' | sed 's/,$//')
  [ -n "$LINES" ] || continue
  printf '%s:%s\n' "$F" "$LINES"
done)

# Compare via temp files — POSIX sh has no process substitution, so <(...) is
# avoided to keep the script runnable under dash on stock Debian/Ubuntu CI.
TMP_EXPECTED=$(mktemp 2>/dev/null || printf '/tmp/m11_exp.%s' "$$")
TMP_ACTUAL=$(mktemp 2>/dev/null || printf '/tmp/m11_act.%s' "$$")
printf '%s\n' "$EXPECTED" > "$TMP_EXPECTED"
printf '%s\n' "$ACTUAL" > "$TMP_ACTUAL"
DIFF=$(diff "$TMP_EXPECTED" "$TMP_ACTUAL" || true)
rm -f "$TMP_EXPECTED" "$TMP_ACTUAL"
[ -z "$DIFF" ] || fail "REQ-11 ordering-preservation drift detected:
$DIFF"
pass "REQ-11 ordering-preservation (all nine files match frozen line signature)"

# Gate 6 — REQ-10 prose-immutability + whitespace hygiene against the integration base.
# BASE env var lets CI override (default = origin/main, falling back to main if unfetched).
# AUDIT.md is excluded because it is a wholly new operator-facing document — every
# line is an addition, none describe a historical entry's prose, and REQ-10 only
# constrains "the prose body, bullet content, file list, or QA notes of any
# historical entry" (spec lines 22–23). The exclude pathspec keeps that intent.
# 260615.md (the M12a milestone entry itself) is excluded for the same reason —
# it is a wholly new entry, not a modification of an existing historical entry.
BASE="${BASE:-origin/main}"
if ! git rev-parse --verify --quiet "$BASE" >/dev/null; then BASE=main; fi
if git rev-parse --verify --quiet "$BASE" >/dev/null; then
  # M12c — Gate 6 allows four retraction-related ADDITIONS (^+ only) so the
  # retraction convention can land its worked example without falsely tripping
  # prose-immutability. Deletions (^-) under docs/changelog/*.md remain
  # forbidden, preserving the original M11 intent.
  NON_HEADING=$(git diff -U0 "$BASE"...HEAD -- 'docs/changelog/*.md' ':!docs/changelog/AUDIT.md' ':!docs/changelog/260615.md' ':!docs/changelog/260616.md' ':!docs/changelog/260617.md' \
    | grep -E '^[+-][^+-]' \
    | grep -vE '^[+-]## [0-9]{6}' \
    | grep -vE '^\+### Retractions[[:space:]]*$' \
    | grep -vE '^\+### Notes[[:space:]]*$' \
    | grep -vE '^\+- \[20[0-9]{2}-[0-9]{2}-[0-9]{2}\] Retracted by \[[0-9]{6}#[a-z0-9_-]+\]\(\./[0-9]{6}\.md#[a-z0-9_-]+\): [^[:space:]].*$' \
    | grep -vE '^\+Retracts: \[[0-9]{6}#[a-z0-9_-]+\]\(\./[0-9]{6}\.md#[a-z0-9_-]+\)[[:space:]]*$' \
    || true)
  [ -z "$NON_HEADING" ] || fail "REQ-10 prose-immutability: non-heading changes under docs/changelog/:
$NON_HEADING"
  pass "REQ-10 prose-immutability (only dated headings + retraction additions changed vs $BASE)"

  # Whitespace hygiene on every changed file we are responsible for.
  git diff --check "$BASE"...HEAD -- 'docs/changelog/*.md' CONTRIBUTING.md scripts/m11-vocabulary-gates.sh >/dev/null \
    || fail "Whitespace hygiene: git diff --check reported violations"
  pass "Whitespace hygiene (no trailing ws, no CRLF mix on changed files)"
else
  printf 'SKIP: no %s ref available — gate 6 skipped (acceptable for shallow CI checkouts)\n' "$BASE"
fi

# Gate 7 — Line-ending portability: every file the M11 vocab gates inspect must be LF-only.
CRLF_HITS=""
for F in CONTRIBUTING.md docs/changelog/*.md; do
  # Detect a literal CR (\r) anywhere in the file. Portable across GNU and BSD grep.
  if LC_ALL=C grep -l "$(printf '\r')" "$F" >/dev/null 2>&1; then
    CRLF_HITS="$CRLF_HITS $F"
  fi
done
[ -z "$CRLF_HITS" ] || fail "Line-ending portability: CRLF detected in:$CRLF_HITS"
pass "Line-ending portability (CONTRIBUTING.md + docs/changelog/*.md are LF-only)"
