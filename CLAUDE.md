# CLAUDE.md — TrustAuth

Project context for Claude Code. Put this file in the root of the repository.

---

## 1. What this project is

**TrustAuth: Adaptive Multi-Factor Authentication Driven by Measured Trustworthiness**

Final-year (graduation) project, Cyber Security, New Uzbekistan University, Faculty of Computing.
Supervisor: **Dr. Arunava Roy**. Team of 4. Duration: 21 weeks, part-time (6–8 h/week per member).

**One-sentence pitch:** a web authentication platform that *measures* how trustworthy each login method
really is (accuracy, attack resistance, usability, availability) and uses those scores, plus the risk of
each login, to choose the best and least predictable set of methods for every login.

**Research positioning (important):**
- Builds on prior work on adaptive MFA factor selection — Nag, Roy & Dasgupta, *"An Adaptive Approach Towards
  the Selection of Multi-factor Authentication"*, IEEE SSCI 2015 — which derived trust values from **published
  error rates** and evaluated selection **only in simulation**. Our supervisor is a co-author; always cite it.
- **Our contribution:** trust values are **measured empirically on a working system** (real attacks, real
  devices and conditions, real volunteers), fed into a risk-aware, unpredictable selector, and validated by
  a user study plus a comparison against fixed / random / greedy selection.
- Other cited works: Ometov et al. 2018 (MFA survey), Wiefling et al. 2019 (risk-based authentication),
  Deng et al. 2019 (ArcFace).

---

## 2. Scope (reduced, final)

**5 authentication methods ("factors") across 4 categories:**

| Category | Factor | Owner |
|---|---|---|
| Something you KNOW | Password (argon2 hash + leaked-password check) | M3 |
| Something you HAVE | Passkey (WebAuthn: fingerprint / face / PIN on device) | M3 |
| Something you HAVE | Phone approval (QR code on login page → scan with registered phone → tap Approve) | M2 |
| Something you ARE | Face verification (InsightFace/ArcFace embeddings + MediaPipe blink liveness + low-light check) | M2 |
| Something you DO | Keystroke rhythm (timing of how the password is typed; one-class model per user) | M3 |

**In scope:** web app (desktop + mobile browser), the 5 factors with one shared interface, Trust Lab,
adaptive engine, simulator, admin dashboard, attack tests, user study with 10–15 consenting volunteers.

**Out of scope (deliberately cut):** voice, mouse dynamics, continuous in-session authentication, TOTP codes,
contextual-bandit / self-learning selection, native mobile apps, production deployment.

**Test conditions (kept small):** laptop vs phone × normal vs dim light.

**Models and datasets (decided week 3, see `docs/decisions.md`):** **pretrained models only**, the team trains
no models (D1). Face uses pretrained ArcFace + MediaPipe (optionally a pretrained anti-spoofing model);
keystroke uses a per-user statistical profile made at enrollment. **Datasets are for evaluation and threshold
tuning only** (D2): LFW for face, CMU Keystroke for keystroke; none for password, passkey, phone approval.

---

## 3. Team and module ownership

| Member | Name | Module | Folder(s) |
|---|---|---|---|
| M1 | Sayfiddinov Doniyor | **Trust Measurement Lab** — test protocol, attack tests, metrics, trust score, statistics, user-study coordination | `trust-lab/` |
| M2 | Anvarova Sevinch | **Face & Phone Approval** | `backend/app/factors/face/`, `backend/app/factors/phone_approval/` (+ their frontend screens) |
| M3 | To'lqunov Nurmuhammad | **Password, Passkey & Keystroke** | `backend/app/factors/password/`, `passkey/`, `keystroke/` (+ their frontend screens) |
| M4 | Kurashev Alisher | **Adaptive Engine & Platform** — context + risk, selection engine, simulator, web app, dashboard, integration, repo/DevOps | `backend/app/engine/`, `backend/app/core/`, `frontend/`, `docker-compose.yml` |

**The person using Claude Code in this repo is usually M4 (Kurashev Alisher)** unless they say otherwise.

Grading is **per person**: keep each member's work in their own folders and branches; never rewrite another
member's module without being asked — suggest changes instead.

---

## 4. Architecture

```
Browser (React + TS)
  ├─ login UI that changes with the chosen factors
  ├─ camera capture (face), key-timing capture (keystroke), WebAuthn (passkey), QR display (phone approval)
  └─ admin dashboard
        │  HTTPS + REST, WebSocket (phone-approval live updates)
        ▼
Backend (Python, FastAPI)
  ├─ core/        users, sessions, auth flow ("challenge loop"), attempt logging
  ├─ engine/      context collector → risk level → factor selection          (M4)
  ├─ factors/     one plug-in per factor, all implement the same interface   (M2, M3)
  └─ trust table  loaded from Trust Lab output (JSON)                         (M1)
        │
        ▼
PostgreSQL (users, enrollments, credentials, trust table, attempt logs) · Redis (sessions, challenges)
```

**Login flow ("challenge loop"):**
1. User starts login → backend collects **context** (device, browser, IP, network, time, known device?).
2. Engine computes **risk level** (low / medium / high) and **selects k factors** (k grows with risk).
3. Frontend shows the first challenge; the factor verifier returns a **FactorResult**.
4. Repeat until all selected factors pass (→ session issued) or one fails (→ retry / fallback / deny).
5. Every attempt is **logged**; all research charts come from this log.

---

## 5. Shared interfaces (contract between modules)

Draft in Week 1–2, agreed Week 3, **frozen end of Week 4**. Change only by team agreement.

### 5.1 FactorResult — every verifier returns this

```json
{
  "factor": "face",              // "password" | "passkey" | "phone_approval" | "face" | "keystroke"
  "accepted": true,
  "score": 0.87,                 // 0–1 match confidence; 1.0 for binary factors that pass
  "duration_ms": 2400,           // time the user spent on this factor
  "context": {                   // factor-specific observations useful to the engine/Trust Lab
    "light": "dim",              // face only
    "liveness_passed": true      // face only
  },
  "error": null                  // e.g. "no_camera", "timeout", "not_enrolled"
}
```

### 5.2 Factor plug-in (Python)

Each factor folder exposes a class like:

```python
class Factor(Protocol):
    name: str                       # "face", ...
    def is_enrolled(self, user_id: str) -> bool: ...
    def is_available(self, ctx: LoginContext) -> bool: ...   # e.g. face needs a camera
    async def start(self, user_id: str, ctx: LoginContext) -> dict: ...   # challenge data for the UI
    async def verify(self, user_id: str, payload: dict, ctx: LoginContext) -> FactorResult: ...
```

Factors register themselves in a registry; the engine never imports factor internals.
Each factor must also work with a **mock** implementation so modules can be developed independently.

### 5.3 LoginContext — collected by the engine

```json
{
  "device_type": "phone",        // "laptop" | "phone"
  "browser": "Chrome 131",
  "ip": "203.0.113.5",
  "network": "unknown",          // "known" | "unknown"
  "known_device": false,
  "hour": 3,
  "light": null                  // filled in later by the face factor if used
}
```

### 5.4 Trust table — produced by M1, read by the engine

JSON keyed by factor and condition, values 0–1 with confidence intervals:

```json
{ "face": { "laptop_normal": {"trust": 0.90, "ci": [0.86, 0.93]}, "phone_dim": {"trust": 0.75, "ci": [0.68, 0.81]} } }
```

### 5.5 Attempt log — one row per factor attempt

`attempt_id, login_id, user_id, timestamp, factor, accepted, score, duration_ms, is_genuine (study label),
attack_type (null or e.g. "printed_photo"), context (JSON), risk_level, selected_factors (JSON)`

---

## 6. Trust score method (M1)

Per factor, per condition, measure four sub-scores, each normalised to 0–1 (1 = best):

| Sub-score | Definition |
|---|---|
| Accuracy | 1 − EER (genuine vs imposter attempts) |
| Attack resistance | 1 − attack success rate |
| Usability | mean of speed score (1 − time/30 s, capped) and genuine-user success rate |
| Availability | share of attempts where the factor could run at all |

**Trust = w1·Accuracy + w2·AttackResistance + w3·Usability + w4·Availability**
Starting weights 0.35 / 0.35 / 0.15 / 0.15; final weights chosen with **AHP** (pairwise comparison).
Report **95% CIs via bootstrapping** (~1000 resamples) and a **sensitivity check** (±0.1 per weight;
does the ranking change?). Optional extra: compare with trust values computed the 2015-paper way.

---

## 7. Adaptive selection engine (M4)

1. **Risk level** from context (rule-based v1): new device, unknown network, unusual hour → raise risk.
   low → 1–2 factors, medium → 2, high → 2–3.
2. **Score each available factor:** `trust(factor, condition) × context_fit − repetition_penalty`
   - `context_fit`: e.g. face in dim light or on no-camera device → low/0.
   - `repetition_penalty`: higher if this factor was used in the user's recent logins in the same context.
3. Pick the top-k with **randomised tie-breaking** (weighted sampling) so the choice is not predictable.
4. Avoid picking only factors from the same category when k ≥ 2 (prefer category diversity).
5. **Simulator:** generate synthetic login contexts; compare fixed / random / greedy (always strongest) /
   adaptive on: average trust of chosen factors, simulated attack success, predictability (Shannon entropy
   of factor sequences), expected login time.

Keep the engine pure and testable (no I/O inside the scoring functions).

---

## 8. Attacks to test (M1 leads, owners support)

| Factor | Attacks |
|---|---|
| Face | printed photo, phone-screen photo/video replay |
| Phone approval | QR phishing (fake login page that relays the QR), approval spamming ("MFA fatigue") |
| Password | leaked-password list / credential stuffing |
| Keystroke | imposter typing the correct password |
| Passkey | phishing via a different domain (should fail by design) |

All attack tools run **locally, against our own system only**. Never target real services.

---

## 9. Evaluation targets

**Research:** EER/FAR/FRR per factor and condition; attack success ≤ 5%; trust 95% CIs; adaptive vs
fixed/random/greedy (risk ↓, entropy ↑); Wilcoxon signed-rank test, p < 0.05.
Datasets: **LFW** (face), **CMU Keystroke Benchmark** (Killourhy & Maxion, 2009) + own volunteer data.

**System / user:** genuine-user login success ≥ 95%; SUS ≥ 70; factor selection ≤ 200 ms;
face verification ≤ 3 s; median time-to-authenticate ≤ 10 s.
User study: 10–15 volunteers, laptop + phone, normal + dim light, informed consent.

---

## 10. Tech stack

| Area | Choice |
|---|---|
| Frontend | React + TypeScript (Vite), WebAuthn browser API (optionally @simplewebauthn/browser), QR code library |
| Backend | Python 3.11, FastAPI, Pydantic, WebSockets |
| Database | PostgreSQL (SQLAlchemy + Alembic migrations), Redis |
| Face | InsightFace (ArcFace), MediaPipe Tasks `FaceLandmarker` (blink via eye aspect ratio), OpenCV; all pretrained |
| Keystroke | Scaled Manhattan per-user profile; scikit-learn (One-Class SVM, Isolation Forest) for comparison; pandas |
| Password | argon2-cffi; leaked-password list check |
| Passkey | py_webauthn |
| Trust Lab | pandas, numpy, scipy, matplotlib, Jupyter |
| DevOps | Docker, docker compose, GitHub Actions (later) |
| Testing | pytest, Playwright, Locust |

Passkeys and phone camera access need **HTTPS** (or localhost); use ngrok or a self-signed cert for phone tests.
The WebAuthn relying-party ID must match the domain exactly.

---

## 11. Repository layout

```
trustauth/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/            sessions, auth flow, logging, db           (M4)
│   │   ├── engine/          context, risk, selection, simulator        (M4)
│   │   └── factors/
│   │       ├── base.py      FactorResult, Factor protocol, registry    (shared, M4 maintains)
│   │       ├── password/    (M3)
│   │       ├── passkey/     (M3)
│   │       ├── keystroke/   (M3)
│   │       ├── face/        (M2)
│   │       └── phone_approval/ (M2)
│   ├── tests/
│   └── requirements.txt
├── frontend/                React app (M4 owns shell; M2/M3 add their factor screens)
├── trust-lab/               notebooks, evaluation scripts, trust table output (M1)
├── docs/                    interface.md, meeting notes, decisions
├── scripts/pre-push         blocks direct pushes to main
├── .github/pull_request_template.md
├── docker-compose.yml
└── README.md
```

---

## 12. Git workflow (free GitHub, no branch protection)

- **Never push directly to `main`.** Work on a branch named `m<N>-<task>` (e.g. `m4-risk-score`).
- Open a Pull Request and squash-merge it yourself (no review required); branch auto-deletes.
- Every member installs the hook once: `cp scripts/pre-push .git/hooks/pre-push && chmod +x .git/hooks/pre-push`.
- Small, focused commits with clear messages.
- When Claude Code creates commits or PRs, keep them scoped to the current member's module.

---

## 13. Security and privacy rules (non-negotiable)

- **Never commit** secrets (`.env`, keys), datasets, face images, embeddings, keystroke recordings, or any
  volunteer data. `data/`, `datasets/`, `*.npy` are git-ignored.
- Volunteer data only with **informed consent**; store locally, pseudonymised user IDs, delete after the project.
- Passwords only as **argon2** hashes. No custom crypto; use the established libraries listed above.
- Attack tooling targets **only our own local system**.

---

## 14. Timeline

21 project weeks. University weekly-progress form covers **semester weeks 9–15 = project weeks 1–7**,
followed by a **progress defense**.

| Project week (semester) | Team | M1 Doniyor | M2 Sevinch | M3 Nurmuhammad | M4 Alisher |
|---|---|---|---|---|---|
| 1 (W9) | Kickoff, meet supervisor, tools installed | Metrics list (FAR, FRR, EER, attack success); first attack list | Install InsightFace + MediaPipe; face-comparison demo | Load CMU Keystroke; study argon2 + WebAuthn | GitHub repo + Docker skeleton (FastAPI, React, PostgreSQL) |
| 2 (W10) | | Threat model, attack-test protocol | Design enrollment/verification + threshold method | Keystroke features + baseline model on CMU | Draft shared interface + context format |
| 3 (W11) | Interface agreed | Trust formula v0; attempt-log format | Mock face + phone-approval verifiers | Mock password, passkey, keystroke verifiers | Registration, session, challenge loop (with mocks) |
| 4 (W12) | **Interface frozen** | Consent form; test-condition grid | Webcam frame → face embedding end-to-end | Password module (argon2 + leaked check) | Context collector v1 + attempt logging |
| 5 (W13) | | Evaluation script: FAR/FRR/EER + DET curves | Face enrollment flow | HTTPS for phones; passkey registration | Risk score v1 |
| 6 (W14) | | Face baseline on LFW | Verification + threshold tuning on LFW | Passkey login complete | Selection engine v1 |
| 7 (W15) | **Prepare progress defense** | Keystroke baseline on CMU; interim results | Blink liveness | Keystroke capture in browser (JS) | Dynamic login screens; demo build |
| 8–11 | Integration checkpoint wk 9; **go/no-go wk 11** | Attack kit; trust score v1; pilot | Light check; phone approval v1 + WebSocket | Keystroke model + enrollment; integration | Simulator; dashboard v1; engine uses trust table |
| 12–15 | **Feature freeze wk 15** | Attack rounds 1–2; trust v2; study protocol | Attack support; dim-light/phone tests | Imposter tests; tuning | E2E tests, load test, simulator results; stable deploy |
| 16–19 | User study; **results final wk 19** | Run sessions; stats; headline table | Face results/charts | Keystroke results/charts | Comparison charts; SUS; demo script |
| 20–21 | Report + final defense | Intro, evaluation chapters | Literature review | Conclusion | Architecture & implementation |

**Fallbacks if a module is late at week 11:** missing trust lab → trust table from public-dataset
baselines; missing face/phone → platform runs with password, passkey, keystroke; missing M3 factors →
keep password + passkey, keystroke as standalone demo; missing engine → simulator-only results.

---

## 15. How Claude Code should work in this repo

- **Current phase:** project week 4 (semester week 12). `docs/interface.md` is **v1.0, frozen**;
  `backend/app/factors/base.py` and `backend/app/core/` implement it. The challenge loop runs with mock factors
  (`FACTOR_MODE=mock`); `FACTOR_MODE=real` uses a factor's real class (`app/factors/<name>/factor.py`, listed in
  `core/factor_setup.py` `REAL`) where it exists and its mock otherwise. Week 4 tasks: M3 real password factor;
  M2 webcam frame → face embedding; M1 consent form + test-condition grid; M4 context collector v1 (known
  network/device, recent failures) + attempt logging (study labels, CSV export). Decisions that changed the
  plan are in `docs/decisions.md`. If the user is M1, M2 or M3, they will say so; then work only in their folders.
- Work in **small, testable steps**; run the code/tests after each change.
- **Explain what you write** (the student must be able to defend every line at the defense).
  Prefer clear, conventional code over clever code.
- Use established libraries; never implement crypto or biometric models from scratch.
- Stay inside the current member's folders unless asked; propose interface changes in `docs/interface.md`
  instead of editing other modules.
- Keep the engine and scoring logic **pure functions with unit tests**.
- Windows teammates: prefer cross-platform commands; mention Git Bash where shell scripts are involved.
- Academic integrity: the team acknowledges AI-assisted coding in the report; check the university's policy.
