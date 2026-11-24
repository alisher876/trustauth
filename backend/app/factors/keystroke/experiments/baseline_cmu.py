"""Baseline keystroke detectors on the CMU Keystroke Benchmark.

Reproduces the evaluation protocol of Killourhy & Maxion (2009),
"Comparing Anomaly-Detection Algorithms for Keystroke Dynamics", DSN 2009:

    for each of the 51 subjects:
        train   = that subject's first 200 repetitions
        genuine = that subject's remaining 200 repetitions
        imposter = first 5 repetitions of each of the other 50 subjects (250)
        EER     = error rate where false-accept rate == false-reject rate
    report mean and standard deviation of the EER over subjects

Every detector outputs an *anomaly score*: higher = less like the genuine user.

Run (from the repository root, in a venv with experiments/requirements.txt):

    python backend/app/factors/keystroke/experiments/baseline_cmu.py
    python backend/app/factors/keystroke/experiments/baseline_cmu.py --subjects 5   # quick run
    python backend/app/factors/keystroke/experiments/baseline_cmu.py --train 10     # few enrollment samples
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import roc_curve
from sklearn.preprocessing import StandardScaler
from sklearn.svm import OneClassSVM

REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_DATA = REPO_ROOT / "datasets" / "cmu-keystroke" / "DSL-StrongPasswordData.csv"

N_TRAIN = 200  # genuine repetitions used for training (paper protocol)
GENUINE_TEST_START = 200  # genuine test set is always repetitions 201-400
N_IMPOSTER_REPS = 5  # repetitions taken from each other subject
RANDOM_STATE = 0  # fixed seed so results are reproducible


# --- Detectors ---------------------------------------------------------------
# Each detector is a pair: fit(train) -> model, score(model, X) -> anomaly scores.


class ScaledManhattan:
    """Reference detector from the paper (reported EER about 0.096).

    Model: per-feature mean and mean absolute deviation of the training samples.
    Score: sum over features of |x - mean| / mean_abs_deviation.
    """

    name = "Manhattan (scaled)"

    def fit(self, train: np.ndarray) -> "ScaledManhattan":
        self.mean = train.mean(axis=0)
        self.mad = np.abs(train - self.mean).mean(axis=0)
        self.mad[self.mad == 0] = 1e-9  # avoid division by zero for a constant feature
        return self

    def score(self, X: np.ndarray) -> np.ndarray:
        return (np.abs(X - self.mean) / self.mad).sum(axis=1)


class OneClassSVMDetector:
    """One-class SVM (RBF kernel) on standardised features.

    scikit-learn's decision_function is positive for inliers, so the anomaly
    score is its negative.
    """

    name = "One-Class SVM"

    def fit(self, train: np.ndarray) -> "OneClassSVMDetector":
        self.scaler = StandardScaler().fit(train)
        self.model = OneClassSVM(kernel="rbf", nu=0.5, gamma="scale").fit(self.scaler.transform(train))
        return self

    def score(self, X: np.ndarray) -> np.ndarray:
        return -self.model.decision_function(self.scaler.transform(X))


class IsolationForestDetector:
    """Isolation Forest: anomalies are isolated by fewer random splits.

    score_samples is higher for normal points, so the anomaly score is its negative.
    """

    name = "Isolation Forest"

    def fit(self, train: np.ndarray) -> "IsolationForestDetector":
        self.model = IsolationForest(n_estimators=200, random_state=RANDOM_STATE).fit(train)
        return self

    def score(self, X: np.ndarray) -> np.ndarray:
        return -self.model.score_samples(X)


DETECTORS = [ScaledManhattan, OneClassSVMDetector, IsolationForestDetector]


# --- Evaluation --------------------------------------------------------------


def equal_error_rate(genuine_scores: np.ndarray, imposter_scores: np.ndarray) -> float:
    """EER from anomaly scores (higher = more anomalous).

    We treat "imposter" as the positive class. For every threshold:
        false positive rate = genuine samples flagged as imposter = FRR
        false negative rate = imposters let through               = FAR
    The EER is where they are equal; on finite data we take the threshold where
    they are closest and report their average.
    """
    labels = np.concatenate([np.zeros(len(genuine_scores)), np.ones(len(imposter_scores))])
    scores = np.concatenate([genuine_scores, imposter_scores])
    frr, tpr, _ = roc_curve(labels, scores)
    far = 1 - tpr
    i = np.argmin(np.abs(frr - far))
    return float((frr[i] + far[i]) / 2)


def load_cmu(path: Path) -> tuple[pd.DataFrame, list[str]]:
    """Load the CSV; return the data and the 31 feature column names."""
    if not path.exists():
        raise SystemExit(
            f"Dataset not found: {path}\n"
            "Download it as described in backend/app/factors/keystroke/experiments/README.md"
        )
    data = pd.read_csv(path)
    feature_columns = list(data.columns[3:])  # first 3 columns: subject, sessionIndex, rep
    return data, feature_columns


def evaluate(data: pd.DataFrame, feature_columns: list[str], detector_cls, subjects: list[str],
             n_train: int = N_TRAIN) -> list[float]:
    """Run the Killourhy & Maxion protocol for one detector; return EER per subject.

    `n_train` < 200 trains on only the first n_train repetitions (to estimate how
    many enrollment samples we need); the test sets stay the same.
    """
    eers = []
    for subject in subjects:
        own = data.loc[data["subject"] == subject, feature_columns].to_numpy()
        train, genuine = own[:n_train], own[GENUINE_TEST_START:]
        imposter = (
            data[data["subject"] != subject]
            .groupby("subject")
            .head(N_IMPOSTER_REPS)[feature_columns]
            .to_numpy()
        )
        detector = detector_cls().fit(train)
        eers.append(equal_error_rate(detector.score(genuine), detector.score(imposter)))
    return eers


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="path to DSL-StrongPasswordData.csv")
    parser.add_argument("--subjects", type=int, default=None, help="only use the first N subjects (quick run)")
    parser.add_argument("--train", type=int, default=N_TRAIN, choices=range(2, N_TRAIN + 1), metavar="2..200",
                        help="number of training (enrollment) repetitions per subject; default 200 as in the paper")
    args = parser.parse_args()

    data, feature_columns = load_cmu(args.data)
    subjects = list(data["subject"].unique())[: args.subjects]
    print(f"{len(subjects)} subjects, {len(feature_columns)} features, "
          f"train={args.train}, genuine test={400 - GENUINE_TEST_START}, imposter test={N_IMPOSTER_REPS * (len(data['subject'].unique()) - 1)}\n")

    print(f"{'Detector':<22}{'EER mean':>10}{'EER std':>10}{'time (s)':>10}")
    for detector_cls in DETECTORS:
        started = time.perf_counter()
        eers = evaluate(data, feature_columns, detector_cls, subjects, args.train)
        elapsed = time.perf_counter() - started
        print(f"{detector_cls.name:<22}{np.mean(eers):>10.3f}{np.std(eers):>10.3f}{elapsed:>10.1f}")


if __name__ == "__main__":
    main()
