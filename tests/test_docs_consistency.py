"""Docs-consistency regression tests for the 2026-06-23 polish-docs commit.

Confirms that:

1. ``CHANGELOG.md`` has a 2026-06-23 (260623) dated entry and that the
   entry uses ONLY tags from the M11 closed vocabulary
   ``{FULL, LITE, SKELETON, DEFERRED}``.
2. The README's quick-start example imports a real public symbol
   (``run_production_gate``) from ``story_automator.core.gate_orchestrator``.
3. Every ``core/`` and ``core/innovation/`` module referenced by
   ``CLAUDE.md``'s "Recently shipped" section is importable.
4. ``CONTRIBUTING.md`` carries the four new section headings the
   polish-docs commit added.

These tests are deliberately structural — they check shape, not
content. Updating the entry text or the wording does not need to
break this suite; the suite only catches a docs drift that removes
or renames a section / module / vocabulary tag.
"""
from __future__ import annotations

import ast
import importlib
import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8")


class ChangelogConsistencyTests(unittest.TestCase):
    """CHANGELOG.md root file gains a 260623 entry under M11 vocabulary."""

    M11_VOCAB = {"FULL", "LITE", "SKELETON", "DEFERRED"}

    def setUp(self) -> None:
        self.text = _read("CHANGELOG.md")

    def test_changelog_2026_06_23_entry_present(self) -> None:
        # Heading shape: '## 260623 - [TAG] Title'.
        match = re.search(r"^## 260623\s*-\s*\[([A-Z]+)\]\s+\S", self.text, re.MULTILINE)
        self.assertIsNotNone(
            match,
            "CHANGELOG.md missing 260623 entry with '## 260623 - [TAG] Title' shape",
        )

    def test_changelog_uses_only_M11_vocabulary(self) -> None:
        # All bracketed tags on dated entry headings must be in the closed
        # vocabulary. We scan EVERY '## YYMMDD - [TAG] ...' line.
        bad = []
        for line in self.text.splitlines():
            m = re.match(r"^## \d{6}\s*-\s*\[([A-Z]+)\]", line)
            if not m:
                continue
            tag = m.group(1)
            if tag not in self.M11_VOCAB:
                bad.append((tag, line))
        self.assertEqual(
            bad,
            [],
            f"Non-M11 tags found in CHANGELOG.md dated entries: {bad}",
        )


class ReadmeImportsResolveTests(unittest.TestCase):
    """README.md quick-start example references real public symbols."""

    def test_readme_quick_start_imports_still_resolve(self) -> None:
        text = _read("README.md")
        self.assertIn(
            "from story_automator.core.gate_orchestrator import run_production_gate",
            text,
            "README.md quick-start no longer imports run_production_gate",
        )
        module = importlib.import_module(
            "story_automator.core.gate_orchestrator"
        )
        self.assertTrue(
            hasattr(module, "run_production_gate"),
            "run_production_gate missing from gate_orchestrator",
        )


class ClaudeMdModuleReferenceTests(unittest.TestCase):
    """Every module referenced in CLAUDE.md exists and is importable."""

    # The modules called out in CLAUDE.md "Recently shipped" + module-map.
    REFERENCED_MODULES = (
        "story_automator.core.audit_env_scrub",
        "story_automator.core.gate_lock_observability",
        "story_automator.core.innovation.cost_attribution",
        "story_automator.core.innovation.cost_evidence",
        "story_automator.core.innovation.lineage_ledger",
        "story_automator.core.innovation.session_usage_capture",
        "story_automator.core.innovation.spec_drift_persistence",
        "story_automator.core.innovation.spec_drift_watcher",
        "story_automator.core.integration.unified_state",
        "story_automator.core.usage_parsers.claude_jsonl",
        "story_automator.core.usage_parsers.codex_rollout",
        "story_automator.core.usage_parsers.gemini_chat",
        "story_automator.core.usage_parsers.none",
        "story_automator.core.usage_parsers.types",
    )

    def test_claude_md_references_modules_that_exist(self) -> None:
        text = _read("CLAUDE.md")
        for dotted in self.REFERENCED_MODULES:
            # 1. CLAUDE.md textually mentions the leaf or the dotted path.
            leaf = dotted.rsplit(".", 1)[-1]
            self.assertIn(
                leaf,
                text,
                f"CLAUDE.md does not textually mention {dotted}",
            )
            # 2. The module is importable.
            try:
                importlib.import_module(dotted)
            except ImportError as exc:  # pragma: no cover - defensive
                self.fail(
                    f"CLAUDE.md references {dotted} but it failed to import: {exc}"
                )


class CostAttributionDocstringTests(unittest.TestCase):
    """``cost_attribution`` module docstring reflects C3 having shipped.

    Pre-fix the docstring asserted the orchestrator wiring was
    "intentionally **not** included" while ``gate_orchestrator`` already
    imports and calls :func:`cost_evidence.emit_gate_cost_report`, which
    dispatches to the helpers in ``cost_attribution``. The regression test
    pins both halves of the contract: (a) the stale "not included" claim
    is gone, and (b) the orchestrator-wiring claim is still backed by the
    actual call site.
    """

    def test_cost_attribution_docstring_no_longer_disclaims_wiring(self) -> None:
        module = importlib.import_module(
            "story_automator.core.innovation.cost_attribution"
        )
        doc = module.__doc__ or ""
        self.assertNotIn(
            "intentionally **not** included",
            doc,
            "cost_attribution docstring still disclaims orchestrator wiring; "
            "C3 has shipped (gate_orchestrator calls emit_gate_cost_report).",
        )

    def test_gate_orchestrator_still_wires_cost_evidence(self) -> None:
        # Defensive: if the wiring ever gets removed, the docstring fix
        # would be a lie. Pin both sides of the C3 contract.
        orch = importlib.import_module(
            "story_automator.core.gate_orchestrator"
        )
        self.assertTrue(
            hasattr(orch, "emit_gate_cost_report"),
            "gate_orchestrator no longer re-exports emit_gate_cost_report; "
            "cost_attribution docstring must be re-checked.",
        )


class ValidateIsolationKwargsDocstringTests(unittest.TestCase):
    """``_validate_isolation_kwargs`` docstring matches the live caller set.

    Pre-fix the docstring listed four entry points that "call at the
    TOP" of the helper:
    ``run_gate_collectors``, ``run_production_gate``,
    ``run_system_gate``, ``_run_collectors``. Grepping the codebase
    confirmed only three direct call sites; ``_run_collectors`` is a
    thin wrapper in ``gate_orchestrator.py`` that forwards to
    ``run_gate_collectors`` (which validates), so validation runs by
    delegation rather than via a direct call from ``_run_collectors``.
    The regression test pins the docstring to (a) not claim
    ``_run_collectors`` as a direct caller and (b) acknowledge the
    delegation pattern, while also verifying the live grep still finds
    exactly three direct call sites in ``core/``.
    """

    CORE_DIR = (
        REPO_ROOT
        / "skills"
        / "bmad-story-automator"
        / "src"
        / "story_automator"
        / "core"
    )

    def _isolation_docstring(self) -> str:
        module = importlib.import_module(
            "story_automator.core.collector_isolation"
        )
        return module._validate_isolation_kwargs.__doc__ or ""

    def test_docstring_does_not_claim_run_collectors_as_direct_caller(self) -> None:
        doc = self._isolation_docstring()
        # The pre-fix docstring listed ``_run_collectors`` inside the
        # "entry point" enumeration. Post-fix, ``_run_collectors`` must
        # appear only in the parenthetical that explains the delegation
        # pattern, never inside an "entry point" enumeration.
        self.assertNotRegex(
            doc,
            r"entry point.*_run_collectors",
            "_validate_isolation_kwargs docstring still lists "
            "_run_collectors as a direct entry-point caller; it "
            "validates by delegation through run_gate_collectors.",
        )

    def test_docstring_acknowledges_delegation_pattern(self) -> None:
        doc = self._isolation_docstring()
        self.assertIn(
            "delegation",
            doc,
            "_validate_isolation_kwargs docstring no longer mentions "
            "the _run_collectors delegation pattern; future contributors "
            "will assume _run_collectors validates directly.",
        )

    def test_live_caller_set_matches_docstring(self) -> None:
        """Defensive: grep ``core/`` for direct call sites of the helper.

        The docstring promises three direct callers
        (``run_gate_collectors``, ``run_production_gate``,
        ``run_system_gate``). Any drift in either direction (a new
        wrapper that forgets to validate, or someone removing a
        validation site) shows up as a mismatch here.
        """
        call_sites: set[str] = set()
        callsite_re = re.compile(r"_validate_isolation_kwargs\s*\(")
        for path in sorted(self.CORE_DIR.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            # Skip the defining module itself.
            if path.name == "collector_isolation.py":
                continue
            for line in text.splitlines():
                # Ignore the ``from ... import`` line — that's not a call.
                if "import" in line:
                    continue
                if callsite_re.search(line):
                    call_sites.add(path.name)
        # The docstring's three direct callers live in exactly these
        # three modules.
        self.assertEqual(
            call_sites,
            {
                "collector_runner.py",
                "gate_orchestrator.py",
                "system_gate.py",
            },
            "Live call sites of _validate_isolation_kwargs no longer "
            "match the three modules its docstring promises; either "
            "update the docstring or add the missing validation.",
        )


class ContributingSectionHeadingsTests(unittest.TestCase):
    """The four polish-docs sections are present in CONTRIBUTING.md."""

    REQUIRED_HEADINGS = (
        "## sw-style discipline",
        "### TDD pattern",
        "### Sibling-module pattern",
        "### Additive-only `gate_file` field rule",
    )

    # Audit-floor heading is matched by a regex rather than a fixed string
    # so the documented class count can be bumped (e.g. "11 green" → "12
    # green") without breaking this test on every new invariant; the
    # regression test that actually pins the count against the live suite
    # lives in ``AuditFloorInvariantCountConsistencyTests`` below.
    AUDIT_FLOOR_HEADING_RE = re.compile(
        r"^### Audit-floor invariants \(\d+ green\)$",
        re.MULTILINE,
    )

    def test_contributing_section_headings_present(self) -> None:
        text = _read("CONTRIBUTING.md")
        missing = [h for h in self.REQUIRED_HEADINGS if h not in text]
        self.assertEqual(
            missing,
            [],
            f"CONTRIBUTING.md missing required section headings: {missing}",
        )

    def test_contributing_audit_floor_heading_present(self) -> None:
        text = _read("CONTRIBUTING.md")
        self.assertRegex(
            text,
            self.AUDIT_FLOOR_HEADING_RE,
            "CONTRIBUTING.md missing '### Audit-floor invariants (N green)' "
            "heading with a numeric class count.",
        )


class AuditFloorInvariantCountConsistencyTests(unittest.TestCase):
    """The "N green" count in CONTRIBUTING.md matches the live class count.

    Pre-fix CONTRIBUTING.md was anchored at "26 green" (a stale
    test-method count snapshot from polish commit 79fbd75) while C5 and
    G2 subsequently added two more invariant classes. CLAUDE.md
    simultaneously quoted "10 → 11" using a per-class delta and
    "24 → 26" using a per-method delta, leaving no single source of
    truth. The fix pins one metric — invariant **classes** — across all
    operator-facing docs and uses this regression test to keep them
    aligned with the live ``tests/test_audit_regression.py`` count.
    """

    AUDIT_REGRESSION_PATH = REPO_ROOT / "tests" / "test_audit_regression.py"
    AUDIT_FLOOR_HEADING_RE = re.compile(
        r"^### Audit-floor invariants \((\d+) green\)$",
        re.MULTILINE,
    )
    # Top-level ``class`` defs whose name ends in ``Invariant`` or
    # ``Baseline``. Excludes the ``_Mixin`` helper. This is the metric
    # CLAUDE.md's G2 entry ("10 → 11") increments and the metric
    # CONTRIBUTING.md is anchored against.
    CLASS_DEF_RE = re.compile(
        r"^class\s+\w+(?:Invariant|Baseline)\b",
        re.MULTILINE,
    )

    def _live_class_count(self) -> int:
        text = self.AUDIT_REGRESSION_PATH.read_text(encoding="utf-8")
        return len(self.CLASS_DEF_RE.findall(text))

    def test_contributing_heading_matches_live_class_count(self) -> None:
        live = self._live_class_count()
        contributing = _read("CONTRIBUTING.md")
        match = self.AUDIT_FLOOR_HEADING_RE.search(contributing)
        self.assertIsNotNone(
            match,
            "CONTRIBUTING.md missing '### Audit-floor invariants (N green)' "
            "heading.",
        )
        documented = int(match.group(1))
        self.assertEqual(
            documented,
            live,
            f"CONTRIBUTING.md heading says '{documented} green' but "
            f"tests/test_audit_regression.py has {live} invariant classes; "
            "bump the heading and the release-blocking guard line below it.",
        )

    def test_contributing_release_blocking_line_matches_live_class_count(self) -> None:
        live = self._live_class_count()
        contributing = _read("CONTRIBUTING.md")
        release_block_re = re.compile(
            r"regressing the class count below (\d+) is a release-blocking",
        )
        match = release_block_re.search(contributing)
        self.assertIsNotNone(
            match,
            "CONTRIBUTING.md missing 'regressing the class count below N is "
            "a release-blocking' sentence anchored to the live class count.",
        )
        documented = int(match.group(1))
        self.assertEqual(
            documented,
            live,
            f"CONTRIBUTING.md release-blocking floor pins '{documented}' "
            f"but live class count is {live}; both must move together.",
        )

    def test_contributing_method_count_aside_matches_live_method_count(self) -> None:
        """The illustrative 'exposes N test methods' aside in CONTRIBUTING.md
        tracks the live test-method count in ``tests/test_audit_regression.py``.

        Pre-fix CONTRIBUTING.md:144 read "exposes 40 test methods" while the
        live suite had 45 test methods (G2's WorktreePerUnitIsolationInvariant
        contributed 5 new methods). The class-count guard above is the
        release-blocking metric, but this method-count aside is still
        operator-facing prose that should not drift; pinning it here means
        future "+ N test methods" additions update the prose at commit time.
        """
        text = self.AUDIT_REGRESSION_PATH.read_text(encoding="utf-8")
        tree = ast.parse(text)
        live_methods = sum(
            1
            for cls in tree.body
            if isinstance(cls, ast.ClassDef)
            for n in cls.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name.startswith("test_")
        )
        contributing = _read("CONTRIBUTING.md")
        match = re.search(
            r"exposes\s+(\d+)\s+test\s+methods",
            contributing,
        )
        self.assertIsNotNone(
            match,
            "CONTRIBUTING.md missing 'exposes N test methods' prose aside in "
            "the Audit-floor invariants section.",
        )
        documented = int(match.group(1))
        self.assertEqual(
            documented,
            live_methods,
            f"CONTRIBUTING.md says 'exposes {documented} test methods' but "
            f"tests/test_audit_regression.py has {live_methods} test methods; "
            "bump the prose aside when adding/removing test methods.",
        )


class ReadmeTestCountFreshnessTests(unittest.TestCase):
    """README test-count claim is not anchored to a known-stale snapshot.

    Pre-fix README.md:62 read ``Tests: 4070 -> 4348 passing across the
    session.`` while the live suite at HEAD reports 4644 tests (4070
    session-start baseline + the C5 self-improving-gate + G2
    worktree-per-unit-isolation milestones that landed after the
    session-rollup doc was written). An operator running the repro
    command from the README and seeing 4644 would either suspect a
    dirty tree or chase ~296 phantom tests.

    The regression test pins the README's session-end claim against a
    known floor: post-fix the README must NOT carry the stale
    ``4070 -> 4348 passing across the session`` shape, AND if it
    quotes a current HEAD count it must be at or above 4644 (the
    confirmed live count when this regression test was added).
    The CHANGELOG.md occurrences at lines 11 and 117 are deliberately
    NOT pinned by this test because they sit inside the sealed
    ``## 260623`` historical entry and the CLAUDE.md hard guardrails
    forbid rewriting the prose body of any historical changelog entry.
    """

    # The frozen lower bound: live test count at the time this test was
    # added (4644). README must not claim fewer than this when it cites
    # a HEAD count. Tolerance band allows the live count to grow without
    # breaking this test — only a regression below the floor (or the
    # pre-fix 4348 anchor) trips it.
    HEAD_TEST_COUNT_FLOOR = 4644

    # Specific stale anchor the pre-fix README carried. Must not appear
    # in the README's tests-line unqualified by "session closed at" or
    # similar framing that makes it clear the number is historical.
    STALE_SESSION_END_ANCHOR = "4348"

    def test_readme_does_not_claim_4070_to_4348_as_current(self) -> None:
        text = _read("README.md")
        # Find any line that mentions the test count.
        tests_line_re = re.compile(r"^Tests:.*$", re.MULTILINE)
        match = tests_line_re.search(text)
        self.assertIsNotNone(
            match,
            "README.md no longer has a 'Tests: ...' line; either restore "
            "the line or update this regression test to match the new shape.",
        )
        tests_line = match.group(0)
        # The pre-fix line was exactly:
        #   ``Tests: 4070 -> 4348 passing across the session.``
        # Post-fix it may still mention 4348 as the historical
        # session-end anchor, but never as the current passing count.
        # We anchor on the precise stale shape "4070 -> 4348 passing
        # across the session" — the exact byte sequence the pre-fix
        # README carried — and reject it.
        stale_shape_re = re.compile(
            r"4070\s*(?:->|→)\s*4348\s+passing\s+across\s+the\s+session",
        )
        self.assertNotRegex(
            tests_line,
            stale_shape_re,
            "README.md still claims '4070 -> 4348 passing across the "
            "session' as the current count. C5 + G2 added ~296 tests "
            f"after the session rollup; live count is at least "
            f"{self.HEAD_TEST_COUNT_FLOOR}.",
        )

    def test_readme_head_count_is_at_or_above_known_floor(self) -> None:
        """If the README cites a current-HEAD test count, it must be >= floor.

        The README's post-fix shape mentions both a historical session
        anchor (4348) and a current HEAD count. The current HEAD count
        must be >= ``HEAD_TEST_COUNT_FLOOR`` (4644 — the live count when
        this test was added). The historical anchor stays unchanged
        because it describes a frozen-in-time snapshot.
        """
        text = _read("README.md")
        tests_line_re = re.compile(r"^Tests:.*$", re.MULTILINE)
        match = tests_line_re.search(text)
        self.assertIsNotNone(match)
        tests_line = match.group(0)
        # Extract every 4-digit integer in the tests line.
        numbers = [int(n) for n in re.findall(r"\b(\d{4})\b", tests_line)]
        self.assertTrue(
            numbers,
            "README.md tests-line carries no numeric test counts; "
            "either restore a numeric count or update this test.",
        )
        # The highest number on the line is treated as the "current
        # HEAD" claim — the README's post-fix shape uses the order
        # ``session-start -> HEAD (parenthetical historical anchor)``
        # so the HEAD number is the largest. Verify the largest number
        # is at or above the known floor.
        head_claim = max(numbers)
        self.assertGreaterEqual(
            head_claim,
            self.HEAD_TEST_COUNT_FLOOR,
            f"README.md tests-line cites '{head_claim}' as its highest "
            f"test count but the live suite at HEAD has at least "
            f"{self.HEAD_TEST_COUNT_FLOOR} tests; the README is stale.",
        )


class FrozenSurfaceLOCWaiverConsistencyTests(unittest.TestCase):
    """The frozen-surface LOC waiver cites a current LOC near the live file.

    Pre-fix ``docs/spec/frozen-gate-surface.md`` line 114 declared
    ``core/gate_orchestrator.py is currently 746 LOC pre-B / 834 LOC
    post-B`` while the actual file had grown to 1137 LOC at HEAD across
    C1, C2, C3, C5, G2 + K-2 / K-5 + three gate-correctness follow-ups.
    The 303-LOC undercount in the authoritative "what not to break"
    contract doc misled operators into believing the +88-LOC waiver
    still bounded current growth.

    The fix updates the waiver to cite the current LOC value alongside
    the historical anchor; this regression test pins the doc to a
    current LOC that is within a generous tolerance of the live file
    so future growth either updates the doc or trips the suite.
    """

    GATE_ORCHESTRATOR_PATH = (
        REPO_ROOT
        / "skills"
        / "bmad-story-automator"
        / "src"
        / "story_automator"
        / "core"
        / "gate_orchestrator.py"
    )
    FROZEN_SURFACE_PATH = REPO_ROOT / "docs" / "spec" / "frozen-gate-surface.md"
    # Tolerance band: doc may lag the live file by up to ~150 LOC before
    # the waiver becomes misleading. This catches the pre-fix 303-LOC
    # undercount while allowing modest in-flight growth between doc
    # bumps.
    LOC_TOLERANCE = 150

    def _live_loc(self) -> int:
        text = self.GATE_ORCHESTRATOR_PATH.read_text(encoding="utf-8")
        return len(text.splitlines())

    def _waiver_cited_loc(self) -> int:
        text = self.FROZEN_SURFACE_PATH.read_text(encoding="utf-8")
        # The post-fix waiver paragraph cites "current LOC is **N**"
        # (with the bold markdown emphasis). Anchor the regex to the
        # surrounding "current LOC" phrasing so unrelated numeric
        # mentions in the doc don't accidentally match.
        match = re.search(
            r"current LOC is \*\*(\d+)\*\*",
            text,
        )
        self.assertIsNotNone(
            match,
            "frozen-gate-surface.md soft-limit waiver no longer carries "
            "a 'current LOC is **N**' marker; either restore the marker "
            "or update this regression test to match the new shape.",
        )
        return int(match.group(1))

    def test_waiver_cites_current_loc_within_tolerance(self) -> None:
        live = self._live_loc()
        cited = self._waiver_cited_loc()
        delta = live - cited
        self.assertLessEqual(
            delta,
            self.LOC_TOLERANCE,
            f"frozen-gate-surface.md soft-limit waiver cites "
            f"{cited} LOC for core/gate_orchestrator.py but the live "
            f"file is {live} LOC ({delta} LOC undercount, tolerance "
            f"{self.LOC_TOLERANCE}). Bump the cited LOC in the waiver "
            "paragraph and enumerate the contributing milestones.",
        )

    def test_waiver_does_not_cite_stale_834_as_current(self) -> None:
        """Pin the specific regression: pre-fix doc said 'currently 834'.

        The pre-fix doc had ``currently 746 LOC pre-B / 834 LOC post-B``
        — the word ``currently`` is what made it a load-bearing false
        claim. Post-fix the 834 may still appear as a historical
        anchor, but never qualified by ``currently``.
        """
        text = self.FROZEN_SURFACE_PATH.read_text(encoding="utf-8")
        self.assertNotRegex(
            text,
            r"currently\s+746\s+LOC\s+pre-B\s*/\s*834\s+LOC\s+post-B",
            "frozen-gate-surface.md still claims 'currently 746 LOC "
            "pre-B / 834 LOC post-B' — that figure is the post-B "
            "historical snapshot, not the current file size.",
        )


class ChangelogTagReferencesResolveTests(unittest.TestCase):
    """Every ``compat-*`` tag mentioned in CHANGELOG.md resolves via ``git tag``.

    Pre-fix CHANGELOG.md:36 referenced ``compat-bugfix-d-04-audit-key-env-scrub``
    while the actual tags are ``compat-secfix-D-04-audit-key-env-scrub`` and
    ``compat-secfix-D-04-sibling-module`` (note ``secfix`` not ``bugfix``,
    uppercase ``D-04`` not lowercase, and the follow-up sibling-module tag
    was unreferenced anywhere). An operator running
    ``git checkout compat-bugfix-d-04-audit-key-env-scrub`` got
    ``not a valid object name``.

    This regression test enumerates every backticked ``compat-*`` token in
    the CHANGELOG and asserts each one is reachable via ``git rev-parse``.
    Catches any future doc-vs-tag drift (typos, case mismatches, dropped
    follow-up tags).
    """

    # Regex for backticked compat-* tag tokens in CHANGELOG markdown. The
    # CHANGELOG enumerates tags inside backticks like:
    #   (`compat-secfix-D-04-audit-key-env-scrub` `1c24a86`)
    # We match the leading backticked token only.
    COMPAT_TAG_RE = re.compile(r"`(compat-[A-Za-z0-9_./-]+)`")

    def _git_tag_exists(self, tag: str) -> bool:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0

    def test_every_referenced_compat_tag_exists_in_git(self) -> None:
        text = _read("CHANGELOG.md")
        tokens = set(self.COMPAT_TAG_RE.findall(text))
        # Sanity-check: we should at minimum see the new D-04 secfix tag
        # after the fix lands; if this assertion fails the regex broke.
        self.assertIn(
            "compat-secfix-D-04-audit-key-env-scrub",
            tokens,
            "CHANGELOG.md no longer references the D-04 audit-key secfix "
            "tag; the regression test's anchor has drifted.",
        )
        missing = sorted(t for t in tokens if not self._git_tag_exists(t))
        self.assertEqual(
            missing,
            [],
            f"CHANGELOG.md references compat-* tags that do not exist in "
            f"git (operators cannot resolve via git checkout / rev-parse): "
            f"{missing}",
        )

    def test_d04_sibling_module_tag_is_referenced(self) -> None:
        """The follow-up sibling-module tag must be cited explicitly.

        Pre-fix the bullet at CHANGELOG.md:36 listed only the original
        D-04 tag and left the follow-up ``compat-secfix-D-04-sibling-module``
        commit (789a7c9) undocumented. Post-fix the bullet must cite
        BOTH tags so a forensic bisecter can find the full work.
        """
        text = _read("CHANGELOG.md")
        self.assertIn(
            "compat-secfix-D-04-sibling-module",
            text,
            "CHANGELOG.md does not reference the D-04 follow-up tag "
            "compat-secfix-D-04-sibling-module; the sibling-module work "
            "(789a7c9) is undocumented for forensic bisecting.",
        )

    def test_legacy_d04_misspelling_is_gone(self) -> None:
        """The pre-fix mis-typed tag must not reappear.

        Pin the specific regression: CHANGELOG.md previously read
        ``compat-bugfix-d-04-audit-key-env-scrub`` (wrong prefix
        ``bugfix``, wrong case ``d-04``). The fix replaced it with the
        actual tag ``compat-secfix-D-04-audit-key-env-scrub``. Re-introducing
        the old spelling would re-introduce the original drift.
        """
        text = _read("CHANGELOG.md")
        self.assertNotIn(
            "compat-bugfix-d-04-audit-key-env-scrub",
            text,
            "CHANGELOG.md re-introduces the legacy mis-typed "
            "'compat-bugfix-d-04-audit-key-env-scrub' tag; the actual tag "
            "is 'compat-secfix-D-04-audit-key-env-scrub' (secfix prefix, "
            "uppercase D-04).",
        )


class RecentlyShippedSectionDateBoundsTests(unittest.TestCase):
    """The "Recently shipped (...)" section heading bounds its bullets.

    Pre-fix CLAUDE.md:59 read ``### Recently shipped (session 2026-06-23)``
    while the bullet at CLAUDE.md:75 (``Worktree-per-unit isolation (G2)``)
    referenced work whose authoritative changelog file is
    ``docs/changelog/2026-06-24-g2-worktree-per-unit.md`` (entry heading
    ``## 260624 - [FULL] G2 worktree-per-unit isolation``). The header
    asserted every milestone in its body shipped on 2026-06-23, but G2
    actually shipped 2026-06-24 — drift that misleads operators reading
    CLAUDE.md as the authoritative session log.

    The regression test parses the section header for the latest
    bounding date and asserts every dated changelog file referenced by
    a bullet in that section has a date <= the bounding date.
    """

    DATED_CHANGELOG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")
    SECTION_HEADING_RE = re.compile(
        r"^### Recently shipped \((.+?)\)$",
        re.MULTILINE,
    )
    DATE_IN_HEADING_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
    CHANGELOG_DIR = REPO_ROOT / "docs" / "changelog"

    def _section_body(self, text: str) -> tuple[str, str]:
        """Return (heading_inner, body) for the Recently shipped section.

        ``heading_inner`` is the parenthetical content (e.g. "sessions
        2026-06-23 + 2026-06-24"). ``body`` is everything between the
        section heading and the next ``### `` heading.
        """
        match = self.SECTION_HEADING_RE.search(text)
        self.assertIsNotNone(
            match,
            "CLAUDE.md no longer has a '### Recently shipped (...)' heading; "
            "update this regression test to match the new shape.",
        )
        start = match.end()
        # Find the next '###' heading after the section start.
        next_heading = re.search(r"^### ", text[start:], re.MULTILINE)
        end = start + next_heading.start() if next_heading else len(text)
        return match.group(1), text[start:end]

    def _bounding_date(self, heading_inner: str) -> tuple[int, int, int]:
        """Latest YYYY-MM-DD date mentioned in the section heading."""
        dates = self.DATE_IN_HEADING_RE.findall(heading_inner)
        self.assertTrue(
            dates,
            f"Section heading '{heading_inner}' carries no YYYY-MM-DD "
            "date; the section header must bound its bullets by date.",
        )
        return max((int(y), int(m), int(d)) for (y, m, d) in dates)

    def _milestone_tags_in_body(self, body: str) -> set[str]:
        """Lower-case milestone slugs hinted by the bullet boldface labels.

        Bullet shape is ``- **<title> (<tag>)** ...``. We extract the
        bracketed ``<tag>`` (e.g. ``G2``, ``C5``, ``N7.1``) and the
        trailing parenthetical hint and lower-case both for matching
        against changelog filenames.
        """
        tags: set[str] = set()
        for line in body.splitlines():
            m = re.match(r"^- \*\*[^*]*\(([A-Za-z0-9./_+ -]+)\)\*\*", line)
            if not m:
                continue
            label = m.group(1).strip().lower()
            # Split a compound bullet label like "C1 + follow-up" or
            # "N7 + C3" into individual milestone tags. We anchor on
            # the leading alphanumeric token of each ``+``-delimited
            # part so e.g. "N7 + C3" -> {"n7", "c3"}.
            for part in label.split("+"):
                token_match = re.match(r"\s*([a-z0-9.]+)", part)
                if token_match:
                    tags.add(token_match.group(1))
        return tags

    def test_section_heading_bounds_dated_changelog_milestones(self) -> None:
        text = _read("CLAUDE.md")
        heading_inner, body = self._section_body(text)
        bound = self._bounding_date(heading_inner)
        tags = self._milestone_tags_in_body(body)
        # For each tag, find the matching dated changelog file (if any)
        # and assert its date <= the section's bounding date. We accept
        # tags that have no matching changelog file (e.g. follow-up
        # work folded into a parent file) — only positive matches are
        # asserted.
        violations: list[str] = []
        for changelog in self.CHANGELOG_DIR.iterdir():
            if not changelog.is_file():
                continue
            name = changelog.name
            if not self.DATED_CHANGELOG_RE.match(name):
                continue
            # Filename shape: YYYY-MM-DD-<slug>.md where slug starts
            # with the milestone tag, e.g. ``2026-06-24-g2-worktree-...``.
            head = name[:10]
            slug = name[11:-3] if name.endswith(".md") else name[11:]
            # The leading slug segment up to the first '-' is the tag.
            tag_segment = slug.split("-", 1)[0].lower()
            if tag_segment not in tags:
                continue
            try:
                y, m, d = (int(head[0:4]), int(head[5:7]), int(head[8:10]))
            except ValueError:
                continue
            if (y, m, d) > bound:
                violations.append(
                    f"{name} (date {head}) > section bound "
                    f"{bound[0]:04d}-{bound[1]:02d}-{bound[2]:02d}",
                )
        self.assertEqual(
            violations,
            [],
            "CLAUDE.md 'Recently shipped (...)' section heading does not "
            "bound the latest changelog date of its bullets: "
            f"{violations}",
        )


class ReadmeQuickStartKwargsCoverageTests(unittest.TestCase):
    """README quick-start enumerates every OPTIONAL kwarg of ``run_production_gate``.

    Pre-fix README.md:75-94 listed only 6 OPTIONAL kwargs
    (``drift_watcher``, ``session_usage``, ``baseline_sha``,
    ``fail_closed``, ``enable_pre_gate_verifier``, ``result_json_path``)
    under the explicit banner ``--- session-2026-06-23 additive kwargs
    (all OPTIONAL, default off) ---``. The live signature in
    ``core/gate_orchestrator.run_production_gate`` carries 10 OPTIONAL
    kwargs: the 6 above plus ``enable_lie_detector`` (Phase 1),
    ``threshold_proposer`` (C5), ``isolation_mode`` (G2), and
    ``max_workers`` (G2). The four omitted kwargs landed in the same
    2026-06-23 / 2026-06-24 timeframe the README banner advertises;
    operators copy-pasting the quick-start as a template would not
    discover the C5 self-improving-gate hook or the G2
    worktree-per-unit isolation surfaces.

    The regression test introspects the live function signature and
    asserts every OPTIONAL kwarg appears verbatim inside the README's
    quick-start fenced code block, so any future kwarg added to the
    signature without a corresponding README update trips this test.
    """

    REQUIRED_OPTIONAL_KWARGS = (
        "enable_lie_detector",
        "baseline_sha",
        "fail_closed",
        "enable_pre_gate_verifier",
        "result_json_path",
        "drift_watcher",
        "session_usage",
        "threshold_proposer",
        "isolation_mode",
        "max_workers",
    )

    def _quick_start_block(self, text: str) -> str:
        # Anchor on the import line that already lives inside the
        # quick-start code fence — the block extends from that line
        # through the next ``` fence terminator.
        anchor = "from story_automator.core.gate_orchestrator import run_production_gate"
        start = text.find(anchor)
        self.assertGreaterEqual(
            start,
            0,
            "README.md quick-start anchor import line missing; the "
            "regression test cannot locate the code block.",
        )
        end_fence = text.find("```", start)
        self.assertGreaterEqual(
            end_fence,
            0,
            "README.md quick-start code block is missing its closing "
            "``` fence after the anchor import.",
        )
        return text[start:end_fence]

    def test_readme_quick_start_lists_every_optional_kwarg(self) -> None:
        text = _read("README.md")
        block = self._quick_start_block(text)
        missing = [
            kw for kw in self.REQUIRED_OPTIONAL_KWARGS
            if not re.search(rf"^\s*{re.escape(kw)}\s*=", block, re.MULTILINE)
        ]
        self.assertEqual(
            missing,
            [],
            "README.md quick-start no longer enumerates every OPTIONAL "
            f"kwarg of run_production_gate; missing: {missing}. "
            "New operators copy-pasting the example as a template will "
            "not learn of these observability surfaces.",
        )

    def test_required_kwarg_set_matches_live_signature(self) -> None:
        """Defensive: the kwarg list above must mirror the live signature.

        If a future milestone adds another OPTIONAL kwarg to
        ``run_production_gate`` (say, an 11th), this assertion fires —
        forcing both the README update AND a bump to
        ``REQUIRED_OPTIONAL_KWARGS`` above. Without this guard the
        README test above could silently lag a new kwarg until someone
        re-audits the README by hand.
        """
        import inspect

        module = importlib.import_module(
            "story_automator.core.gate_orchestrator"
        )
        sig = inspect.signature(module.run_production_gate)
        live_optional = {
            name for name, p in sig.parameters.items()
            if p.kind is inspect.Parameter.KEYWORD_ONLY
            and p.default is not inspect.Parameter.empty
        }
        documented = set(self.REQUIRED_OPTIONAL_KWARGS)
        # The signature also includes default-bearing keyword-only
        # kwargs that predate Path B (``priority``,
        # ``has_unmitigated_risk_9``, ``waivers``, ``audit_policy``,
        # ``audit_path``); those are not part of the quick-start's
        # "session 2026-06-23 additive kwargs" banner so we filter them
        # by the documented set (intersection = the path-B family this
        # test pins). New kwargs that show up in live_optional but not
        # in documented are flagged below.
        pre_path_b_kwargs = {
            "priority",
            "has_unmitigated_risk_9",
            "waivers",
            "audit_policy",
            "audit_path",
        }
        new_in_live = live_optional - documented - pre_path_b_kwargs
        self.assertEqual(
            new_in_live,
            set(),
            "run_production_gate has new OPTIONAL kwargs not pinned by "
            f"REQUIRED_OPTIONAL_KWARGS in this test: {sorted(new_in_live)}. "
            "Add them to REQUIRED_OPTIONAL_KWARGS and update README.md.",
        )
        # And every documented kwarg must still exist on the function.
        missing_from_live = documented - live_optional
        self.assertEqual(
            missing_from_live,
            set(),
            "REQUIRED_OPTIONAL_KWARGS references kwargs no longer on "
            f"run_production_gate: {sorted(missing_from_live)}",
        )


class SpecDriftWatcherLOCSoftLimitTests(unittest.TestCase):
    """``spec_drift_watcher.py`` stays under the CLAUDE.md 500-LOC soft limit.

    Pre-fix the watcher sat at 528 LOC, breaching the soft cap that
    the sibling ``spec_drift_persistence.py`` module's docstring
    explicitly cites as the reason for its own existence ("split out
    of ``spec_drift_watcher.py`` ... to keep the 500-LOC soft limit
    in play"). The C1 follow-ups (persistence_key wiring, atomic
    set_baseline, clobber-guard) added ~55 lines without a
    corresponding split. The fix extracted the dataclasses, error
    class, severity constants, and the four standalone helpers
    (``_validate_thresholds``, ``_now_iso``, ``_satisfied_ids``,
    ``_score``) into a new ``spec_drift_types`` sibling, mirroring
    the ``threshold_proposer`` / ``threshold_proposer_helpers``
    pattern.

    The regression test pins both halves of the contract: (a) the
    canonical watcher stays under the soft limit, and (b) the new
    sibling exists and re-exports the symbols so the public surface
    is preserved.
    """

    SPEC_DRIFT_WATCHER_PATH = (
        REPO_ROOT
        / "skills"
        / "bmad-story-automator"
        / "src"
        / "story_automator"
        / "core"
        / "innovation"
        / "spec_drift_watcher.py"
    )
    SPEC_DRIFT_TYPES_PATH = (
        REPO_ROOT
        / "skills"
        / "bmad-story-automator"
        / "src"
        / "story_automator"
        / "core"
        / "innovation"
        / "spec_drift_types.py"
    )
    SOFT_LIMIT_LOC = 500

    def test_spec_drift_watcher_under_soft_limit(self) -> None:
        text = self.SPEC_DRIFT_WATCHER_PATH.read_text(encoding="utf-8")
        loc = len(text.splitlines())
        self.assertLessEqual(
            loc,
            self.SOFT_LIMIT_LOC,
            f"spec_drift_watcher.py is {loc} LOC but the CLAUDE.md "
            f"soft cap is {self.SOFT_LIMIT_LOC}. Extract another helper "
            "into the sibling spec_drift_types module to recover headroom.",
        )

    def test_spec_drift_types_sibling_exists_and_reexports(self) -> None:
        """The split must preserve the public surface of the watcher.

        If a future refactor moves ``SpecDriftError`` / ``SpecDriftEvent``
        / ``SpecDriftSnapshot`` back into the watcher but forgets to
        delete the sibling, this test still passes — we only assert the
        sibling exposes the moved symbols. If the watcher stops
        re-exporting them, the existing
        ``tests/test_spec_drift_watcher.py`` import line breaks first.
        """
        self.assertTrue(
            self.SPEC_DRIFT_TYPES_PATH.exists(),
            "spec_drift_types.py sibling missing; the LOC split has "
            "regressed and the watcher will breach the soft cap again.",
        )
        types_module = importlib.import_module(
            "story_automator.core.innovation.spec_drift_types"
        )
        for symbol in (
            "SpecDriftError",
            "SpecDriftEvent",
            "SpecDriftSnapshot",
            "_validate_thresholds",
            "_now_iso",
            "_satisfied_ids",
            "_score",
        ):
            self.assertTrue(
                hasattr(types_module, symbol),
                f"spec_drift_types no longer exposes {symbol!r}; the "
                "sibling-split contract has regressed.",
            )


class SpecDriftPersistenceDocstringConsistencyTests(unittest.TestCase):
    """``spec_drift_persistence`` docstring matches the bytes its writer emits.

    Pre-fix the module docstring at ``spec_drift_persistence.py:11``
    described ``baseline.json`` as a "canonical-JSON serialization" while
    ``persist_baseline`` writes through ``core.common.compact_json`` —
    which only sets ``separators=(',', ':')`` and does NOT pass
    ``sort_keys=True``. The project's own ``gate_schema.canonical_json``
    helper defines "canonical JSON" as ``sort_keys=True`` everywhere
    audit-grade serialization matters (evidence_io, lineage_ledger,
    runtime_policy). The byte sequence happened to be stable today
    because ``_snapshot_to_dict`` builds the dict with a fixed literal
    field order, but the "canonical" promise was aspirational: any
    future contributor migrating to ``dataclasses.asdict`` or
    ``**kwargs``-style extension would silently break it without
    tripping any existing semantic round-trip test.

    The fix weakens the docstring to say "compact JSON
    (deterministic insertion-ordered ... NOT ... ``sort_keys=True``)"
    so the contract matches the bytes its writer emits. This
    regression test pins both halves:

    1. The docstring no longer carries the misleading
       "canonical-JSON" promise.
    2. The docstring explicitly disclaims being the project's
       ``gate_schema.canonical_json`` flavor so a future contributor
       reading just this module knows where to look for the
       audit-grade flavor.
    """

    def test_baseline_docstring_does_not_claim_canonical_json(self) -> None:
        module = importlib.import_module(
            "story_automator.core.innovation.spec_drift_persistence"
        )
        doc = module.__doc__ or ""
        # The exact pre-fix phrase that promised audit-grade canonicality.
        # Note: we look for the precise "canonical-JSON" hyphenated form
        # so a legitimate post-fix mention of "NOT ... canonical_json"
        # (the helper name) survives.
        self.assertNotIn(
            "canonical-JSON serialization",
            doc,
            "spec_drift_persistence docstring still claims "
            "'canonical-JSON serialization' for baseline.json, but "
            "persist_baseline writes through common.compact_json which "
            "does NOT pass sort_keys=True. Either weaken the docstring "
            "or switch the writer to gate_schema.canonical_json.",
        )

    def test_baseline_docstring_disclaims_gate_schema_flavor(self) -> None:
        # Post-fix docstring must explicitly disclaim the audit-grade
        # flavor so a future contributor knows where the project's
        # sort_keys=True canonical JSON lives.
        module = importlib.import_module(
            "story_automator.core.innovation.spec_drift_persistence"
        )
        doc = module.__doc__ or ""
        self.assertIn(
            "sort_keys=True",
            doc,
            "spec_drift_persistence docstring no longer disclaims the "
            "gate_schema.canonical_json sort_keys=True flavor. Future "
            "contributors will assume baseline.json is audit-grade JSON.",
        )

    def test_writer_helper_is_compact_json_not_canonical_json(self) -> None:
        """Defensive: the writer must still be ``compact_json``.

        If a future contributor swaps the writer to
        ``gate_schema.canonical_json`` (the suggested-fix alternative),
        the docstring weakening above would itself become stale. This
        test pins the choice so the docstring and the writer stay in
        sync: as long as the writer is ``compact_json``, the docstring
        must NOT claim "canonical-JSON". If someone bumps the writer
        to ``canonical_json``, this test trips and forces a docstring
        re-audit at the same time.
        """
        persistence_src = (
            REPO_ROOT
            / "skills"
            / "bmad-story-automator"
            / "src"
            / "story_automator"
            / "core"
            / "innovation"
            / "spec_drift_persistence.py"
        ).read_text(encoding="utf-8")
        # The persist_baseline writer call site.
        self.assertIn(
            "compact_json(_snapshot_to_dict(snapshot))",
            persistence_src,
            "persist_baseline no longer writes through compact_json; "
            "if the writer was bumped to canonical_json, the docstring "
            "may need to revert to claiming 'canonical-JSON' — re-audit "
            "the docstring weakening and update this regression test.",
        )


class RunProductionGateDriftWatcherDocstringTests(unittest.TestCase):
    """``run_production_gate`` drift_watcher docstring matches actual poll sites.

    Pre-fix the docstring at ``gate_orchestrator.run_production_gate``
    promised the orchestrator calls ``watcher.poll()`` "twice per gate
    run" without qualification. In practice three early-return paths
    (``pre_gate_failed`` from the inline verifier, the reuse cache-hit
    short-circuit, and the lie-detector ``baseline_drift`` abort) all
    return BEFORE either poll site executes — yielding zero polls on
    those reachable paths. An operator watching ``watcher.poll`` counts
    as a dashboard signal would silently lose visibility on cache-hits
    and HEAD-mismatches (the two paths where stalled/drifted sessions
    are MOST likely to occur).

    The fix tightens the docstring to (a) say "twice per FULL gate
    run" instead of "twice per gate run", and (b) explicitly enumerate
    that early-return paths skip BOTH polls because the anchoring
    lifecycle events (marker-written / evaluate_gate-returned) do not
    occur. This regression test pins both halves.
    """

    def test_drift_watcher_docstring_clarifies_full_gate_run_scope(self) -> None:
        module = importlib.import_module(
            "story_automator.core.gate_orchestrator"
        )
        doc = module.run_production_gate.__doc__ or ""
        # The fix replaces "twice per gate run" with "twice per FULL
        # gate run" to disambiguate the early-return paths. The phrase
        # "twice per gate run" (without FULL) is the pre-fix misleading
        # form; we accept either the precise post-fix wording or any
        # other qualifier ("twice per FRESH gate run", "twice per
        # complete gate run", etc.) that includes an uppercase
        # adjective between "twice per" and "gate run".
        self.assertNotRegex(
            doc,
            r"twice per gate run(?![\w-])",
            "run_production_gate docstring still claims 'twice per gate "
            "run' without qualification, but three early-return paths "
            "(pre_gate_failed / reuse cache-hit / baseline_drift) skip "
            "both polls. Tighten the wording to 'twice per FULL gate "
            "run' or similar.",
        )

    def test_drift_watcher_docstring_enumerates_early_return_skips(self) -> None:
        module = importlib.import_module(
            "story_automator.core.gate_orchestrator"
        )
        doc = module.run_production_gate.__doc__ or ""
        # Post-fix docstring must explicitly tell operators that
        # early-return paths skip both polls so they can correctly
        # interpret poll-count dashboards. Normalize whitespace
        # because docstring line-wrap inserts newlines+indent between
        # the phrase-pinning words.
        normalized = re.sub(r"\s+", " ", doc)
        self.assertIn(
            "Early-return paths skip BOTH polls",
            normalized,
            "run_production_gate docstring no longer enumerates that "
            "early-return paths skip both drift_watcher polls; "
            "operators monitoring poll counts will misinterpret zero "
            "polls on cache-hits / baseline-drift as a watcher bug.",
        )
        # Also assert all three early-return paths are named so the
        # docstring stays exhaustive (future contributors adding a
        # fourth early-return path must extend the docstring too).
        for path_name in (
            "pre-gate-verifier",
            "reuse cache-hit",
            "baseline_drift",
        ):
            self.assertIn(
                path_name,
                normalized,
                f"run_production_gate docstring no longer names the "
                f"{path_name!r} early-return path in its drift_watcher "
                "section; the enumeration is incomplete.",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
