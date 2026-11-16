# TrustAuth — Shared Interface (draft v0.1)

| | |
|---|---|
| **Status** | Draft for discussion — week 1 |
| **Maintainer** | M4 (Alisher) |
| **Agree by** | end of week 3 |
| **Frozen** | end of week 4 — after that, changes only by team agreement |

This document is the contract between modules. If your code follows it, it will plug into the platform
without anyone else changing their code. Items marked **[proposed]** are additions to the original plan
in `CLAUDE.md` — please comment on them. Open questions are collected in [section 9](#9-open-questions).

---

## 1. How the pieces fit — the login "challenge loop"

```
 Browser                         Backend core (M4)              Engine (M4)            Factor plug-in (M2/M3)
   │ POST /auth/login/start ───────▶│ build LoginContext ───────▶│ risk level           │
   │                                │                            │ select k factors     │
   │                                │◀─────── [passkey, face] ───│                      │
   │                                │ factor.start() ─────────────────────────────────▶│ challenge data
   │◀────── first challenge ────────│                                                  │
   │ POST /auth/login/{id}/verify ─▶│ factor.verify() ────────────────────────────────▶│ FactorResult
   │                                │ log attempt                                      │
   │◀── next challenge / session / denied                                              │
```

The engine never imports factor code. It only sees factor **names**, the **trust table** and the
**LoginContext**. The core only talks to factors through the `Factor` interface (section 4).

---

## 2. Factor names

These exact strings are used everywhere: API, database, trust table, logs.

| Name | Category | Owner |
|---|---|---|
| `password` | know | M3 |
| `passkey` | have | M3 |
| `phone_approval` | have | M2 |
| `face` | are | M2 |
| `keystroke` | do | M3 |

Python: `FactorName = Literal["password", "passkey", "phone_approval", "face", "keystroke"]`.

---

## 3. LoginContext

Built by the core when a login starts; passed to the engine and to every factor call.

| Field | Type | Example | How it is filled |
|---|---|---|---|
| `device_type` | `"laptop" \| "phone"` | `"phone"` | From the User-Agent string |
| `browser` | `str` | `"Chrome 131"` | From the User-Agent string |
| `ip` | `str` | `"203.0.113.5"` | Request address |
| `network` | `"known" \| "unknown"` | `"unknown"` | `known` if this user logged in successfully from this IP before |
| `known_device` | `bool` | `false` | `true` if the browser sends a device cookie we issued to this user before |
| `hour` | `int` 0–23 | `3` | Server time, Asia/Tashkent |
| `light` | `"normal" \| "dim" \| null` | `null` | Filled in by the face factor after it sees a frame |
| `has_camera` **[proposed]** | `bool` | `true` | Reported by the browser (`navigator.mediaDevices`) |
| `webauthn_supported` **[proposed]** | `bool` | `true` | Reported by the browser (`window.PublicKeyCredential`) |

**Why the two proposed fields:** `face.is_available()` needs to know whether there is a camera, and
`passkey.is_available()` whether the browser supports WebAuthn. Without them, the engine could select a
factor the user cannot possibly complete.

**Condition key** for the trust table is derived from the context: `f"{device_type}_{light or 'normal'}"`
→ one of `laptop_normal`, `laptop_dim`, `phone_normal`, `phone_dim`.

---

## 4. Factor plug-in interface (Python)

Lives in `backend/app/factors/base.py` (maintained by M4). Each factor folder provides one class.

```python
class Factor(Protocol):
    name: FactorName

    def is_enrolled(self, user_id: str) -> bool: ...
    def is_available(self, ctx: LoginContext) -> bool: ...
    async def start(self, user_id: str, ctx: LoginContext) -> dict: ...
    async def verify(self, user_id: str, payload: dict, ctx: LoginContext) -> FactorResult: ...
```

| Method | Called when | Must |
|---|---|---|
| `is_enrolled` | Before selection | Return `True` only if the user has finished enrollment for this factor |
| `is_available` | Before selection | Return `False` if this factor cannot run in this context (no camera, no WebAuthn, …). No side effects |
| `start` | The factor is the next challenge | Return the data the frontend screen needs (e.g. WebAuthn options, QR code payload). Must be JSON-serialisable |
| `verify` | The browser submits an answer | Return a `FactorResult` — **never raise** for a wrong answer; use `accepted=false` / `error` |

**Registry:** each factor registers itself, e.g. `register(FaceFactor())`. The core looks factors up by
name.

**Mocks (required for week 3):** every owner also provides a mock version of each factor that accepts or
rejects based on the payload (e.g. `{"mock_accept": true}`), so the full login flow can be built and
tested before the real factor is finished. Switched with the environment variable `FACTOR_MODE=mock|real`.

**Enrollment [proposed]:** each factor also needs enrollment. Suggested, same pattern:

```python
    async def enroll_start(self, user_id: str, ctx: LoginContext) -> dict: ...
    async def enroll_finish(self, user_id: str, payload: dict, ctx: LoginContext) -> bool: ...
```

---

## 5. FactorResult

Returned by every `verify()`.

| Field | Type | Meaning |
|---|---|---|
| `factor` | `FactorName` | Which factor produced this |
| `accepted` | `bool` | Did the user pass? |
| `score` | `float` 0–1 | Match confidence. Binary factors (password, passkey, phone approval): `1.0` pass, `0.0` fail |
| `duration_ms` | `int` | Time the user spent on this factor (from `start` to `verify`) |
| `context` | `dict` | Factor-specific observations, see below |
| `error` | `str \| null` | Why it could not be completed; `null` if it ran normally (even if rejected) |

```json
{
  "factor": "face",
  "accepted": true,
  "score": 0.87,
  "duration_ms": 2400,
  "context": { "light": "dim", "liveness_passed": true },
  "error": null
}
```

**Allowed `context` keys** (add yours here so the Trust Lab knows what to expect):

| Factor | Keys |
|---|---|
| `face` | `light` (`"normal"`/`"dim"`), `liveness_passed` (bool) |
| `keystroke` | `n_keys` (int) — number of key events used |
| `password` | `leaked` (bool) — password found in the leaked list |
| others | none yet |

**Error codes** **[proposed — shared list]:**

| Code | Meaning |
|---|---|
| `not_enrolled` | User has no enrollment for this factor |
| `unavailable` | Factor cannot run here (no camera, no WebAuthn, …) |
| `timeout` | User did not finish in time |
| `cancelled` | User cancelled (e.g. closed the WebAuthn prompt, tapped Deny) |
| `bad_payload` | Malformed request from the browser |
| `internal` | Unexpected server error |

`accepted=false` with `error=null` means **the factor ran and the user failed** (wrong face, wrong
password). This distinction matters for the Trust Lab: errors count against *availability*, rejections
against *accuracy*.

---

## 6. REST API for the challenge loop **[proposed]**

All endpoints are under `/api` from the browser (the frontend proxy strips it).

### `POST /auth/login/start`
```json
// request
{ "username": "alice", "client": { "has_camera": true, "webauthn_supported": true } }
// response
{ "login_id": "8f3c…", "factors": ["passkey", "face"],
  "next": { "factor": "passkey", "challenge": { /* from factor.start() */ } } }
```
`risk_level` is **not** returned to the browser (it would help attackers); it is logged only.
For an unknown username the response looks the same (fake factors), so attackers cannot find out which
usernames exist.

### `POST /auth/login/{login_id}/verify`
```json
// request
{ "factor": "passkey", "payload": { /* factor-specific answer */ } }
// response — one of:
{ "status": "next",          "next": { "factor": "face", "challenge": { } } }
{ "status": "authenticated", "session": "…" }
{ "status": "retry",         "next": { "factor": "face", "challenge": { } }, "reason": "rejected" }
{ "status": "denied" }
```

### `WS /ws/phone-approval/{login_id}`
Pushes `{"status": "approved" | "denied" | "expired"}` to the login page when the phone responds (M2).

Retry and fallback rules (how many retries, when to switch factor) — see open question 4.

---

## 7. Trust table (M1 → engine)

File: `trust-lab/output/trust_table.json`, loaded by the engine at start-up.

```json
{
  "version": "2026-12-01",
  "factors": {
    "face": {
      "laptop_normal": { "trust": 0.90, "ci": [0.86, 0.93], "n": 120 },
      "phone_dim":     { "trust": 0.75, "ci": [0.68, 0.81], "n": 80 }
    }
  }
}
```

- `trust` and `ci` in 0–1; `n` **[proposed]** = number of attempts behind the value.
- A missing condition means "not measured yet": the engine falls back to the factor's average over the
  other conditions, and if the factor is missing entirely, to a default of `0.5`.
- Until real measurements exist (week 11), M1 provides a placeholder table based on published error rates.

---

## 8. Attempt log (core → Trust Lab)

One row per factor attempt, in PostgreSQL table `attempts`. M1 exports it for analysis.

| Column | Type | Notes |
|---|---|---|
| `attempt_id` | uuid | |
| `login_id` | uuid | Groups the attempts of one login |
| `user_id` | text | **Pseudonymised** ID, never the real name |
| `timestamp` | timestamptz | |
| `factor` | text | Factor name |
| `accepted` | bool | |
| `score` | real | |
| `duration_ms` | int | |
| `error` | text, nullable | **[proposed]** — needed for the availability sub-score |
| `is_genuine` | bool, nullable | Study label: real user (`true`) or imposter/attack (`false`) |
| `attack_type` | text, nullable | e.g. `printed_photo`, `mfa_fatigue` |
| `condition` | text | **[proposed]** — e.g. `phone_dim`, so analysis does not have to re-derive it |
| `context` | jsonb | Full LoginContext + FactorResult `context` |
| `risk_level` | text | `low` / `medium` / `high` |
| `selected_factors` | jsonb | e.g. `["passkey", "face"]` |
| `selector` | text | **[proposed]** — `adaptive` / `fixed` / `random` / `greedy`, needed to compare strategies in the study |

How `is_genuine` and `attack_type` are set during the study (e.g. a researcher switch in the admin
dashboard) — see open question 5.

---

## 9. Open questions

Please answer in the PR or at the next meeting.

1. **Proposed fields** — OK to add `has_camera`, `webauthn_supported` (context), `error`, `condition`,
   `selector` (log), `n` (trust table)?
2. **Sync or async** — will `is_enrolled()` need the database? If yes, it should be `async` too.
3. **Enrollment** — OK with `enroll_start` / `enroll_finish` on the same class?
4. **Retries** — how many retries per factor before switching to another factor or denying? Proposal:
   1 retry, then replace with the next-best factor, deny after 2 failed factors.
5. **Study labels** — who sets `is_genuine` / `attack_type`, and how? Proposal: the researcher selects
   "genuine" or an attack type in the admin dashboard before each session.
6. **Keystroke and password** — keystroke rhythm is captured while the password is typed. Are they one
   screen (with two FactorResults) or can keystroke be selected without password?
7. **Light detection** — face sets `light` after the first frame, but selection already happened.
   Should the engine re-check face's trust once `light` is known?
