# Metrics (M1)

| | |
|---|---|
| **Status** | Week 2 draft |
| **Implemented in** | [`src/trustlab/metrics.py`](../src/trustlab/metrics.py), tested in [`tests/test_metrics.py`](../tests/test_metrics.py) |
| **Data source** | The attempt log (`docs/interface.md` §8), one row per factor attempt |

## 1. Three kinds of attempts

Every attempt row is one of three kinds. Keeping them apart is the basis of every metric.

| Kind | Who | Log labels | Feeds |
|---|---|---|---|
| **Genuine** | The real user, trying normally | `is_genuine = true`, `attack_type = null` | FRR, genuine success, usability, availability |
| **Imposter** | A *different real person* making a normal attempt (wrong face, someone else typing the victim's password) | `is_genuine = false`, `attack_type = null` | FAR, EER (**accuracy**) |
| **Attack** | A crafted attack (printed photo, QR relay, …) | `is_genuine = false`, `attack_type = "<code>"` | attack success rate (**attack resistance**) |

**Exception:** `imposter_typing` (keystroke) is an attack code, but it is the normal imposter case for
keystroke (another person who knows the password). For keystroke, rows with `attack_type =
"imposter_typing"` are used for **both** FAR/EER and attack success. This is the only exception.

**Which rows count where:**
- Accuracy metrics (FAR, FRR, EER) use only rows with `error = null`: the factor ran and gave a
  decision. A crash or a missing camera says nothing about accuracy.
- Availability uses all rows.
- Everything is computed **per factor × condition** (`condition` column: `laptop_normal`,
  `laptop_dim`, `phone_normal`, `phone_dim`), then per factor overall.

## 2. Score convention

`FactorResult.score` is 0–1, **higher = more like the genuine user**. A factor accepts when
`score >= threshold`. Binary factors (password, passkey, phone approval) give 1.0 or 0.0; for them FAR and
FRR are just the acceptance rates and EER is not meaningful (report FAR and FRR instead).

## 3. Metric definitions

| Metric | Formula / definition | Computed from (log columns) | Target (CLAUDE.md §9) | Function |
|---|---|---|---|---|
| **FAR** (false accept rate) | imposter attempts with `score ≥ t` / imposter attempts | `is_genuine=false`, `attack_type=null`, `error=null`, `score` (or `accepted` at the deployed threshold) | report at deployed threshold and at EER | `far(imposter_scores, t)` |
| **FRR** (false reject rate) | genuine attempts with `score < t` / genuine attempts | `is_genuine=true`, `error=null`, `score` / `accepted` | report | `frr(genuine_scores, t)` |
| **EER** (equal error rate) | the rate where FAR = FRR. On finite data: the threshold where \|FAR − FRR\| is smallest, report (FAR + FRR) / 2 | `score` of genuine vs imposter rows | per factor and condition | `eer(genuine, imposter)` → `(rate, threshold)` |
| **DET curve** | FRR plotted against FAR for every threshold (every observed score) | `score` | figure per factor, one line per condition | `det_curve(genuine, imposter)` |
| **Attack success rate** | attack attempts accepted / attack attempts, **per `attack_type`** | `attack_type`, `accepted` | **≤ 5%** | `attack_success_rate(accepted)` |
| **Genuine success rate** | genuine attempts accepted / genuine attempts (all rows, including errors: an error is a failed login for the user) | `is_genuine=true`, `accepted` | **≥ 95%** per login (whole login, not per factor) | `genuine_success_rate(accepted)` |
| **Time to authenticate** | per factor: median `duration_ms` of genuine accepted attempts; per login: sum of `duration_ms` over the attempts of one `login_id` (password + keystroke share a screen and the same duration: count it once) | `duration_ms`, `login_id`, `factor` | median login **≤ 10 s**; face **≤ 3 s** | pandas `groupby` |
| **Availability** | attempts where the factor could run / all attempts. "Could not run" = `error` in {`unavailable`, `internal`, `bad_payload`}. `timeout` and `cancelled` are user behaviour and count against usability instead | `error` | report | `availability(errors)` |
| **Speed score** | `max(0, 1 − median_time / 30 s)` | `duration_ms` | — | `speed_score(ms)` |
| **Accuracy** sub-score | `1 − EER` (binary factors: `1 − (FAR + FRR) / 2`) | as above | — | |
| **Attack resistance** sub-score | `1 − attack success rate`, using the **worst** attack type of the factor (an attacker picks the best attack) | as above | — | |
| **Usability** sub-score | mean of speed score and genuine success rate | as above | — | |
| **Availability** sub-score | availability | as above | — | |
| **Trust** | `0.35·Accuracy + 0.35·AttackResistance + 0.15·Usability + 0.15·Availability`; final weights by **AHP** (week 8–11), sensitivity check ±0.1 per weight | the four sub-scores | — | `trust_score(subs, weights)` |
| **95% CI** | percentile bootstrap: resample the **attempt rows** of one factor × condition with replacement 1000 times, recompute the metric (or trust) each time, take the 2.5th and 97.5th percentiles. Seed fixed for reproducibility | rows of one factor × condition | reported for every trust value | `bootstrap_ci(rows, statistic)` |
| **Predictability** | Shannon entropy `H = −Σ p·log2 p` of the selected factor **sets** per user (and per user × context), compared between selectors | `selected_factors`, `selector`, `user_id` | adaptive higher than fixed / greedy | `shannon_entropy(items)` |
| **SUS** | standard 10-item System Usability Scale. Odd items: score − 1; even items: 5 − score; sum × 2.5 → 0–100 | questionnaire after the study session (not in the log) | **≥ 70** | week 16 |
| **Statistical test** | Wilcoxon signed-rank test (`scipy.stats.wilcoxon`) on paired per-user results, adaptive vs each other selector, two-sided, p < 0.05 | per-user aggregates by `selector` | p < 0.05 | week 16–19 |
| **Selection time** | time the engine needs to choose factors | engine timing (M4 adds a log field or benchmark) | **≤ 200 ms** | M4 |

## 4. Notes and decisions

- **Bootstrap unit.** Rows from the same volunteer are not independent. With 10–15 volunteers, a better
  CI resamples **users** (all rows of a resampled user together). Plan: report row-level bootstrap in
  week 11 (simple), switch to user-level for the final results and compare the two.
- **Small samples.** An attack success of 0 / 20 does not prove 0%; its 95% upper bound (rule of three)
  is about 3/20 = 15%. Report the number of trials `n` next to every rate (trust table field `n`).
- **Minimum trials per cell:** 20 attack trials per attack type × condition, and for EER at least 50
  genuine and 50 imposter attempts per factor × condition (from datasets for face/keystroke, plus
  volunteers).
- **Comparison with Nag, Roy & Dasgupta (2015)**: optional extra, trust values from published error
  rates, as the placeholder table before week 11.

## 5. Interface review (open questions 1 and 5)

**Q1: proposed fields.** Yes to all of them:
- `error` in the log: **required**. Availability cannot be computed without it, and accuracy must exclude
  error rows.
- `condition` in the log: yes. It is derived from context, but `light` is only known after the face factor
  runs; storing the final value avoids re-deriving it differently in analysis.
- `selector` in the log: **required** for the strategy comparison and the Wilcoxon test.
- `n` in the trust table: yes, and also show it on the dashboard.
- `has_camera`, `webauthn_supported` in context: yes; they explain availability.
- **Additional request:** a `session_id` (study session) or a way to group rows by study session, so a
  volunteer's rows from one sitting can be found. Could also live in `context`.

**Q5: study labels.** Agree with the proposal: the researcher sets the label in the admin dashboard
before each block of attempts ("genuine", "imposter: <volunteer>", or an attack code), and the core
writes it into every attempt row until it is changed. Rules:
- The label is set **before** the attempts, never edited afterwards (avoids biased relabelling).
- The dashboard shows the current label in large text so it is not forgotten between blocks.
- Outside study sessions the label is `null` (normal use; excluded from analysis).

The §7 trust table and §8 log columns are then enough to compute every metric above, except SUS
(questionnaire) and selection time (engine benchmark).
