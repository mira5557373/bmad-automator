"""Innovation moats: deterministic post-hoc analyses over factory output.

Modules here MUST be self-contained, stdlib-only, and side-effect free at
import time. They are layered on top of the factory's collector + evidence
output so the runtime can keep evolving without breaking analytical tools.
"""

from __future__ import annotations
