from __future__ import annotations

"""Kernel violation classifier.

Inspects a story kernel and reports which of the four closed violation
categories it triggers. Designed to run in front of the production gate so
that briefs that bundle concerns, dodge falsifiability, prescribe an
implementation, or chain together vendors are rejected before a child
agent burns cycles on them.

The four violation categories are intentionally closed:

* ``mixed-concerns`` — the brief bundles multiple unrelated problem domains
  into a single kernel (Capabilities span disjoint vocabularies).
* ``non-falsifiable`` — the Success signal has no measurable predicate
  (no number, no comparison, no observable threshold), or is missing
  entirely.
* ``solution-disguised`` — the Problem statement reads as an implementation
  spec rather than a user pain (prescribes specific tech, classes, or uses
  "we should add ..." phrasing).
* ``vendor-soup`` — Constraints or Capabilities lock in three or more
  competing vendors / SaaS products without justification.

The classifier accepts either Markdown text or an already-parsed
``{section_name: body}`` mapping. Markdown parsing is intentionally
lightweight (H2 sectioning only) so the classifier stays self-contained
and runs without dragging in the gate-time kernel schema.
"""

import re
from dataclasses import dataclass
from typing import Mapping

VIOLATION_TYPES: tuple[str, ...] = (
    "mixed-concerns",
    "non-falsifiable",
    "solution-disguised",
    "vendor-soup",
)

# Sections the classifier reasons about. The kernel may declare more, but
# the classifier only inspects these.
_INSPECTED_SECTIONS: tuple[str, ...] = (
    "Problem",
    "Capabilities",
    "Constraints",
    "Non-goals",
    "Success signal",
)

# Tokens that indicate a measurable, falsifiable predicate in the Success
# signal. The presence of ANY of these short-circuits the non-falsifiable
# rule.
_FALSIFIABLE_NUMBER_RE = re.compile(r"\d")
_FALSIFIABLE_TOKENS: tuple[str, ...] = (
    "below",
    "above",
    "under",
    "over",
    "at most",
    "at least",
    "less than",
    "greater than",
    "fewer than",
    "more than",
    "%",
    "percent",
    "p50",
    "p95",
    "p99",
    "ms",
    "seconds",
    "minutes",
    "hours",
    "per second",
    "per minute",
    "per hour",
    "per day",
    "per week",
    "per month",
)

# Phrases that betray a solution-disguised problem. These are matched
# case-insensitively as whole substrings.
_SOLUTION_DISGUISED_PATTERNS: tuple[str, ...] = (
    "we should add",
    "we should build",
    "we should introduce",
    "we should adopt",
    "we should switch to",
    "we should use",
    "let's add",
    "let's build",
    "let's switch to",
    "add a redis",
    "add a postgres",
    "add a kafka",
    "add a kubernetes",
    "introduce a microservice",
    "rewrite in",
    "port to",
    "migrate to ",
)

# Implementation-flavored nouns that, combined with prescriptive verbs,
# indicate the problem statement is really a solution sketch.
_SOLUTION_TECH_NOUNS: tuple[str, ...] = (
    "redis",
    "postgres",
    "mysql",
    "kafka",
    "rabbitmq",
    "kubernetes",
    "docker",
    "lambda",
    "s3 bucket",
    "dynamodb",
    "graphql",
    "grpc",
)

# A closed list of vendor / SaaS product names the classifier recognizes
# when scoring vendor-soup. Match is case-insensitive on word boundaries.
_KNOWN_VENDORS: tuple[str, ...] = (
    "datadog",
    "new relic",
    "splunk",
    "grafana",
    "grafana cloud",
    "pagerduty",
    "opsgenie",
    "sentry",
    "honeycomb",
    "dynatrace",
    "elastic",
    "elasticsearch",
    "snowflake",
    "databricks",
    "bigquery",
    "redshift",
    "looker",
    "tableau",
    "mode",
    "segment",
    "amplitude",
    "mixpanel",
    "stripe",
    "braintree",
    "adyen",
    "salesforce",
    "hubspot",
    "zendesk",
    "intercom",
    "auth0",
    "okta",
    "cognito",
)

# Domain vocabularies used by the mixed-concerns rule. Each set is a
# bag-of-keywords that strongly clusters with one product domain. When a
# kernel's Capabilities trip three or more distinct domains, the rule
# fires.
_DOMAIN_VOCABULARIES: dict[str, frozenset[str]] = {
    "auth": frozenset({
        "oauth",
        "sso",
        "single-sign-on",
        "password",
        "login",
        "refresh token",
        "access token",
        "mfa",
        "2fa",
        "session",
    }),
    "billing": frozenset({
        "invoice",
        "billing",
        "charge",
        "stripe",
        "subscription",
        "pro-rated",
        "prorated",
        "tax",
        "refund",
        "dunning",
    }),
    "notifications": frozenset({
        "email",
        "sms",
        "push notification",
        "slack",
        "webhook",
        "digest",
    }),
    "analytics": frozenset({
        "dashboard",
        "report",
        "metric",
        "kpi",
        "funnel",
        "cohort",
        "histogram",
    }),
    "search": frozenset({
        "search",
        "index",
        "query",
        "autocomplete",
        "ranking",
        "facet",
    }),
    "scheduling": frozenset({
        "schedule",
        "calendar",
        "appointment",
        "reminder",
        "recurring",
        "timezone",
    }),
}


class KernelClassifierError(ValueError):
    """Raised when the classifier receives input it cannot interpret."""


@dataclass(frozen=True)
class KernelViolation:
    """A single classification result.

    ``code`` is one of ``VIOLATION_TYPES``. ``evidence`` is a short,
    human-readable string explaining why the rule fired; it is intended
    for display in the gate audit, not for machine parsing.
    """

    code: str
    evidence: str


_H2_RE = re.compile(r"^##\s+(.+?)\s*$")


def _parse_markdown_sections(text: str) -> dict[str, str]:
    """Lightweight H2 sectioner.

    Recognizes ``## <Name>`` headings whose name matches one of the
    inspected sections; everything else is folded into the body of the
    most recent inspected section. Deliberately self-contained so the
    classifier does not depend on the gate-time kernel schema parser.
    """
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        match = _H2_RE.match(raw_line)
        if match is not None:
            name = match.group(1).strip()
            if name in _INSPECTED_SECTIONS:
                current = name
                sections.setdefault(current, [])
                continue
            # Unknown H2: keep folding into the previous inspected section.
        if current is None:
            continue
        sections[current].append(raw_line)
    return {
        name: "\n".join(lines).strip() for name, lines in sections.items()
    }


def _normalize_input(kernel: object) -> dict[str, str]:
    if isinstance(kernel, str):
        return _parse_markdown_sections(kernel)
    if isinstance(kernel, Mapping):
        out: dict[str, str] = {}
        for key, value in kernel.items():
            if not isinstance(key, str):
                raise KernelClassifierError(
                    f"kernel section names must be strings, got {type(key).__name__}"
                )
            if value is None:
                out[key] = ""
                continue
            if not isinstance(value, str):
                raise KernelClassifierError(
                    f"kernel section body for {key!r} must be a string, "
                    f"got {type(value).__name__}"
                )
            out[key] = value
        return out
    raise KernelClassifierError(
        "kernel must be a string or a mapping of section -> body, "
        f"got {type(kernel).__name__}"
    )


def _has_falsifiable_predicate(success_signal: str) -> bool:
    """Return True if the success signal contains a measurable predicate."""
    if not success_signal.strip():
        return False
    if _FALSIFIABLE_NUMBER_RE.search(success_signal):
        return True
    lowered = success_signal.lower()
    return any(token in lowered for token in _FALSIFIABLE_TOKENS)


def _detect_non_falsifiable(sections: Mapping[str, str]) -> KernelViolation | None:
    signal = sections.get("Success signal", "")
    if not signal.strip():
        return KernelViolation(
            code="non-falsifiable",
            evidence="Success signal is missing or empty",
        )
    if _has_falsifiable_predicate(signal):
        return None
    return KernelViolation(
        code="non-falsifiable",
        evidence=(
            "Success signal has no measurable predicate "
            "(no number, comparison, or observable threshold)"
        ),
    )


def _detect_solution_disguised(
    sections: Mapping[str, str],
) -> KernelViolation | None:
    problem = sections.get("Problem", "").lower()
    if not problem:
        return None
    for phrase in _SOLUTION_DISGUISED_PATTERNS:
        if phrase in problem:
            return KernelViolation(
                code="solution-disguised",
                evidence=f"Problem prescribes implementation: {phrase!r}",
            )
    # Combined check: prescriptive verb + named tech noun.
    for noun in _SOLUTION_TECH_NOUNS:
        if noun in problem and (
            "add" in problem or "use" in problem or "introduce" in problem
        ):
            return KernelViolation(
                code="solution-disguised",
                evidence=(
                    "Problem names a specific technology "
                    f"({noun!r}) and prescribes adoption"
                ),
            )
    return None


def _vendor_hits(text: str) -> list[str]:
    lowered = text.lower()
    hits: list[str] = []
    seen: set[str] = set()
    for vendor in _KNOWN_VENDORS:
        # Word-boundary match keeps "elastic" from matching "inelastic".
        pattern = r"\b" + re.escape(vendor) + r"\b"
        if re.search(pattern, lowered) and vendor not in seen:
            hits.append(vendor)
            seen.add(vendor)
    return hits


def _detect_vendor_soup(sections: Mapping[str, str]) -> KernelViolation | None:
    pool = "\n".join(
        sections.get(name, "") for name in ("Constraints", "Capabilities")
    )
    hits = _vendor_hits(pool)
    if len(hits) >= 3:
        joined = ", ".join(hits[:5])
        return KernelViolation(
            code="vendor-soup",
            evidence=f"Constraints/Capabilities chain {len(hits)} vendors: {joined}",
        )
    return None


def _domain_hits(text: str) -> set[str]:
    lowered = text.lower()
    hit_domains: set[str] = set()
    for domain, vocab in _DOMAIN_VOCABULARIES.items():
        for token in vocab:
            if token in lowered:
                hit_domains.add(domain)
                break
    return hit_domains


def _detect_mixed_concerns(
    sections: Mapping[str, str],
) -> KernelViolation | None:
    capabilities = sections.get("Capabilities", "")
    if not capabilities.strip():
        return None
    domains = _domain_hits(capabilities)
    if len(domains) >= 3:
        joined = ", ".join(sorted(domains))
        return KernelViolation(
            code="mixed-concerns",
            evidence=f"Capabilities span {len(domains)} disjoint domains: {joined}",
        )
    return None


# Registry preserves the deterministic ``VIOLATION_TYPES`` order, so
# ``classify_kernel`` returns results in that order regardless of which
# rules fire.
_DETECTORS: tuple[
    tuple[str, "callable[[Mapping[str, str]], KernelViolation | None]"], ...
] = (
    ("mixed-concerns", _detect_mixed_concerns),
    ("non-falsifiable", _detect_non_falsifiable),
    ("solution-disguised", _detect_solution_disguised),
    ("vendor-soup", _detect_vendor_soup),
)


def classify_kernel(kernel: object) -> list[KernelViolation]:
    """Classify a kernel against the four violation categories.

    ``kernel`` may be either:

    * a Markdown string with H2 section headings, or
    * a mapping of ``{section_name: body}`` strings.

    Returns a list of ``KernelViolation`` records, in the deterministic
    order declared by ``VIOLATION_TYPES``. A clean kernel returns an
    empty list.
    """
    sections = _normalize_input(kernel)
    violations: list[KernelViolation] = []
    for _code, detector in _DETECTORS:
        result = detector(sections)
        if result is not None:
            violations.append(result)
    return violations
