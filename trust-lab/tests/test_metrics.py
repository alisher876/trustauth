"""Unit tests for trustlab.metrics on small synthetic data where the answer is known."""

import numpy as np
import pytest

from trustlab.metrics import (
    attack_success_rate,
    availability,
    bootstrap_ci,
    det_curve,
    eer,
    far,
    frr,
    genuine_success_rate,
    shannon_entropy,
    speed_score,
    trust_score,
)

GENUINE = [0.9, 0.8, 0.7, 0.6, 0.3]  # one genuine attempt scores low
IMPOSTER = [0.1, 0.2, 0.4, 0.5, 0.65]  # one imposter attempt scores high


def test_far_counts_imposters_at_or_above_threshold():
    assert far(IMPOSTER, 0.5) == pytest.approx(0.4)  # 0.5 and 0.65
    assert far(IMPOSTER, 0.0) == 1.0
    assert far(IMPOSTER, 1.0) == 0.0


def test_frr_counts_genuine_below_threshold():
    assert frr(GENUINE, 0.5) == pytest.approx(0.2)  # 0.3
    assert frr(GENUINE, 0.0) == 0.0
    assert frr(GENUINE, 0.95) == 1.0


def test_perfectly_separated_scores_have_zero_eer():
    rate, threshold = eer([0.8, 0.9, 1.0], [0.1, 0.2, 0.3])
    assert rate == 0.0
    assert 0.3 < threshold <= 0.8


def test_overlapping_scores_eer():
    # At threshold 0.6: FAR = 1/5 (0.65), FRR = 1/5 (0.3) -> EER 0.2
    rate, threshold = eer(GENUINE, IMPOSTER)
    assert rate == pytest.approx(0.2)
    assert far(IMPOSTER, threshold) == pytest.approx(frr(GENUINE, threshold))


def test_identical_distributions_give_eer_around_half():
    rng = np.random.default_rng(1)
    scores = rng.random(2000)
    rate, _ = eer(scores[:1000], scores[1000:])
    assert rate == pytest.approx(0.5, abs=0.05)


def test_det_curve_is_monotonic():
    thresholds, far_values, frr_values = det_curve(GENUINE, IMPOSTER)
    assert np.all(np.diff(thresholds) > 0)
    assert np.all(np.diff(far_values) <= 0)
    assert np.all(np.diff(frr_values) >= 0)
    assert far_values[-1] == 0.0 and frr_values[-1] == 1.0


def test_rates_from_accepted_flags():
    assert attack_success_rate([False] * 19 + [True]) == pytest.approx(0.05)
    assert genuine_success_rate([True, True, True, False]) == pytest.approx(0.75)


def test_availability_counts_only_could_not_run_errors():
    errors = [None, None, "timeout", "unavailable", None, "cancelled", "internal", None]
    assert availability(errors) == pytest.approx(6 / 8)


def test_speed_score_is_clipped():
    assert speed_score(0) == 1.0
    assert speed_score(15_000) == pytest.approx(0.5)
    assert speed_score(60_000) == 0.0


def test_trust_score_default_weights():
    subs = {"accuracy": 0.9, "attack_resistance": 0.8, "usability": 0.7, "availability": 1.0}
    expected = 0.35 * 0.9 + 0.35 * 0.8 + 0.15 * 0.7 + 0.15 * 1.0
    assert trust_score(subs) == pytest.approx(expected)


def test_trust_score_rejects_bad_input():
    subs = {"accuracy": 0.9, "attack_resistance": 0.8, "usability": 0.7, "availability": 1.0}
    with pytest.raises(ValueError):
        trust_score({**subs, "accuracy": 1.5})
    with pytest.raises(ValueError):
        trust_score(subs, {"accuracy": 0.5, "attack_resistance": 0.5, "usability": 0.5, "availability": 0.5})
    with pytest.raises(ValueError):
        trust_score({"accuracy": 0.9})


def test_bootstrap_ci_contains_the_mean_and_is_reproducible():
    rng = np.random.default_rng(2)
    flags = rng.random(500) < 0.9  # about 90% success
    low, high = bootstrap_ci(flags, np.mean)
    assert low < flags.mean() < high
    assert high - low < 0.1
    assert bootstrap_ci(flags, np.mean) == (low, high)  # same seed, same answer


def test_shannon_entropy():
    assert shannon_entropy(["a"] * 10) == 0.0
    assert shannon_entropy(["a", "b"] * 5) == pytest.approx(1.0)
    assert shannon_entropy([("passkey", "face"), ("password",), ("x",), ("y",)]) == pytest.approx(2.0)


def test_empty_input_raises():
    with pytest.raises(ValueError):
        far([], 0.5)
    with pytest.raises(ValueError):
        eer([0.5], [])
