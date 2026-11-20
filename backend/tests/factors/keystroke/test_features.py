"""Unit tests for app.factors.keystroke.features (pure functions, no I/O)."""

import pytest

from app.factors.keystroke.features import (
    FeatureError,
    extract_features,
    feature_names,
    n_keys_from_features,
)

# The 31 feature columns of DSL-StrongPasswordData.csv, in file order.
CMU_COLUMNS = (
    "H.period,DD.period.t,UD.period.t,H.t,DD.t.i,UD.t.i,H.i,DD.i.e,UD.i.e,H.e,DD.e.five,UD.e.five,"
    "H.five,DD.five.Shift.r,UD.five.Shift.r,H.Shift.r,DD.Shift.r.o,UD.Shift.r.o,H.o,DD.o.a,UD.o.a,"
    "H.a,DD.a.n,UD.a.n,H.n,DD.n.l,UD.n.l,H.l,DD.l.Return,UD.l.Return,H.Return"
).split(",")

CMU_KEYS = [".", "t", "i", "e", "5", "R", "o", "a", "n", "l", "Enter"]


def press(key, down, up):
    """Two events for one key press (times in ms)."""
    return [{"key": key, "type": "down", "t": down}, {"key": key, "type": "up", "t": up}]


def typed(keys, start=0.0, gap=200.0, hold=100.0):
    """Events for keys typed one after another without overlap."""
    events = []
    for i, key in enumerate(keys):
        down = start + i * gap
        events += press(key, down, down + hold)
    return events


def test_two_keys_give_hold_dd_ud_in_seconds():
    events = press("a", 0, 100) + press("b", 250, 330)

    assert extract_features(events) == pytest.approx([0.100, 0.250, 0.150, 0.080])


def test_cmu_password_gives_31_features_in_cmu_order():
    features = extract_features(typed(CMU_KEYS))

    assert len(features) == 31
    assert feature_names(CMU_KEYS) == CMU_COLUMNS
    # Every H is the hold (0.1 s), every DD the gap (0.2 s), every UD gap - hold.
    named = dict(zip(CMU_COLUMNS, features))
    assert named["H.Shift.r"] == pytest.approx(0.1)
    assert named["DD.five.Shift.r"] == pytest.approx(0.2)
    assert named["UD.l.Return"] == pytest.approx(0.1)


def test_n_keys_is_inverse_of_feature_count():
    assert n_keys_from_features([0.0] * 31) == 11
    assert n_keys_from_features([0.0]) == 1


def test_shift_is_ignored_and_capital_matches_lowercase_keyup():
    # Shift down, R down, Shift up, r up (browser reports lower-case after Shift is released).
    events = [
        {"key": "Shift", "type": "down", "t": 0},
        {"key": "R", "type": "down", "t": 50},
        {"key": "Shift", "type": "up", "t": 90},
        {"key": "r", "type": "up", "t": 140},
    ]

    assert extract_features(events) == pytest.approx([0.090])


def test_overlapping_keys_give_negative_ud():
    # "b" is pressed before "a" is released (fast typists do this).
    events = [
        {"key": "a", "type": "down", "t": 0},
        {"key": "b", "type": "down", "t": 80},
        {"key": "a", "type": "up", "t": 120},
        {"key": "b", "type": "up", "t": 200},
    ]

    assert extract_features(events) == pytest.approx([0.120, 0.080, -0.040, 0.120])


def test_events_out_of_order_are_sorted_by_time():
    events = press("a", 0, 100) + press("b", 250, 330)

    assert extract_features(list(reversed(events))) == extract_features(events)


def test_auto_repeat_and_stray_keyup_are_ignored():
    events = [
        {"key": "x", "type": "up", "t": 0},  # released before the field had focus
        {"key": "a", "type": "down", "t": 10},
        {"key": "a", "type": "down", "t": 60},  # auto-repeat
        {"key": "a", "type": "up", "t": 110},
    ]

    assert extract_features(events) == pytest.approx([0.100])


def test_expected_keys_mismatch_is_rejected():
    with pytest.raises(FeatureError):
        extract_features(typed(["a", "b"]), expected_keys=3)


@pytest.mark.parametrize(
    "events",
    [
        [],
        "not a list",
        [{"key": "a", "type": "down", "t": 0}],  # never released
        typed(["a", "Backspace", "b"]),  # user corrected a typo
        [{"key": "a", "type": "press", "t": 0}],  # unknown type
        [{"key": "", "type": "down", "t": 0}],  # empty key
        [{"key": "a", "type": "down", "t": -5}],  # negative time
        [{"key": "a", "type": "down", "t": float("nan")}],
        [{"key": "a", "type": "down", "t": True}],  # bool is not a time
        ["a"],  # not an object
    ],
)
def test_malformed_input_raises_feature_error(events):
    with pytest.raises(FeatureError):
        extract_features(events)
