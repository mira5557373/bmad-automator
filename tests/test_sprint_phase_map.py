from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from story_automator.core.integration.sprint_phase_map import (
    DualStoreError,
    DualStoreInconsistencyError,
    DualStoreState,
    Inconsistency,
    PHASE_TO_SPRINT_STATUS,
    Phase,
    SPRINT_STATUS_TO_PHASE,
    compute_dual_state,
    is_consistent,
    phase_for_sprint_status,
    phase_store_path,
    read_phase_store,
    sprint_status_for_phase,
    validate_dual_store,
    write_phase,
)


SPRINT_STATUS_FIXTURE = textwrap.dedent(
    """\
    development_status:
      1-1-host-feasibility-probe: done
      1-2-docker-dev-test-environment: in-progress
      1-3-database-wrapper-migrations: not_started
      2-1-users-schema-permanent-admin: review-running
    """
)


class PhaseEnumTests(unittest.TestCase):
    """Phase StrEnum must mirror bmad-auto's 11-value lifecycle."""

    def test_phase_has_eleven_members(self) -> None:
        self.assertEqual(len(list(Phase)), 11)

    def test_phase_terminal_members_present(self) -> None:
        self.assertIn(Phase.DONE, set(Phase))
        self.assertIn(Phase.DEFERRED, set(Phase))
        self.assertIn(Phase.ESCALATED, set(Phase))

    def test_phase_values_are_kebab_case_strings(self) -> None:
        # JSON-round-trippable identifiers.
        for member in Phase:
            self.assertIsInstance(member.value, str)
            self.assertEqual(member.value, member.value.lower())
            self.assertNotIn("_", member.value)


class StatusPhaseMappingTests(unittest.TestCase):
    """Bidirectional map between sprint-status string and Phase."""

    def test_forward_map_covers_canonical_statuses(self) -> None:
        # The canonical sprint-status vocabulary we support.
        for status in ("done", "in-progress", "not_started", "review-running"):
            self.assertIn(status, SPRINT_STATUS_TO_PHASE)

    def test_forward_map_done_is_phase_done(self) -> None:
        self.assertEqual(SPRINT_STATUS_TO_PHASE["done"], Phase.DONE)

    def test_inverse_map_round_trips_for_phase(self) -> None:
        # Every phase must produce a sprint-status string.
        for phase in Phase:
            self.assertIn(phase, PHASE_TO_SPRINT_STATUS)
            self.assertIsInstance(PHASE_TO_SPRINT_STATUS[phase], str)

    def test_phase_for_sprint_status_unknown_returns_none(self) -> None:
        self.assertIsNone(phase_for_sprint_status("totally-bogus"))

    def test_phase_for_sprint_status_returns_phase_for_known(self) -> None:
        self.assertEqual(phase_for_sprint_status("done"), Phase.DONE)

    def test_sprint_status_for_phase_accepts_string(self) -> None:
        # Callers loading phase from JSON may pass a raw string.
        self.assertEqual(sprint_status_for_phase("done"), "done")

    def test_sprint_status_for_phase_unknown_raises(self) -> None:
        with self.assertRaises(DualStoreError):
            sprint_status_for_phase("totally-bogus")


class ConsistencyTests(unittest.TestCase):
    """`is_consistent` is the dual-store invariant — both stores agree."""

    def test_done_done_is_consistent(self) -> None:
        self.assertTrue(is_consistent("done", Phase.DONE))

    def test_done_with_dev_running_is_inconsistent(self) -> None:
        self.assertFalse(is_consistent("done", Phase.DEV_RUNNING))

    def test_unknown_sprint_status_is_inconsistent(self) -> None:
        # Fail-closed when a store is unparseable.
        self.assertFalse(is_consistent("not-a-real-status", Phase.DONE))

    def test_unknown_phase_string_is_inconsistent(self) -> None:
        self.assertFalse(is_consistent("done", "not-a-real-phase"))


class PhaseStoreIOTests(unittest.TestCase):
    """write_phase / read_phase_store — atomic, idempotent file I/O."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        # Materialize the sprint-status.yaml sibling tree the path helpers expect.
        sprint_dir = Path(phase_store_path(self.root)).parent
        sprint_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_phase_store_path_under_project_root(self) -> None:
        store = phase_store_path(self.root)
        self.assertTrue(str(store).startswith(self.root))

    def test_write_then_read_round_trip(self) -> None:
        write_phase(self.root, "1.1", Phase.DONE)
        loaded = read_phase_store(self.root)
        self.assertEqual(loaded.get("1.1"), Phase.DONE)

    def test_write_phase_is_idempotent_for_same_value(self) -> None:
        write_phase(self.root, "1.1", Phase.DONE)
        before = Path(phase_store_path(self.root)).read_text(encoding="utf-8")
        write_phase(self.root, "1.1", Phase.DONE)
        after = Path(phase_store_path(self.root)).read_text(encoding="utf-8")
        self.assertEqual(before, after)

    def test_write_phase_updates_existing_entry(self) -> None:
        write_phase(self.root, "1.1", Phase.DEV_RUNNING)
        write_phase(self.root, "1.1", Phase.DONE)
        loaded = read_phase_store(self.root)
        self.assertEqual(loaded.get("1.1"), Phase.DONE)
        # No duplicate entry.
        text = Path(phase_store_path(self.root)).read_text(encoding="utf-8")
        self.assertEqual(text.count("1.1:"), 1)

    def test_read_phase_store_missing_file_returns_empty(self) -> None:
        loaded = read_phase_store(self.root)
        self.assertEqual(loaded, {})

    def test_read_phase_store_skips_blank_and_comments(self) -> None:
        store = phase_store_path(self.root)
        Path(store).write_text(
            "# comment line\n\n1.1: done\n# another\n2.1: dev-running\n",
            encoding="utf-8",
        )
        loaded = read_phase_store(self.root)
        self.assertEqual(loaded, {"1.1": Phase.DONE, "2.1": Phase.DEV_RUNNING})

    def test_read_phase_store_unknown_phase_raises(self) -> None:
        store = phase_store_path(self.root)
        Path(store).write_text("1.1: bogus-phase\n", encoding="utf-8")
        with self.assertRaises(DualStoreError):
            read_phase_store(self.root)

    def test_write_phase_rejects_unknown_phase_string(self) -> None:
        with self.assertRaises(DualStoreError):
            write_phase(self.root, "1.1", "bogus-phase")


class ComputeDualStateTests(unittest.TestCase):
    """compute_dual_state reads both stores and returns a paired snapshot."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        # Materialize sprint-status.yaml.
        from story_automator.core.story_keys import sprint_status_file
        sprint_path = Path(sprint_status_file(self.root))
        sprint_path.parent.mkdir(parents=True, exist_ok=True)
        sprint_path.write_text(SPRINT_STATUS_FIXTURE, encoding="utf-8")
        # And the phase store sibling.
        Path(phase_store_path(self.root)).parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_compute_dual_state_done_story_returns_phase(self) -> None:
        write_phase(self.root, "1.1", Phase.DONE)
        state = compute_dual_state(self.root, "1.1")
        self.assertIsInstance(state, DualStoreState)
        self.assertEqual(state.sprint_status, "done")
        self.assertEqual(state.phase, Phase.DONE)
        self.assertTrue(state.consistent)

    def test_compute_dual_state_missing_phase_falls_back_to_sprint(self) -> None:
        # When the phase store has no entry, derive Phase from sprint-status.
        state = compute_dual_state(self.root, "1.1")
        self.assertEqual(state.sprint_status, "done")
        self.assertEqual(state.phase, Phase.DONE)
        self.assertTrue(state.consistent)
        self.assertTrue(state.phase_derived)

    def test_compute_dual_state_inconsistent_flagged(self) -> None:
        # sprint-status says done, phase store says dev-running.
        write_phase(self.root, "1.1", Phase.DEV_RUNNING)
        state = compute_dual_state(self.root, "1.1")
        self.assertEqual(state.sprint_status, "done")
        self.assertEqual(state.phase, Phase.DEV_RUNNING)
        self.assertFalse(state.consistent)
        self.assertFalse(state.phase_derived)

    def test_compute_dual_state_unknown_story_returns_not_found(self) -> None:
        state = compute_dual_state(self.root, "9.9")
        self.assertFalse(state.found)


class ValidateDualStoreTests(unittest.TestCase):
    """validate_dual_store walks every story and reports mismatches."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        from story_automator.core.story_keys import sprint_status_file
        sprint_path = Path(sprint_status_file(self.root))
        sprint_path.parent.mkdir(parents=True, exist_ok=True)
        sprint_path.write_text(SPRINT_STATUS_FIXTURE, encoding="utf-8")
        Path(phase_store_path(self.root)).parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_validate_empty_phase_store_returns_no_inconsistencies(self) -> None:
        # No phase store entries — nothing to check against.
        results = validate_dual_store(self.root)
        self.assertEqual(results, [])

    def test_validate_matching_pair_returns_no_inconsistencies(self) -> None:
        write_phase(self.root, "1-1-host-feasibility-probe", Phase.DONE)
        results = validate_dual_store(self.root)
        self.assertEqual(results, [])

    def test_validate_reports_mismatch(self) -> None:
        write_phase(self.root, "1-1-host-feasibility-probe", Phase.DEV_RUNNING)
        results = validate_dual_store(self.root)
        self.assertEqual(len(results), 1)
        finding = results[0]
        self.assertIsInstance(finding, Inconsistency)
        self.assertEqual(finding.story_key, "1-1-host-feasibility-probe")
        self.assertEqual(finding.sprint_status, "done")
        self.assertEqual(finding.phase, Phase.DEV_RUNNING)

    def test_validate_reports_orphan_phase_entry(self) -> None:
        # Phase entry without a sprint-status row → still flagged.
        write_phase(self.root, "9-9-orphan", Phase.DEV_RUNNING)
        results = validate_dual_store(self.root)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].sprint_status, "")
        self.assertEqual(results[0].phase, Phase.DEV_RUNNING)


class InconsistencyExceptionTests(unittest.TestCase):
    def test_inconsistency_error_carries_findings(self) -> None:
        findings = [Inconsistency("1.1", "done", Phase.DEV_RUNNING)]
        err = DualStoreInconsistencyError("mismatch", findings)
        self.assertEqual(err.findings, findings)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
