from __future__ import annotations

import io
import json
import shutil
import sys  # noqa: F401
import tempfile
import threading  # noqa: F401
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from story_automator.commands.state import cmd_build_state_doc

REPO_ROOT = Path(__file__).resolve().parents[1]


class _PatchEnv:
    def __init__(self, project_root: Path) -> None:
        self.project_root = str(project_root)
        self.previous: str | None = None

    def __enter__(self) -> None:
        import os

        self.previous = os.environ.get("PROJECT_ROOT")
        os.environ["PROJECT_ROOT"] = self.project_root

    def __exit__(self, exc_type, exc, tb) -> None:
        import os

        if self.previous is None:
            os.environ.pop("PROJECT_ROOT", None)
        else:
            os.environ["PROJECT_ROOT"] = self.previous


def _install_bundle(project_root: Path) -> None:
    source_skill = REPO_ROOT / "skills" / "bmad-story-automator"
    source_review = REPO_ROOT / "skills" / "bmad-story-automator-review"
    target_root = project_root / ".claude" / "skills"
    target_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_skill, target_root / "bmad-story-automator")
    shutil.copytree(source_review, target_root / "bmad-story-automator-review")


def _install_required_skills(project_root: Path) -> None:
    for name in (
        "bmad-create-story",
        "bmad-dev-story",
        "bmad-retrospective",
        "bmad-qa-generate-e2e-tests",
    ):
        skill_dir = project_root / ".claude" / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
        (skill_dir / "workflow.md").write_text(f"# {name}\n", encoding="utf-8")
    (
        project_root / ".claude" / "skills" / "bmad-create-story" / "discover-inputs.md"
    ).write_text("# discover\n", encoding="utf-8")
    (
        project_root / ".claude" / "skills" / "bmad-create-story" / "checklist.md"
    ).write_text("# checklist\n", encoding="utf-8")
    (
        project_root / ".claude" / "skills" / "bmad-create-story" / "template.md"
    ).write_text("# template\n", encoding="utf-8")
    (
        project_root / ".claude" / "skills" / "bmad-dev-story" / "checklist.md"
    ).write_text("# checklist\n", encoding="utf-8")
    (
        project_root
        / ".claude"
        / "skills"
        / "bmad-qa-generate-e2e-tests"
        / "checklist.md"
    ).write_text("# checklist\n", encoding="utf-8")


def _config() -> dict[str, object]:
    return {
        "epic": "1",
        "epicName": "Epic 1",
        "storyRange": ["1.1"],
        "status": "READY",
        "aiCommand": "claude",
    }


class LegacyMarkerCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project_root = Path(self._tmp.name)
        self.output_dir = self.project_root / "_bmad-output" / "story-automator"
        _install_bundle(self.project_root)
        _install_required_skills(self.project_root)
        self.template = (
            self.project_root
            / ".claude"
            / "skills"
            / "bmad-story-automator"
            / "templates"
            / "state-document.md"
        )

    def test_build_state_doc_unlinks_legacy_marker_at_startup(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        legacy = self.output_dir / ".state-build.marker"
        legacy.write_text("stale legacy sentinel", encoding="utf-8")

        stdout = io.StringIO()
        with _PatchEnv(self.project_root), redirect_stdout(stdout):
            code = cmd_build_state_doc(
                [
                    "--template",
                    str(self.template),
                    "--output-folder",
                    str(self.output_dir),
                    "--config-json",
                    json.dumps(_config()),
                ]
            )

        self.assertEqual(code, 0)
        self.assertFalse(legacy.exists(), "legacy marker must be removed")

    def test_build_state_doc_succeeds_without_legacy_marker(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # No legacy marker present — unlink must be missing_ok.
        stdout = io.StringIO()
        with _PatchEnv(self.project_root), redirect_stdout(stdout):
            code = cmd_build_state_doc(
                [
                    "--template",
                    str(self.template),
                    "--output-folder",
                    str(self.output_dir),
                    "--config-json",
                    json.dumps(_config()),
                ]
            )

        self.assertEqual(code, 0)


class AtomicWriteIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project_root = Path(self._tmp.name)
        self.output_dir = self.project_root / "_bmad-output" / "story-automator"
        _install_bundle(self.project_root)
        _install_required_skills(self.project_root)
        self.template = (
            self.project_root
            / ".claude"
            / "skills"
            / "bmad-story-automator"
            / "templates"
            / "state-document.md"
        )

    def test_cmd_build_state_doc_routes_through_write_atomic_text(self) -> None:
        """REQ-10: state.py must route every previous ``write_text`` site
        through ``write_atomic_text``. We assert this by patching
        ``story_automator.commands.state.write_atomic_text`` and checking it
        was invoked with the rendered state-doc path and the rendered text.
        """
        from unittest.mock import patch

        recorded: list[tuple[Path, str]] = []

        def _spy(path: Path, data: str, *, encoding: str = "utf-8") -> None:
            recorded.append((Path(path), data))
            Path(path).write_bytes(data.encode(encoding))

        stdout = io.StringIO()
        with (
            _PatchEnv(self.project_root),
            redirect_stdout(stdout),
            patch(
                "story_automator.commands.state.write_atomic_text", side_effect=_spy
            ) as spy,
        ):
            code = cmd_build_state_doc(
                [
                    "--template",
                    str(self.template),
                    "--output-folder",
                    str(self.output_dir),
                    "--config-json",
                    json.dumps(_config()),
                ]
            )

        self.assertEqual(code, 0)
        # write_atomic_text is the only allowed write path for the rendered
        # state document. Multiple calls are permissible (acquire_run_lock
        # writes its identity payload through write_atomic_text too); we just
        # require that the state-doc target itself was written through it.
        self.assertTrue(spy.called, "write_atomic_text must be invoked")
        targets = {str(call_path) for call_path, _ in recorded}
        payload = json.loads(stdout.getvalue())
        self.assertIn(payload["path"], targets)


class RunLockGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project_root = Path(self._tmp.name)
        self.output_dir = self.project_root / "_bmad-output" / "story-automator"
        _install_bundle(self.project_root)
        _install_required_skills(self.project_root)
        self.template = (
            self.project_root
            / ".claude"
            / "skills"
            / "bmad-story-automator"
            / "templates"
            / "state-document.md"
        )

    def test_cmd_build_state_doc_acquires_run_lock(self) -> None:
        """REQ-11: the run-lock API must guard the write."""
        from unittest.mock import patch
        from story_automator.core.atomic_io import acquire_run_lock as _real

        captured: list[Path] = []

        def _spy(lock_path: Path, *, run_id: str, timeout: float = 0.0):
            captured.append(Path(lock_path))
            return _real(lock_path, run_id=run_id, timeout=timeout)

        stdout = io.StringIO()
        with (
            _PatchEnv(self.project_root),
            redirect_stdout(stdout),
            patch("story_automator.commands.state.acquire_run_lock", side_effect=_spy),
        ):
            code = cmd_build_state_doc(
                [
                    "--template",
                    str(self.template),
                    "--output-folder",
                    str(self.output_dir),
                    "--config-json",
                    json.dumps(_config()),
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(len(captured), 1, "exactly one run-lock acquisition expected")
        self.assertEqual(captured[0].name, ".state-build.lock")
        self.assertEqual(captured[0].parent, self.output_dir.resolve())

    def test_cmd_build_state_doc_releases_run_lock_after_success(self) -> None:
        """The lock-identity payload at lock_path must be deleted on release;
        the sibling FileLock sentinel (``.state-build.lock.lock``) may remain
        — filelock owns its lifecycle.
        """
        stdout = io.StringIO()
        with _PatchEnv(self.project_root), redirect_stdout(stdout):
            code = cmd_build_state_doc(
                [
                    "--template",
                    str(self.template),
                    "--output-folder",
                    str(self.output_dir),
                    "--config-json",
                    json.dumps(_config()),
                ]
            )

        self.assertEqual(code, 0)
        lock_payload = self.output_dir / ".state-build.lock"
        self.assertFalse(
            lock_payload.exists(),
            "RunLockHandle.release must unlink the identity payload",
        )


class RunLockContentionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project_root = Path(self._tmp.name)
        self.output_dir = self.project_root / "_bmad-output" / "story-automator"
        _install_bundle(self.project_root)
        _install_required_skills(self.project_root)
        self.template = (
            self.project_root
            / ".claude"
            / "skills"
            / "bmad-story-automator"
            / "templates"
            / "state-document.md"
        )

    def test_returns_run_lock_busy_envelope_when_lock_is_held(self) -> None:
        """If a sibling holder already owns the .state-build.lock, the next
        cmd_build_state_doc invocation must surface
        ``{"ok": False, "error": "run_lock_busy"}`` and exit 1, NOT crash.
        """
        from story_automator.core.atomic_io import acquire_run_lock

        self.output_dir.mkdir(parents=True, exist_ok=True)
        holder_lock_path = self.output_dir / ".state-build.lock"

        # Hold the lock from this thread. timeout=0.0 means no waiting; the
        # subsequent cmd_build_state_doc call must hit RunLockBusy
        # immediately.
        with acquire_run_lock(holder_lock_path, run_id="holder", timeout=0.0):
            stdout = io.StringIO()
            with _PatchEnv(self.project_root), redirect_stdout(stdout):
                code = cmd_build_state_doc(
                    [
                        "--template",
                        str(self.template),
                        "--output-folder",
                        str(self.output_dir),
                        "--config-json",
                        json.dumps(_config()),
                    ]
                )

        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload, {"ok": False, "error": "run_lock_busy"})


class CleanupBeforeLockOrderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project_root = Path(self._tmp.name)
        self.output_dir = self.project_root / "_bmad-output" / "story-automator"
        _install_bundle(self.project_root)
        _install_required_skills(self.project_root)
        self.template = (
            self.project_root
            / ".claude"
            / "skills"
            / "bmad-story-automator"
            / "templates"
            / "state-document.md"
        )

    def test_legacy_marker_cleanup_runs_before_lock_acquisition(self) -> None:
        """REQ-11 ordering claim: legacy-marker cleanup happens at startup,
        BEFORE acquire_run_lock is called. Verified by patching
        ``acquire_run_lock`` to raise ``RunLockBusy`` immediately and
        asserting the legacy file was already removed — which can only be
        true if cleanup ran before the lock attempt.
        """
        from unittest.mock import patch

        from story_automator.core.atomic_io import RunLockBusy

        self.output_dir.mkdir(parents=True, exist_ok=True)
        legacy = self.output_dir / ".state-build.marker"
        legacy.write_text("garbage", encoding="utf-8")

        def _busy(*args, **kwargs):
            raise RunLockBusy("simulated contention")

        stdout = io.StringIO()
        with (
            _PatchEnv(self.project_root),
            redirect_stdout(stdout),
            patch("story_automator.commands.state.acquire_run_lock", side_effect=_busy),
        ):
            code = cmd_build_state_doc(
                [
                    "--template",
                    str(self.template),
                    "--output-folder",
                    str(self.output_dir),
                    "--config-json",
                    json.dumps(_config()),
                ]
            )

        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload, {"ok": False, "error": "run_lock_busy"})
        self.assertFalse(
            legacy.exists(),
            "cleanup must happen BEFORE lock acquisition — RunLockBusy on "
            "the first lock attempt must not skip the cleanup step",
        )


if __name__ == "__main__":
    unittest.main()
