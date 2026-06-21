"""Pre-gate sub-checks invoked by collectors.

Each check module is a stdlib-only rubric exposed as a small, pure API so
collectors can import the verdict logic without re-implementing parsing.
"""

from __future__ import annotations
