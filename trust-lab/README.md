# Trust Measurement Lab (M1)

Measures how trustworthy each TrustAuth factor really is and produces the **trust table** the adaptive
engine uses (`output/trust_table.json`, format in [`docs/interface.md`](../docs/interface.md) §8).

Owner: **M1, Sayfiddinov Doniyor**. Other members do not edit this folder; they suggest changes in a PR
comment or at the meeting.

## Folders

| Folder | What goes there |
|---|---|
| `docs/` | Method documents: [`metrics.md`](docs/metrics.md) (every metric and how it is computed), [`threat-model.md`](docs/threat-model.md) (who attacks what), [`attack-protocol.md`](docs/attack-protocol.md) (how each attack test is run), [`attempt-log.md`](docs/attempt-log.md) (the log columns and labels), [`trust-formula.md`](docs/trust-formula.md) (trust v0 and the placeholder table) |
| `src/trustlab/` | Python code used by the notebooks and scripts. [`metrics.py`](src/trustlab/metrics.py): FAR, FRR, EER, DET curve, attack success, availability, trust score, bootstrap CI, entropy. [`attempts.py`](src/trustlab/attempts.py): log columns and genuine / imposter / attack split. [`trust.py`](src/trustlab/trust.py): sub-scores, trust, trust table. [`evaluation.py`](src/trustlab/evaluation.py): FAR / FRR / EER per factor × condition, operating points, DET plots, loading the CSV export |
| `scripts/` | Command-line scripts. [`make_placeholder_table.py`](scripts/make_placeholder_table.py): writes the placeholder trust table. [`evaluate.py`](scripts/evaluate.py): evaluation tables and DET curves |
| `tests/` | Unit tests for `src/trustlab/` (`pytest`) |
| `notebooks/` | Jupyter notebooks for exploring data and making charts. Clear outputs that show personal data before committing |
| `output/` | Results that other modules read: `trust_table.json` (placeholder until week 11, see [`trust-formula.md`](docs/trust-formula.md) §3; then measured) |

Data never goes in this folder. Exported attempt logs, LFW, CMU and volunteer data live in the
repository-level `datasets/` and `data/` folders, which are git-ignored (CLAUDE.md §13).

## Setup

Python 3.11, in a local virtual environment (from the repository root):

```sh
python -m venv .venv
.venv\Scripts\activate                     # Windows PowerShell;  source .venv/bin/activate on macOS/Linux
pip install -r trust-lab/requirements.txt
```

## Run the tests

```sh
cd trust-lab
pytest
```

Expected: all tests pass (`33 passed`).

## Make the trust table

```sh
python trust-lab/scripts/make_placeholder_table.py      # placeholder (until real data exists)
```

From a real attempt-log export, see [`docs/attempt-log.md`](docs/attempt-log.md) §3.

## Evaluate: FAR / FRR / EER and DET curves (week 5)

```sh
python trust-lab/scripts/evaluate.py demo                                   # synthetic data, to see the output
python trust-lab/scripts/evaluate.py log data/exports/attempts-<date>.csv  # the platform's attempt log
python trust-lab/scripts/evaluate.py scores data/lfw/scores.csv --name face-lfw   # label,score[,condition]
```

Prints one row per factor × condition (and `all`): number of genuine / imposter attempts, FAR and FRR at
the platform's own decisions, EER and its threshold (biometric factors), and the worst attack's success
rate. Saves `evaluation.csv` and `det_<factor>.png` under `data/evaluation/<name>/` (git-ignored). The
`scores` mode also reports the threshold and FRR at FAR 0.1 % and 1 % (the face threshold rule in
`face/DESIGN.md` §3), and is what weeks 6–7 use for LFW and CMU.

## Use the metrics

```python
from trustlab.metrics import eer, far, frr, trust_score

genuine = [0.91, 0.85, 0.40]     # FactorResult.score of genuine attempts
imposter = [0.10, 0.35, 0.62]    # FactorResult.score of imposter attempts
rate, threshold = eer(genuine, imposter)
```

Scores follow the interface convention: 0–1, **higher = more like the genuine user**, accepted when
`score >= threshold`.
