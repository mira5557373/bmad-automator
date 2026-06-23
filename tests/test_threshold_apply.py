"""Tests for ``core/innovation/threshold_apply.py`` (spec §7.3).

Each test uses a tmpdir-isolated project root AND a synthesized
target module dropped under ``sys.path`` so the production
``story_automator.core.gate_rules`` is NEVER mutated. The synthesized
module is rebuilt fresh per test and unloaded after.
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from filelock import Timeout

from story_automator.core.atomic_io import write_atomic_text
from story_automator.core.common import compact_json
from story_automator.core.innovation import threshold_apply
from story_automator.core.innovation.threshold_apply import (
    MAX_PROPOSAL_AGE_HOURS,
    AppliedThresholdRecord,
    ThresholdApplyError,
    apply_threshold_proposal,
)
from story_automator.core.innovation.threshold_decisions import (
    calibration_dir,
    decisions_path,
    load_decisions,
)


_FRESH_ISO = "2026-06-23T17:42:11Z"
_OLD_ISO = "2020-01-01T00:00:00Z"
_DEFAULT_SLUG = "deadbeef"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_FAKE_MODULE_TEMPLATE = '''"""Synthesized fake gate_rules module for tests."""
from __future__ import annotations

PRIORITY_THRESHOLDS: dict[str, tuple[int, int]] = {{
    "P0": (100, 100),
    "P1": ({p1_required}, 90),  # required_pct, fail_floor
    "P2": (85, 80),
    "P3": (70, 0),
}}

MINOR_MAX = {minor_max}
'''


def _build_fake_module(
    tmp_path: Path,
    *,
    module_name: str,
    p1_required: int = 95,
    minor_max: int = 10,
    bom: bool = False,
    leading_comment: str | None = None,
) -> Path:
    """Drop a synthetic ``gate_rules``-shaped module under ``tmp_path``."""
    pkg = tmp_path / module_name
    pkg.mkdir(parents=True, exist_ok=True)
    init = pkg / "__init__.py"
    init.write_text("", encoding="utf-8")
    src = _FAKE_MODULE_TEMPLATE.format(p1_required=p1_required, minor_max=minor_max)
    if leading_comment is not None:
        src = f"# {leading_comment}\n" + src
    src_bytes = src.encode("utf-8")
    if bom:
        src_bytes = b"\xef\xbb\xbf" + src_bytes
    target_path = pkg / "gate_rules.py"
    target_path.write_bytes(src_bytes)
    return target_path


def _register_fake_module(tmp_path: Path, module_name: str, target_path: Path) -> str:
    """Make ``module_name.gate_rules`` importable via ``find_spec``."""
    if str(tmp_path) not in sys.path:
        sys.path.insert(0, str(tmp_path))
    qual = f"{module_name}.gate_rules"
    # Drop any cached spec so find_spec rediscovers the path.
    sys.modules.pop(qual, None)
    sys.modules.pop(module_name, None)
    importlib.invalidate_caches()
    return qual


def _make_proposal(
    *,
    project_root: Path,
    proposal_id: str,
    target_module: str,
    target_symbol: str = "PRIORITY_THRESHOLDS",
    selector: dict[str, Any] | None = None,
    current_value: int | float = 95,
    proposed_value: int | float = 92,
    confirm_slug: str = _DEFAULT_SLUG,
    created_at_iso: str = _FRESH_ISO,
    ttl_hours: int = MAX_PROPOSAL_AGE_HOURS,
) -> Path:
    """Write a minimal valid proposal JSON to disk; return its path."""
    if selector is None:
        selector = {"kind": "dict_tuple_element", "key": "P1", "index": 0}
    payload = {
        "schema_version": 1,
        "proposal_id": proposal_id,
        "target_module": target_module,
        "target_symbol": target_symbol,
        "target_category": "correctness",
        "target_file_hint": "",
        "selector": selector,
        "current_value": current_value,
        "proposed_value": proposed_value,
        "delta": proposed_value - current_value,
        "rationale": "synthetic test rationale",
        "evidence_window": ["gate-001", "gate-002", "gate-003", "gate-004", "gate-005"],
        "created_at_iso": created_at_iso,
        "confirm_slug": confirm_slug,
        "proposer_config": {
            "min_evidence_window": 5,
            "target_pass_rate_band": [0.80, 0.95],
            "max_delta_pct": 5,
            "consecutive_runs": 3,
            "enable_drift_band_proposals": False,
            "ttl_hours": ttl_hours,
        },
    }
    proposals = calibration_dir(project_root, create=True) / "proposals"
    proposals.mkdir(parents=True, exist_ok=True)
    target = proposals / f"{proposal_id}.json"
    target.write_text(compact_json(payload), encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# Test base class
# ---------------------------------------------------------------------------


class _ApplyTestBase(unittest.TestCase):
    """Shared tmp-project + fake-module setup."""

    counter = 0

    def setUp(self) -> None:
        type(self).counter += 1
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.project_root = self.tmp_path / "project"
        self.project_root.mkdir(parents=True, exist_ok=True)
        self.module_root = self.tmp_path / "modules"
        self.module_root.mkdir(parents=True, exist_ok=True)
        self.module_pkg_name = f"_c5_fake_pkg_{os.getpid()}_{type(self).counter}"
        self.target_path = _build_fake_module(self.module_root, module_name=self.module_pkg_name)
        self.target_module = _register_fake_module(
            self.module_root, self.module_pkg_name, self.target_path
        )

    def tearDown(self) -> None:
        with contextlib.suppress(ValueError):
            sys.path.remove(str(self.module_root))
        sys.modules.pop(self.target_module, None)
        sys.modules.pop(self.module_pkg_name, None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class ProposalNotFoundTests(_ApplyTestBase):
    def test_missing_proposal_raises_proposal_not_found(self) -> None:
        with self.assertRaises(ThresholdApplyError) as cm:
            apply_threshold_proposal(
                self.project_root,
                "0a1b2c3d4e5f6789",
                confirm=_DEFAULT_SLUG,
                operator_id="local",
            )
        self.assertEqual(cm.exception.code, "PROPOSAL_NOT_FOUND")
        # No source mutation; target file byte-identical.
        self.assertIn(b"(95, 90)", self.target_path.read_bytes())
        # No decisions appended.
        self.assertFalse(decisions_path(self.project_root).exists())


class ConfirmMismatchTests(_ApplyTestBase):
    def test_bad_length_confirm_raises_with_length_hint_no_decision(self) -> None:
        _make_proposal(
            project_root=self.project_root,
            proposal_id="aaaa1111bbbb2222",
            target_module=self.target_module,
        )
        with self.assertRaises(ThresholdApplyError) as cm:
            apply_threshold_proposal(
                self.project_root,
                "aaaa1111bbbb2222",
                confirm="short",
                operator_id="local",
            )
        self.assertEqual(cm.exception.code, "CONFIRM_MISMATCH")
        self.assertIn("8 hex chars", cm.exception.hint)
        # Length check is BEFORE load → no confirm_failed decision.
        self.assertFalse(decisions_path(self.project_root).exists())

    def test_wrong_slug_correct_length_appends_confirm_failed(self) -> None:
        _make_proposal(
            project_root=self.project_root,
            proposal_id="bbbb2222cccc3333",
            target_module=self.target_module,
            confirm_slug="deadbeef",
        )
        with self.assertRaises(ThresholdApplyError) as cm:
            apply_threshold_proposal(
                self.project_root,
                "bbbb2222cccc3333",
                confirm="cafef00d",
                operator_id="local",
            )
        self.assertEqual(cm.exception.code, "CONFIRM_MISMATCH")
        self.assertEqual(cm.exception.hint, "confirm slug does not match")
        # Confirm_failed decision appended.
        decisions = load_decisions(self.project_root, proposal_id="bbbb2222cccc3333")
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].action, "confirm_failed")


class ProposalExpiredTests(_ApplyTestBase):
    def test_ttl_exceeded_raises_proposal_expired(self) -> None:
        _make_proposal(
            project_root=self.project_root,
            proposal_id="cccc3333dddd4444",
            target_module=self.target_module,
            created_at_iso=_OLD_ISO,
        )
        with self.assertRaises(ThresholdApplyError) as cm:
            apply_threshold_proposal(
                self.project_root,
                "cccc3333dddd4444",
                confirm=_DEFAULT_SLUG,
                operator_id="local",
            )
        self.assertEqual(cm.exception.code, "PROPOSAL_EXPIRED")


class StaleProposalTests(_ApplyTestBase):
    def test_newer_proposal_supersedes_stale(self) -> None:
        # Older proposal first.
        _make_proposal(
            project_root=self.project_root,
            proposal_id="dddd4444eeee5555",
            target_module=self.target_module,
            created_at_iso="2026-06-23T10:00:00Z",
            confirm_slug="11111111",
        )
        # Newer proposal on same selector.
        _make_proposal(
            project_root=self.project_root,
            proposal_id="eeee5555ffff6666",
            target_module=self.target_module,
            created_at_iso="2026-06-23T12:00:00Z",
            confirm_slug="22222222",
        )
        with self.assertRaises(ThresholdApplyError) as cm:
            apply_threshold_proposal(
                self.project_root,
                "dddd4444eeee5555",
                confirm="11111111",
                operator_id="local",
            )
        self.assertEqual(cm.exception.code, "STALE_PROPOSAL")


class ModuleNotResolvableTests(_ApplyTestBase):
    def test_missing_module_raises(self) -> None:
        _make_proposal(
            project_root=self.project_root,
            proposal_id="ffff6666aaaa7777",
            target_module="story_automator.does_not_exist_anywhere_at_all",
        )
        with self.assertRaises(ThresholdApplyError) as cm:
            apply_threshold_proposal(
                self.project_root,
                "ffff6666aaaa7777",
                confirm=_DEFAULT_SLUG,
                operator_id="local",
            )
        self.assertEqual(cm.exception.code, "MODULE_NOT_RESOLVABLE")

    def test_find_spec_returns_none_raises(self) -> None:
        _make_proposal(
            project_root=self.project_root,
            proposal_id="ffff6666aaaa7778",
            target_module=self.target_module,
        )
        with mock.patch.object(importlib.util, "find_spec", return_value=None):
            with self.assertRaises(ThresholdApplyError) as cm:
                apply_threshold_proposal(
                    self.project_root,
                    "ffff6666aaaa7778",
                    confirm=_DEFAULT_SLUG,
                    operator_id="local",
                )
        self.assertEqual(cm.exception.code, "MODULE_NOT_RESOLVABLE")


class LiveValueDriftedTests(_ApplyTestBase):
    def test_source_edited_after_propose_raises(self) -> None:
        # Source currently has P1.required_pct = 95.
        _make_proposal(
            project_root=self.project_root,
            proposal_id="aaaa8888bbbb9999",
            target_module=self.target_module,
            current_value=80,  # claims live==80 but live is 95
            proposed_value=85,
        )
        with self.assertRaises(ThresholdApplyError) as cm:
            apply_threshold_proposal(
                self.project_root,
                "aaaa8888bbbb9999",
                confirm=_DEFAULT_SLUG,
                operator_id="local",
            )
        self.assertEqual(cm.exception.code, "LIVE_VALUE_DRIFTED")
        # Target source byte-identical (no splice happened).
        self.assertIn(b"(95, 90)", self.target_path.read_bytes())


class TypeMismatchTests(_ApplyTestBase):
    def test_float_proposed_int_target_raises(self) -> None:
        # Hand-craft a proposal whose current_value is 95.0 (float) but
        # live source has 95 (int). The dataclass invariant
        # would normally reject this; bypass it by writing JSON directly.
        proposal_path = _make_proposal(
            project_root=self.project_root,
            proposal_id="aaaaccccbbbbdddd",
            target_module=self.target_module,
        )
        payload = json.loads(proposal_path.read_text("utf-8"))
        payload["current_value"] = 95.0
        payload["proposed_value"] = 92.0
        payload["delta"] = -3.0
        proposal_path.write_text(compact_json(payload), encoding="utf-8")
        with self.assertRaises(ThresholdApplyError) as cm:
            apply_threshold_proposal(
                self.project_root,
                "aaaaccccbbbbdddd",
                confirm=_DEFAULT_SLUG,
                operator_id="local",
            )
        self.assertEqual(cm.exception.code, "TYPE_MISMATCH")


class NonLiteralTargetTests(_ApplyTestBase):
    def test_operator_wrote_expression_not_constant(self) -> None:
        # Replace target with `MINOR_MAX = 1/10` (BinOp not Constant).
        path = self.module_root / self.module_pkg_name / "gate_rules.py"
        text = path.read_text("utf-8")
        text = text.replace("MINOR_MAX = 10", "MINOR_MAX = 1 / 10")
        path.write_text(text, encoding="utf-8")
        # Bust any cached module.
        sys.modules.pop(self.target_module, None)
        importlib.invalidate_caches()

        _make_proposal(
            project_root=self.project_root,
            proposal_id="aaaaeeeeccccffff",
            target_module=self.target_module,
            target_symbol="MINOR_MAX",
            selector={"kind": "name", "name": "MINOR_MAX"},
            current_value=10,
            proposed_value=11,
        )
        with self.assertRaises(ThresholdApplyError) as cm:
            apply_threshold_proposal(
                self.project_root,
                "aaaaeeeeccccffff",
                confirm=_DEFAULT_SLUG,
                operator_id="local",
            )
        self.assertEqual(cm.exception.code, "NON_LITERAL_TARGET")


class UnsupportedSelectorKindTests(_ApplyTestBase):
    def test_unknown_kind_raises_before_io(self) -> None:
        _make_proposal(
            project_root=self.project_root,
            proposal_id="aabbccddeeff0011",
            target_module=self.target_module,
            selector={"kind": "foo"},
        )
        with self.assertRaises(ThresholdApplyError) as cm:
            apply_threshold_proposal(
                self.project_root,
                "aabbccddeeff0011",
                confirm=_DEFAULT_SLUG,
                operator_id="local",
            )
        self.assertEqual(cm.exception.code, "UNSUPPORTED_SELECTOR_KIND")
        # No source mutation.
        self.assertIn(b"(95, 90)", self.target_path.read_bytes())


class HappyPathDictTupleTests(_ApplyTestBase):
    def test_byte_diff_equals_leaf_only(self) -> None:
        before_bytes = self.target_path.read_bytes()
        _make_proposal(
            project_root=self.project_root,
            proposal_id="11112222333344ff",
            target_module=self.target_module,
            current_value=95,
            proposed_value=92,
        )
        record = apply_threshold_proposal(
            self.project_root,
            "11112222333344ff",
            confirm=_DEFAULT_SLUG,
            operator_id="local",
        )
        self.assertIsInstance(record, AppliedThresholdRecord)
        after_bytes = self.target_path.read_bytes()
        # Annotation and trailing comment preserved byte-identically.
        self.assertIn(b"dict[str, tuple[int, int]]", after_bytes)
        self.assertIn(b"# required_pct, fail_floor", after_bytes)
        # The single number changed.
        self.assertIn(b"(92, 90)", after_bytes)
        self.assertNotIn(b"(95, 90)", after_bytes)
        # Length difference should be 1 byte (95 → 92 == same width).
        self.assertEqual(len(after_bytes), len(before_bytes))


class HappyPathNameTests(_ApplyTestBase):
    def test_name_selector_only_changes_value(self) -> None:
        _make_proposal(
            project_root=self.project_root,
            proposal_id="22223333444455ff",
            target_module=self.target_module,
            target_symbol="MINOR_MAX",
            selector={"kind": "name", "name": "MINOR_MAX"},
            current_value=10,
            proposed_value=11,
        )
        apply_threshold_proposal(
            self.project_root,
            "22223333444455ff",
            confirm=_DEFAULT_SLUG,
            operator_id="local",
        )
        text = self.target_path.read_bytes().decode("utf-8")
        self.assertIn("MINOR_MAX = 11", text)
        self.assertNotIn("MINOR_MAX = 10", text)


class BomPreservedTests(_ApplyTestBase):
    def setUp(self) -> None:
        super().setUp()
        # Rebuild target with a BOM.
        target = self.module_root / self.module_pkg_name / "gate_rules.py"
        body = target.read_bytes()
        target.write_bytes(b"\xef\xbb\xbf" + body)

    def test_bom_preserved_after_splice(self) -> None:
        _make_proposal(
            project_root=self.project_root,
            proposal_id="bbbbcccdddd11111",
            target_module=self.target_module,
            current_value=95,
            proposed_value=92,
        )
        apply_threshold_proposal(
            self.project_root,
            "bbbbcccdddd11111",
            confirm=_DEFAULT_SLUG,
            operator_id="local",
        )
        result = self.target_path.read_bytes()
        self.assertTrue(result.startswith(b"\xef\xbb\xbf"), "BOM must be preserved")
        self.assertIn(b"(92, 90)", result)


class NonAsciiContentTests(_ApplyTestBase):
    def setUp(self) -> None:
        super().setUp()
        target = self.module_root / self.module_pkg_name / "gate_rules.py"
        body = target.read_text("utf-8")
        # Inject a non-ASCII Cyrillic comment ABOVE the assignment so the
        # byte offset of the target's line shifts versus a character
        # offset. The col_offset MUST be interpreted as a UTF-8 byte
        # offset for the splice to land correctly.
        body = "# Привет non-ASCII\n" + body
        target.write_text(body, encoding="utf-8")

    def test_non_ascii_elsewhere_does_not_misalign_splice(self) -> None:
        _make_proposal(
            project_root=self.project_root,
            proposal_id="cccdddd111122223",
            target_module=self.target_module,
            current_value=95,
            proposed_value=92,
        )
        apply_threshold_proposal(
            self.project_root,
            "cccdddd111122223",
            confirm=_DEFAULT_SLUG,
            operator_id="local",
        )
        text = self.target_path.read_text("utf-8")
        # Cyrillic comment preserved + target splice landed correctly.
        self.assertIn("Привет non-ASCII", text)
        self.assertIn("(92, 90)", text)
        self.assertNotIn("(95, 90)", text)


class BackupBeforeSpliceTests(_ApplyTestBase):
    def test_target_byte_identical_when_write_fails(self) -> None:
        before_bytes = self.target_path.read_bytes()
        _make_proposal(
            project_root=self.project_root,
            proposal_id="ddddeeee11112222",
            target_module=self.target_module,
        )

        original_write = write_atomic_text
        backup_path = (
            calibration_dir(self.project_root)
            / "proposals"
            / "ddddeeee11112222.applied"
            / "before.py.gate_rules"
        )

        def fake_write(path: Path, data: str, *, encoding: str = "utf-8") -> None:
            # Allow the backup to land, then fail every subsequent call
            # (the target write).
            if Path(path) == backup_path:
                return original_write(path, data, encoding=encoding)
            raise OSError("synthetic target-write failure")

        with mock.patch.object(threshold_apply, "write_atomic_text", fake_write):
            with self.assertRaises(OSError):
                apply_threshold_proposal(
                    self.project_root,
                    "ddddeeee11112222",
                    confirm=_DEFAULT_SLUG,
                    operator_id="local",
                )
        # Target byte-identical to pre-apply.
        self.assertEqual(self.target_path.read_bytes(), before_bytes)
        # Backup exists.
        self.assertTrue(backup_path.is_file())


class PostSpliceParseFailureRestoresBackupTests(_ApplyTestBase):
    def test_synthetic_corruption_restores_backup(self) -> None:
        before_bytes = self.target_path.read_bytes()
        _make_proposal(
            project_root=self.project_root,
            proposal_id="eeeeffff11112222",
            target_module=self.target_module,
        )

        # Patch _splice_bytes to emit invalid Python.
        with mock.patch.object(
            threshold_apply, "_splice_bytes", return_value=b"@@@ not python @@@"
        ):
            with self.assertRaises(ThresholdApplyError) as cm:
                apply_threshold_proposal(
                    self.project_root,
                    "eeeeffff11112222",
                    confirm=_DEFAULT_SLUG,
                    operator_id="local",
                )
        self.assertEqual(cm.exception.code, "APPLY_REWRITE_INVALID")
        # Target byte-identical (backup was restored).
        self.assertEqual(self.target_path.read_bytes(), before_bytes)


class RecordAndDecisionWrittenTests(_ApplyTestBase):
    def test_record_json_and_accept_decision_written(self) -> None:
        _make_proposal(
            project_root=self.project_root,
            proposal_id="ffffaaaa11112222",
            target_module=self.target_module,
        )
        record = apply_threshold_proposal(
            self.project_root,
            "ffffaaaa11112222",
            confirm=_DEFAULT_SLUG,
            operator_id="local",
        )
        record_json = (
            calibration_dir(self.project_root)
            / "proposals"
            / "ffffaaaa11112222.applied"
            / "record.json"
        )
        self.assertTrue(record_json.is_file())
        data = json.loads(record_json.read_text("utf-8"))
        self.assertEqual(data["proposal_id"], "ffffaaaa11112222")
        self.assertEqual(data["operator_id"], "local")
        self.assertEqual(data["target_file"], record.target_file)
        # Accept decision durably appended.
        decisions = load_decisions(self.project_root, proposal_id="ffffaaaa11112222")
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].action, "accept")


def _concurrent_apply_worker(args: tuple[str, str, str, str]) -> tuple[bool, str]:
    """Top-level worker for the concurrent-apply multiprocess test."""
    project_root_s, proposal_id, target_module, module_path = args
    import importlib as _il
    import sys as _sys

    if module_path not in _sys.path:
        _sys.path.insert(0, module_path)
    _il.invalidate_caches()
    from story_automator.core.innovation.threshold_apply import (
        ThresholdApplyError as _Err,
        apply_threshold_proposal as _apply,
    )

    try:
        _apply(project_root_s, proposal_id, confirm=_DEFAULT_SLUG, operator_id="local")
        return True, ""
    except _Err as exc:
        return False, exc.code
    except Exception as exc:  # pragma: no cover
        return False, f"OTHER:{type(exc).__name__}"


class ConcurrentApplyTests(_ApplyTestBase):
    def test_second_concurrent_apply_sees_live_value_drifted(self) -> None:
        # Use in-process threads for determinism; the second caller
        # serializes via the .calibration.lock and will encounter the
        # already-applied source (live==92), failing LIVE_VALUE_DRIFTED.
        _make_proposal(
            project_root=self.project_root,
            proposal_id="aaaa9999bbbb0000",
            target_module=self.target_module,
        )

        results: list[tuple[bool, str]] = []
        results_lock = threading.Lock()

        def worker() -> None:
            try:
                apply_threshold_proposal(
                    self.project_root,
                    "aaaa9999bbbb0000",
                    confirm=_DEFAULT_SLUG,
                    operator_id="local",
                )
                with results_lock:
                    results.append((True, ""))
            except ThresholdApplyError as exc:
                with results_lock:
                    results.append((False, exc.code))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30.0)

        successes = sum(1 for ok, _ in results if ok)
        codes = [code for ok, code in results if not ok]
        self.assertEqual(successes, 1, results)
        self.assertEqual(codes, ["LIVE_VALUE_DRIFTED"], results)


class ReapplyRaisesLiveValueDriftedTests(_ApplyTestBase):
    def test_reapply_after_first_apply_drifted(self) -> None:
        _make_proposal(
            project_root=self.project_root,
            proposal_id="bbbb0000ccccdddd",
            target_module=self.target_module,
        )
        apply_threshold_proposal(
            self.project_root,
            "bbbb0000ccccdddd",
            confirm=_DEFAULT_SLUG,
            operator_id="local",
        )
        with self.assertRaises(ThresholdApplyError) as cm:
            apply_threshold_proposal(
                self.project_root,
                "bbbb0000ccccdddd",
                confirm=_DEFAULT_SLUG,
                operator_id="local",
            )
        self.assertEqual(cm.exception.code, "LIVE_VALUE_DRIFTED")


class LockTimeoutTests(_ApplyTestBase):
    def test_lock_timeout_raises_lock_timeout(self) -> None:
        _make_proposal(
            project_root=self.project_root,
            proposal_id="ccccdddd0000aaaa",
            target_module=self.target_module,
        )

        class _FakeLock:
            def __init__(self, *_args: Any, **_kwargs: Any) -> None:
                pass

            def acquire(self, *, timeout: float) -> None:
                raise Timeout("synthetic lock contention")

            def release(self) -> None:
                pass

        with mock.patch.object(threshold_apply, "FileLock", _FakeLock):
            with self.assertRaises(ThresholdApplyError) as cm:
                apply_threshold_proposal(
                    self.project_root,
                    "ccccdddd0000aaaa",
                    confirm=_DEFAULT_SLUG,
                    operator_id="local",
                )
        self.assertEqual(cm.exception.code, "LOCK_TIMEOUT")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
