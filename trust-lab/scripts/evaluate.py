"""Evaluation script (M1, week 5): FAR / FRR / EER tables and DET curves.

Run from the repository root (the trust-lab environment, see trust-lab/README.md):

    # 1. the platform's attempt log (GET /admin/attempts.csv, saved under data/exports/)
    python trust-lab/scripts/evaluate.py log data/exports/attempts-2026-12-01.csv

    # 2. scores from a dataset run: a CSV with columns label (genuine / imposter), score [, condition]
    python trust-lab/scripts/evaluate.py scores data/lfw/face_scores.csv --name face-lfw

    # 3. try it without any data: a synthetic attempt log, clearly marked as synthetic
    python trust-lab/scripts/evaluate.py demo

Results go to data/evaluation/<name>/ (git-ignored, because they come from volunteer data):
    evaluation.csv          the table printed on screen
    det_<factor>.png        DET curve, one line per condition (biometric factors only)
Copy a figure into the report only when it is final; never commit the exports themselves.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # so "trustlab" can be imported

from trustlab.attempts import BINARY_FACTORS  # noqa: E402
from trustlab.evaluation import det_inputs, evaluate_log, load_attempts, plot_det, score_report  # noqa: E402

DEFAULT_OUT = Path("data/evaluation")


def _print_table(table: pd.DataFrame) -> None:
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(table.to_string(index=False, float_format=lambda v: f"{v:.3f}", na_rep="-"))


def run_log(attempts: pd.DataFrame, out: Path, synthetic: bool = False) -> pd.DataFrame:
    table = evaluate_log(attempts)
    if table.empty:
        sys.exit("No labelled study rows (is_genuine is empty everywhere). Was the study label set?")
    out.mkdir(parents=True, exist_ok=True)
    table.to_csv(out / "evaluation.csv", index=False)
    _print_table(table)
    note = " (SYNTHETIC DEMO DATA)" if synthetic else ""
    for factor in sorted(set(table["factor"]) - BINARY_FACTORS):
        curves = det_inputs(attempts, factor)
        if curves:
            path = plot_det(curves, out / f"det_{factor}.png", f"DET: {factor}{note}")
            print(f"\nDET curve: {path}")
    print(f"table: {out / 'evaluation.csv'}")
    print("FAR / FRR = at the platform's own decisions; EER from the scores (biometric factors only); "
          "attack rows are counted separately (worst attack type).")
    return table


def run_scores(path: Path, name: str, out: Path) -> None:
    scores = pd.read_csv(path)
    if not {"label", "score"} <= set(scores.columns):
        sys.exit("the scores CSV needs the columns: label (genuine / imposter), score [, condition]")
    labels = scores["label"].str.strip().str.lower()
    if not set(labels) <= {"genuine", "imposter"}:
        sys.exit(f"label must be 'genuine' or 'imposter', found: {sorted(set(labels))}")
    scores = scores.assign(label=labels)
    if "condition" not in scores.columns:
        scores["condition"] = "all"

    rows, curves = [], {}
    for condition, cell in scores.groupby("condition", sort=True):
        genuine = cell.loc[cell["label"] == "genuine", "score"].to_numpy(float)
        imposter = cell.loc[cell["label"] == "imposter", "score"].to_numpy(float)
        if len(genuine) == 0 or len(imposter) == 0:
            print(f"skipping condition {condition!r}: needs genuine AND imposter scores")
            continue
        rows.append({"condition": condition, **score_report(genuine, imposter)})
        curves[str(condition)] = (genuine, imposter)
    if not rows:
        sys.exit("nothing to evaluate")

    out.mkdir(parents=True, exist_ok=True)
    table = pd.DataFrame(rows)
    table.to_csv(out / "evaluation.csv", index=False)
    _print_table(table)
    print(f"\nDET curve: {plot_det(curves, out / f'det_{name}.png', f'DET: {name}')}")
    print(f"table: {out / 'evaluation.csv'}")


def synthetic_attempts(seed: int = 0) -> pd.DataFrame:
    """A made-up attempt log with the real columns, to try the script before real data exists.

    Face is made worse in dim light and on the phone, keystroke overlaps more than face, password and
    passkey are binary, and a few attacks and errors are mixed in, so every part of the output shows up.
    """
    rng = np.random.default_rng(seed)
    rows = []

    def add(factor, condition, n, genuine, scores, threshold, attack_type=None, error_rate=0.0):
        for score in scores:
            error = "unavailable" if rng.random() < error_rate else None
            score = float(np.clip(score, 0, 1))
            accepted = error is None and score >= threshold
            rows.append({"factor": factor, "condition": condition, "score": score if error is None else 0.0,
                         "accepted": accepted, "duration_ms": int(rng.integers(1500, 6000)), "error": error,
                         "is_genuine": genuine, "attack_type": attack_type})

    face_quality = {"laptop_normal": 0.62, "laptop_dim": 0.52, "phone_normal": 0.58, "phone_dim": 0.45}
    for condition, mean in face_quality.items():
        add("face", condition, 60, True, rng.normal(mean, 0.14, 60), 0.35, error_rate=0.03)
        add("face", condition, 60, False, rng.normal(0.18, 0.10, 60), 0.35)
        add("face", condition, 20, False, rng.normal(0.30, 0.10, 20), 0.35, attack_type="printed_photo")
    for condition in ("laptop_normal", "phone_normal"):
        add("keystroke", condition, 80, True, rng.beta(6, 3, 80), 0.5)
        add("keystroke", condition, 80, False, rng.beta(3, 5, 80), 0.5, attack_type="imposter_typing")
        add("password", condition, 50, True, (rng.random(50) > 0.04).astype(float), 0.5)
        add("password", condition, 50, False, np.zeros(50), 0.5)
        add("passkey", condition, 40, True, (rng.random(40) > 0.02).astype(float), 0.5)
        add("passkey", condition, 20, False, np.zeros(20), 0.5, attack_type="passkey_phishing")
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)
    log = sub.add_parser("log", help="evaluate an attempt-log CSV export")
    log.add_argument("csv", type=Path)
    log.add_argument("--name", default=None, help="results folder name (default: the CSV file name)")
    scores = sub.add_parser("scores", help="evaluate a label,score CSV from a dataset run")
    scores.add_argument("csv", type=Path)
    scores.add_argument("--name", required=True, help="e.g. face-lfw, keystroke-cmu")
    sub.add_parser("demo", help="synthetic data, to see what the output looks like")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="parent folder for results (git-ignored)")
    args = parser.parse_args()

    if args.mode == "log":
        run_log(load_attempts(args.csv), args.out / (args.name or args.csv.stem))
    elif args.mode == "scores":
        run_scores(args.csv, args.name, args.out / args.name)
    else:
        print("SYNTHETIC DEMO DATA: made-up numbers, not results.\n")
        run_log(synthetic_attempts(), args.out / "demo", synthetic=True)


if __name__ == "__main__":
    main()
