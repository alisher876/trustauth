"""Evaluation script core (week 5): FAR / FRR / EER per factor x condition, and DET curves.

Two kinds of input, the same numbers out:

1. The attempt log (docs/interface.md §9, exported by GET /admin/attempts.csv): the platform's own
   decisions. evaluate_log() gives one row per factor x condition (plus "all" per factor).
2. Plain scores from a dataset run (LFW face pairs in week 6, CMU keystroke in week 7):
   score_report() on two lists, genuine and imposter scores.

Definitions follow docs/metrics.md §3 and use trustlab.metrics; the genuine / imposter / attack split
follows trustlab.attempts (metrics.md §1). Score convention: 0..1, higher = more genuine, accept if
score >= threshold.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from trustlab.attempts import BINARY_FACTORS, attack_rows, decided, genuine_rows, imposter_rows, validate_attempts
from trustlab.metrics import det_curve, eer

# Operating points reported for biometric factors: the threshold where FAR is at most this.
# 0.1 % is the face target in face/DESIGN.md §3 (security first); 1 % is a common second point.
TARGET_FARS = (0.001, 0.01)
ALL_CONDITIONS = "all"

BOOL_COLUMNS = ("accepted", "is_genuine")
_TRUE = {"true", "1", "t", "yes"}
_FALSE = {"false", "0", "f", "no"}


# --- loading the export --------------------------------------------------------------------------


def _to_bool(value):
    """CSV text -> True / False / None. Empty cells (study label not set) become None."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    if text == "":
        return None
    raise ValueError(f"not a boolean: {value!r}")


def load_attempts(path: str | Path) -> pd.DataFrame:
    """Read an attempt-log CSV export and give every column its proper type.

    The export writes empty cells for null and "True"/"False" for booleans. pandas guesses types per
    column, which differs between files (a column with blanks stays text), so the types are set here.
    """
    df = pd.read_csv(path, dtype={"error": "string", "attack_type": "string", "condition": "string",
                                  "factor": "string"}, keep_default_na=True)
    for column in BOOL_COLUMNS:
        if column in df.columns:
            df[column] = df[column].map(_to_bool).astype("object")
    for column in ("error", "attack_type"):
        if column in df.columns:
            df[column] = df[column].astype("object").where(df[column].notna(), None)
    df["score"] = df["score"].astype(float)
    return df


# --- scores: EER, operating points ------------------------------------------------------------------


def threshold_at_far(imposter_scores: Iterable[float], target_far: float,
                     genuine_scores: Iterable[float] = ()) -> tuple[float, float]:
    """The LOWEST threshold whose FAR is at most `target_far`, and the FAR there.

    Lowest, because among all thresholds that keep FAR low enough it rejects the fewest genuine users.
    Candidate thresholds are the observed scores (genuine and imposter), as in det_curve. With n
    imposter scores FAR moves in steps of 1/n, so a target below 1/n can only be met by rejecting
    every imposter seen (FAR = 0, which says little with small n: report n with it).
    """
    if not 0.0 <= target_far <= 1.0:
        raise ValueError("target_far must be in 0..1")
    imposter = np.asarray(list(imposter_scores), dtype=float)
    genuine = np.asarray(list(genuine_scores), dtype=float)
    if imposter.size == 0:
        raise ValueError("imposter_scores must not be empty")
    candidates = np.append(np.unique(np.concatenate([genuine, imposter])), np.inf)
    for threshold in candidates:  # ascending: FAR only falls as the threshold rises
        far_here = float(np.mean(imposter >= threshold))
        if far_here <= target_far:
            return float(threshold), far_here
    raise AssertionError("unreachable: the infinite threshold has FAR 0")


def score_report(genuine_scores: Sequence[float], imposter_scores: Sequence[float],
                 target_fars: Sequence[float] = TARGET_FARS) -> dict:
    """EER and operating points for one set of genuine and imposter scores (e.g. LFW pairs)."""
    genuine = np.asarray(list(genuine_scores), dtype=float)
    imposter = np.asarray(list(imposter_scores), dtype=float)
    rate, threshold = eer(genuine, imposter)
    report = {"n_genuine": int(genuine.size), "n_imposter": int(imposter.size),
              "eer": rate, "eer_threshold": threshold}
    for target in target_fars:
        t, actual_far = threshold_at_far(imposter, target, genuine)
        report[f"threshold_at_far_{target:g}"] = t
        report[f"far_at_far_{target:g}"] = actual_far
        report[f"frr_at_far_{target:g}"] = float(np.mean(genuine < t))
    return report


# --- the attempt log: one row per factor x condition -----------------------------------------------


def _cell(rows: pd.DataFrame, factor: str, condition: str) -> dict:
    """Numbers for the attempts of one factor in one condition (or all conditions)."""
    ran = decided(rows)  # accuracy uses only attempts that gave a decision (error = null)
    genuine, imposter = genuine_rows(ran), imposter_rows(ran, factor)
    accepted_g = genuine["accepted"].astype(bool)
    accepted_i = imposter["accepted"].astype(bool)
    row = {
        "factor": factor,
        "condition": condition,
        "n_genuine": len(genuine),
        "n_imposter": len(imposter),
        # At the threshold the platform used (its accept / reject decisions):
        "far": float(accepted_i.mean()) if len(imposter) else np.nan,
        "frr": float(1.0 - accepted_g.mean()) if len(genuine) else np.nan,
        "eer": np.nan,
        "eer_threshold": np.nan,
    }
    # EER needs real scores on both sides; binary factors (1.0 / 0.0) report FAR and FRR only (metrics.md §2).
    if factor not in BINARY_FACTORS and len(genuine) and len(imposter):
        row["eer"], row["eer_threshold"] = eer(genuine["score"], imposter["score"])

    attacks = attack_rows(rows)
    row["n_attack"] = len(attacks)
    if len(attacks):
        success = attacks.groupby("attack_type")["accepted"].apply(lambda a: a.astype(bool).mean())
        row["worst_attack"] = str(success.idxmax())
        row["worst_attack_success"] = float(success.max())
    else:
        row["worst_attack"], row["worst_attack_success"] = np.nan, np.nan
    return row


def evaluate_log(attempts: pd.DataFrame) -> pd.DataFrame:
    """FAR / FRR / EER / attack success per factor x condition, plus an "all" row per factor.

    Only labelled study rows count (validate_attempts drops rows with is_genuine = null).
    """
    rows = validate_attempts(attempts)
    table = []
    for factor, by_factor in rows.groupby("factor", sort=True):
        for condition, cell in by_factor.groupby("condition", sort=True):
            table.append(_cell(cell, str(factor), str(condition)))
        table.append(_cell(by_factor, str(factor), ALL_CONDITIONS))
    columns = ["factor", "condition", "n_genuine", "n_imposter", "far", "frr", "eer", "eer_threshold",
               "n_attack", "worst_attack", "worst_attack_success"]
    return pd.DataFrame(table, columns=columns)


def det_inputs(attempts: pd.DataFrame, factor: str) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """{condition: (genuine scores, imposter scores)} of one factor, for plot_det. Skips empty sides."""
    rows = decided(validate_attempts(attempts))
    rows = rows[rows["factor"] == factor]
    curves = {}
    for condition, cell in rows.groupby("condition", sort=True):
        genuine, imposter = genuine_rows(cell)["score"], imposter_rows(cell, factor)["score"]
        if len(genuine) and len(imposter):
            curves[str(condition)] = (genuine.to_numpy(float), imposter.to_numpy(float))
    return curves


# --- DET plot ------------------------------------------------------------------------------------------

DET_TICKS = (0.001, 0.01, 0.05, 0.2, 0.5)  # 0.1 %, 1 %, 5 %, 20 %, 50 %
_EPS = 1e-4  # rates of exactly 0 or 1 have no place on a probit axis: clip them to the plot edge


def _probit(rates):
    from scipy.stats import norm

    return norm.ppf(np.clip(rates, _EPS, 1 - _EPS))


def plot_det(curves: dict[str, tuple[Sequence[float], Sequence[float]]], path: str | Path, title: str) -> Path:
    """Save a DET curve: FRR against FAR on normal-deviate (probit) axes, one line per label.

    Probit axes are the standard for DET plots (Martin et al., 1997): they stretch the low-error corner,
    and normally distributed scores give straight lines. The EER of each line is marked with a dot.
    """
    import matplotlib

    matplotlib.use("Agg")  # draw to a file, no window (works on servers and in tests)
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(5.5, 5.5))
    for label, (genuine, imposter) in curves.items():
        _, far_values, frr_values = det_curve(genuine, imposter)
        rate, _ = eer(genuine, imposter)
        ax.plot(_probit(far_values), _probit(frr_values), label=f"{label} (EER {rate:.1%}, n={len(genuine)}+{len(imposter)})")
        ax.plot(_probit([rate]), _probit([rate]), "o", color=ax.lines[-1].get_color())
    ticks = _probit(np.array(DET_TICKS))
    names = [f"{t:.1%}".replace(".0%", "%") for t in DET_TICKS]
    ax.set_xticks(ticks, names)
    ax.set_yticks(ticks, names)
    limit = _probit(np.array([0.0005, 0.6]))
    ax.set_xlim(*limit)
    ax.set_ylim(*limit)
    ax.plot(limit, limit, ":", color="grey", linewidth=0.8)  # FAR = FRR: each EER dot sits on this line
    ax.set_xlabel("False accept rate (FAR)")
    ax.set_ylabel("False reject rate (FRR)")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, loc="upper right")
    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path
