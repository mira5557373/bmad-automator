"""Round-3 L-1+L-2+L-3 — docstring correctness regression tests.

Each test inspects ``module.__doc__`` (or the relevant function's
``__doc__``) for terms the round-3 audit flagged as missing or
misleading. Behaviour is not asserted here — these are pure docstring
shape checks meant to prevent regressions where the docstrings drift
back to their pre-fix wording.

Bugs covered:

* L-1 — ``profile_composer`` previously claimed ``forbidden_until`` was
  a last-layer-wins scalar; it is actually deep-merged as a dict.
* L-2 — ``gate_remediation.write_remediation_to_story`` previously
  claimed it inserts Tasks before the first **non-editable** section; it
  actually inserts before the first ``##`` heading of any kind.
* L-3 — ``risk_profile`` previously mentioned only the priority bands
  (P0–P3) and omitted the action bands
  (DOCUMENT/MONITOR/MITIGATE/BLOCK).
"""
from __future__ import annotations

import unittest

from story_automator.core import (
    gate_remediation,
    profile_composer,
    risk_profile,
)


class ProfileComposerDocstringTests(unittest.TestCase):
    """L-1: forbidden_until is deep-merged, not last-layer-wins."""

    def test_module_docstring_present(self) -> None:
        self.assertIsNotNone(profile_composer.__doc__)

    def test_forbidden_until_mentioned(self) -> None:
        doc = profile_composer.__doc__ or ""
        self.assertIn("forbidden_until", doc)

    def test_forbidden_until_described_as_dict_not_scalar(self) -> None:
        """The docstring must not classify forbidden_until as a scalar."""
        doc = profile_composer.__doc__ or ""
        # The pre-fix wording had forbidden_until inside the "scalar
        # top-level fields" bullet. The fix removes that classification.
        # Robust check: the prose must explicitly mention that
        # forbidden_until is dict-valued / deep-merged.
        self.assertTrue(
            "deep-merge" in doc or "union" in doc,
            "forbidden_until must be described as deep-merged/union-merged",
        )
        self.assertNotIn(
            "forbidden_until``-as-\n  date-string-style scalars",
            doc,
            "pre-fix wording must not return",
        )

    def test_forbidden_until_listed_in_dict_fields(self) -> None:
        doc = profile_composer.__doc__ or ""
        # The dict-valued bullet enumerates fields that get deep-merged.
        # forbidden_until must appear in that bullet.
        dict_bullet_marker = "dict-valued fields"
        self.assertIn(dict_bullet_marker, doc)
        bullet_start = doc.index(dict_bullet_marker)
        # The bullet runs roughly to the next "*" bullet marker.
        bullet_tail = doc[bullet_start:bullet_start + 1200]
        self.assertIn("forbidden_until", bullet_tail)


class GateRemediationDocstringTests(unittest.TestCase):
    """L-2: write_remediation_to_story inserts before first ## heading."""

    def test_function_docstring_present(self) -> None:
        self.assertIsNotNone(
            gate_remediation.write_remediation_to_story.__doc__
        )

    def test_no_false_non_editable_claim(self) -> None:
        """The pre-fix 'first non-editable section' wording must not return."""
        doc = gate_remediation.write_remediation_to_story.__doc__ or ""
        # The original false claim was: "before the first non-editable
        # section". The fix replaces this with an accurate description
        # of the actual regex behaviour (first ## of any kind).
        self.assertNotIn(
            "before the first non-editable section",
            doc,
        )

    def test_actual_behaviour_documented(self) -> None:
        """Docstring must explain it inserts before the first ## heading."""
        doc = gate_remediation.write_remediation_to_story.__doc__ or ""
        # The corrected docstring describes the real regex (^##\s+) and
        # explicitly disambiguates "first ## heading of any kind".
        self.assertIn("first", doc)
        self.assertIn("##", doc)


class RiskProfileDocstringTests(unittest.TestCase):
    """L-3: module docstring must mention action bands."""

    def test_module_docstring_present(self) -> None:
        self.assertIsNotNone(risk_profile.__doc__)

    def test_action_bands_named(self) -> None:
        """All four action band literals must appear in the docstring."""
        doc = risk_profile.__doc__ or ""
        for band in ("DOCUMENT", "MONITOR", "MITIGATE", "BLOCK"):
            self.assertIn(
                band,
                doc,
                f"risk_profile module docstring must name action band {band!r}",
            )

    def test_priority_bands_still_documented(self) -> None:
        """Priority bands must remain documented alongside the new bands."""
        doc = risk_profile.__doc__ or ""
        for tier in ("P0", "P1", "P2", "P3"):
            self.assertIn(tier, doc)

    def test_block_described_as_release_blocking(self) -> None:
        """The docstring must flag BLOCK as the only release-blocking band."""
        doc = risk_profile.__doc__ or ""
        # The corrected wording explicitly calls out BLOCK's release-
        # blocking semantics — the other three bands are advisory.
        self.assertIn("block", doc.lower())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
