"""Trust formula v0 (week 3): attempt log -> four sub-scores -> trust -> trust table.

    Trust = 0.35 * Accuracy + 0.35 * AttackResistance + 0.15 * Usability + 0.15 * Availability

Definitions are in docs/metrics.md §3 and docs/trust-formula.md. Output format is
docs/interface.md §8 (trust_table.json), read by the M4 engine.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from trustlab.attempts import (
    BINARY_FACTORS,
    attack_rows,
    decided,
    genuine_rows,
    imposter_rows,
    validate_attempts,
)
from trustlab.metrics import availability, bootstrap_ci, eer, speed_score, trust_score

# A sub-score with no data yet counts as 0.5 ("unknown"), the same neutral value the
# engine uses for a factor missing from the trust table (interface §8).
UNKNOWN = 0.5


def accuracy(rows: pd.DataFrame, factor: str) -> float | None:
    """1 - EER for biometric factors; 1 - (FAR + FRR) / 2 for binary factors. None if no data."""
    rows = decided(rows)
    genuine, imposter = genuine_rows(rows), imposter_rows(rows, factor)
    if genuine.empty or imposter.empty:
        return None
    if factor in BINARY_FACTORS:
        false_accept = imposter["accepted"].astype(float).mean()
        false_reject = 1.0 - genuine["accepted"].astype(float).mean()
        return float(1.0 - (false_accept + false_reject) / 2)
    rate, _ = eer(genuine["score"], imposter["score"])
    return 1.0 - rate


def attack_resistance(rows: pd.DataFrame) -> float | None:
    """1 - success rate of the factor's WORST attack type (an attacker picks the best attack)."""
    attacks = attack_rows(rows)
    if attacks.empty:
        return None
    worst = attacks.groupby("attack_type")["accepted"].apply(lambda a: a.astype(float).mean()).max()
    return float(1.0 - worst)


def usability(rows: pd.DataFrame) -> float | None:
    """Mean of the speed score (median time of accepted genuine attempts) and the genuine success rate."""
    genuine = genuine_rows(rows)
    if genuine.empty:
        return None
    success = genuine["accepted"].astype(float).mean()
    accepted = genuine[genuine["accepted"] == True]  # noqa: E712
    speed = speed_score(float(accepted["duration_ms"].median())) if not accepted.empty else 0.0
    return float((speed + success) / 2)


def sub_scores(rows: pd.DataFrame, factor: str) -> dict[str, float | None]:
    """The four sub-scores for the rows of ONE factor x condition. None = no data yet."""
    return {
        "accuracy": accuracy(rows, factor),
        "attack_resistance": attack_resistance(rows),
        "usability": usability(rows),
        "availability": availability(list(rows["error"])) if len(rows) else None,
    }


def trust_from_rows(rows: pd.DataFrame, factor: str, weights: dict[str, float] | None = None) -> float:
    """Trust of one factor x condition. Missing sub-scores count as UNKNOWN (0.5)."""
    subs = {k: (UNKNOWN if v is None else v) for k, v in sub_scores(rows, factor).items()}
    return trust_score(subs, weights)


def build_trust_table(attempts: pd.DataFrame, n_resamples: int = 1000, seed: int = 0,
                      weights: dict[str, float] | None = None, version: str | None = None) -> dict:
    """Trust table (interface §8) from an attempt log: trust, 95% bootstrap CI and n per factor x condition.

    The CI resamples the attempt rows of each factor x condition with replacement
    (row-level bootstrap, metrics.md §4) and recomputes the trust each time.
    """
    rows = validate_attempts(attempts)
    table: dict[str, dict] = {}
    for (factor, condition), group in rows.groupby(["factor", "condition"], sort=True):
        group = group.reset_index(drop=True)
        value = trust_from_rows(group, factor, weights)
        low, high = bootstrap_ci(np.arange(len(group)),
                                 lambda idx: trust_from_rows(group.iloc[idx], factor, weights),
                                 n_resamples=n_resamples, seed=seed)
        table.setdefault(factor, {})[condition] = {
            "trust": round(value, 3), "ci": [round(low, 3), round(high, 3)], "n": int(len(group)),
        }
    return {"version": version or date.today().isoformat(), "factors": table}


def write_trust_table(table: dict, path: str | Path) -> None:
    """Save the table as JSON (what the engine loads at start-up)."""
    Path(path).write_text(json.dumps(table, indent=2) + "\n", encoding="utf-8")
