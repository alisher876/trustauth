# Keystroke experiments (M3)

Prototype scripts for the keystroke-rhythm factor. They use heavy libraries (scikit-learn, pandas) that
are not in the backend Docker image, so run them in a local virtual environment.

## 1. Dataset: CMU Keystroke Dynamics Benchmark

- **Source:** Killourhy & Maxion, *"Comparing Anomaly-Detection Algorithms for Keystroke Dynamics"*,
  DSN 2009. Page: <https://www.cs.cmu.edu/~keystroke/>
- **File:** `DSL-StrongPasswordData.csv` (about 4.5 MB, 20,400 rows)
- **Where it goes:** `datasets/cmu-keystroke/DSL-StrongPasswordData.csv` at the repository root.
  `datasets/` is git-ignored: **never commit the dataset**.

Download (Git Bash, from the repository root):

```sh
mkdir -p datasets/cmu-keystroke
curl -L -o datasets/cmu-keystroke/DSL-StrongPasswordData.csv \
  https://www.cs.cmu.edu/~keystroke/DSL-StrongPasswordData.csv
```

### What is in it

51 subjects typed the same password `.tie5Roanl` followed by Return, 400 times each
(8 sessions × 50 repetitions, at least one day between sessions). One row = one repetition.

| Column(s) | Meaning |
|---|---|
| `subject` | Subject ID, e.g. `s002` (51 subjects; IDs are not consecutive) |
| `sessionIndex` | 1–8 |
| `rep` | 1–50 within the session |
| `H.<key>` (11) | **Hold** time of a key: key-up − key-down |
| `DD.<a>.<b>` (10) | **Down-down** time: key-down of `b` − key-down of `a` |
| `UD.<a>.<b>` (10) | **Up-down** time: key-down of `b` − key-up of `a` (negative if the keys overlap) |

All times are in **seconds**. Keys are named `period`, `t`, `i`, `e`, `five`, `Shift.r` (capital R),
`o`, `a`, `n`, `l`, `Return`. The order is `H.period, DD.period.t, UD.period.t, H.t, …, H.Return`
(31 features). Our [`features.py`](../features.py) produces exactly this order and unit from browser
key events, so models tested here can be used on our own data later.

## 2. Setup

```sh
python -m venv .venv
.venv\Scripts\activate                 # Windows PowerShell;  source .venv/bin/activate on macOS/Linux
pip install -r backend/app/factors/keystroke/experiments/requirements.txt
```

## 3. Baseline: `baseline_cmu.py`

Compares three anomaly detectors with the **paper's evaluation protocol**:

- for each subject: train on the first 200 repetitions;
- genuine test = that subject's remaining 200 repetitions;
- imposter test = first 5 repetitions of each of the other 50 subjects (250 samples);
- EER per subject (where false-accept rate = false-reject rate), then mean and standard deviation.

```sh
python backend/app/factors/keystroke/experiments/baseline_cmu.py                # full run (~20 s)
python backend/app/factors/keystroke/experiments/baseline_cmu.py --subjects 5   # quick check
python backend/app/factors/keystroke/experiments/baseline_cmu.py --train 20     # only 20 training samples
```

### Results (51 subjects, run on 2026-11-19)

| Detector | EER, train = 200 | train = 50 | train = 20 | train = 10 | Paper (train = 200) |
|---|---|---|---|---|---|
| Manhattan (scaled) | **0.096** ± 0.070 | 0.154 ± 0.105 | 0.197 ± 0.122 | 0.229 ± 0.138 | 0.096 |
| One-Class SVM | 0.102 ± 0.065 | 0.161 ± 0.102 | 0.184 ± 0.111 | 0.207 ± 0.123 | 0.102 |
| Isolation Forest | **0.085** ± 0.066 | 0.133 ± 0.091 | 0.179 ± 0.101 | 0.243 ± 0.134 | — |

Values are mean ± standard deviation over the 51 subjects. With `--train` < 200 the test sets stay the
same (repetitions 201–400), so the training samples all come from session 1 and the test samples from
sessions 5–8. This is realistic (enrollment happens once, logins happen days later) but pessimistic.

**What this tells us:**

1. Our Manhattan and One-Class SVM numbers match the paper, so the protocol is implemented correctly.
2. Isolation Forest is the best with many samples, but it is ~20× slower and the worst with 10 samples.
3. With the number of samples a real user will give at enrollment (10–20), the EER is about **0.18–0.23**.
   Keystroke rhythm is therefore a **weak** factor on its own; this is expected and will show up as a
   lower trust value. It should improve if the model is updated with accepted logins (see
   [`../DESIGN.md`](../DESIGN.md)).

### Detectors

| Detector | Model | Anomaly score (higher = less like the user) |
|---|---|---|
| Manhattan (scaled) | per-feature mean `μ` and mean absolute deviation `a` | `Σ |x − μ| / a` |
| One-Class SVM | `StandardScaler` + `OneClassSVM(kernel="rbf", nu=0.5, gamma="scale")` | `−decision_function(x)` |
| Isolation Forest | `IsolationForest(n_estimators=200, random_state=0)` | `−score_samples(x)` |

How the anomaly score becomes `FactorResult.score` (0–1, higher = more genuine) is described in
[`../DESIGN.md`](../DESIGN.md#4-score-and-threshold).
