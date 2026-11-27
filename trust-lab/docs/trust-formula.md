# Trust formula v0 (M1, week 3)

| | |
|---|---|
| **Status** | v0, week 3. Weights fixed at 0.35 / 0.35 / 0.15 / 0.15; AHP weights in weeks 8–11 |
| **Code** | [`src/trustlab/trust.py`](../src/trustlab/trust.py), tested in [`tests/test_trust.py`](../tests/test_trust.py) |
| **Input** | Attempt log ([`attempt-log.md`](attempt-log.md)) |
| **Output** | `output/trust_table.json` in the format of `docs/interface.md` §8 |

## 1. Formula

For every **factor × condition** (e.g. `face` × `phone_dim`):

```
Trust = 0.35 · Accuracy + 0.35 · AttackResistance + 0.15 · Usability + 0.15 · Availability
```

| Sub-score | v0 computation (rows of one factor × condition) |
|---|---|
| **Accuracy** | Rows with `error = null` only. Biometric (face, keystroke): `1 − EER` of genuine vs imposter `score`. Binary (password, passkey, phone approval): `1 − (FAR + FRR) / 2` from `accepted` |
| **Attack resistance** | `1 − success rate of the worst attack_type` for this factor (an attacker uses the best attack) |
| **Usability** | Mean of the **speed score** `max(0, 1 − median_time / 30 s)` (median `duration_ms` of accepted genuine attempts) and the **genuine success rate** (all genuine rows, errors included) |
| **Availability** | Share of rows whose `error` is not `unavailable`, `internal` or `bad_payload` |

Exact row selection (genuine / imposter / attack, the keystroke `imposter_typing` exception, unlabelled rows
excluded) is in [`metrics.md`](metrics.md) §1 and implemented in [`attempts.py`](../src/trustlab/attempts.py).

## 2. Decisions in v0

1. **Missing data.** A sub-score with no rows yet (e.g. no attack trials so far) counts as **0.5 =
   "unknown"**. The same value is the engine's default for a factor missing from the table
   (interface §8). Neither good nor bad, so a factor is not rewarded for being untested.
2. **Worst attack, not average.** Attack resistance uses the attack type with the highest success rate.
   An average would hide a single attack that works.
3. **95% CI.** Row-level percentile bootstrap: resample the rows of the factor × condition with replacement
   1000 times, recompute trust each time, take the 2.5th and 97.5th percentiles, seed 0. User-level
   bootstrap follows for the final results (metrics.md §4).
4. **`n`** = number of labelled rows behind the value. `n = 0` marks a placeholder value.

## 3. Placeholder table (until week 11)

The engine needs a trust table before any measurement exists. `scripts/make_placeholder_table.py` fills
**only accuracy**, from sources; the other three sub-scores are 0.5 (unknown). All conditions get the same
value because there is no per-condition data yet.

| Factor | Accuracy | Source | Trust |
|---|---|---|---|
| password | 1.000 | Exact match, no false accepts/rejects by design | 0.675 |
| passkey | 1.000 | Signature check, no false accepts/rejects by design | 0.675 |
| phone_approval | 1.000 | Explicit approve/deny (laptop conditions only) | 0.675 |
| face | 0.998 | ArcFace 99.83% verification accuracy on LFW (Deng et al., 2019) | 0.674 |
| keystroke | 0.771 | Our CMU baseline, Manhattan, 10 enrollment samples, EER 0.229 (laptop only) | 0.595 |

**Limitation, stated openly:** with three unknown sub-scores the placeholder values are nearly equal; they
only let the engine run. The real differences between factors (attacks on password and face, usability of
phone approval) appear once attack rounds and the pilot produce data (weeks 8–15).

```sh
python trust-lab/scripts/make_placeholder_table.py
```

## 4. Next (weeks 8–15)

- AHP pairwise comparison for the weights; sensitivity check ±0.1 per weight (does the ranking change?).
- Replace placeholder accuracy with our own LFW (week 6) and CMU (week 7) runs through the real factors.
- Optional comparison with trust computed the 2015-paper way (published error rates only).
