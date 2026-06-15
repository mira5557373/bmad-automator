"""Failure-triage taxonomy foundation for bmad-automator (M07a).

This module defines the pure-data substrate that downstream triage
(M07b classify dispatch), adaptive retry (M08), gate decisions (M09),
and the retrospective summariser (M10) consume:

- ``FailureClass`` — the closed 13-member taxonomy of failure shapes.
- ``Confidence`` — three-level confidence ordinal (HIGH/MEDIUM/LOW).
- ``Classification`` — frozen, kw-only result record paired with each
  failure-shaped event.
- ``IMPLIES_GRAPH`` — the static implication edges between members of
  ``FailureClass``. Runtime classifiers may extend the per-event
  ``implies`` tuple based on payload hints (e.g. transport hints on a
  tmux crash) — those extensions live in ``classify`` (M07b) and are
  not encoded here.

M07a is data-only: no ``classify`` function, no dispatch logic, no I/O,
no third-party imports. The classify dispatch and per-event helpers
land in M07b.
"""

from __future__ import annotations


import enum


class FailureClass(enum.Enum):
    """Closed taxonomy of failure shapes consumed by triage.

    Exactly thirteen members. Declaration order is the canonical order
    asserted by the taxonomy-completeness gate (REQ-02). String values
    equal the member name so JSONL serialisations in M07b round-trip
    cleanly.
    """

    CRASH = "CRASH"
    TIMEOUT = "TIMEOUT"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    REVIEW_REJECTED = "REVIEW_REJECTED"
    TEST_FAILURE = "TEST_FAILURE"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    PARSE_ERROR = "PARSE_ERROR"
    AGENT_REFUSED = "AGENT_REFUSED"
    NETWORK_ERROR = "NETWORK_ERROR"
    GATE_DEFER = "GATE_DEFER"
    PLATEAU = "PLATEAU"
    REPEATED_RETRY = "REPEATED_RETRY"
    UNKNOWN = "UNKNOWN"


class Confidence(enum.Enum):
    """Three-level confidence ordinal for a classification.

    Case-sensitive member names mirror the value strings; serialisations
    in M07b emit the bare member name so downstream policy engines (M08
    adaptive retry, M09 gate) can match on string equality without
    needing to import this enum.
    """

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
