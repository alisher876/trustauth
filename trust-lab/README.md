# Trust Measurement Lab (M1)

Measures how trustworthy each TrustAuth factor really is and produces the **trust table** the adaptive
engine uses (`output/trust_table.json`, format in [`docs/interface.md`](../docs/interface.md) §7).

Owner: **M1, Sayfiddinov Doniyor**. Other members do not edit this folder; they suggest changes in a PR
comment or at the meeting.

## Folders

| Folder | What goes there |
|---|---|
| `docs/` | Method documents: [`metrics.md`](docs/metrics.md) (every metric and how it is computed), [`threat-model.md`](docs/threat-model.md) (who attacks what), [`attack-protocol.md`](docs/attack-protocol.md) (how each attack test is run) |
| `src/trustlab/` | Python code used by the notebooks and scripts. [`metrics.py`](src/trustlab/metrics.py): FAR, FRR, EER, DET curve, attack success, availability, trust score, bootstrap CI, entropy |
| `tests/` | Unit tests for `src/trustlab/` (`pytest`) |
| `notebooks/` | Jupyter notebooks for exploring data and making charts. Clear outputs that show personal data before committing |
| `output/` | Results that other modules read: `trust_table.json` (from week 11; a placeholder from published error rates before that) |

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

Expected: all tests pass (`14 passed`).

## Use the metrics

```python
from trustlab.metrics import eer, far, frr, trust_score

genuine = [0.91, 0.85, 0.40]     # FactorResult.score of genuine attempts
imposter = [0.10, 0.35, 0.62]    # FactorResult.score of imposter attempts
rate, threshold = eer(genuine, imposter)
```

Scores follow the interface convention: 0–1, **higher = more like the genuine user**, accepted when
`score >= threshold`.
