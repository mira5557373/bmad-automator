# M01 Plan — Adversarial Review (v1)

**Date:** 2026-06-14
**Reviewer:** general-purpose subagent (fresh context, no prior conversation memory)
**Subject:** `docs/superpowers/plans/2026-06-14-m01-event-types.md` (commit `c7fc50a`)
**Verdict:** REWORK
**Action taken:** plan v2 applies all CRITICAL + HIGH + NOTE fixes (see commit `<v2-commit>` below)

---

## Findings summary

| # | Severity | Category | Finding | v2 fix |
|---|---|---|---|---|
| 1 | CRITICAL | Spec violation | REQ-07 "missing required field raises TypeError" silently violated by `= ""` / `= 0` defaults on subclass fields | Switched all 13 subclasses to `@dataclass(kw_only=True)` with no field defaults |
| 2 | HIGH | Gate non-enforcing | `coverage report` lacks `--fail-under=85` flag; gate is informational only | Added `--fail-under=85` to Task 14 Step 3 |
| 3 | HIGH | Wording mismatch | Spec says `pytest`, plan uses `unittest`; pytest not installed | Added pytest dev-install to Task 14 Step 0; canonical test command remains unittest, pytest only runs the spec gate |
| 4 | HIGH | Gate proxy | `wc -l` for 500-LOC gate overcounts docstrings/blanks | Documented as conservative proxy + added optional SLOC tool note |
| 5 | HIGH | Antipattern | `UnknownEvent.raw_fields: dict = None` + `__post_init__` | Replaced with `field(default_factory=dict)` |
| 6 | HIGH | Test hygiene | Registry-mutating tests rely on `finally:` cleanup that aborts skip; mutation leaks across tests | Wrapped registry-mutating tests in `setUp`/`tearDown` snapshot/restore |
| 7 | HIGH | Spec adherence | Task 13 UnknownEvent round-trip uses `json.loads()` equality, softer than REQ-09 byte-equal | Added `self.assertEqual(reemitted, original)` byte-equal assertion |
| 8 | NOTE | Code smell | `_RequiresPayload` defined but unused in Task 8 Step 1 | Removed dead code |
| 9 | NOTE | Confusing prose | Task 9 Step 3 self-contradicts about which test is at risk | Rewrote the explanatory paragraph |
| 10 | NOTE | Test wording | `test_subclass_without_event_type_is_not_registered` doesn't actually instantiate the class | Strengthened the test to assert it can be instantiated AND is absent from registry |
| 11 | NOTE | Inventory exhaustiveness | Site-inventory grep could also have searched `to_json_line`, `parse_event`, `dataclass.*Event` | Added these patterns to Task 1 Step 1 |

## Reviewer notes preserved verbatim (selected)

> "Plan as written will pass its own tests but **violates the spec it claims to implement**. Recommendation: rework Task 9-12 to use `@dataclass(kw_only=True)` and drop the `= ""` / `= 0` defaults on subclass fields. Re-validate Task 8's `test_parse_missing_required_field_raises_type_error` against the new shape — should pass naturally."

> "Coverage realism: Module structure is mostly dataclass declarations + 4 method implementations + 1 parse function. Reaching 85% line coverage is trivial — every line outside `__init_subclass__` duplicate-detection branch is naturally exercised by the round-trip tests. Should easily hit 95%+."

> "All test bodies use plain Python strings and dicts — no shell escapes. Plan-level commands assume git-bash; documented assumption is acceptable."

## Process

1. v1 plan (`c7fc50a`) → adversarial review (this document)
2. v2 plan applies all findings — commit message references this review
3. Optional: a second adversarial review on v2 to confirm closure (not run; cost vs benefit doesn't justify it for a 14-task wedge atom)

The reviewer's full report is preserved in the conversation transcript and in
`docs/superpowers/reviews/transcripts/2026-06-14-m01-plan-review-raw.md` if
the operator wants to audit independently.
