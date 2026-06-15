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
