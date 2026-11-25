"""Factor selection.

Week 3 has only the FIXED selector, so the challenge loop can be built and tested.
The adaptive selector (trust x context fit - repetition penalty, weighted random
choice, category diversity; CLAUDE.md §7) replaces it in week 6.

Pure functions: no database, no Redis, no randomness here.
"""

from __future__ import annotations

# Order of preference for the fixed selector, and for picking a replacement when a factor fails.
# Keystroke is not selected on its own: it only rides along with password (interface §6.3),
# which the challenge loop adds in a later week.
FIXED_ORDER = ("password", "passkey", "face", "phone_approval")

# How many factors to ask for. Week 3: always 2. From week 5 this depends on the risk level.
DEFAULT_K = 2


def candidates(usable: list[str]) -> list[str]:
    """The usable factors (enrolled AND available here) that may be selected, in preference order."""
    return [name for name in FIXED_ORDER if name in usable]


def select_fixed(usable: list[str], k: int = DEFAULT_K) -> list[str]:
    """Fixed selector: the first k usable factors in FIXED_ORDER.

    Returns fewer than k if fewer are usable (the caller decides what to do then).
    """
    if k < 1:
        raise ValueError("k must be at least 1")
    return candidates(usable)[:k]
