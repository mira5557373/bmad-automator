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


class ContributingSectionHeadingsTests(unittest.TestCase):
    """The four polish-docs sections are present in CONTRIBUTING.md."""

    REQUIRED_HEADINGS = (
        "## sw-style discipline",
        "### TDD pattern",
        "### Audit-floor invariants (26 green)",
        "### Sibling-module pattern",
        "### Additive-only `gate_file` field rule",
    )

    def test_contributing_section_headings_present(self) -> None:
        text = _read("CONTRIBUTING.md")
        missing = [h for h in self.REQUIRED_HEADINGS if h not in text]
        self.assertEqual(
            missing,
            [],
            f"CONTRIBUTING.md missing required section headings: {missing}",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
