from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_automator.core.collector_checkout import (
    CollectorCheckoutError,
    _is_transient_lock_error,
    _sanitize_name_hint,
    cleanup_collector_checkout,
    collector_checkout,
    create_collector_checkout,
)


def _init_test_repo(path: Path) -> str:
    """Create a minimal git repo with one commit, return the SHA."""
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        capture_output=True,
        check=True,
    )
    marker = path / "marker.txt"
    marker.write_text("initial")
    subprocess.run(
        ["git", "-C", str(path), "add", "."],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        capture_output=True,
        check=True,
    )
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


class CreateCollectorCheckoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_dir = Path(tempfile.mkdtemp(prefix="sa-test-repo-"))
        self.sha = _init_test_repo(self.repo_dir)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo_dir), "worktree", "prune"],
            capture_output=True,
        )
        import shutil

        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def test_creates_checkout_at_sha(self) -> None:
        checkout = create_collector_checkout(self.repo_dir, self.sha)
        try:
            self.assertTrue(checkout.is_dir())
            result = subprocess.run(
                ["git", "-C", str(checkout), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
            )
            self.assertTrue(result.stdout.strip().startswith(self.sha[:7]))
        finally:
            cleanup_collector_checkout(checkout, self.repo_dir)

    def test_checkout_has_repo_contents(self) -> None:
        checkout = create_collector_checkout(self.repo_dir, self.sha)
        try:
            self.assertTrue((checkout / "marker.txt").exists())
            self.assertEqual((checkout / "marker.txt").read_text(), "initial")
        finally:
            cleanup_collector_checkout(checkout, self.repo_dir)

    def test_empty_sha_raises(self) -> None:
        with self.assertRaises(CollectorCheckoutError):
            create_collector_checkout(self.repo_dir, "")

    def test_invalid_sha_raises(self) -> None:
        with self.assertRaises(CollectorCheckoutError):
            create_collector_checkout(self.repo_dir, "deadbeef" * 5)

    def test_not_a_git_repo_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(CollectorCheckoutError):
                create_collector_checkout(td, "abc123")


class CleanupCollectorCheckoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_dir = Path(tempfile.mkdtemp(prefix="sa-test-repo-"))
        self.sha = _init_test_repo(self.repo_dir)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo_dir), "worktree", "prune"],
            capture_output=True,
        )
        import shutil

        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def test_removes_checkout_dir(self) -> None:
        checkout = create_collector_checkout(self.repo_dir, self.sha)
        self.assertTrue(checkout.is_dir())
        cleanup_collector_checkout(checkout, self.repo_dir)
        self.assertFalse(checkout.exists())

    def test_cleanup_nonexistent_no_error(self) -> None:
        cleanup_collector_checkout(Path("/nonexistent/path"), self.repo_dir)


class CollectorCheckoutContextManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_dir = Path(tempfile.mkdtemp(prefix="sa-test-repo-"))
        self.sha = _init_test_repo(self.repo_dir)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo_dir), "worktree", "prune"],
            capture_output=True,
        )
        import shutil

        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def test_yields_checkout_path(self) -> None:
        with collector_checkout(self.repo_dir, self.sha) as checkout:
            self.assertTrue(checkout.is_dir())
            self.assertTrue((checkout / "marker.txt").exists())

    def test_cleans_up_on_exit(self) -> None:
        with collector_checkout(self.repo_dir, self.sha) as checkout:
            path = checkout
        self.assertFalse(path.exists())

    def test_cleans_up_on_exception(self) -> None:
        path = None
        with self.assertRaises(ValueError):
            with collector_checkout(self.repo_dir, self.sha) as checkout:
                path = checkout
                raise ValueError("boom")
        self.assertIsNotNone(path)
        self.assertFalse(path.exists())


# ---------------------------------------------------------------------------
# G2 — additive kwarg tests (AC-C-01..C-09) and helper unit tests.
# Sanitize-FIRST (drop chars not in [A-Za-z0-9._-]) then truncate-SECOND
# (take LAST 32 chars of sanitized). Empty / fully-rejected → "".
# ---------------------------------------------------------------------------


class SanitizeNameHintTests(unittest.TestCase):
    """Unit tests for _sanitize_name_hint helper (G2)."""

    def test_empty_input_returns_empty(self) -> None:
        self.assertEqual(_sanitize_name_hint(""), "")

    def test_whitespace_only_returns_empty(self) -> None:
        # Whitespace chars are not in the allow-list → fully rejected.
        self.assertEqual(_sanitize_name_hint("   "), "")

    def test_allowed_charset_preserved(self) -> None:
        self.assertEqual(_sanitize_name_hint("static_p1.v-2"), "static_p1.v-2")

    def test_path_traversal_dropped(self) -> None:
        # Drops '/', '.', '..' characters that don't match charset.
        # Actually '.' IS in the allow-list. Slashes are not.
        self.assertEqual(_sanitize_name_hint("../etc/passwd"), "..etcpasswd")

    def test_slashes_and_backslashes_dropped(self) -> None:
        self.assertEqual(_sanitize_name_hint("foo/bar\\baz"), "foobarbaz")

    def test_non_ascii_dropped(self) -> None:
        # "static_τ_p1" — τ is U+03C4 GREEK SMALL LETTER TAU.
        self.assertEqual(_sanitize_name_hint("static_τ_p1"), "static__p1")

    def test_newline_dropped(self) -> None:
        self.assertEqual(_sanitize_name_hint("foo\nbar"), "foobar")

    def test_takes_last_32_chars_after_sanitize(self) -> None:
        hint = "a" * 40
        result = _sanitize_name_hint(hint)
        self.assertEqual(result, "a" * 32)
        self.assertEqual(len(result), 32)

    def test_sanitize_first_then_truncate(self) -> None:
        # 40 allowed chars interspersed with 40 disallowed chars; after
        # sanitize-FIRST the allowed survivors are 40 chars; then the
        # LAST 32 are kept.
        body = ("a" + "/") * 40  # "a/a/a/...", 80 chars
        # Sanitized: 40 'a's. Last 32 of those: 32 'a's.
        self.assertEqual(_sanitize_name_hint(body), "a" * 32)

    def test_preserves_disambiguating_tail(self) -> None:
        # Long-prefixed collector ids share a prefix; ensure the
        # disambiguating tail wins. 30 'x's + "_collector_p1" = 43 chars
        # of allowed input; last 32 chars include the tail.
        hint = "x" * 30 + "_collector_p1"
        result = _sanitize_name_hint(hint)
        self.assertEqual(len(result), 32)
        self.assertTrue(result.endswith("_collector_p1"))


class IsTransientLockErrorTests(unittest.TestCase):
    """Unit tests for _is_transient_lock_error helper (G2)."""

    def test_could_not_lock(self) -> None:
        self.assertTrue(
            _is_transient_lock_error("fatal: could not lock config file .git/config: File exists")
        )

    def test_already_locked(self) -> None:
        self.assertTrue(_is_transient_lock_error("fatal: ref is already locked"))

    def test_index_lock(self) -> None:
        self.assertTrue(_is_transient_lock_error("fatal: Unable to create .git/index.lock"))

    def test_config_lock(self) -> None:
        self.assertTrue(_is_transient_lock_error("could not write config.lock atomically"))

    def test_locked_by_another_process(self) -> None:
        self.assertTrue(_is_transient_lock_error("fatal: worktree is locked by another process"))

    def test_case_insensitive(self) -> None:
        self.assertTrue(_is_transient_lock_error("COULD NOT LOCK foo"))
        self.assertTrue(_is_transient_lock_error("Already Locked"))

    def test_empty_returns_false(self) -> None:
        self.assertFalse(_is_transient_lock_error(""))

    def test_unrelated_error_returns_false(self) -> None:
        self.assertFalse(_is_transient_lock_error("fatal: bad revision 'deadbeef'"))


class CreateCollectorCheckoutNameHintTests(unittest.TestCase):
    """AC-C-01..C-05 — name_hint additive kwarg semantics."""

    def setUp(self) -> None:
        self.repo_dir = Path(tempfile.mkdtemp(prefix="sa-test-repo-"))
        self.sha = _init_test_repo(self.repo_dir)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo_dir), "worktree", "prune"],
            capture_output=True,
        )
        import shutil

        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def test_ac_c_01_empty_name_hint_byte_identical_suffix(self) -> None:
        """AC-C-01 — name_hint="" → byte-identical suffix shape."""
        checkout = create_collector_checkout(self.repo_dir, self.sha, name_hint="")
        try:
            # Suffix is `-<sha8>` (no trailing name_hint segment).
            self.assertTrue(checkout.name.startswith("sa-collector-"))
            self.assertTrue(checkout.name.endswith(f"-{self.sha[:8]}"))
        finally:
            cleanup_collector_checkout(checkout, self.repo_dir)

    def test_ac_c_02_static_name_hint_appended(self) -> None:
        """AC-C-02 — name_hint="static_p1" → suffix ends with `-<sha8>-static_p1`."""
        checkout = create_collector_checkout(self.repo_dir, self.sha, name_hint="static_p1")
        try:
            self.assertTrue(checkout.name.startswith("sa-collector-"))
            self.assertTrue(
                checkout.name.endswith(f"-{self.sha[:8]}-static_p1"),
                msg=f"unexpected name: {checkout.name}",
            )
        finally:
            cleanup_collector_checkout(checkout, self.repo_dir)

    def test_ac_c_03_traversal_name_hint_sanitized(self) -> None:
        """AC-C-03 — name_hint="../etc/passwd" → no `/` or `..` in path."""
        checkout = create_collector_checkout(self.repo_dir, self.sha, name_hint="../etc/passwd")
        try:
            # Sanitized form has slashes dropped; '.' chars are allowed.
            # Result will end with "-<sha8>-..etcpasswd" — no slashes.
            self.assertNotIn("/etc/", checkout.name)
            self.assertNotIn("\\", checkout.name)
            # The whole basename ends with the sanitized hint.
            self.assertTrue(
                checkout.name.endswith(f"-{self.sha[:8]}-..etcpasswd"),
                msg=f"unexpected name: {checkout.name}",
            )
        finally:
            cleanup_collector_checkout(checkout, self.repo_dir)

    def test_ac_c_04_long_name_hint_takes_last_32(self) -> None:
        """AC-C-04 — name_hint 40 chars → suffix uses LAST 32 chars."""
        hint = "x" * 30 + "_collector_p1"  # 43 chars, all allowed
        checkout = create_collector_checkout(self.repo_dir, self.sha, name_hint=hint)
        try:
            sanitized = _sanitize_name_hint(hint)
            self.assertEqual(len(sanitized), 32)
            self.assertTrue(
                checkout.name.endswith(f"-{self.sha[:8]}-{sanitized}"),
                msg=f"unexpected name: {checkout.name}",
            )
        finally:
            cleanup_collector_checkout(checkout, self.repo_dir)

    def test_ac_c_05_empty_sanitized_drops_hint_segment(self) -> None:
        """AC-C-05 — name_hint with no allowed chars → suffix omits hint segment."""
        # "///" has no allowed chars → _sanitize returns "" → segment dropped.
        checkout = create_collector_checkout(self.repo_dir, self.sha, name_hint="///")
        try:
            # Suffix is `-<sha8>` only (no trailing extra segment).
            self.assertTrue(checkout.name.endswith(f"-{self.sha[:8]}"))
        finally:
            cleanup_collector_checkout(checkout, self.repo_dir)


class CreateCollectorCheckoutAddTimeoutTests(unittest.TestCase):
    """AC-C-06..C-07 — add_timeout additive kwarg semantics."""

    def setUp(self) -> None:
        self.repo_dir = Path(tempfile.mkdtemp(prefix="sa-test-repo-"))
        self.sha = _init_test_repo(self.repo_dir)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo_dir), "worktree", "prune"],
            capture_output=True,
        )
        import shutil

        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def test_ac_c_06_default_add_timeout_is_30(self) -> None:
        """AC-C-06 — add_timeout=None → subprocess.run uses timeout=30."""
        real_run = subprocess.run
        captured: list[int] = []

        def fake_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args")
            if (
                isinstance(cmd, list)
                and len(cmd) >= 3
                and cmd[0] == "git"
                and cmd[1] == "worktree"
                and cmd[2] == "add"
            ):
                captured.append(kwargs.get("timeout"))
            return real_run(*args, **kwargs)

        with mock.patch(
            "story_automator.core.collector_checkout.subprocess.run",
            side_effect=fake_run,
        ):
            checkout = create_collector_checkout(self.repo_dir, self.sha)
        try:
            self.assertEqual(captured, [30])
        finally:
            cleanup_collector_checkout(checkout, self.repo_dir)

    def test_ac_c_07_custom_add_timeout_threaded_through(self) -> None:
        """AC-C-07 — add_timeout=90 → subprocess.run uses timeout=90."""
        real_run = subprocess.run
        captured: list[int] = []

        def fake_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args")
            if (
                isinstance(cmd, list)
                and len(cmd) >= 3
                and cmd[0] == "git"
                and cmd[1] == "worktree"
                and cmd[2] == "add"
            ):
                captured.append(kwargs.get("timeout"))
            return real_run(*args, **kwargs)

        with mock.patch(
            "story_automator.core.collector_checkout.subprocess.run",
            side_effect=fake_run,
        ):
            checkout = create_collector_checkout(self.repo_dir, self.sha, add_timeout=90)
        try:
            self.assertEqual(captured, [90])
        finally:
            cleanup_collector_checkout(checkout, self.repo_dir)


class CreateCollectorCheckoutRetryTests(unittest.TestCase):
    """AC-C-08, AC-C-09 — bounded retry on transient lock errors."""

    def setUp(self) -> None:
        self.repo_dir = Path(tempfile.mkdtemp(prefix="sa-test-repo-"))
        self.sha = _init_test_repo(self.repo_dir)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo_dir), "worktree", "prune"],
            capture_output=True,
        )
        import shutil

        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def _make_completed(
        self, returncode: int, stderr: str = ""
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["git", "worktree", "add"], returncode=returncode, stdout="", stderr=stderr
        )

    def test_ac_c_08_transient_lock_retried_then_succeeds(self) -> None:
        """AC-C-08 — transient stderr is retried; second attempt succeeds."""
        real_run = subprocess.run
        worktree_add_calls = {"n": 0}

        def fake_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args")
            if (
                isinstance(cmd, list)
                and len(cmd) >= 3
                and cmd[0] == "git"
                and cmd[1] == "worktree"
                and cmd[2] == "add"
            ):
                worktree_add_calls["n"] += 1
                if worktree_add_calls["n"] == 1:
                    # First attempt fails with a transient lock error.
                    return self._make_completed(
                        returncode=128,
                        stderr=("fatal: could not lock config file .git/config: File exists"),
                    )
                # Second attempt: delegate to the real subprocess.run.
                return real_run(*args, **kwargs)
            return real_run(*args, **kwargs)

        sleep_calls: list[float] = []

        def fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        with (
            mock.patch(
                "story_automator.core.collector_checkout.subprocess.run",
                side_effect=fake_run,
            ),
            mock.patch(
                "story_automator.core.collector_checkout.time.sleep",
                side_effect=fake_sleep,
            ),
        ):
            checkout = create_collector_checkout(self.repo_dir, self.sha)
        try:
            self.assertEqual(worktree_add_calls["n"], 2)
            # Slept once with the configured backoff before retry.
            self.assertEqual(sleep_calls, [0.05])
            self.assertTrue(checkout.is_dir())
        finally:
            cleanup_collector_checkout(checkout, self.repo_dir)

    def test_ac_c_08_retry_exhausted_raises(self) -> None:
        """AC-C-08 — exhausted retries (3 attempts) raise CollectorCheckoutError."""
        real_run = subprocess.run
        worktree_add_calls = {"n": 0}

        def fake_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args")
            if (
                isinstance(cmd, list)
                and len(cmd) >= 3
                and cmd[0] == "git"
                and cmd[1] == "worktree"
                and cmd[2] == "add"
            ):
                worktree_add_calls["n"] += 1
                # Always return a transient lock error.
                return self._make_completed(
                    returncode=128,
                    stderr="fatal: could not lock index.lock",
                )
            return real_run(*args, **kwargs)

        sleep_calls: list[float] = []

        def fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        with (
            mock.patch(
                "story_automator.core.collector_checkout.subprocess.run",
                side_effect=fake_run,
            ),
            mock.patch(
                "story_automator.core.collector_checkout.time.sleep",
                side_effect=fake_sleep,
            ),
        ):
            with self.assertRaises(CollectorCheckoutError) as ctx:
                create_collector_checkout(self.repo_dir, self.sha)

        # Three attempts total (configured by _MAX_WORKTREE_ADD_ATTEMPTS=3).
        self.assertEqual(worktree_add_calls["n"], 3)
        # Slept TWICE (between attempts 1->2 and 2->3); NOT after attempt 3.
        self.assertEqual(sleep_calls, [0.05, 0.05])
        self.assertIn("could not lock", str(ctx.exception))

    def test_ac_c_09_non_transient_error_not_retried(self) -> None:
        """AC-C-09 — non-transient git error is NOT retried; raised on first failure."""
        real_run = subprocess.run
        worktree_add_calls = {"n": 0}

        def fake_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args")
            if (
                isinstance(cmd, list)
                and len(cmd) >= 3
                and cmd[0] == "git"
                and cmd[1] == "worktree"
                and cmd[2] == "add"
            ):
                worktree_add_calls["n"] += 1
                # Non-transient: e.g., bad revision.
                return self._make_completed(
                    returncode=128,
                    stderr="fatal: invalid reference: deadbeef",
                )
            return real_run(*args, **kwargs)

        sleep_calls: list[float] = []

        def fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        with (
            mock.patch(
                "story_automator.core.collector_checkout.subprocess.run",
                side_effect=fake_run,
            ),
            mock.patch(
                "story_automator.core.collector_checkout.time.sleep",
                side_effect=fake_sleep,
            ),
        ):
            with self.assertRaises(CollectorCheckoutError) as ctx:
                create_collector_checkout(self.repo_dir, self.sha)

        # Exactly ONE attempt; no retries because the error is non-transient.
        self.assertEqual(worktree_add_calls["n"], 1)
        self.assertEqual(sleep_calls, [])
        self.assertIn("invalid reference", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
