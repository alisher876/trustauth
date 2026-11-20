"""Evaluation metrics for TrustAuth factors (M1, Trust Measurement Lab).

Definitions are in trust-lab/docs/metrics.md. All functions are pure (no I/O)
so they can be unit-tested and reused by notebooks and evaluation scripts.

Score convention (docs/interface.md, FactorResult.score):
    score is in 0..1 and HIGHER = MORE LIKE THE GENUINE USER.
    A factor accepts an attempt when  score >= threshold.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Sequence

import numpy as np

# Error codes (docs/interface.md §5) that mean "the factor could not run at all".
# They count against availability. timeout and cancelled are the user's choice
# or slowness, so they count against usability instead (see metrics.md).
UNAVAILABLE_ERRORS = frozenset({"unavailable", "internal", "bad_payload"})

DEFAULT_WEIGHTS = {"accuracy": 0.35, "attack_resistance": 0.35, "usability": 0.15, "availability": 0.15}
SPEED_LIMIT_MS = 30_000  # 30 s: an attempt this slow or slower gets speed score 0


def _as_array(values: Iterable[float], name: str) -> np.ndarray:
    array = np.asarray(list(values), dtype=float)
    if array.size == 0:
        raise ValueError(f"{name} must not be empty")
    return array


# --- Accuracy: FAR, FRR, DET curve, EER -------------------------------------


def far(imposter_scores: Iterable[float], threshold: float) -> float:
    """False accept rate: share of imposter attempts with score >= threshold."""
    imposter = _as_array(imposter_scores, "imposter_scores")
    return float(np.mean(imposter >= threshold))


def frr(genuine_scores: Iterable[float], threshold: float) -> float:
    """False reject rate: share of genuine attempts with score < threshold."""
    genuine = _as_array(genuine_scores, "genuine_scores")
    return float(np.mean(genuine < threshold))


def det_curve(genuine_scores: Iterable[float], imposter_scores: Iterable[float]):
    """FAR and FRR at every useful threshold (every observed score, plus one above the maximum).

    Returns (thresholds, far_values, frr_values) as numpy arrays, thresholds ascending.
    As the threshold rises, FAR falls and FRR rises. Plot FRR against FAR for a DET curve.
    """
    genuine = _as_array(genuine_scores, "genuine_scores")
    imposter = _as_array(imposter_scores, "imposter_scores")
    all_scores = np.unique(np.concatenate([genuine, imposter]))
    thresholds = np.append(all_scores, np.inf)  # inf = reject everything (FAR 0, FRR 1)
    far_values = np.array([np.mean(imposter >= t) for t in thresholds])
    frr_values = np.array([np.mean(genuine < t) for t in thresholds])
    return thresholds, far_values, frr_values


def eer(genuine_scores: Iterable[float], imposter_scores: Iterable[float]) -> tuple[float, float]:
    """Equal error rate and the threshold where it happens.

    On finite data FAR and FRR are rarely exactly equal, so we take the threshold
    where |FAR - FRR| is smallest and report (FAR + FRR) / 2 there.
    Returns (eer, threshold).
    """
    thresholds, far_values, frr_values = det_curve(genuine_scores, imposter_scores)
    i = int(np.argmin(np.abs(far_values - frr_values)))
    return float((far_values[i] + frr_values[i]) / 2), float(thresholds[i])


# --- Rates from accepted flags -----------------------------------------------


def acceptance_rate(accepted: Iterable[bool]) -> float:
    """Share of attempts that were accepted.

    Used for the attack success rate (on attack rows of one attack_type) and the
    genuine success rate (on genuine rows).
    """
    flags = _as_array(accepted, "accepted")
    return float(np.mean(flags))


def attack_success_rate(accepted: Iterable[bool]) -> float:
    """Attack attempts accepted / attack attempts (pass the rows of one attack_type)."""
    return acceptance_rate(accepted)


def genuine_success_rate(accepted: Iterable[bool]) -> float:
    """Genuine attempts accepted / genuine attempts."""
    return acceptance_rate(accepted)


def availability(errors: Iterable[str | None]) -> float:
    """Share of attempts where the factor could run (error not in UNAVAILABLE_ERRORS)."""
    error_list = list(errors)
    if not error_list:
        raise ValueError("errors must not be empty")
    could_run = [e not in UNAVAILABLE_ERRORS for e in error_list]
    return float(np.mean(could_run))


def speed_score(median_duration_ms: float, limit_ms: float = SPEED_LIMIT_MS) -> float:
    """1 - time / 30 s, clipped to 0..1 (CLAUDE.md §6)."""
    if median_duration_ms < 0:
        raise ValueError("duration must be >= 0")
    return float(max(0.0, 1.0 - median_duration_ms / limit_ms))


# --- Trust score ---------------------------------------------------------------


def trust_score(sub_scores: dict[str, float], weights: dict[str, float] | None = None) -> float:
    """Weighted sum of the four sub-scores (CLAUDE.md §6).

    sub_scores keys: accuracy, attack_resistance, usability, availability (each 0..1).
    weights default to 0.35 / 0.35 / 0.15 / 0.15 and must sum to 1.
    """
    weights = DEFAULT_WEIGHTS if weights is None else weights
    if set(sub_scores) != set(DEFAULT_WEIGHTS) or set(weights) != set(DEFAULT_WEIGHTS):
        raise ValueError(f"keys must be exactly {sorted(DEFAULT_WEIGHTS)}")
    if not np.isclose(sum(weights.values()), 1.0):
        raise ValueError("weights must sum to 1")
    for name, value in sub_scores.items():
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be in 0..1, got {value}")
    return float(sum(weights[k] * sub_scores[k] for k in DEFAULT_WEIGHTS))


# --- Confidence intervals and predictability -----------------------------------


def bootstrap_ci(
    values: Sequence,
    statistic: Callable[[np.ndarray], float],
    n_resamples: int = 1000,
    confidence: float = 0.95,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile bootstrap confidence interval for statistic(values).

    Resample the rows with replacement n_resamples times, compute the statistic
    each time, and take the 2.5th and 97.5th percentiles (for 95%).
    `values` can be a 1-D array or an array of rows; the fixed seed makes results reproducible.
    """
    data = np.asarray(values)
    if len(data) == 0:
        raise ValueError("values must not be empty")
    rng = np.random.default_rng(seed)
    stats = [statistic(data[rng.integers(0, len(data), len(data))]) for _ in range(n_resamples)]
    alpha = (1 - confidence) / 2
    low, high = np.quantile(stats, [alpha, 1 - alpha])
    return float(low), float(high)


def shannon_entropy(items: Iterable) -> float:
    """Shannon entropy in bits of the distribution of items.

    For predictability, items are e.g. the selected factor sets of a user's logins
    as tuples: [("passkey", "face"), ("password", "keystroke"), ...].
    0 bits = always the same choice; higher = harder to predict.
    """
    counts = np.array(list(Counter(items).values()), dtype=float)
    if counts.size == 0:
        raise ValueError("items must not be empty")
    p = counts / counts.sum()
    return float(-(p * np.log2(p)).sum() + 0.0)  # + 0.0 turns -0.0 into 0.0
