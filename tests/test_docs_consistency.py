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


class ClaudeMdInnovationModuleMapEnumerationTests(unittest.TestCase):
    """CLAUDE.md's module-map line for ``core/innovation/`` enumerates every
    session-shipped module family in its parenthetical capability summary.

    Pre-fix the parenthetical at CLAUDE.md:20 listed 12 capability hints
    (spec-drift watcher + persistence, lineage ledger, cost attribution +
    cost evidence + session usage capture, RAMR, ledger, kernel classifier,
    adversarial review, replay diff, phase budget, stack risk weights) while
    the C5 self-improving-gate landed FOUR new modules in the same
    subdirectory: ``threshold_apply.py``, ``threshold_decisions.py``,
    ``threshold_proposer.py``, ``threshold_proposer_helpers.py``. The four
    threshold_* modules ARE fully documented 54 lines later under the
    "Self-improving gate (C5)" bullet, but the module-map summary line was
    a self-contained capability enumeration and an operator skimming the
    map would miss the C5 family. ``threshold_proposer_helpers.py`` in
    particular was not mentioned anywhere in CLAUDE.md prior to this fix.

    The regression test pins the line-20 parenthetical against a token
    list that must mention at minimum "threshold" so the C5 family is
    surfaced in the high-level module map.
    """

    INNOVATION_DIR = (
        REPO_ROOT
        / "skills"
        / "bmad-story-automator"
        / "src"
        / "story_automator"
        / "core"
        / "innovation"
    )

    def _module_map_innovation_line(self) -> str:
        text = _read("CLAUDE.md")
        match = re.search(
            r"^  - `src/story_automator/core/innovation/`.*$",
            text,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            match,
            "CLAUDE.md no longer has the '  - `src/story_automator/core/"
            "innovation/`' module-map line; update this regression test "
            "to match the new shape.",
        )
        return match.group(0)

    def test_innovation_line_mentions_threshold_family(self) -> None:
        line = self._module_map_innovation_line()
        self.assertIn(
            "threshold",
            line.lower(),
            "CLAUDE.md module-map line for core/innovation/ does not mention "
            "the C5 threshold_* module family (threshold_apply, "
            "threshold_decisions, threshold_proposer, threshold_proposer_helpers). "
            "An operator skimming the module map would miss the C5 "
            "self-improving-gate substrate even though the directory ships "
            "four threshold_* modules.",
        )

    def test_innovation_dir_actually_carries_threshold_modules(self) -> None:
        """Defensive: the disk genuinely carries the four C5 threshold_* modules.

        If a future refactor moves the threshold_* modules out of
        ``core/innovation/`` (say, into a dedicated ``core/calibration/``
        subdirectory), the line-20 mention becomes stale; this test trips
        so the module-map line gets re-audited at the same commit.
        """
        expected = {
            "threshold_apply.py",
            "threshold_decisions.py",
            "threshold_proposer.py",
            "threshold_proposer_helpers.py",
        }
        actual = {p.name for p in self.INNOVATION_DIR.glob("threshold_*.py")}
        missing = expected - actual
        self.assertEqual(
            missing,
            set(),
            f"core/innovation/ no longer carries the expected C5 threshold_* "
            f"modules: missing {sorted(missing)}. Either restore them or "
            "update this regression test (and the CLAUDE.md module-map line).",
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


class SiblingModulePatternExemplarCompletenessTests(unittest.TestCase):
    """``### Sibling-module pattern`` enumerates every session-shipped sibling.

    Pre-fix CONTRIBUTING.md:171 read "Three examples land this session"
    and listed `core/audit_env_scrub.py`,
    `core/innovation/spec_drift_persistence.py`, and
    `core/gate_lock_observability.py` — but the same session window
    also shipped three other sibling-module extractions whose own
    module docstrings self-describe as applications of the same pattern:

    - `core/collector_isolation_outcomes.py` (added by `ee69149 fix(g2):
      post-impl review fold-in`, 2026-06-24) — docstring says
      "Extracted from ``collector_isolation.py`` to keep that module
      under the 500-LOC soft limit".
    - `core/innovation/threshold_proposer_helpers.py` (added by
      `10eb18a fix(c5): post-impl review fold-in`, 2026-06-23) —
      docstring says "split sibling of ``threshold_proposer``".
    - `core/integration/_unified_state_repair.py` (added by
      `f5c8cdf feat(integration): G7`, 2026-06-22) — docstring says
      "Kept as a sibling private module so the public-surface module
      (``unified_state.py``) stays comfortably under the 500-LOC soft
      limit".

    The "Three examples" framing understated the pattern's prevalence
    by a factor of two and silently omitted half the actual exemplar
    set. The regression test pins both halves of the contract:

    1. The numeric framing must be at least "Six" (so future additions
       can bump to "Seven", "Eight", etc., but a regression back to
       "Three" trips this test).
    2. The bullet list must mention every sibling-module Python file
       whose docstring self-describes as an application of the pattern
       — caught by a leaf-name presence check against the section body.
    """

    CORE_DIR = (
        REPO_ROOT
        / "skills"
        / "bmad-story-automator"
        / "src"
        / "story_automator"
        / "core"
    )
    # Word forms accepted as the numeric framing in the section's
    # introductory sentence. Pre-fix said "Three"; post-fix says "Six".
    # We accept "Six" or any higher count word so future sibling-module
    # additions can grow this without breaking the test.
    ACCEPTED_COUNT_WORDS = ("Six", "Seven", "Eight", "Nine", "Ten")
    # Bullets the post-fix doc MUST carry. These are the six siblings
    # the disk currently ships whose docstrings self-describe the
    # pattern. If a future session adds a seventh, add its leaf name
    # here and bump ACCEPTED_COUNT_WORDS coverage.
    REQUIRED_SIBLING_LEAVES = (
        "audit_env_scrub.py",
        "spec_drift_persistence.py",
        "gate_lock_observability.py",
        "collector_isolation_outcomes.py",
        "threshold_proposer_helpers.py",
        "_unified_state_repair.py",
    )

    def _section_body(self) -> str:
        text = _read("CONTRIBUTING.md")
        # The section is delimited by the '### Sibling-module pattern'
        # heading and the next '### ' heading (or end-of-file).
        match = re.search(
            r"^### Sibling-module pattern.*$",
            text,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            match,
            "CONTRIBUTING.md no longer carries a '### Sibling-module "
            "pattern' heading; this regression test cannot locate the "
            "section.",
        )
        start = match.end()
        next_heading = re.search(r"^### ", text[start:], re.MULTILINE)
        end = start + next_heading.start() if next_heading else len(text)
        return text[start:end]

    def test_intro_sentence_uses_post_fix_count_word(self) -> None:
        body = self._section_body()
        # The introductory sentence is shaped:
        #   "<Word> examples land this session:"
        # Pre-fix this was "Three". Post-fix at least "Six".
        intro_re = re.compile(
            r"\b([A-Z][a-z]+)\s+examples\s+land\s+this\s+session\b",
        )
        match = intro_re.search(body)
        self.assertIsNotNone(
            match,
            "Sibling-module section no longer carries a '<Count> "
            "examples land this session' framing sentence.",
        )
        word = match.group(1)
        self.assertIn(
            word,
            self.ACCEPTED_COUNT_WORDS,
            f"Sibling-module section intro says '{word} examples land "
            "this session' but the disk ships at least six self-described "
            "sibling-module extractions; pre-fix said 'Three' and the "
            "regression test pins the post-fix count word to one of "
            f"{self.ACCEPTED_COUNT_WORDS}.",
        )

    def test_every_required_sibling_leaf_appears_in_section_body(self) -> None:
        body = self._section_body()
        missing = [
            leaf for leaf in self.REQUIRED_SIBLING_LEAVES if leaf not in body
        ]
        self.assertEqual(
            missing,
            [],
            "Sibling-module section omits sibling-module Python files "
            "whose docstrings self-describe as applications of the "
            f"pattern: {missing}. Either add a bullet for each missing "
            "leaf or update REQUIRED_SIBLING_LEAVES in this regression "
            "test if the file moved.",
        )

    def test_required_sibling_files_self_describe_on_disk(self) -> None:
        """Defensive: every leaf in ``REQUIRED_SIBLING_LEAVES`` exists.

        If a future refactor renames or removes any of these, the
        bullet list in CONTRIBUTING.md would still trivially pass the
        leaf-presence check above (the string would just be stale
        prose). This test confirms each leaf is a live Python file on
        disk so the bullet list is anchored against reality.
        """
        # Search the full ``core/`` subtree because the siblings live in
        # several subdirectories (``core/``, ``core/innovation/``,
        # ``core/integration/``).
        leaves_on_disk = {p.name for p in self.CORE_DIR.rglob("*.py")}
        missing = [
            leaf for leaf in self.REQUIRED_SIBLING_LEAVES
            if leaf not in leaves_on_disk
        ]
        self.assertEqual(
            missing,
            [],
            "Sibling-module bullet list references files no longer on "
            f"disk under core/: {missing}. The bullet list is stale.",
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
    # added (4644), bumped to 4720 after the round-2 bug-fix sweep
    # landed +76 tests across the post-session bug-fix rounds. README
    # must not claim fewer than this when it cites a HEAD count.
    # Tolerance band allows the live count to grow without breaking
    # this test — only a regression below the floor (or the pre-fix
    # 4348 anchor) trips it.
    HEAD_TEST_COUNT_FLOOR = 4720

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


class ReadmeWhatShippedSectionDateBoundsTests(unittest.TestCase):
    """README.md "What shipped this session (...)" heading bounds its bullets.

    Pre-fix README.md:22 read ``## What shipped this session (2026-06-23)``
    while the section body at lines 23-67 discussed both C5 (changelog
    ``docs/changelog/2026-06-23-c5-self-improving-gate.md``) and G2
    (changelog ``docs/changelog/2026-06-24-g2-worktree-per-unit.md``).
    G2's authoritative changelog filename anchors it on 2026-06-24, but
    the README heading asserted every milestone in its body shipped on
    2026-06-23 alone, so the README misrepresented the date range it
    covered. Commit 8772327 had already fixed the identical drift in
    CLAUDE.md:59 ("session 2026-06-23" -> "sessions 2026-06-23 +
    2026-06-24") and pinned it via ``RecentlyShippedSectionDateBoundsTests``
    above, but the parallel README heading remained unprotected.

    This regression test mirrors the CLAUDE.md test pattern for the
    README's "What shipped this session (...)" heading: parse the
    heading for the latest bounding date, then assert every dated
    changelog file referenced by a bullet in that section has a date
    <= the bounding date. Body-level mentions of C5 + G2 (lines 62-63)
    and quick-start kwargs (lines 96-97) ensure the bullets reach
    forward to 2026-06-24 work, so the heading must too.
    """

    DATED_CHANGELOG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")
    SECTION_HEADING_RE = re.compile(
        r"^## What shipped this session \((.+?)\)$",
        re.MULTILINE,
    )
    DATE_IN_HEADING_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
    CHANGELOG_DIR = REPO_ROOT / "docs" / "changelog"

    def _section_body(self, text: str) -> tuple[str, str]:
        """Return (heading_inner, body) for the "What shipped" section."""
        match = self.SECTION_HEADING_RE.search(text)
        self.assertIsNotNone(
            match,
            "README.md no longer has a '## What shipped this session (...)' "
            "heading; update this regression test to match the new shape.",
        )
        start = match.end()
        # Find the next '## ' heading after the section start.
        next_heading = re.search(r"^## ", text[start:], re.MULTILINE)
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
        """Lower-case milestone slugs hinted by the section body.

        Sources of milestone tags include:

        * Bullet boldface labels of shape ``- **<tag>** ...`` or
          ``- **<tag1> / <tag2>** ...`` (e.g. ``- **C1 / C2 / C3**``).
        * Body-prose mentions of milestone tokens shaped like a
          capital letter / capital letter + digit / capital letter +
          digit + dot-digit (e.g. ``C5``, ``G2``, ``N6.5``,
          ``D-04``). The README's session-rollup paragraph at lines
          62-63 ("C5 + G2 landed afterward") references work whose
          changelog files anchor the section's bounding-date floor,
          so the extractor must surface those tags even when no
          boldface bullet carries them.

        Tokens are lower-cased and split on ``/`` / ``+`` delimiters
        before being returned.
        """
        tags: set[str] = set()
        # Source 1: boldface bullet labels.
        for line in body.splitlines():
            m = re.match(r"^- \*\*([^*]+)\*\*", line)
            if not m:
                continue
            label = m.group(1).strip().lower()
            # Split a compound bullet label like "C1 / C2 / C3" or
            # "L1 / L2 / L1-followup" into individual milestone tags.
            for part in re.split(r"[/+]", label):
                token_match = re.match(r"\s*([a-z0-9.]+)", part)
                if token_match:
                    tags.add(token_match.group(1))
        # Source 2: body-prose mentions of milestone tokens shaped
        # like ``C5``, ``G2``, ``N6.5``, ``D-04``. Anchor on a
        # capital letter followed by one or more digits with an
        # optional ``.<digit>`` minor-version segment; require a
        # non-word-char boundary on both sides so e.g. ``ABC123`` is
        # not picked up.
        token_re = re.compile(r"(?<![\w-])([A-Z]\d+(?:\.\d+)?)(?![\w-])")
        for token in token_re.findall(body):
            tags.add(token.lower())
        return tags

    def test_section_heading_bounds_dated_changelog_milestones(self) -> None:
        text = _read("README.md")
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
            "README.md '## What shipped this session (...)' heading does "
            "not bound the latest changelog date of its bullets: "
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


class LineageLedgerLOCSoftLimitTests(unittest.TestCase):
    """``lineage_ledger.py`` stays under the CLAUDE.md 500-LOC soft limit.

    Pre-fix the ledger sat at 617 LOC, breaching the soft cap. The C2
    follow-ups (path-traversal rejection, rollback-on-index-write
    failure, topological orphan detection, multi-genesis corruption
    flagging) added ~140 lines without a corresponding split. The fix
    extracted the disk-persistence helpers (``get_lineage_root_dir``,
    ``lineage_index_path``, ``get_lineage_lock``, ``_entry_disk_path``,
    ``_read_index``, ``_write_index``, ``persist_lineage_entry``,
    ``load_lineage_entry``, ``_index_sort_key``, ``load_lineage_chain``,
    ``load_lineage_root``) into a new ``lineage_persistence`` sibling,
    mirroring the ``spec_drift_watcher`` / ``spec_drift_persistence``
    pattern.

    The regression test pins both halves of the contract: (a) the
    canonical ledger stays under the soft limit, and (b) the new sibling
    exists and re-exports the symbols so the public surface is preserved.
    """

    LINEAGE_LEDGER_PATH = (
        REPO_ROOT
        / "skills"
        / "bmad-story-automator"
        / "src"
        / "story_automator"
        / "core"
        / "innovation"
        / "lineage_ledger.py"
    )
    LINEAGE_PERSISTENCE_PATH = (
        REPO_ROOT
        / "skills"
        / "bmad-story-automator"
        / "src"
        / "story_automator"
        / "core"
        / "innovation"
        / "lineage_persistence.py"
    )
    SOFT_LIMIT_LOC = 500

    def test_lineage_ledger_under_soft_limit(self) -> None:
        text = self.LINEAGE_LEDGER_PATH.read_text(encoding="utf-8")
        loc = len(text.splitlines())
        self.assertLessEqual(
            loc,
            self.SOFT_LIMIT_LOC,
            f"lineage_ledger.py is {loc} LOC but the CLAUDE.md "
            f"soft cap is {self.SOFT_LIMIT_LOC}. Extract another helper "
            "into the sibling lineage_persistence module to recover headroom.",
        )

    def test_lineage_persistence_sibling_exists_and_reexports(self) -> None:
        """The split must preserve the public surface of the ledger.

        Tests + ``commands.lineage_cmd`` consume both public functions
        (``persist_lineage_entry`` / ``load_lineage_root`` / ...) and
        private helpers (``_read_index`` / ``_write_index`` /
        ``_index_sort_key``) via ``from ... lineage_ledger import``. The
        re-export contract keeps that import path working while the
        definitions live in ``lineage_persistence``.
        """
        self.assertTrue(
            self.LINEAGE_PERSISTENCE_PATH.exists(),
            "lineage_persistence.py sibling missing; the LOC split has "
            "regressed and the ledger will breach the soft cap again.",
        )
        persistence_module = importlib.import_module(
            "story_automator.core.innovation.lineage_persistence"
        )
        ledger_module = importlib.import_module(
            "story_automator.core.innovation.lineage_ledger"
        )
        for symbol in (
            "get_lineage_root_dir",
            "lineage_index_path",
            "get_lineage_lock",
            "_entry_disk_path",
            "_read_index",
            "_write_index",
            "_index_sort_key",
            "persist_lineage_entry",
            "load_lineage_entry",
            "load_lineage_chain",
            "load_lineage_root",
        ):
            self.assertTrue(
                hasattr(persistence_module, symbol),
                f"lineage_persistence no longer exposes {symbol!r}; the "
                "sibling-split contract has regressed.",
            )
            self.assertTrue(
                hasattr(ledger_module, symbol),
                f"lineage_ledger no longer re-exports {symbol!r}; existing "
                "callers (commands.lineage_cmd, system_gate, tests) would "
                "break.",
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


class CliDispatcherSiblingModuleDocConsistencyTests(unittest.TestCase):
    """CLAUDE.md's N6.5 bullet matches the live cli_dispatcher module layout.

    Pre-fix CLAUDE.md:56 framed the sibling-module split as a
    hypothetical future action ("500-LOC soft limit watched; split into
    ``core/cli_dispatcher_invokers.py`` if approached") while in
    reality:

    1. ``core/cli_dispatcher_invokers.py`` already exists (added by the
       N6.5 follow-up commit ``1d030f5`` ``fix(compat): N6.5
       follow-up``) — the split has already happened.
    2. ``core/cli_dispatcher.py`` is currently 545 LOC, i.e. ALREADY
       45 lines over the project's own 500-LOC soft cap codified in
       the CLAUDE.md Conventions section — the limit was already
       crossed, not "watched".
    3. ``cli_dispatcher.py::_default_invoker`` is a thin shim that
       delegates to ``cli_dispatcher_invokers.default_invoker`` (see
       ``cli_dispatcher.py:287`` ``from .cli_dispatcher_invokers
       import default_invoker as _impl``) — the actual tmux_runtime
       wiring lives in ``claude_code_invoker`` inside the sibling
       module, not in ``_default_invoker`` itself.

    Operators reading the pre-fix bullet would not learn that the
    sibling module shipped, would underestimate the parent's LOC, and
    would mis-attribute the tmux_runtime wiring. This regression test
    pins three independent halves of the post-fix contract so future
    re-edits to the bullet cannot silently regress any of them.
    """

    CLI_DISPATCHER_PATH = (
        REPO_ROOT
        / "skills"
        / "bmad-story-automator"
        / "src"
        / "story_automator"
        / "core"
        / "cli_dispatcher.py"
    )
    CLI_DISPATCHER_INVOKERS_PATH = (
        REPO_ROOT
        / "skills"
        / "bmad-story-automator"
        / "src"
        / "story_automator"
        / "core"
        / "cli_dispatcher_invokers.py"
    )

    def _claude_md_text(self) -> str:
        return _read("CLAUDE.md")

    def _n65_bullet(self, text: str) -> str:
        """Return the N6.5 bullet body (a single Markdown bullet line)."""
        match = re.search(
            r"^- \*\*CLI dispatcher \(N6\.5\)\*\*.*$",
            text,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            match,
            "CLAUDE.md no longer has the '- **CLI dispatcher (N6.5)**' "
            "bullet; update this regression test to match the new shape.",
        )
        return match.group(0)

    def test_cli_dispatcher_invokers_sibling_exists(self) -> None:
        """Defensive: the sibling module must actually exist on disk.

        This is the pre-condition for the doc fix; if a future refactor
        deletes the sibling and re-inlines the invokers, the CLAUDE.md
        bullet must be re-audited so the sibling reference does not
        become a dangling pointer.
        """
        self.assertTrue(
            self.CLI_DISPATCHER_INVOKERS_PATH.exists(),
            "cli_dispatcher_invokers.py sibling missing; CLAUDE.md's N6.5 "
            "bullet now references a non-existent module — either restore "
            "the split or rewrite the bullet.",
        )

    def test_n65_bullet_no_longer_frames_split_as_hypothetical(self) -> None:
        """The pre-fix 'if approached' framing must be gone.

        Pin the specific regression: the bullet previously said
        ``500-LOC soft limit watched; split into
        core/cli_dispatcher_invokers.py if approached`` — phrased as a
        conditional future action even though the split had already
        shipped. Post-fix the bullet must not carry that 'if approached'
        framing.
        """
        bullet = self._n65_bullet(self._claude_md_text())
        self.assertNotIn(
            "if approached",
            bullet,
            "CLAUDE.md N6.5 bullet still frames the cli_dispatcher_invokers "
            "split as 'if approached' (hypothetical future); the split has "
            "already shipped and the parent is already past the soft limit.",
        )

    def test_n65_bullet_names_invokers_sibling_as_shipped(self) -> None:
        """Post-fix bullet must surface the sibling as an existing module."""
        bullet = self._n65_bullet(self._claude_md_text())
        self.assertIn(
            "cli_dispatcher_invokers.py",
            bullet,
            "CLAUDE.md N6.5 bullet no longer names "
            "cli_dispatcher_invokers.py; operators planning a new "
            "milestone would not know the sibling module exists.",
        )

    def test_n65_bullet_acknowledges_parent_past_soft_limit(self) -> None:
        """Pin the post-fix acknowledgement that the parent is past 500 LOC.

        The fix's body claim is that ``cli_dispatcher.py`` is already
        over the soft cap. Anchor on the explicit "past the 500-LOC
        soft limit" phrasing so the bullet cannot drift back to the
        pre-fix "watched" framing without tripping this test.
        """
        bullet = self._n65_bullet(self._claude_md_text())
        self.assertRegex(
            bullet,
            r"past the 500-LOC soft limit",
            "CLAUDE.md N6.5 bullet no longer acknowledges that "
            "cli_dispatcher.py is past the 500-LOC soft limit; the doc "
            "would mislead operators about the current module layout.",
        )

    def test_parent_loc_actually_exceeds_soft_limit(self) -> None:
        """Defensive: the live parent module is genuinely past 500 LOC.

        If a future refactor splits more code out of cli_dispatcher.py
        and brings it back under 500 LOC, the bullet's "already past
        the soft limit" claim becomes stale. This test trips when that
        happens so the bullet gets re-audited at the same commit.
        """
        text = self.CLI_DISPATCHER_PATH.read_text(encoding="utf-8")
        loc = len(text.splitlines())
        self.assertGreater(
            loc,
            500,
            f"cli_dispatcher.py is {loc} LOC (<= 500). The CLAUDE.md "
            "N6.5 bullet still claims the file is past the soft limit; "
            "either re-tighten the bullet's wording or update this test.",
        )


class CliDispatcherDocsCliIdVocabularyTests(unittest.TestCase):
    """Doc-quoted ``cli_id`` tokens match the live ``KNOWN_CLI_IDS`` allowlist.

    Pre-fix ``CLAUDE.md:56`` and ``docs/spec/frozen-gate-surface.md:84``
    listed ``codex`` / ``gemini`` / ``none`` as ``cli_id`` values the
    dispatcher "resolves stop-hook dialects per ``cli_id``" — but the
    live closed vocabularies in ``core/cli_profile.py`` are:

    - ``KNOWN_CLI_IDS = ('claude-code', 'codex', 'gemini-cli')``
    - ``KNOWN_HOOK_DIALECTS = ('claude', 'codex', 'gemini', 'none')``

    The bare token ``gemini`` is a ``hook_dialect`` value, not a
    ``cli_id``; the canonical ``cli_id`` for the future Gemini CLI is
    ``gemini-cli``. Similarly, ``none`` belongs in the
    ``hook_dialect`` axis, not in ``cli_id``. An operator copying
    ``cli_id='gemini'`` from the docs would be rejected at
    ``CLIProfile`` construction with ``CLIProfileError: cli_id must be
    one of ['claude-code', 'codex', 'gemini-cli']``.

    The regression test pins the doc-vs-code drift: every backticked
    token quoted inside the dispatcher's "per ``cli_id``" parenthetical
    must be a member of the live ``KNOWN_CLI_IDS`` tuple, OR be
    explicitly disclaimed as a ``hook_dialect``-axis token.
    """

    # Tokens that, if quoted inside the "per cli_id" parenthetical
    # without an explicit hook_dialect disclaimer, would mislead an
    # operator into authoring an invalid CLIProfile. ``gemini`` is the
    # primary failure-mode anchor — it is a live hook_dialect token
    # whose cli_id counterpart is the suffixed ``gemini-cli``.
    BARE_GEMINI_TOKEN_RE = re.compile(r"`gemini`")

    def _live_known_cli_ids(self) -> tuple[str, ...]:
        cli_profile = importlib.import_module(
            "story_automator.core.cli_profile"
        )
        return tuple(cli_profile.KNOWN_CLI_IDS)

    def _live_known_hook_dialects(self) -> tuple[str, ...]:
        cli_profile = importlib.import_module(
            "story_automator.core.cli_profile"
        )
        return tuple(cli_profile.KNOWN_HOOK_DIALECTS)

    def _n65_bullet_in_claude_md(self) -> str:
        text = _read("CLAUDE.md")
        match = re.search(
            r"^- \*\*CLI dispatcher \(N6\.5\)\*\*.*$",
            text,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            match,
            "CLAUDE.md no longer has the '- **CLI dispatcher (N6.5)**' "
            "bullet; update this regression test to match the new shape.",
        )
        return match.group(0)

    def _frozen_surface_cli_dispatcher_line(self) -> str:
        text = _read("docs/spec/frozen-gate-surface.md")
        match = re.search(
            r"^- Stop-hook dialect resolver per `cli_id`.*$",
            text,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            match,
            "frozen-gate-surface.md no longer has the 'Stop-hook dialect "
            "resolver per `cli_id`' bullet; update this regression test "
            "to match the new shape.",
        )
        return match.group(0)

    def test_known_cli_ids_anchor_matches_expected_live_set(self) -> None:
        """Defensive: the live KNOWN_CLI_IDS tuple matches the doc fix's
        assumption that ``gemini-cli`` is the canonical Gemini ``cli_id``.

        If a future refactor renames the cli_id to bare ``gemini``,
        this test trips and forces the doc text to be re-audited at
        the same commit.
        """
        live = self._live_known_cli_ids()
        self.assertIn(
            "gemini-cli",
            live,
            "KNOWN_CLI_IDS no longer contains 'gemini-cli'; the doc fix "
            "at CLAUDE.md:56 + frozen-gate-surface.md:84 now references a "
            "non-existent cli_id. Either restore 'gemini-cli' or rewrite "
            "the docs to use the new canonical token.",
        )
        self.assertNotIn(
            "gemini",
            live,
            "KNOWN_CLI_IDS contains bare 'gemini' as a cli_id; the doc "
            "fix's hook_dialect disclaimer is now stale because the two "
            "axes have collapsed.",
        )

    def test_known_hook_dialects_anchor_matches_expected_live_set(self) -> None:
        """Defensive: ``gemini`` + ``none`` remain hook_dialect tokens.

        The doc fix's disclaimer ("the ``none`` token is a
        ``hook_dialect`` value, not a ``cli_id``") and the canonical
        ``gemini-cli`` rename depend on this two-axis split staying in
        place. If a future refactor collapses the axes, the disclaimer
        becomes misleading and this test trips.
        """
        live = self._live_known_hook_dialects()
        self.assertIn(
            "gemini",
            live,
            "KNOWN_HOOK_DIALECTS no longer contains 'gemini'; the doc "
            "fix's hook_dialect disclaimer is stale.",
        )
        self.assertIn(
            "none",
            live,
            "KNOWN_HOOK_DIALECTS no longer contains 'none'; the doc "
            "fix's 'none is a hook_dialect, not a cli_id' disclaimer "
            "is stale.",
        )

    def test_claude_md_n65_bullet_uses_gemini_cli_not_bare_gemini(self) -> None:
        """CLAUDE.md's N6.5 bullet must not quote the bare ``gemini`` token.

        Pin the specific regression: pre-fix the bullet listed
        ``future codex/gemini/none`` as cli_id values. Post-fix the
        bullet must use ``gemini-cli`` (the canonical KNOWN_CLI_IDS
        token) and either drop ``none`` or disclaim it as a
        hook_dialect-axis token.
        """
        bullet = self._n65_bullet_in_claude_md()
        # The bare backticked ``gemini`` token must not appear inside
        # the "per cli_id" parenthetical without a hook_dialect
        # disclaimer chained to it.
        self.assertNotRegex(
            bullet,
            r"`gemini`(?![- `])",
            "CLAUDE.md N6.5 bullet still quotes bare `gemini` as a cli_id "
            "value; the live KNOWN_CLI_IDS tuple uses `gemini-cli` "
            "(bare `gemini` is a hook_dialect token).",
        )
        # And the canonical token must appear.
        self.assertIn(
            "gemini-cli",
            bullet,
            "CLAUDE.md N6.5 bullet no longer names `gemini-cli` as a "
            "future cli_id; an operator following the docs would author "
            "an invalid CLIProfile.",
        )

    def test_frozen_surface_cli_dispatcher_uses_gemini_cli_not_bare_gemini(self) -> None:
        """frozen-gate-surface.md's cli_dispatcher line uses the canonical token.

        Pin the specific regression: pre-fix the line listed
        ``codex / gemini / none raise NotImplementedError until
        implemented``. Post-fix the line must use ``gemini-cli`` and
        either drop ``none`` from the ``cli_id`` enumeration or
        explicitly disclaim it as a ``hook_dialect`` token.
        """
        line = self._frozen_surface_cli_dispatcher_line()
        self.assertNotRegex(
            line,
            r"`gemini`(?![- `])",
            "frozen-gate-surface.md cli_dispatcher line still quotes bare "
            "`gemini` as a cli_id value; the live KNOWN_CLI_IDS tuple "
            "uses `gemini-cli`.",
        )
        self.assertIn(
            "gemini-cli",
            line,
            "frozen-gate-surface.md cli_dispatcher line no longer names "
            "`gemini-cli` as a future cli_id; the doc would mislead "
            "operators into authoring an invalid CLIProfile.",
        )


class RecentlyShippedSiblingModuleMentionTests(unittest.TestCase):
    """CLAUDE.md's "Recently shipped" bullets name every shipped sibling module.

    Pre-fix the K-2 bullet at CLAUDE.md said only "memoization with explicit
    invalidation on persist; observability-only — no behavior change" and
    never named the implementing module ``core/evidence_cache.py`` (165 LOC,
    imported 7 times by ``evidence_io.py``, ``verdict_engine.py``, and
    ``gate_orchestrator.py``). Similarly the G2 bullet named only
    ``core/collector_isolation.py`` and never mentioned the sibling
    ``core/collector_isolation_outcomes.py`` (139 LOC of pure outcome-reifier
    helpers extracted to keep the parent under the 500-LOC soft limit;
    imported 4 times by ``collector_isolation.py``).

    Given CLAUDE.md's own directive "Read these existing modules before
    planning any new milestone — interfaces are stable", an engineer
    designing a new milestone that touches evidence-bundle memoization
    would not discover ``evidence_cache.py`` from the doc and could
    design a parallel cache, breaking the K-2 "explicit invalidation on
    persist" contract. The regression test pins both module names to the
    respective bullets.
    """

    EVIDENCE_CACHE_PATH = (
        REPO_ROOT
        / "skills"
        / "bmad-story-automator"
        / "src"
        / "story_automator"
        / "core"
        / "evidence_cache.py"
    )
    COLLECTOR_ISOLATION_OUTCOMES_PATH = (
        REPO_ROOT
        / "skills"
        / "bmad-story-automator"
        / "src"
        / "story_automator"
        / "core"
        / "collector_isolation_outcomes.py"
    )

    def _k2_bullet(self) -> str:
        text = _read("CLAUDE.md")
        match = re.search(
            r"^- \*\*Evidence-bundle memoization \(K-2\)\*\*.*$",
            text,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            match,
            "CLAUDE.md no longer has the '- **Evidence-bundle memoization "
            "(K-2)**' bullet; update this regression test to match the new shape.",
        )
        return match.group(0)

    def _g2_bullet(self) -> str:
        text = _read("CLAUDE.md")
        match = re.search(
            r"^- \*\*Worktree-per-unit isolation \(G2\)\*\*.*$",
            text,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            match,
            "CLAUDE.md no longer has the '- **Worktree-per-unit isolation "
            "(G2)**' bullet; update this regression test to match the new shape.",
        )
        return match.group(0)

    def test_k2_bullet_names_evidence_cache_module(self) -> None:
        bullet = self._k2_bullet()
        self.assertIn(
            "evidence_cache.py",
            bullet,
            "CLAUDE.md K-2 bullet no longer names ``core/evidence_cache.py`` "
            "(the 165-LOC module that actually implements the K-2 memoization "
            "with explicit invalidation on persist). An operator planning a new "
            "milestone that touches evidence-bundle caching would not discover "
            "the module from the doc and could design a parallel cache, breaking "
            "the K-2 'invalidate on persist' contract.",
        )

    def test_g2_bullet_names_collector_isolation_outcomes_module(self) -> None:
        bullet = self._g2_bullet()
        self.assertIn(
            "collector_isolation_outcomes.py",
            bullet,
            "CLAUDE.md G2 bullet no longer names ``core/collector_isolation_outcomes.py`` "
            "(the 139-LOC sibling extracted to keep the parent under the 500-LOC "
            "soft limit after the AC-I-13 / AC-I-14 fold-in). An operator planning "
            "a new milestone that touches per-unit outcome reification would not "
            "discover the helper module from the doc.",
        )

    def test_evidence_cache_module_actually_exists(self) -> None:
        """Defensive: ``evidence_cache.py`` must exist on disk.

        If a future refactor moves the K-2 cache somewhere else (e.g.
        inlines it back into ``evidence_io.py``), the CLAUDE.md mention
        becomes a dangling pointer. This test trips so the doc gets
        re-audited at the same commit.
        """
        self.assertTrue(
            self.EVIDENCE_CACHE_PATH.exists(),
            "core/evidence_cache.py missing; CLAUDE.md's K-2 bullet now "
            "references a non-existent module — either restore the file or "
            "rewrite the bullet.",
        )

    def test_collector_isolation_outcomes_module_actually_exists(self) -> None:
        """Defensive: ``collector_isolation_outcomes.py`` must exist on disk.

        If a future refactor folds the outcome reifiers back into
        ``collector_isolation.py``, the CLAUDE.md mention becomes a
        dangling pointer. This test trips so the doc gets re-audited at
        the same commit.
        """
        self.assertTrue(
            self.COLLECTOR_ISOLATION_OUTCOMES_PATH.exists(),
            "core/collector_isolation_outcomes.py missing; CLAUDE.md's G2 "
            "bullet now references a non-existent module — either restore "
            "the file or rewrite the bullet.",
        )


class ValidateCliIdDocstringGrammarTests(unittest.TestCase):
    """``_validate_cli_id`` docstring uses third-person-singular "Raises".

    Pre-fix the docstring at
    ``core/innovation/session_usage_capture.py:128`` opened its second
    paragraph with ``Raised :class:`SessionUsageCaptureError` wraps the
    underlying :class:`ParseError` so callers can catch one class.`` —
    the clause ``Raised X wraps Y`` is ungrammatical because the past
    participle ``Raised`` has no implicit subject before the finite
    verb ``wraps`` arrives. The sibling docstring on
    :func:`capture_session_usage` (same module, ~50 lines below) uses
    the conventional PEP-257 ``Raises :class:`SessionUsageCaptureError`
    if ...`` form, confirming the file's own voice convention is
    third-person-singular ``Raises``. The fix changes ``Raised`` →
    ``Raises`` and rephrases as ``Raises ..., wrapping ...``.

    The regression test pins the post-fix grammar by asserting:

    1. The docstring contains the third-person-singular ``Raises``
       opener (PEP-257 style).
    2. The pre-fix ungrammatical clause ``Raised :class:`Session...
       wraps`` is gone — so a future refactor that re-introduces the
       typo trips this test.
    """

    def _docstring(self) -> str:
        module = importlib.import_module(
            "story_automator.core.innovation.session_usage_capture"
        )
        return module._validate_cli_id.__doc__ or ""

    def test_validate_cli_id_uses_third_person_singular_raises(self) -> None:
        doc = self._docstring()
        # The post-fix docstring must contain a ``Raises`` line — the
        # PEP-257 convention for documenting what a function raises.
        self.assertRegex(
            doc,
            r"\bRaises\s+:class:`SessionUsageCaptureError`",
            "_validate_cli_id docstring does not use the third-person-"
            "singular 'Raises :class:`SessionUsageCaptureError`' opener; "
            "the sibling docstring on capture_session_usage uses this "
            "PEP-257 form so the module voice should be consistent.",
        )

    def test_validate_cli_id_does_not_carry_pre_fix_typo(self) -> None:
        """Pin the specific regression: pre-fix said 'Raised X wraps Y'.

        Reverting to the pre-fix wording would re-introduce the
        ungrammatical 'Raised :class:`SessionUsageCaptureError` wraps
        the underlying :class:`ParseError`' clause.
        """
        doc = self._docstring()
        self.assertNotRegex(
            doc,
            r"Raised\s+:class:`SessionUsageCaptureError`\s+wraps",
            "_validate_cli_id docstring re-introduces the pre-fix "
            "ungrammatical 'Raised :class:`SessionUsageCaptureError` "
            "wraps' clause; use 'Raises ..., wrapping ...' instead.",
        )


class SessionUsageCaptureFailSoftDocstringTests(unittest.TestCase):
    """``session_usage_capture`` module docstring matches its conditional warning.

    Pre-fix the module docstring at ``session_usage_capture.py:30-31``
    promised "Unparseable content => return zero-valued
    :class:`UsageMetrics` with ``parser_id='unparseable'`` and a logged
    warning." — an unconditional logging promise. The actual
    implementation at ``session_usage_capture.py:232-244`` gates the
    warning on TWO conditions: ``bytes_read > 0`` AND
    ``parser_id not in _ZERO_BY_CONTRACT_PARSER_IDS``. So an empty
    transcript (bytes_read == 0) and the contractually-zero parser
    dialects (``"none"``, ``"codex-rollout"``, ``"gemini-chat"``) both
    silently downgrade ``parser_id`` to ``"unparseable"`` without
    emitting any warning. Audit consumers relying on log-scraping to
    detect runtime degradation would miss those cases.

    The fix tightens the docstring to spell out both suppression
    conditions and explain why ("contractually zero-returning, so
    logging a 'parser returned zero usage' warning there would falsely
    imply degradation where there is none"). The intent and inline
    comments at lines 215-231 already documented this rationale; the
    module-level fail-soft contract bullet now mirrors it.

    The regression test pins both halves of the contract:

    1. The high-level docstring bullet no longer carries the
       unconditional "and a logged warning" promise (the pre-fix
       wording).
    2. The docstring explicitly names the two suppression conditions
       (the ``bytes_read > 0`` / "non-empty" guard AND the
       ``_ZERO_BY_CONTRACT_PARSER_IDS`` reference) so future readers
       can find the rationale without grepping the source.
    """

    def _module_doc(self) -> str:
        module = importlib.import_module(
            "story_automator.core.innovation.session_usage_capture"
        )
        return module.__doc__ or ""

    def test_failsoft_bullet_no_longer_promises_unconditional_warning(self) -> None:
        # Normalize whitespace because the docstring line-wraps.
        normalized = re.sub(r"\s+", " ", self._module_doc())
        # The pre-fix bullet read ``parser_id="unparseable" and a logged
        # warning`` as the unconditional fail-soft contract for
        # unparseable content (literal source has double backticks
        # around the parser_id token, but they are not significant for
        # matching). The unconditional ``and a logged warning`` clause
        # MUST be gone post-fix; the only acceptable framing is a
        # qualified clause that names a suppression condition.
        self.assertNotRegex(
            normalized,
            r"parser_id=\"unparseable\"``\s+and\s+a\s+logged\s+warning\.",
            "session_usage_capture module docstring still carries the "
            "pre-fix unconditional 'parser_id=\"unparseable\" and a "
            "logged warning.' promise; the implementation actually "
            "suppresses the warning for empty transcripts and "
            "contractually-zero parser dialects.",
        )

    def test_failsoft_bullet_documents_both_suppression_conditions(self) -> None:
        # Post-fix the bullet must explicitly disclose BOTH guards so
        # future readers do not have to grep the source to learn that
        # empty transcripts and contractually-zero dialects skip the
        # warning. Normalize whitespace because the docstring line-wraps.
        normalized = re.sub(r"\s+", " ", self._module_doc())
        # Guard 1: non-empty (bytes_read > 0).
        self.assertIn(
            "non-empty",
            normalized,
            "session_usage_capture module docstring does not mention the "
            "'non-empty' transcript precondition for the zero-on-nonempty "
            "warning. Empty transcripts silently downgrade parser_id to "
            "'unparseable' without a warning; the docstring must say so.",
        )
        # Guard 2: zero-by-contract parser ids. Anchor on the constant
        # name so a future rename trips the test at the same commit.
        self.assertIn(
            "_ZERO_BY_CONTRACT_PARSER_IDS",
            normalized,
            "session_usage_capture module docstring does not reference "
            "_ZERO_BY_CONTRACT_PARSER_IDS — the constant that pins the "
            "second suppression condition (none / codex-rollout / "
            "gemini-chat dialects). Audit consumers need the pointer to "
            "find the suppression rationale.",
        )

    def test_failsoft_bullet_implementation_still_matches_docstring(self) -> None:
        """Defensive: the live constant still holds the three contract dialects.

        If a future refactor changes :data:`_ZERO_BY_CONTRACT_PARSER_IDS`
        to add/remove dialects, the docstring's ``"none"`` / ``"codex-rollout"``
        / ``"gemini-chat"`` enumeration becomes stale and this test trips
        so the docstring gets re-audited at the same commit.
        """
        module = importlib.import_module(
            "story_automator.core.innovation.session_usage_capture"
        )
        self.assertEqual(
            module._ZERO_BY_CONTRACT_PARSER_IDS,
            frozenset({"none", "codex-rollout", "gemini-chat"}),
            "_ZERO_BY_CONTRACT_PARSER_IDS membership changed; re-audit "
            "the session_usage_capture module docstring enumeration of "
            "contractually-zero parser dialects.",
        )


class SpecDriftWatcherPersistenceKeyDocstringTests(unittest.TestCase):
    """``SpecDriftWatcher.__init__`` docstring documents both-kwargs precedence.

    Pre-fix the ``persistence_key`` docstring said "the watcher loads any
    persisted baseline at init" unconditionally. The live code only loads
    from disk when ``baseline_snapshot is None`` (line 157 of
    ``spec_drift_watcher.py``); when BOTH ``baseline_snapshot`` and
    ``persistence_key`` are supplied AND disk already holds a different
    baseline, the caller-supplied snapshot wins in memory while the
    on-disk baseline is conservatively preserved. This is intentional
    design (the inline comment at lines 164-166 documents the
    "previously-persisted baseline is never clobbered by a stale
    caller-supplied snapshot" choice), but the docstring did not surface
    the in-memory/on-disk divergence corner case.

    The regression test pins the clarified docstring so a future
    refactor that removes the precedence-rule documentation trips this
    test at the same commit. Doc-precision fix only — no code change.
    """

    def test_persistence_key_docstring_documents_both_kwargs_precedence(
        self,
    ) -> None:
        module = importlib.import_module(
            "story_automator.core.innovation.spec_drift_watcher"
        )
        init_doc = module.SpecDriftWatcher.__init__.__doc__ or ""
        # Normalize whitespace so the assertion does not depend on
        # the docstring's wrap column.
        normalized = re.sub(r"\s+", " ", init_doc).strip()
        # Pin the BOTH-kwargs precedence rule.
        self.assertIn(
            "baseline_snapshot``",
            normalized,
            "SpecDriftWatcher.__init__ docstring no longer references "
            "the baseline_snapshot kwarg by name in the persistence_key "
            "section; the both-kwargs precedence corner case must stay "
            "documented so operators do not assume disk wins.",
        )
        # Pin the explicit clarification that both-kwargs leaves disk
        # alone when a baseline already exists there.
        self.assertIn(
            "previously-persisted baseline is conservatively preserved",
            normalized,
            "SpecDriftWatcher.__init__ docstring no longer documents "
            "that a previously-persisted on-disk baseline is preserved "
            "when both baseline_snapshot and persistence_key are "
            "supplied. This corner case (in-memory and on-disk baselines "
            "may diverge) is intentional design and must remain "
            "documented so operators audit drift telemetry against the "
            "correct truth source.",
        )

    def test_persistence_key_docstring_clarifies_load_precondition(
        self,
    ) -> None:
        """The 'loads any persisted baseline at init' phrase is now scoped.

        Pre-fix the docstring promised an unconditional load; the live
        code only loads when ``baseline_snapshot is None``. Pin that the
        load promise is now qualified.
        """
        module = importlib.import_module(
            "story_automator.core.innovation.spec_drift_watcher"
        )
        init_doc = module.SpecDriftWatcher.__init__.__doc__ or ""
        normalized = re.sub(r"\s+", " ", init_doc).strip()
        # The qualifier must appear adjacent to the "loads any persisted
        # baseline at init" promise. We assert the conjunction shape
        # ("provided AND baseline_snapshot") rather than an exact phrase
        # so a future rewording does not falsely trip.
        self.assertRegex(
            normalized,
            r"provided\s+AND\s+``baseline_snapshot``\s+is\s+``None``",
            "SpecDriftWatcher.__init__ docstring no longer qualifies the "
            "'loads any persisted baseline at init' promise with the "
            "'AND baseline_snapshot is None' precondition. Without the "
            "qualifier the docstring contradicts the live code at line "
            "157 which only loads from disk when self._baseline is None.",
        )


class HookBusDocsConsistencyTests(unittest.TestCase):
    """CLAUDE.md + frozen-gate-surface.md HookBus stage names match KNOWN_EVENTS.

    Pre-fix CLAUDE.md (the N6.2/N6.3 bullet) and
    ``docs/spec/frozen-gate-surface.md`` (the hookbus_shim section)
    both claimed: ``core/gate_orchestrator.py`` fires HookBus at 6
    lifecycle stages ``{pre_gate, pre_collect, post_collect,
    pre_adjudicate, post_adjudicate, post_gate}``. Two independent
    drifts:

    1. **Wrong module.** ``grep -i 'hookbus\\|emit_hook' core/gate_orchestrator.py``
       returns ZERO matches. The actual wiring lives in
       ``commands/orchestrator.py`` (N6.3 orchestrator-helper CLI).
    2. **Wrong stage names.** ``hookbus_shim.KNOWN_EVENTS`` is
       ``{post_dev_phase, pre_review, post_review, pre_gate, post_gate,
       pre_commit}``. The four names ``pre_collect``, ``post_collect``,
       ``pre_adjudicate``, ``post_adjudicate`` are not in the
       allowlist; a plugin author registering on them would get
       ``HookbusShimError``.

    The regression test pins three independent halves of the post-fix
    contract:

    1. ``core/gate_orchestrator.py`` truly carries no HookBus import or
       emit call so a future re-introduction of the doc drift is
       caught at the same commit.
    2. Both docs name the six stages currently in ``KNOWN_EVENTS`` and
       avoid the four non-existent ones.
    3. Both docs attribute the dispatch to ``commands/orchestrator.py``
       (not ``core/gate_orchestrator.py``).
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
    # Stage names the pre-fix docs claimed but that do NOT exist in
    # ``hookbus_shim.KNOWN_EVENTS``. A plugin author copying these from
    # the docs would get ``HookbusShimError`` at registration.
    NON_EXISTENT_STAGE_NAMES = (
        "pre_collect",
        "post_collect",
        "pre_adjudicate",
        "post_adjudicate",
    )

    def _live_known_events(self) -> frozenset[str]:
        shim = importlib.import_module(
            "story_automator.core.bauto_bridge.hookbus_shim"
        )
        return shim.KNOWN_EVENTS

    def test_gate_orchestrator_carries_no_hookbus_wiring(self) -> None:
        """Defensive: the live source backs the post-fix doc claim.

        If a future milestone wires HookBus into ``core/gate_orchestrator.py``,
        this test trips so both docs get re-audited at the same commit
        (the post-fix doc text says ``core/gate_orchestrator.py`` does
        NOT call HookBus — that claim must remain true).
        """
        text = self.GATE_ORCHESTRATOR_PATH.read_text(encoding="utf-8")
        # Use a regex that ignores case so 'HookBus' / 'hookbus' both
        # trip. The shim's import path token uniquely anchors any
        # HookBus reference because the only public type is
        # HookBusShim and its only module is hookbus_shim.
        forbidden = re.compile(
            r"hookbus_shim|HookBusShim",
            re.IGNORECASE,
        )
        match = forbidden.search(text)
        self.assertIsNone(
            match,
            "core/gate_orchestrator.py now references HookBus "
            f"({match.group(0) if match else '?'}); CLAUDE.md + "
            "frozen-gate-surface.md both claim the file does NOT "
            "wire HookBus. Either re-audit those doc bullets or "
            "revert the new import.",
        )

    def test_known_events_anchor_matches_post_fix_doc_text(self) -> None:
        """Defensive: the live ``KNOWN_EVENTS`` matches the doc's named six.

        The post-fix CLAUDE.md + frozen-gate-surface.md bullets
        enumerate ``post_dev_phase, pre_review, post_review, pre_gate,
        post_gate, pre_commit``. If a future refactor widens or shrinks
        ``KNOWN_EVENTS``, this test trips so both doc enumerations get
        re-audited at the same commit.
        """
        live = self._live_known_events()
        expected = frozenset({
            "post_dev_phase",
            "pre_review",
            "post_review",
            "pre_gate",
            "post_gate",
            "pre_commit",
        })
        self.assertEqual(
            live,
            expected,
            f"hookbus_shim.KNOWN_EVENTS is {sorted(live)} but CLAUDE.md "
            f"+ frozen-gate-surface.md enumerate {sorted(expected)}; "
            "either widen/shrink the doc enumerations or rebind "
            "KNOWN_EVENTS.",
        )

    def test_claude_md_hookbus_bullet_names_real_stage_names(self) -> None:
        """CLAUDE.md's HookBus bullet must name every live stage name.

        Pin the specific regression: pre-fix CLAUDE.md listed four
        stage names (``pre_collect``, ``post_collect``,
        ``pre_adjudicate``, ``post_adjudicate``) that are NOT in
        ``KNOWN_EVENTS`` and omitted the four real ones that are.
        """
        text = _read("CLAUDE.md")
        match = re.search(
            r"^- \*\*HookBus \(N6\.2/N6\.3\)\*\*.*$",
            text,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            match,
            "CLAUDE.md no longer has the '- **HookBus (N6.2/N6.3)**' "
            "bullet; update this regression test to match the new shape.",
        )
        bullet = match.group(0)
        # Every live KNOWN_EVENTS name must appear backticked in the
        # bullet so the doc enumeration matches the allowlist.
        for stage in self._live_known_events():
            self.assertIn(
                f"`{stage}`",
                bullet,
                f"CLAUDE.md HookBus bullet no longer names `{stage}` "
                "as a lifecycle stage. The live KNOWN_EVENTS allowlist "
                "carries this token; the doc enumeration must match or "
                "operators following the spec will register on the "
                "wrong stage names.",
            )
        # The four pre-fix non-existent stage names MUST be gone.
        for stage in self.NON_EXISTENT_STAGE_NAMES:
            self.assertNotIn(
                f"`{stage}`",
                bullet,
                f"CLAUDE.md HookBus bullet still lists `{stage}` as a "
                "lifecycle stage, but the token is not in "
                "hookbus_shim.KNOWN_EVENTS. A plugin author registering "
                "on this stage name would get HookbusShimError.",
            )

    def test_claude_md_hookbus_bullet_attributes_dispatch_to_commands(
        self,
    ) -> None:
        """CLAUDE.md must point operators at the actual dispatch site.

        Pre-fix CLAUDE.md said ``core/gate_orchestrator.py`` fires
        HookBus; post-fix it must name ``commands/orchestrator.py``
        because that is where the six emit call sites actually live.
        """
        text = _read("CLAUDE.md")
        match = re.search(
            r"^- \*\*HookBus \(N6\.2/N6\.3\)\*\*.*$",
            text,
            re.MULTILINE,
        )
        self.assertIsNotNone(match)
        bullet = match.group(0)
        self.assertIn(
            "commands/orchestrator.py",
            bullet,
            "CLAUDE.md HookBus bullet no longer names "
            "`commands/orchestrator.py` as the dispatch site; the "
            "actual emit call sites live there (the bus is not wired "
            "into core/gate_orchestrator.py).",
        )

    def test_frozen_surface_hookbus_section_names_real_stage_names(
        self,
    ) -> None:
        """frozen-gate-surface.md's hookbus_shim section enumerates the live six.

        Pin the spec's HookBus enumeration to ``KNOWN_EVENTS`` so a
        future doc edit cannot silently regress to the pre-fix
        four-bogus-stages enumeration.
        """
        text = self.FROZEN_SURFACE_PATH.read_text(encoding="utf-8")
        # The section is delimited by the
        # ``### `core/bauto_bridge/hookbus_shim.py` (Path B / N6.2)``
        # heading and the next ``### `` heading.
        section_re = re.compile(
            r"^### `core/bauto_bridge/hookbus_shim\.py`.*?$",
            re.MULTILINE,
        )
        match = section_re.search(text)
        self.assertIsNotNone(
            match,
            "frozen-gate-surface.md no longer has the "
            "'### `core/bauto_bridge/hookbus_shim.py`' section heading; "
            "update this regression test to match the new shape.",
        )
        start = match.end()
        next_heading = re.search(r"^### ", text[start:], re.MULTILINE)
        end = start + next_heading.start() if next_heading else len(text)
        body = text[start:end]
        for stage in self._live_known_events():
            self.assertIn(
                f"`{stage}`",
                body,
                f"frozen-gate-surface.md hookbus_shim section no longer "
                f"names `{stage}` as a lifecycle stage. The live "
                "KNOWN_EVENTS allowlist carries this token; the doc "
                "enumeration must match.",
            )
        for stage in self.NON_EXISTENT_STAGE_NAMES:
            self.assertNotIn(
                f"`{stage}`",
                body,
                f"frozen-gate-surface.md hookbus_shim section still "
                f"lists `{stage}` as a lifecycle stage, but the token "
                "is not in hookbus_shim.KNOWN_EVENTS.",
            )

    def test_frozen_surface_hookbus_section_attributes_dispatch_to_commands(
        self,
    ) -> None:
        """frozen-gate-surface.md must point operators at the real dispatch site.

        Pre-fix the section said
        ``core/gate_orchestrator.run_production_gate fires it`` — but
        ``core/gate_orchestrator.py`` carries no HookBus import or call.
        Post-fix the section must name ``commands/orchestrator.py``.
        """
        text = self.FROZEN_SURFACE_PATH.read_text(encoding="utf-8")
        section_re = re.compile(
            r"^### `core/bauto_bridge/hookbus_shim\.py`.*?$",
            re.MULTILINE,
        )
        match = section_re.search(text)
        self.assertIsNotNone(match)
        start = match.end()
        next_heading = re.search(r"^### ", text[start:], re.MULTILINE)
        end = start + next_heading.start() if next_heading else len(text)
        body = text[start:end]
        self.assertIn(
            "commands/orchestrator.py",
            body,
            "frozen-gate-surface.md hookbus_shim section no longer "
            "names `commands/orchestrator.py` as the dispatch site; "
            "the bus emit call sites live there, not in "
            "core/gate_orchestrator.py.",
        )


class ActionEnumDocsConsistencyTests(unittest.TestCase):
    """CLAUDE.md + frozen-gate-surface.md Action enum vocabulary matches code.

    Pre-fix both ``docs/spec/frozen-gate-surface.md`` (N6.6 section) and
    ``CLAUDE.md`` (N6.6 bullet) stated the action enum closed vocabulary
    was ``{"continue", "remediate", "park", "halt"}`` while the live
    ``core/action_enum.py`` exports
    ``VALID_ACTIONS = ("done", "remediate", "park", "defer", "escalate")``
    and ``Action = Literal["done", "remediate", "park", "defer",
    "escalate"]``. Two of the four documented strings (``continue``,
    ``halt``) do not exist in code; three of the five actual strings
    (``done``, ``defer``, ``escalate``) were absent from the documented
    set.

    The drift was bidirectional and the doc is the binding contract per
    its preamble ("the symbols, fields, and behaviors listed here are
    public contracts"). A plugin author calling
    ``canonicalize_action("continue")`` would hit ``ActionError`` at
    runtime; an operator enumerating verifier return values from the
    doc would miss ``done``, ``defer``, ``escalate``.

    The regression test pins both doc surfaces to the live
    ``VALID_ACTIONS`` tuple so future drift in either direction trips
    at the same commit.
    """

    FROZEN_SURFACE_PATH = REPO_ROOT / "docs" / "spec" / "frozen-gate-surface.md"

    def _live_valid_actions(self) -> tuple[str, ...]:
        module = importlib.import_module(
            "story_automator.core.action_enum"
        )
        return tuple(module.VALID_ACTIONS)

    def _frozen_surface_n66_section(self) -> str:
        text = self.FROZEN_SURFACE_PATH.read_text(encoding="utf-8")
        # The section is delimited by the
        # ``### `core/action_enum.py` (Path B / N6.6)`` heading and the
        # next ``### `` heading.
        section_re = re.compile(
            r"^### `core/action_enum\.py` \(Path B / N6\.6\).*?$",
            re.MULTILINE,
        )
        match = section_re.search(text)
        self.assertIsNotNone(
            match,
            "frozen-gate-surface.md no longer has the "
            "'### `core/action_enum.py` (Path B / N6.6)' section heading; "
            "update this regression test to match the new shape.",
        )
        start = match.end()
        next_heading = re.search(r"^### ", text[start:], re.MULTILINE)
        end = start + next_heading.start() if next_heading else len(text)
        return text[start:end]

    def _claude_md_n66_bullet(self) -> str:
        text = _read("CLAUDE.md")
        match = re.search(
            r"^- \*\*Action enum \(N6\.6\)\*\*.*$",
            text,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            match,
            "CLAUDE.md no longer has the '- **Action enum (N6.6)**' "
            "bullet; update this regression test to match the new shape.",
        )
        return match.group(0)

    def test_valid_actions_anchor_matches_expected_live_set(self) -> None:
        """Defensive: live ``VALID_ACTIONS`` matches the doc fix's tuple.

        Pin both halves of the contract: if a future refactor renames
        any of these or adds a sixth value, this test trips so the docs
        get re-audited at the same commit.
        """
        live = self._live_valid_actions()
        expected = ("done", "remediate", "park", "defer", "escalate")
        self.assertEqual(
            live,
            expected,
            f"core.action_enum.VALID_ACTIONS is {live} but CLAUDE.md + "
            f"frozen-gate-surface.md enumerate {expected}; either widen/"
            "shrink the doc enumerations or rebind VALID_ACTIONS.",
        )

    def test_frozen_surface_n66_section_names_real_action_strings(self) -> None:
        """frozen-gate-surface.md N6.6 section enumerates every live action.

        Pin the spec's action vocabulary to ``VALID_ACTIONS`` so a future
        doc edit cannot silently regress to the pre-fix bogus
        ``{continue, halt}`` enumeration.
        """
        body = self._frozen_surface_n66_section()
        for action in self._live_valid_actions():
            self.assertIn(
                f'"{action}"',
                body,
                f"frozen-gate-surface.md N6.6 section no longer "
                f"names \"{action}\" as a verifier action. The live "
                "VALID_ACTIONS tuple carries this token; the doc "
                "enumeration must match or plugin authors will hit "
                "ActionError at runtime.",
            )
        # The two pre-fix non-existent action strings MUST be gone.
        for action in ("continue", "halt"):
            self.assertNotIn(
                f'"{action}"',
                body,
                f"frozen-gate-surface.md N6.6 section still lists "
                f'"{action}" as an action, but the token is not in '
                "core.action_enum.VALID_ACTIONS. A plugin author calling "
                f"canonicalize_action('{action}') would get ActionError.",
            )

    def test_claude_md_n66_bullet_names_real_action_strings(self) -> None:
        """CLAUDE.md N6.6 bullet enumerates every live action.

        Pin the specific regression: pre-fix CLAUDE.md listed two
        action strings (``continue``, ``halt``) that are NOT in
        ``VALID_ACTIONS`` and omitted the three real ones (``done``,
        ``defer``, ``escalate``).
        """
        bullet = self._claude_md_n66_bullet()
        for action in self._live_valid_actions():
            self.assertIn(
                f'"{action}"',
                bullet,
                f"CLAUDE.md N6.6 bullet no longer names \"{action}\" "
                "as a verifier action. The live VALID_ACTIONS tuple "
                "carries this token; the doc enumeration must match.",
            )
        for action in ("continue", "halt"):
            self.assertNotIn(
                f'"{action}"',
                bullet,
                f"CLAUDE.md N6.6 bullet still lists \"{action}\" as "
                "an action, but the token is not in "
                "core.action_enum.VALID_ACTIONS.",
            )


class WorktreePerUnitIsolationInvariantSubTestCountTests(unittest.TestCase):
    """The ``WorktreePerUnitIsolationInvariant`` class docstring's
    ``"Five sub-tests"`` (or similar word-form) count tracks the live
    test-method count on the class, and the matching mention in
    ``CLAUDE.md`` does too.

    Pre-fix the class docstring read ``"Four sub-tests"`` and CLAUDE.md
    read ``"(4 sub-tests; …)"``, even though the class exposed FIVE
    ``test_*`` methods after the round-1-fix-37 sibling-coverage
    regression was folded in (``test_glob_scan_covers_sibling_collector_isolation_modules``).
    The drift is documentation-only — the audit-floor invariant runs
    correctly — but it misleads contributors counting sub-tests by
    inspection rather than by ``dir(cls)``.

    The regression test walks the live class with ``inspect``, counts
    the number of ``test_*`` attributes, and asserts that BOTH the class
    docstring and the CLAUDE.md G2 bullet quote a matching number-word
    or numeric token.
    """

    _WORDS = {
        1: "one",
        2: "two",
        3: "three",
        4: "four",
        5: "five",
        6: "six",
        7: "seven",
        8: "eight",
        9: "nine",
        10: "ten",
    }

    @classmethod
    def _live_test_method_count(cls) -> int:
        import importlib
        import inspect

        mod = importlib.import_module("tests.test_audit_regression")
        target = getattr(mod, "WorktreePerUnitIsolationInvariant")
        return sum(
            1
            for name, value in inspect.getmembers(target)
            if name.startswith("test_") and callable(value)
        )

    @classmethod
    def _docstring(cls) -> str:
        import importlib

        mod = importlib.import_module("tests.test_audit_regression")
        target = getattr(mod, "WorktreePerUnitIsolationInvariant")
        return target.__doc__ or ""

    def test_class_docstring_sub_test_count_matches_live(self) -> None:
        live = self._live_test_method_count()
        word = self._WORDS.get(live)
        self.assertIsNotNone(
            word,
            f"Add a number-word mapping for {live} to _WORDS",
        )
        doc = self._docstring()
        pattern = re.compile(
            rf"\b{word}\s+sub-tests\b",
            re.IGNORECASE,
        )
        self.assertRegex(
            doc,
            pattern,
            f"WorktreePerUnitIsolationInvariant class docstring no longer "
            f"says '{word.capitalize()} sub-tests' but the live class "
            f"exposes {live} test_* methods; bump the docstring count "
            "when adding/removing test methods.",
        )

    def test_claude_md_g2_bullet_sub_test_count_matches_live(self) -> None:
        live = self._live_test_method_count()
        claude_md = _read("CLAUDE.md")
        pattern = re.compile(
            r"Pinned by `WorktreePerUnitIsolationInvariant` \((\d+) sub-tests;",
        )
        match = pattern.search(claude_md)
        self.assertIsNotNone(
            match,
            "CLAUDE.md G2 bullet missing the "
            "'Pinned by `WorktreePerUnitIsolationInvariant` (N sub-tests; …)' "
            "shape — the docstring-vs-CLAUDE.md cross-reference test relies "
            "on this anchor.",
        )
        documented = int(match.group(1))
        self.assertEqual(
            documented,
            live,
            f"CLAUDE.md G2 bullet says '({documented} sub-tests)' but the "
            f"live WorktreePerUnitIsolationInvariant class exposes {live} "
            "test_* methods; both must move together.",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
