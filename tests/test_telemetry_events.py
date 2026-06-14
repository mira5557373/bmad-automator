from __future__ import annotations

import json
import unittest
from typing import Any

from story_automator.core.telemetry_events import (
    Event,
    UnknownEvent,
    StoryStarted,
    StoryCompleted,
    StoryFailed,
    StoryDeferred,
    RetryAttempt,
    EscalationTriggered,
    ReviewCycle,
    RetroFired,
    TmuxSessionSpawned,
    TmuxSessionCompleted,
    TmuxSessionCrashed,
    CostCharged,
    BudgetAlert,
    parse_event,
)


class TestEventRegistry(unittest.TestCase):
    """Test Event base class, registration, and registry structure."""


class TestEventSerialization(unittest.TestCase):
    """Test to_dict and to_json_line methods."""


class TestParseEvent(unittest.TestCase):
    """Test parse_event function with all branches and error cases."""


class TestRoundTrip(unittest.TestCase):
    """Test round-trip invariant: construct → to_json_line → parse_event."""


if __name__ == "__main__":
    unittest.main()
