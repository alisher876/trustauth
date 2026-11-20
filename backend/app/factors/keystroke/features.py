"""Keystroke feature extraction: browser key events -> timing feature vector.

This module is a *pure* function library (no I/O, no database, no global state),
so it can be unit-tested and reused by the baseline experiment and, later, by
the real keystroke factor.

Input (the proposed `verify()` payload, see keystroke/DESIGN.md):

    {"events": [
        {"key": "t", "type": "down", "t": 0.0},
        {"key": "t", "type": "up",   "t": 95.3},
        {"key": "i", "type": "down", "t": 180.1},
        ...
    ]}

`t` is milliseconds from `performance.now()` in the browser.

Output: a list of floats in the same order and unit (seconds) as the CMU
Keystroke Benchmark (Killourhy & Maxion, 2009). For keystrokes k0, k1, ..., kn:

    H.k0, DD.k0.k1, UD.k0.k1, H.k1, DD.k1.k2, UD.k1.k2, ..., H.kn

    H  (hold)       = up(k)        - down(k)
    DD (down-down)  = down(k+1)    - down(k)
    UD (up-down)    = down(k+1)    - up(k)      (negative when keys overlap)

So n keystrokes give 3n - 2 features (11 keystrokes -> 31 features, like CMU).

Privacy: the vector contains timings only, never the typed characters.
`feature_names()` produces CMU-style names (which do contain characters); it is
only meant for comparing with the CMU dataset and must not be stored per user.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Modifier keys produce their own key events but are not keystrokes of the
# password itself. CMU also ignores them: capital R is one keystroke "Shift.r".
MODIFIER_KEYS = frozenset({"Shift", "Control", "Alt", "AltGraph", "Meta", "CapsLock"})

# Editing keys mean the user corrected a typo. The rhythm is then not a clean
# sample, so we refuse it and the UI asks the user to retype.
EDITING_KEYS = frozenset({"Backspace", "Delete", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown",
                          "Home", "End"})

MS_PER_SECOND = 1000.0


class FeatureError(ValueError):
    """The events cannot be turned into features. The factor maps this to `bad_payload`."""


@dataclass(frozen=True)
class Keystroke:
    """One physical key press: when it went down and when it came up (milliseconds)."""

    key: str
    down: float
    up: float


def _normalise_key(key: str) -> str:
    """Make key-down and key-up of the same key comparable.

    A key-up may report "r" while its key-down reported "R" (Shift released first),
    so single characters are compared in lower case.
    """
    return key.lower() if len(key) == 1 else key


def _validate_event(event: object, index: int) -> tuple[str, str, float]:
    """Check one event's shape and return (key, type, t). Raises FeatureError."""
    if not isinstance(event, dict):
        raise FeatureError(f"event {index} is not an object")
    key, kind, t = event.get("key"), event.get("type"), event.get("t")
    if not isinstance(key, str) or not key:
        raise FeatureError(f"event {index}: 'key' must be a non-empty string")
    if kind not in ("down", "up"):
        raise FeatureError(f"event {index}: 'type' must be 'down' or 'up'")
    # bool is a subclass of int in Python, so exclude it explicitly.
    if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0:
        raise FeatureError(f"event {index}: 't' must be a finite number >= 0")
    return key, kind, float(t)


def events_to_keystrokes(events: list[dict]) -> list[Keystroke]:
    """Pair each key-down with its key-up, in the order the keys were pressed.

    Rules:
    - modifier keys (Shift, ...) are skipped;
    - an editing key (Backspace, arrows, ...) makes the sample invalid;
    - a repeated key-down while the key is still held (auto-repeat) is ignored;
    - a key-up with no earlier key-down is ignored (the key was pressed before
      the password field had focus);
    - a key-down with no key-up is an error (sample incomplete).
    """
    if not isinstance(events, list) or not events:
        raise FeatureError("'events' must be a non-empty list")

    parsed = [_validate_event(e, i) for i, e in enumerate(events)]
    # Sort by time; Python's sort is stable, so equal times keep their original order.
    parsed.sort(key=lambda item: item[2])

    finished: list[Keystroke] = []
    held: dict[str, tuple[str, float]] = {}  # normalised key -> (original key, down time)

    for key, kind, t in parsed:
        if key in MODIFIER_KEYS:
            continue
        if key in EDITING_KEYS:
            raise FeatureError("sample contains editing keys; ask the user to retype")
        norm = _normalise_key(key)
        if kind == "down":
            if norm not in held:  # ignore auto-repeat
                held[norm] = (key, t)
        else:  # "up"
            if norm in held:
                original_key, down_t = held.pop(norm)
                finished.append(Keystroke(original_key, down_t, t))
            # else: stray key-up, ignore

    if held:
        raise FeatureError("some keys were pressed but never released")

    # Order keystrokes by when they were pressed (key-ups can arrive out of order
    # when keys overlap, e.g. "n" released after "l" was pressed).
    finished.sort(key=lambda k: k.down)
    return finished


def keystrokes_to_features(keystrokes: list[Keystroke]) -> list[float]:
    """Turn keystrokes into the CMU-ordered vector [H0, DD01, UD01, H1, ..., Hn] in seconds."""
    if not keystrokes:
        raise FeatureError("no keystrokes")

    features: list[float] = []
    for i, current in enumerate(keystrokes):
        features.append((current.up - current.down) / MS_PER_SECOND)  # H
        if i + 1 < len(keystrokes):
            following = keystrokes[i + 1]
            features.append((following.down - current.down) / MS_PER_SECOND)  # DD
            features.append((following.down - current.up) / MS_PER_SECOND)  # UD
    return features


def extract_features(events: list[dict], expected_keys: int | None = None) -> list[float]:
    """Main entry point: browser key events -> CMU-ordered timing features (seconds).

    `expected_keys` (optional): the number of keystrokes the password should have.
    If given and the count differs, the sample is rejected, because vectors of
    different lengths cannot be compared with the user's model.
    """
    keystrokes = events_to_keystrokes(events)
    if expected_keys is not None and len(keystrokes) != expected_keys:
        raise FeatureError(f"expected {expected_keys} keystrokes, got {len(keystrokes)}")
    return keystrokes_to_features(keystrokes)


def n_keys_from_features(features: list[float]) -> int:
    """Number of keystrokes behind a vector (inverse of 3n - 2). Used for FactorResult.context.n_keys."""
    return (len(features) + 2) // 3


# --- CMU naming, only for comparing with the dataset -------------------------

_CMU_KEY_NAMES = {
    ".": "period",
    "\n": "Return",
    "Enter": "Return",
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
    "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
}


def cmu_key_name(key: str) -> str:
    """CMU name of one key: '.' -> 'period', '5' -> 'five', 'R' -> 'Shift.r', Enter -> 'Return'."""
    if key in _CMU_KEY_NAMES:
        return _CMU_KEY_NAMES[key]
    if len(key) == 1 and key.isupper():
        return f"Shift.{key.lower()}"
    return key


def feature_names(keys: list[str]) -> list[str]:
    """CMU-style column names for a key sequence, e.g. ['H.period', 'DD.period.t', ...]."""
    names = [cmu_key_name(k) for k in keys]
    columns: list[str] = []
    for i, name in enumerate(names):
        columns.append(f"H.{name}")
        if i + 1 < len(names):
            columns.append(f"DD.{name}.{names[i + 1]}")
            columns.append(f"UD.{name}.{names[i + 1]}")
    return columns
