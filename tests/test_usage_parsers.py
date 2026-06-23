"""Tests for :mod:`story_automator.core.usage_parsers`."""

from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError

from story_automator.core.usage_parsers import (
    KNOWN_PARSERS,
    ParseError,
    UsageMetrics,
    get_parser,
)
from story_automator.core.usage_parsers import (
    claude_jsonl as claude_jsonl_module,
    codex_rollout as codex_module,
    gemini_chat as gemini_module,
    none as none_module,
)


class KnownParsersTests(unittest.TestCase):
    def test_known_parsers_set_closed(self) -> None:
        # The KNOWN_PARSERS map is the contract surface; if it grows,
        # tests + docs must grow with it.
        self.assertEqual(
            set(KNOWN_PARSERS.keys()),
            {"claude-code", "codex", "gemini-cli", "none"},
        )
        self.assertEqual(
            set(KNOWN_PARSERS.values()),
            {"claude-jsonl", "codex-rollout", "gemini-chat", "none"},
        )

    def test_get_parser_returns_callable_for_each_known_id(self) -> None:
        for cli_id in KNOWN_PARSERS:
            parser = get_parser(cli_id)
            self.assertTrue(callable(parser), f"parser for {cli_id!r} not callable")
            # Each parser must accept a string and return UsageMetrics
            # without raising on an empty input.
            result = parser("")
            self.assertIsInstance(result, UsageMetrics)

    def test_get_parser_unknown_raises(self) -> None:
        with self.assertRaises(ParseError):
            get_parser("openai-gpt")
        with self.assertRaises(ParseError):
            get_parser("")


class NoneParserTests(unittest.TestCase):
    def test_none_parser_always_zero(self) -> None:
        zero = UsageMetrics()
        self.assertEqual(none_module.parse_usage(""), zero)
        self.assertEqual(none_module.parse_usage("anything"), zero)
        self.assertEqual(
            none_module.parse_usage(json.dumps({"usage": {"input_tokens": 9999}})),
            zero,
        )
        self.assertEqual(none_module.PARSER_ID, "none")


class ClaudeJsonlParserTests(unittest.TestCase):
    def test_claude_jsonl_parses_result_message(self) -> None:
        line = json.dumps(
            {
                "type": "result",
                "message": {
                    "usage": {
                        "input_tokens": 1000,
                        "output_tokens": 250,
                    }
                },
            }
        )
        result = claude_jsonl_module.parse_usage(line + "\n")
        self.assertEqual(result.input_tokens, 1000)
        self.assertEqual(result.output_tokens, 250)
        self.assertAlmostEqual(result.total_cost_usd, 1000 * 3e-6 + 250 * 15e-6)

    def test_claude_jsonl_handles_malformed_returns_zero(self) -> None:
        # A mix of malformed JSON, empty lines, and non-dict entries
        # must all be skipped silently.
        text = "\n".join(
            [
                "not json",
                "",
                "{",
                "[1, 2, 3]",
                json.dumps("a string"),
                json.dumps(42),
            ]
        )
        result = claude_jsonl_module.parse_usage(text)
        self.assertEqual(result, UsageMetrics())

    def test_claude_jsonl_computes_cost_from_tokens(self) -> None:
        line = json.dumps(
            {"usage": {"input_tokens": 10_000, "output_tokens": 5_000}}
        )
        result = claude_jsonl_module.parse_usage(line)
        expected = 10_000 * 3e-6 + 5_000 * 15e-6
        self.assertAlmostEqual(result.total_cost_usd, expected)

    def test_claude_jsonl_handles_empty_input(self) -> None:
        self.assertEqual(claude_jsonl_module.parse_usage(""), UsageMetrics())
        self.assertEqual(claude_jsonl_module.parse_usage("\n\n\n"), UsageMetrics())

    def test_claude_jsonl_handles_multiple_result_messages(self) -> None:
        lines = [
            json.dumps({"usage": {"input_tokens": 100, "output_tokens": 50}}),
            json.dumps(
                {
                    "message": {
                        "usage": {"input_tokens": 200, "output_tokens": 80}
                    }
                }
            ),
            json.dumps({"usage": {"input_tokens": 0, "output_tokens": 0}}),
        ]
        result = claude_jsonl_module.parse_usage("\n".join(lines))
        self.assertEqual(result.input_tokens, 300)
        self.assertEqual(result.output_tokens, 130)

    def test_claude_jsonl_counts_tool_calls(self) -> None:
        lines = [
            json.dumps(
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": "let me read"},
                            {"type": "tool_use", "name": "Read"},
                        ],
                        "usage": {"input_tokens": 10, "output_tokens": 5},
                    }
                }
            ),
            json.dumps({"type": "tool_use", "name": "Edit"}),
        ]
        result = claude_jsonl_module.parse_usage("\n".join(lines))
        self.assertEqual(result.tool_calls_count, 2)
        self.assertEqual(result.input_tokens, 10)

    def test_claude_jsonl_picks_max_duration_ms(self) -> None:
        lines = [
            json.dumps({"duration_ms": 1000}),
            json.dumps({"duration_ms": 5000}),
            json.dumps({"duration_ms": 2000}),
        ]
        result = claude_jsonl_module.parse_usage("\n".join(lines))
        self.assertAlmostEqual(result.duration_s, 5.0)

    def test_claude_jsonl_negative_or_missing_tokens_safe(self) -> None:
        lines = [
            json.dumps({"usage": {"input_tokens": "not-an-int"}}),
            json.dumps({"usage": {"input_tokens": -5, "output_tokens": -10}}),
            json.dumps({"usage": {}}),
        ]
        result = claude_jsonl_module.parse_usage("\n".join(lines))
        self.assertEqual(result.input_tokens, 0)
        self.assertEqual(result.output_tokens, 0)


class StubParserTests(unittest.TestCase):
    def test_codex_stub_returns_zeros(self) -> None:
        self.assertEqual(codex_module.parse_usage(""), UsageMetrics())
        self.assertEqual(codex_module.parse_usage("anything"), UsageMetrics())
        self.assertEqual(codex_module.PARSER_ID, "codex-rollout")

    def test_gemini_stub_returns_zeros(self) -> None:
        self.assertEqual(gemini_module.parse_usage(""), UsageMetrics())
        self.assertEqual(gemini_module.parse_usage("anything"), UsageMetrics())
        self.assertEqual(gemini_module.PARSER_ID, "gemini-chat")


class UsageMetricsTests(unittest.TestCase):
    def test_usage_metrics_frozen(self) -> None:
        metrics = UsageMetrics(input_tokens=1, output_tokens=2)
        with self.assertRaises(FrozenInstanceError):
            metrics.input_tokens = 99  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
