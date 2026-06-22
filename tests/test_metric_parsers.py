"""Tests for metric parsers and adjudicator->collector metric threading (A-01).

Bug A-01: collectors emit useful metrics in stdout (MUTATION_RESULT JSON,
BURN_IN_RESULT JSON, ``coverage: X.X%`` lines, semgrep/trivy/osv JSON) but
the adjudicator throws stdout away. Verdict rules in ``category_rules`` then
read ``metrics["mutation_score"]`` / ``metrics["coverage_pct"]`` /
``metrics["sast_high_count"]`` / etc. and see ``0`` everywhere — which
silently passes the gate even when collectors detected violations.

These tests pin:
1. ``parse_*`` functions return the right dict for happy-path stdout
2. Every parser is fail-safe (returns ``{}`` on garbage / empty input)
3. ``CollectorConfig`` accepts a ``parse_metrics`` callable
4. ``run_collector_with_timeout`` threads parser output into the evidence record
5. Parser exceptions inside the adjudicator are swallowed (defence-in-depth)
"""
from __future__ import annotations

import sys
import unittest

from story_automator.core.collector_config import CollectorConfig
from story_automator.core.metric_parsers import (
    parse_burn_in_metrics,
    parse_coverage_metrics,
    parse_gitleaks_metrics,
    parse_mutation_metrics,
    parse_osv_metrics,
    parse_semgrep_metrics,
    parse_trivy_metrics,
)


class ParseMutationMetricsTests(unittest.TestCase):
    def test_parses_mutation_result_json_line(self) -> None:
        stdout = (
            "mutation score: 73.4% (threshold: 60%)\n"
            'MUTATION_RESULT: {"tool":"mutmut","mutation_score":73.4,'
            '"mutants_total":100,"mutants_killed":73,"mutants_survived":27,'
            '"threshold":60,"passed":true}\n'
        )
        result = parse_mutation_metrics(stdout)
        self.assertEqual(result["mutation_score"], 73.4)
        self.assertEqual(result["mutants_total"], 100)
        self.assertEqual(result["mutants_killed"], 73)
        self.assertEqual(result["mutants_survived"], 27)

    def test_returns_empty_on_missing_line(self) -> None:
        self.assertEqual(parse_mutation_metrics("nothing useful here"), {})

    def test_returns_empty_on_malformed_json(self) -> None:
        self.assertEqual(parse_mutation_metrics("MUTATION_RESULT: {not-json"), {})

    def test_returns_empty_on_empty(self) -> None:
        self.assertEqual(parse_mutation_metrics(""), {})

    def test_only_extracts_known_numeric_keys(self) -> None:
        """Defence-in-depth: arbitrary extra keys in the JSON line are dropped
        so a misbehaving collector cannot smuggle non-numeric metrics that
        would trip schema validation downstream."""
        stdout = (
            'MUTATION_RESULT: {"mutation_score":50,"mutants_total":10,'
            '"mutants_killed":5,"mutants_survived":5,"evil_key":["a","b"]}'
        )
        result = parse_mutation_metrics(stdout)
        self.assertNotIn("evil_key", result)
        self.assertEqual(result["mutation_score"], 50)


class ParseCoverageMetricsTests(unittest.TestCase):
    def test_parses_coverage_line(self) -> None:
        stdout = "coverage: 82.7% (threshold: 80%)\n"
        result = parse_coverage_metrics(stdout)
        self.assertAlmostEqual(result["coverage_pct"], 82.7)

    def test_parses_decimal_coverage(self) -> None:
        stdout = "coverage: 100.0% (threshold: 80%)\n"
        self.assertAlmostEqual(parse_coverage_metrics(stdout)["coverage_pct"], 100.0)

    def test_returns_empty_on_no_match(self) -> None:
        self.assertEqual(parse_coverage_metrics("no coverage info"), {})

    def test_returns_empty_on_empty(self) -> None:
        self.assertEqual(parse_coverage_metrics(""), {})


class ParseBurnInMetricsTests(unittest.TestCase):
    def test_parses_burn_in_result_json_line(self) -> None:
        stdout = (
            "run 1/3: PASS\nrun 2/3: PASS\nrun 3/3: PASS\n"
            'BURN_IN_RESULT: {"total_runs":3,"passed_runs":3,"failed_runs":0,'
            '"flaky":false,"flaky_count":0,"flaky_tests":[]}\n'
        )
        result = parse_burn_in_metrics(stdout)
        self.assertEqual(result["flaky_count"], 0)

    def test_parses_flaky_count_when_present(self) -> None:
        stdout = (
            'BURN_IN_RESULT: {"total_runs":5,"passed_runs":3,"failed_runs":2,'
            '"flaky":true,"flaky_count":4,"flaky_tests":[]}'
        )
        result = parse_burn_in_metrics(stdout)
        self.assertEqual(result["flaky_count"], 4)

    def test_returns_empty_on_empty(self) -> None:
        self.assertEqual(parse_burn_in_metrics(""), {})

    def test_returns_empty_on_garbage(self) -> None:
        self.assertEqual(parse_burn_in_metrics("BURN_IN_RESULT: not-json"), {})


class ParseSemgrepMetricsTests(unittest.TestCase):
    def test_counts_high_severity_findings(self) -> None:
        stdout = (
            '{"results":['
            '{"extra":{"severity":"ERROR"}},'
            '{"extra":{"severity":"WARNING"}},'
            '{"extra":{"severity":"ERROR"}},'
            '{"extra":{"severity":"INFO"}}'
            ']}'
        )
        result = parse_semgrep_metrics(stdout)
        self.assertEqual(result["sast_high_count"], 2)

    def test_counts_zero_on_no_findings(self) -> None:
        stdout = '{"results":[]}'
        result = parse_semgrep_metrics(stdout)
        self.assertEqual(result["sast_high_count"], 0)

    def test_returns_empty_on_malformed_json(self) -> None:
        self.assertEqual(parse_semgrep_metrics("not json"), {})

    def test_returns_empty_on_empty(self) -> None:
        self.assertEqual(parse_semgrep_metrics(""), {})


class ParseTrivyMetricsTests(unittest.TestCase):
    def test_counts_critical_vulnerabilities(self) -> None:
        stdout = (
            '{"Results":[{"Vulnerabilities":['
            '{"Severity":"CRITICAL"},'
            '{"Severity":"HIGH"},'
            '{"Severity":"CRITICAL"}'
            ']}]}'
        )
        result = parse_trivy_metrics(stdout)
        self.assertEqual(result["deps_critical_count"], 2)

    def test_zero_on_no_critical(self) -> None:
        stdout = '{"Results":[{"Vulnerabilities":[{"Severity":"LOW"}]}]}'
        self.assertEqual(parse_trivy_metrics(stdout)["deps_critical_count"], 0)

    def test_returns_empty_on_malformed_json(self) -> None:
        self.assertEqual(parse_trivy_metrics("not json"), {})


class ParseOsvMetricsTests(unittest.TestCase):
    def test_counts_critical_vulnerabilities(self) -> None:
        stdout = (
            '{"results":[{"packages":[{"vulnerabilities":['
            '{"database_specific":{"severity":"CRITICAL"}},'
            '{"database_specific":{"severity":"HIGH"}}'
            ']}]}]}'
        )
        result = parse_osv_metrics(stdout)
        self.assertEqual(result["deps_critical_count"], 1)

    def test_returns_empty_on_malformed_json(self) -> None:
        self.assertEqual(parse_osv_metrics("not json"), {})


class ParseGitleaksMetricsTests(unittest.TestCase):
    def test_counts_findings(self) -> None:
        stdout = '[{"RuleID":"r1"},{"RuleID":"r2"},{"RuleID":"r3"}]'
        self.assertEqual(parse_gitleaks_metrics(stdout)["secrets_count"], 3)

    def test_zero_on_empty_array(self) -> None:
        self.assertEqual(parse_gitleaks_metrics("[]")["secrets_count"], 0)

    def test_returns_empty_on_malformed_json(self) -> None:
        self.assertEqual(parse_gitleaks_metrics("oops"), {})


class CollectorConfigParseMetricsFieldTests(unittest.TestCase):
    def test_accepts_parse_metrics_field(self) -> None:
        cfg = CollectorConfig(
            collector_id="x",
            tool="t",
            category="mutation",
            build_cmd=lambda _c, _p: ["true"],
            parse_metrics=parse_mutation_metrics,
        )
        self.assertIs(cfg.parse_metrics, parse_mutation_metrics)

    def test_defaults_to_none(self) -> None:
        cfg = CollectorConfig(
            collector_id="x",
            tool="t",
            category="static",
            build_cmd=lambda _c, _p: ["true"],
        )
        self.assertIsNone(cfg.parse_metrics)


class AdjudicatorMetricThreadingTests(unittest.TestCase):
    def test_metrics_populated_from_stdout_on_ok(self) -> None:
        from story_automator.core.adjudicator import run_collector_with_timeout

        stdout_text = (
            'MUTATION_RESULT: {"tool":"mutmut","mutation_score":80,'
            '"mutants_total":10,"mutants_killed":8,"mutants_survived":2,'
            '"threshold":60,"passed":true}'
        )
        record = run_collector_with_timeout(
            [sys.executable, "-c", f"print({stdout_text!r})"],
            collector="mutmut-mutation",
            tool="python3",
            category="mutation",
            timeout_s=10,
            parse_metrics=parse_mutation_metrics,
        )
        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["metrics"]["mutation_score"], 80)
        self.assertEqual(record["metrics"]["mutants_total"], 10)

    def test_metrics_populated_from_stdout_on_violation(self) -> None:
        """Mutation/coverage/security collectors return non-zero exit when
        below threshold — metrics must still be parsed so the verdict rule
        can compute the right verdict."""
        from story_automator.core.adjudicator import run_collector_with_timeout

        script = (
            "import sys; "
            "print('MUTATION_RESULT: {\"mutation_score\":40,\"mutants_total\":10,"
            "\"mutants_killed\":4,\"mutants_survived\":6}'); "
            "sys.exit(1)"
        )
        record = run_collector_with_timeout(
            [sys.executable, "-c", script],
            collector="mutmut-mutation",
            tool="python3",
            category="mutation",
            timeout_s=10,
            parse_metrics=parse_mutation_metrics,
        )
        self.assertEqual(record["status"], "violation")
        self.assertEqual(record["metrics"]["mutation_score"], 40)
        self.assertEqual(record["metrics"]["mutants_killed"], 4)

    def test_no_parser_keeps_metrics_empty(self) -> None:
        from story_automator.core.adjudicator import run_collector_with_timeout

        record = run_collector_with_timeout(
            [sys.executable, "-c", "print('whatever')"],
            collector="t",
            tool="t",
            category="static",
            timeout_s=10,
        )
        self.assertEqual(record["metrics"], {})

    def test_parser_exception_swallowed(self) -> None:
        """Defence-in-depth: if a custom parser raises, the adjudicator must
        still produce a valid evidence record (with empty metrics) — never
        crash the gate."""
        from story_automator.core.adjudicator import run_collector_with_timeout

        def broken_parser(_stdout: str) -> dict:
            raise RuntimeError("parser exploded")

        record = run_collector_with_timeout(
            [sys.executable, "-c", "print('ok')"],
            collector="t",
            tool="t",
            category="mutation",
            timeout_s=10,
            parse_metrics=broken_parser,
        )
        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["metrics"], {})

    def test_parser_returning_non_dict_swallowed(self) -> None:
        """A parser that returns a non-dict must not break schema validation."""
        from story_automator.core.adjudicator import run_collector_with_timeout

        def bad_return(_stdout: str):
            return ["not", "a", "dict"]

        record = run_collector_with_timeout(
            [sys.executable, "-c", "print('ok')"],
            collector="t",
            tool="t",
            category="mutation",
            timeout_s=10,
            parse_metrics=bad_return,
        )
        self.assertEqual(record["metrics"], {})

    def test_parser_returning_invalid_values_swallowed(self) -> None:
        """A parser that returns a dict with non-bool|int|float|str values
        must not break schema validation either."""
        from story_automator.core.adjudicator import run_collector_with_timeout

        def bad_values(_stdout: str):
            return {"k": [1, 2, 3]}

        record = run_collector_with_timeout(
            [sys.executable, "-c", "print('ok')"],
            collector="t",
            tool="t",
            category="mutation",
            timeout_s=10,
            parse_metrics=bad_values,
        )
        self.assertEqual(record["metrics"], {})


if __name__ == "__main__":
    unittest.main()
