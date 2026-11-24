# TrustAuth — Shared Interface (v0.2)

| | |
|---|---|
| **Status** | v0.2, for agreement at the week 3 meeting |
| **Maintainer** | M4 (Alisher) |
| **Agree by** | end of week 3 |
| **Frozen** | end of week 4; after that, changes only by team agreement |
| **Code** | `backend/app/factors/base.py` implements sections 2–5 |

This document is the contract between modules. If your code follows it, it plugs into the platform
without anyone else changing their code. v0.2 merges the answers and proposals from the week 2 DESIGN.md
files and `trust-lab/docs/metrics.md`; [section 10](#10-changes-from-v01) lists every change.
Items still to confirm at the meeting are marked **[confirm]**.

---

## 1. How the pieces fit: the login "challenge loop"

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

| Name | Category | Owner | Requires |
|---|---|---|---|
| `password` | know | M3 | — |
| `passkey` | have | M3 | — |
| `phone_approval` | have | M2 | — |
| `face` | are | M2 | — |
| `keystroke` | do | M3 | `password` (same screen, see §6.3) |

Python: `FactorName = Literal["password", "passkey", "phone_approval", "face", "keystroke"]`.

---

## 3. LoginContext

Built by the core when a login starts; passed to the engine and to every factor call.

| Field | Type | Example | How it is filled |
|---|---|---|---|
| `login_id` | `str` | `"8f3c…"` | Created by the core for this login. Factors use it as a key (passkey challenge, phone-approval token) |
| `device_type` | `"laptop" \| "phone"` | `"phone"` | From the User-Agent string |
| `browser` | `str` | `"Chrome 131"` | From the User-Agent string |
| `ip` | `str` | `"203.0.113.5"` | Request address |
| `network` | `"known" \| "unknown"` | `"unknown"` | `known` if this user logged in successfully from this IP before |
| `known_device` | `bool` | `false` | `true` if the browser sends a device cookie we issued to this user before |
| `hour` | `int` 0–23 | `3` | Server time, Asia/Tashkent |
| `has_camera` | `bool` | `true` | Reported by the browser (`navigator.mediaDevices`) |
| `webauthn_supported` | `bool` | `true` | Reported by the browser (`window.PublicKeyCredential`) |
| `light_hint` | `"normal" \| "dim" \| null` | `null` | Optional: browser measures the brightness of one camera frame before login (§9 Q7) |
| `light` | `"normal" \| "dim" \| null` | `null` | Filled in by the face factor after it sees frames; overrides `light_hint` |
| `recent_failures` | `int` | `0` | Failed password attempts for this user in the last 15 minutes (Redis counter, core) |

**Condition key** for the trust table and the attempt log:
`f"{device_type}_{light or light_hint or 'normal'}"` → `laptop_normal`, `laptop_dim`, `phone_normal`, `phone_dim`.

---

## 4. Factor plug-in interface (Python)

In `backend/app/factors/base.py`. Each factor folder provides one class (real) and one mock class.

```python
class Factor(Protocol):
    name: FactorName

    async def is_enrolled(self, user_id: str) -> bool: ...
    def is_available(self, ctx: LoginContext) -> bool: ...
    async def start(self, user_id: str, ctx: LoginContext) -> dict: ...
    async def verify(self, user_id: str, payload: dict, ctx: LoginContext) -> FactorResult: ...
    async def enroll_start(self, user_id: str, ctx: LoginContext) -> dict: ...
    async def enroll_finish(self, user_id: str, payload: dict, ctx: LoginContext) -> EnrollResult: ...
```

| Method | Called when | Must |
|---|---|---|
| `is_enrolled` | Before selection | `True` only if the user finished enrollment. **async**: it reads the database |
| `is_available` | Before selection | `False` if the factor cannot run in this context (no camera, no WebAuthn, phone-only limits, …). No side effects, no I/O |
| `start` | The factor is the next challenge | Return the data the screen needs (§6). JSON-serialisable |
| `verify` | The browser submits an answer | Return a `FactorResult`. **Never raise** for a wrong answer; use `accepted=false` / `error` |
| `enroll_start` | User opens enrollment for this factor | Return what the enrollment screen needs |
| `enroll_finish` | Browser submits enrollment data | Return `EnrollResult`. Can be called **several times** (keystroke needs 10 samples) |

**EnrollResult:**

```json
{ "done": false, "remaining": 7, "reason": null }      // keep going
{ "done": true,  "remaining": 0, "reason": null }      // enrolled
{ "done": false, "remaining": null, "reason": "leaked" }  // refused; show the reason
```

Reason codes so far: `leaked`, `too_short`, `too_long` (password); `too_few_good_frames`, `too_dark` (face);
`bad_payload` (any).

**Registry:** each factor registers itself: `register(FaceFactor())`. The core looks factors up by name
with `get_factor("face")`.

**Mocks (week 3):** every owner provides a mock for each factor. `base.py` contains a `MockFactor` helper
class to subclass. A mock accepts when `payload["mock_accept"]` is true, otherwise rejects, and returns a
realistic `FactorResult` (same `context` keys as the real factor). Mode is chosen with the environment
variable `FACTOR_MODE=mock|real` (default `mock` until the real factors exist).

---

## 5. FactorResult

Returned by every `verify()`.

| Field | Type | Meaning |
|---|---|---|
| `factor` | `FactorName` | Which factor produced this |
| `accepted` | `bool` | Did the user pass? |
| `score` | `float` 0–1 | **Higher = more like the genuine user.** Binary factors (password, passkey, phone approval): `1.0` pass, `0.0` fail |
| `duration_ms` | `int` ≥ 0 | Time the user spent on this factor (from `start` to `verify`) |
| `context` | `dict` | Factor-specific observations, see table below |
| `error` | `str \| null` | Why it could not be completed; `null` if it ran normally (even if rejected) |

`accepted=false` with `error=null` means **the factor ran and the user failed** (wrong face, wrong
password). Errors count against *availability / usability*; rejections against *accuracy*.

**Allowed `context` keys:**

| Factor | Keys |
|---|---|
| `face` | `light` (`"normal"`/`"dim"`), `liveness_passed` (bool), `reason` (e.g. `"no_face"`, only with an error) |
| `keystroke` | `n_keys` (int): number of keystrokes used |
| `password` | `leaked` (bool): password found in the leaked-password list |
| `passkey` | `user_verified` (bool); optional `backed_up` (bool) |
| `phone_approval` | `scanned` (bool), `decision` (`"approved"`/`"denied"`/`null`) |

**Error codes:**

| Code | Meaning |
|---|---|
| `not_enrolled` | User has no enrollment for this factor |
| `unavailable` | Factor cannot run here: no camera, no WebAuthn, camera permission denied, **no usable face in any frame** (`context.reason = "no_face"`) |
| `timeout` | User did not finish in time (incl. expired challenge, phone request expired) |
| `cancelled` | User cancelled: closed the WebAuthn prompt, tapped **Deny** on the phone |
| `bad_payload` | Malformed request; keystroke sample with editing keys or wrong length; `verify` called while phone approval is still pending |
| `internal` | Unexpected server error |

**Browser-side failures** are sent in the verify payload as `{"client_error": "<DOMException name>"}`
(e.g. `NotAllowedError`), and the factor maps them to `cancelled` / `unavailable` / `bad_payload`.

---

## 6. Factor payloads

Details and reasons are in each factor's `DESIGN.md`.

### 6.1 face (M2)
```json
// start() returns
{ "frames_needed": 15, "fps": 5, "blink_required": true, "timeout_s": 10 }
// verify payload: JPEG 640x480, quality 0.8; never stored
{ "frames": ["data:image/jpeg;base64,...", "..."], "fps": 5 }
```
The verify endpoint accepts request bodies up to **2 MB**.

### 6.2 phone_approval (M2)
```json
// start() returns
{ "qr_url": "https://<host>/phone/approve/<token>", "expires_in": 60 }
// verify payload: empty; the factor reads the phone's decision from Redis, never trusts the browser
{}
```

### 6.3 password + keystroke (M3): one screen, two results
- `keystroke` is only selected together with `password`. The browser sends one request:
  ```json
  { "factor": "password", "payload": { "password": "...", "keystroke": { "events": [...] } } }
  ```
- The core calls `password.verify()`; if the password is **correct** and keystroke was selected, it calls
  `keystroke.verify()` with `payload["keystroke"]`. Two attempt rows are logged, with the same `duration_ms`.
- If the password is wrong, keystroke is not evaluated and no keystroke row is logged.
- `events[].key` is an **opaque label** per physical key (`"k1"`, `"k2"`, …), except special keys
  (`Shift`, `Enter`, `Backspace`, …), so the password is not sent twice and never stored.
```json
// password.start()
{}
// keystroke.start()
{ "mode": "with_password", "expected_keys": 11 }
// keystroke events
{ "events": [ {"key": "k1", "type": "down", "t": 0.0}, {"key": "k1", "type": "up", "t": 95.3} ] }
```

### 6.4 passkey (M3)
```json
// start() returns WebAuthn options (from webauthn.options_to_json)
{ "options": { "challenge": "...", "rpId": "localhost", "allowCredentials": [...], "userVerification": "required" } }
// verify payload: the object returned by @simplewebauthn/browser startAuthentication()
{ "credential": { "id": "...", "rawId": "...", "type": "public-key", "response": { } } }
```

---

## 7. REST API for the challenge loop

All endpoints are under `/api` from the browser (the frontend proxy strips it).

### `POST /auth/register`
```json
{ "username": "alice" }   // response: { "user_id": "u_…" }  (factors are enrolled separately)
```

### `POST /auth/login/start`
```json
// request
{ "username": "alice",
  "client": { "has_camera": true, "webauthn_supported": true, "light_hint": null } }
// response
{ "login_id": "8f3c…", "factors": ["passkey", "face"],
  "next": { "factor": "passkey", "challenge": { /* from factor.start() */ } } }
```
`risk_level` is **not** returned to the browser; it is logged only. For an unknown username the response
looks the same (fake factors), so attackers cannot find out which usernames exist.

### `POST /auth/login/{login_id}/verify`
```json
// request
{ "factor": "passkey", "payload": { /* §6 */ } }
// response, one of:
{ "status": "next",          "next": { "factor": "face", "challenge": { } } }
{ "status": "authenticated", "session": "…" }
{ "status": "retry",         "next": { "factor": "face", "challenge": { } }, "reason": "rejected" }
{ "status": "denied" }
```

### Enrollment
`POST /auth/enroll/{factor}/start` → `enroll_start()`; `POST /auth/enroll/{factor}/finish` → `EnrollResult`.
Requires a logged-in session (or the registration session for the first factor).

### Phone approval (M2, routed by the core)
- `WS /ws/phone-approval/{login_id}`, server → login page:
  `{"status": "waiting" | "scanned" | "approved" | "denied" | "expired"}`; closed after the last three.
- `GET/POST /phone/approve/{token}`, `GET /phone/register/{token}`: pages for the phone.

### Retry and fallback rules [confirm]
1. A rejected factor (`accepted=false`, `error=null`) gets **1 retry**.
2. After the retry fails, or after an error, the factor is **replaced** by the next-best available factor.
3. **Face rejected with `light = "dim"`**: replaced straight away, no retry (a retry in the same light
   would likely fail again).
4. **Denied** after 2 different factors have failed.

---

## 8. Trust table (M1 → engine)

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

- `trust` and `ci` in 0–1; `n` = number of attempts behind the value.
- Missing condition → the engine uses the factor's average over its other conditions; missing factor → `0.5`.
- Until real measurements exist (week 11), M1 provides a placeholder table from public-dataset baselines
  and published error rates (`docs/decisions.md` D2).

---

## 9. Attempt log (core → Trust Lab)

One row per factor attempt, PostgreSQL table `attempts`. M1 exports it for analysis.

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
| `error` | text, nullable | Needed for the availability sub-score |
| `is_genuine` | bool, nullable | Study label: real user (`true`) or imposter/attack (`false`); `null` outside study sessions |
| `attack_type` | text, nullable | e.g. `printed_photo`, `mfa_fatigue` (codes in `trust-lab/docs/threat-model.md`) |
| `study_session_id` | text, nullable | Groups the rows of one study session (M1 request) |
| `condition` | text | e.g. `phone_dim` (§3) |
| `context` | jsonb | Full LoginContext + FactorResult `context` |
| `risk_level` | text | `low` / `medium` / `high` |
| `selected_factors` | jsonb | e.g. `["passkey", "face"]` |
| `selector` | text | `adaptive` / `fixed` / `random` / `greedy` |

**Study labels:** the researcher sets the label (genuine / imposter / attack code, plus study session) in the
admin dashboard **before** each block of attempts; the core writes it into every row until changed. Labels
are never edited afterwards.

---

## 10. Changes from v0.1

| # | Change | From |
|---|---|---|
| 1 | Proposed fields accepted: `has_camera`, `webauthn_supported` (context); `error`, `condition`, `selector` (log); `n` (trust table) | v0.1 Q1, answered by M1 |
| 2 | `is_enrolled` is **async** | Q2, M3 |
| 3 | `enroll_start` / `enroll_finish` on the factor class; `enroll_finish` returns `EnrollResult` and may be called several times | Q3, M3 + M2 |
| 4 | Retry and fallback rules written down (§7) **[confirm]** | Q4, M4 + M2 (dim-light rule) |
| 5 | Study labels set in the dashboard before each block, never edited; new log column `study_session_id` | Q5, M1 |
| 6 | Keystroke only with password: one screen, one request, two results, keystroke skipped if password wrong; opaque key labels | Q6, M3 |
| 7 | `light_hint` from the browser before selection; face's `light` overrides it | Q7, M2 |
| 8 | New context fields `login_id`, `recent_failures` | M3 (passkey, password) |
| 9 | "No face found" = `unavailable` with `context.reason = "no_face"` instead of a new error code, so the Trust Lab's availability metric needs no change | M2 proposed `no_face`; M4 |
| 10 | `{"client_error": …}` convention for browser-side failures | M3 (passkey) |
| 11 | Factor payloads (§6), phone-approval WebSocket statuses `waiting` / `scanned`, new context keys for passkey and phone approval | M2, M3 |
| 12 | Factor `requires` column (§2); enrollment endpoints (§7); `MockFactor` helper and `FACTOR_MODE` default | M4 |
| 13 | Pretrained models only; datasets for evaluation only | `docs/decisions.md` D1, D2 |

## 11. Still open

- **Retry rules (§7):** confirm at the meeting.
- **Phone deny:** `cancelled` (proposed by M2) vs `accepted=false, error=null`. v0.2 uses `cancelled` +
  `context.decision = "denied"`, so the Trust Lab can count a deny during an attack as a successful defence.
