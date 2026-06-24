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

import importlib
import re
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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
