# Attempt-log format (M1, week 3)

| | |
|---|---|
| **Status** | Week 3, matches `docs/interface.md` v0.2 §9 |
| **Written by** | the core (M4): one row per factor attempt, PostgreSQL table `attempts` |
| **Read by** | the Trust Lab: [`src/trustlab/attempts.py`](../src/trustlab/attempts.py) checks the columns |

## 1. Columns

| Column | Type | Used by the Trust Lab for | Rules |
|---|---|---|---|
| `attempt_id` | uuid | de-duplication | unique |
| `login_id` | uuid | time per login (sum of `duration_ms`) | same for all attempts of one login |
| `user_id` | text | user-level bootstrap, per-user Wilcoxon test | **pseudonymised**, never a name |
| `timestamp` | timestamptz | ordering, session timeline | server time |
| `factor` | text | grouping | one of the 5 factor names |
| `accepted` | bool | FAR, FRR, success rates | |
| `score` | real 0–1 | EER, DET curve | higher = more genuine |
| `duration_ms` | int | speed score, time to authenticate | password and keystroke rows of one screen share the value: count once per login |
| `error` | text, nullable | availability; accuracy uses only `error = null` | shared error codes |
| `is_genuine` | bool, nullable | genuine vs imposter/attack | `null` = normal use, **excluded** from all metrics |
| `attack_type` | text, nullable | attack success per type | codes from [`threat-model.md`](threat-model.md); `null` for genuine and plain imposter rows |
| `study_session_id` | text, nullable | grouping study sessions; matching the session sheet | set with the label in the dashboard |
| `condition` | text | grouping per factor × condition | `laptop_normal`, `laptop_dim`, `phone_normal`, `phone_dim` |
| `context` | jsonb | light, liveness, n_keys, leaked, … | LoginContext + FactorResult `context` |
| `risk_level` | text | strategy comparison | `low` / `medium` / `high` |
| `selected_factors` | jsonb | predictability (entropy) | e.g. `["passkey", "face"]` |
| `selector` | text | strategy comparison, Wilcoxon | `adaptive` / `fixed` / `random` / `greedy` |

The Trust Lab requires at least: `factor, accepted, score, duration_ms, error, is_genuine, attack_type,
condition` (`attempts.REQUIRED_COLUMNS`).

## 2. Label combinations

| Kind | `is_genuine` | `attack_type` |
|---|---|---|
| Normal use (not analysed) | `null` | `null` |
| Genuine | `true` | `null` |
| Imposter (different real person) | `false` | `null` |
| Attack | `false` | code, e.g. `printed_photo` |
| Keystroke imposter (both imposter and attack) | `false` | `imposter_typing` |

`is_genuine = true` with an `attack_type` is invalid; the dashboard must not allow it.

## 3. Export

- **How:** M4 provides an export (admin dashboard button or script) to CSV: `data/exports/attempts-<date>.csv`.
  `data/` is git-ignored; exports are **never committed** (volunteer data).
- **`context`, `selected_factors`:** exported as JSON strings; load with `json.loads` when needed.
- **Load in Python:**
  ```python
  import pandas as pd
  from trustlab.trust import build_trust_table, write_trust_table

  attempts = pd.read_csv("data/exports/attempts-2027-03-10.csv")
  write_trust_table(build_trust_table(attempts), "trust-lab/output/trust_table.json")
  ```

## 4. Requests to M4 (core)

1. Write `error` exactly as the factor returned it (no rewriting), including `null`.
2. Copy the dashboard label (`is_genuine`, `attack_type`, `study_session_id`) into every row while it is set.
3. Store `condition` from `LoginContext.condition` **after** the factor ran (face fills in `light`).
