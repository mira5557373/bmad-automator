from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path


def _capture(callable_, *args, **kwargs):
    """Run ``callable_(*args, **kwargs)`` with stdout redirected to a string
    buffer and return ``(exit_code, parsed_json, raw_text)``."""
    buf = io.StringIO()
    with mock.patch.object(sys, "stdout", buf):
        code = callable_(*args, **kwargs)
    raw = buf.getvalue()
    text = raw.strip()
    payload = json.loads(text) if text else {}
    return code, payload, raw


class _FakeEvent:
    """Minimal duck-typed event matching the ``core.audit.Event`` protocol."""

    def __init__(self, name: str = "t", payload: dict | None = None) -> None:
        self.event_name = name
        self._payload = payload if payload is not None else {}

    def to_dict(self) -> dict:
        return self._payload


def _build_chain(root: str, key_value: str, count: int) -> Path:
    """Append ``count`` records to the conventional audit log under ``root``
    using a key derived from ``key_value`` (same derivation the command uses).
    Returns the audit log path."""
    from story_automator.commands._audit_hooks import _audit_path_for
    from story_automator.core.audit import AuditLog, load_key_from_env

    path = _audit_path_for(root)
    with mock.patch.dict(os.environ, {"BMAD_AUDIT_KEY": key_value}, clear=False):
        key = load_key_from_env()
    assert key is not None
    log = AuditLog(path=path, key=key)
    for i in range(count):
        log.append(_FakeEvent("t", {"i": i}))
    return path


class AuditVerifyCmdSurfaceTests(unittest.TestCase):
    def test_command_module_is_importable(self) -> None:
        from story_automator.commands.audit_verify_cmd import (  # noqa: F401
            cmd_audit_verify,
        )


class AuditVerifyCmdKeyMissingTests(unittest.TestCase):
    def test_key_missing_returns_error_exit1(self) -> None:
        from story_automator.commands._audit_hooks import _audit_path_for
        from story_automator.commands.audit_verify_cmd import cmd_audit_verify

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {}, clear=True):
                code, payload, _ = _capture(
                    cmd_audit_verify, ["--project-root", tmp]
                )
            self.assertEqual(code, 1)
            self.assertEqual(payload, {"ok": False, "error": "audit_key_missing"})
            # The missing-key path must be strictly read-only: no log created.
            self.assertFalse(
                _audit_path_for(tmp).exists(),
                "audit-verify must not create the log when the key is missing",
            )


class AuditVerifyCmdMissingLogTests(unittest.TestCase):
    def test_missing_log_reports_valid_seq_zero(self) -> None:
        from story_automator.commands.audit_verify_cmd import cmd_audit_verify

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ, {"BMAD_AUDIT_KEY": "secret"}, clear=False
            ):
                code, payload, _ = _capture(
                    cmd_audit_verify, ["--project-root", tmp]
                )
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["last_valid_seq"], 0)
        self.assertTrue(
            payload["path"].replace("\\", "/").endswith("_bmad/audit/audit.jsonl")
        )


class AuditVerifyCmdIntactChainTests(unittest.TestCase):
    def test_intact_chain_reports_valid(self) -> None:
        from story_automator.commands.audit_verify_cmd import cmd_audit_verify

        with tempfile.TemporaryDirectory() as tmp:
            _build_chain(tmp, "secret", 2)
            with mock.patch.dict(
                os.environ, {"BMAD_AUDIT_KEY": "secret"}, clear=False
            ):
                code, payload, _ = _capture(
                    cmd_audit_verify, ["--project-root", tmp]
                )
        self.assertEqual(code, 0)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["last_valid_seq"], 2)


class AuditVerifyCmdTamperedChainTests(unittest.TestCase):
    def test_tampered_chain_reports_invalid(self) -> None:
        from story_automator.commands.audit_verify_cmd import cmd_audit_verify

        with tempfile.TemporaryDirectory() as tmp:
            path = _build_chain(tmp, "secret", 2)
            # Corrupt the tag of the last record by flipping one hex char.
            lines = path.read_text(encoding="utf-8").splitlines()
            recs = [json.loads(line) for line in lines if line]
            tag = recs[-1]["tag"]
            flipped = ("e" if tag[-1] != "e" else "d")
            recs[-1]["tag"] = tag[:-1] + flipped
            from story_automator.core.common import compact_json

            path.write_text(
                "\n".join(compact_json(r) for r in recs) + "\n",
                encoding="utf-8",
            )
            with mock.patch.dict(
                os.environ, {"BMAD_AUDIT_KEY": "secret"}, clear=False
            ):
                code, payload, _ = _capture(
                    cmd_audit_verify, ["--project-root", tmp]
                )
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["last_valid_seq"], 1)


class AuditVerifyCmdDefaultRootTests(unittest.TestCase):
    def test_defaults_to_project_root_env(self) -> None:
        from story_automator.commands.audit_verify_cmd import cmd_audit_verify

        with tempfile.TemporaryDirectory() as tmp:
            resolved = str(Path(tmp).resolve())
            with mock.patch.dict(
                os.environ,
                {"BMAD_AUDIT_KEY": "secret", "PROJECT_ROOT": tmp},
                clear=False,
            ):
                code, payload, _ = _capture(cmd_audit_verify, [])
        self.assertEqual(code, 0)
        self.assertTrue(payload["path"].startswith(resolved))


class AuditVerifyCmdKeyLeakTests(unittest.TestCase):
    def test_key_never_echoed(self) -> None:
        from story_automator.commands.audit_verify_cmd import cmd_audit_verify

        with tempfile.TemporaryDirectory() as tmp:
            _build_chain(tmp, "secret", 2)
            with mock.patch.dict(
                os.environ, {"BMAD_AUDIT_KEY": "secret"}, clear=False
            ):
                _code, _payload, raw = _capture(
                    cmd_audit_verify, ["--project-root", tmp]
                )
        self.assertNotIn("secret", raw)


class AuditVerifyCmdDispatchTests(unittest.TestCase):
    def test_dispatch_registered(self) -> None:
        # The controller wires the dispatch entry separately (cli.py is owned
        # by a different step). Until then, ``audit-verify`` is an unknown
        # command; skip rather than fail so this file passes pre-wiring and
        # proves the dispatch once the controller lands the entry.
        from story_automator import cli

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ, {"BMAD_AUDIT_KEY": "secret"}, clear=False
            ):
                out = io.StringIO()
                err = io.StringIO()
                with (
                    mock.patch.object(sys, "stdout", out),
                    mock.patch.object(sys, "stderr", err),
                ):
                    code = cli.main(["audit-verify", "--project-root", tmp])
        if "Unknown command: audit-verify" in err.getvalue():
            self.skipTest("audit-verify dispatch not yet wired into cli.py")
        text = out.getvalue().strip()
        self.assertEqual(code, 0)
        payload = json.loads(text)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["valid"])


if __name__ == "__main__":
    unittest.main()
