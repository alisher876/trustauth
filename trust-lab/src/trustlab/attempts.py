"""Attempt-log format (docs/interface.md §9) and how rows are split for analysis.

The core writes one row per factor attempt into the PostgreSQL table `attempts`;
M1 exports it to CSV/Parquet and loads it into a pandas DataFrame. This module
checks the columns and splits rows into genuine / imposter / attack, following
docs/metrics.md §1.
"""

from __future__ import annotations

import pandas as pd

# Columns the analysis needs. The table has more (attempt_id, login_id, timestamp, context, ...).
REQUIRED_COLUMNS = (
    "factor", "accepted", "score", "duration_ms", "error",
    "is_genuine", "attack_type", "condition",
)

# Factors whose score is only 1.0 / 0.0 (interface §5): EER is not meaningful for them.
BINARY_FACTORS = frozenset({"password", "passkey", "phone_approval"})

# For keystroke, "an imposter types the correct password" is both the normal imposter case
# (accuracy) and an attack (attack resistance). metrics.md §1, the only exception.
IMPOSTER_ATTACKS = {"keystroke": "imposter_typing"}


def validate_attempts(df: pd.DataFrame) -> pd.DataFrame:
    """Check the required columns exist; return only the labelled study rows.

    Rows with is_genuine = null come from normal use outside study sessions and are
    excluded from every metric (metrics.md §5, Q5).
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"attempt log is missing columns: {missing}")
    return df[df["is_genuine"].notna()].copy()


def _no_error(rows: pd.DataFrame) -> pd.Series:
    return rows["error"].isna()


def genuine_rows(rows: pd.DataFrame) -> pd.DataFrame:
    """The real user trying normally."""
    return rows[(rows["is_genuine"] == True) & rows["attack_type"].isna()]  # noqa: E712 (pandas needs ==)


def imposter_rows(rows: pd.DataFrame, factor: str) -> pd.DataFrame:
    """A different real person making a normal attempt (plus imposter_typing for keystroke)."""
    plain = (rows["is_genuine"] == False) & rows["attack_type"].isna()  # noqa: E712
    special = IMPOSTER_ATTACKS.get(factor)
    if special is not None:
        plain = plain | ((rows["is_genuine"] == False) & (rows["attack_type"] == special))  # noqa: E712
    return rows[plain]


def attack_rows(rows: pd.DataFrame) -> pd.DataFrame:
    """Crafted attacks: any row with an attack_type code."""
    return rows[(rows["is_genuine"] == False) & rows["attack_type"].notna()]  # noqa: E712


def decided(rows: pd.DataFrame) -> pd.DataFrame:
    """Rows where the factor ran and gave a decision (error = null). Used for accuracy."""
    return rows[_no_error(rows)]
