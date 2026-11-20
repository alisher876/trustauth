# Password factor: design (M3)

| | |
|---|---|
| **Factor name** | `password` (category: something you **know**) |
| **Owner** | M3 (Nurmuhammad) |
| **Status** | Week 1–2 study and design. Implementation is week 4 |
| **Related** | [`../keystroke/DESIGN.md`](../keystroke/DESIGN.md) (same screen), [`docs/interface.md`](../../../../docs/interface.md) |

## 1. Hashing with argon2-cffi

We never store passwords, only **argon2id** hashes made by the `argon2-cffi` library (no custom crypto).

```python
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

ph = PasswordHasher()                     # argon2id with the parameters below

stored = ph.hash(password)                # registration: "$argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>"

try:
    ph.verify(stored, password)           # login: returns True or raises
except VerifyMismatchError:
    ...                                   # wrong password -> accepted=false, error=null
except (VerificationError, InvalidHashError):
    ...                                   # corrupt hash in DB -> error="internal"

if ph.check_needs_rehash(stored):         # after a successful login only
    stored = ph.hash(password)            # parameters were raised since the hash was made -> update DB
```

| Parameter | Value | Why |
|---|---|---|
| Variant | argon2id | Resists both GPU cracking and side-channel attacks; recommended by RFC 9106 and OWASP |
| `time_cost` | 3 | argon2-cffi default = RFC 9106 "low-memory" recommended profile |
| `memory_cost` | 65536 KiB (64 MiB) | same profile; above the OWASP minimum (19 MiB, t=2) |
| `parallelism` | 4 | same profile |
| `hash_len` / `salt_len` | 32 / 16 bytes | defaults; the salt is random per hash and stored inside the hash string |

The parameters, salt and hash are all inside the stored string, so `verify()` and
`check_needs_rehash()` need nothing else. In week 4 we measure the hashing time in the Docker
container (expected ~50–150 ms); if it is much slower we lower `memory_cost`, never below the OWASP
minimum.

**Unknown usernames:** the interface returns fake factors for unknown usernames. To avoid leaking
"user exists" through response time, `verify()` for a non-existent user still runs `ph.verify()` against
a fixed dummy hash and returns `accepted=false`.

## 2. Password rules

Following NIST SP 800-63B (current guidance): length ≥ **8** characters, maximum **128**
(to bound hashing work), any characters allowed, **no** composition rules ("one capital, one digit"),
no forced periodic change, and **block passwords from a leaked-password list**.

## 3. Leaked-password check

| Option | How | Pros | Cons |
|---|---|---|---|
| **A. Local list** (chosen) | A text file of common/leaked passwords (e.g. top 100,000 from the public SecLists project) in `datasets/leaked-passwords/`, loaded into a Python `set` at start-up | Offline, fast (set lookup), deterministic for experiments, no data leaves our system | Only covers the list we choose; the file must be downloaded (git-ignored, see below) |
| B. HaveIBeenPwned range API | SHA-1 the password, send the **first 5 hex characters** to `https://api.pwnedpasswords.com/range/<prefix>`, compare the returned suffixes locally (k-anonymity) | Covers ~1 billion real leaked passwords, always current | Needs internet; sends data (a hash prefix) to an outside service, and reveals *that* a user at our IP is registering/logging in at that time; adds latency; results can change between study sessions |

**Decision:** option A by default. The project rules say volunteer data stays local, and the user study
must be reproducible. Option B can be added behind a setting (`LEAKED_CHECK=local|hibp|off`) as a
demonstration, **off by default**, with the privacy trade-off explained in the report.
Even though only 5 characters of a SHA-1 hash are sent (each prefix matches hundreds of leaked hashes),
it is still a request to a third party that we would have to mention in the consent form.

**When the check runs:**
- **Registration / password change:** a leaked password is refused (`enroll_finish` →
  `{"done": false, "reason": "leaked"}`).
- **Login:** checked again, because lists grow after registration. A correct but leaked password is still
  `accepted=true`, with `context.leaked = true`; the engine can use this to raise the risk level, and the
  UI can ask the user to change the password.
- **Attack tests (`credential_stuffing`):** M1 needs test accounts whose password *is* in the list. A
  setting `ALLOW_LEAKED_FOR_TEST_ACCOUNTS` (off by default, local only) skips the registration block for
  accounts created by the attack kit.

The list file is a public dataset, not personal data, but it is large, so it lives in `datasets/`
(git-ignored) with download instructions in the factor README (week 4).

## 4. Brute force: rate limiting instead of hard lockout

Hard lockout ("5 wrong passwords → account locked") lets anyone lock a victim out (denial of service).
Proposal:

- Count failed password attempts per user in Redis: key `pwfail:<user_id>`, TTL 15 minutes.
- **≥ 3 failures:** the core/engine raises the risk level of the next login for this user (more factors).
- **≥ 10 failures in 15 minutes:** delay each further attempt (e.g. 5 s) and return the normal "rejected"
  answer. The real user can still log in with other factors.
- Also a per-IP limit in the core (many usernames from one IP = credential stuffing).

This needs one new context field (proposal below). The counter itself is core/M4 territory; the
password factor only reports `accepted`.

## 5. Plug-in behaviour (from week 3, against `base.py`)

| Method | Behaviour |
|---|---|
| `is_enrolled(user_id)` | user has a stored password hash (database read → `async`, see keystroke DESIGN §9 Q2) |
| `is_available(ctx)` | always `True` (every browser can type) |
| `start(user_id, ctx)` | returns `{}` (nothing secret); if keystroke is also selected, see keystroke DESIGN §5 |
| `verify(user_id, payload, ctx)` | `ph.verify(hash, payload["password"])` → `FactorResult` |
| `enroll_start` / `enroll_finish` | returns rules `{"min_length": 8, "max_length": 128}` / hashes and stores the new password after the leaked check |
| mock | accepts if `payload["mock_accept"]` is true |

**Payloads:**

```json
// start() returns
{}
// verify() payload from the browser
{ "password": "correct horse battery staple" }
// FactorResult
{ "factor": "password", "accepted": true, "score": 1.0, "duration_ms": 4200,
  "context": { "leaked": false }, "error": null }
```

Error codes: `not_enrolled` (no hash), `bad_payload` (missing / not a string / longer than 128),
`internal` (corrupt hash). Wrong password → `accepted=false`, `score=0.0`, `error=null`.

**The password must never appear in logs, exceptions, FactorResult or the attempt log.** FastAPI
validation errors echo the request body by default, so the core must not log raw payloads.

**Storage:** table `password_credentials (user_id PK/FK, hash TEXT, created_at, updated_at)`.
Changing the password resets the keystroke enrollment (see keystroke DESIGN §3).

## 6. Attacks

| `attack_type` | How (local system only) | Expected |
|---|---|---|
| `credential_stuffing` | Script tries username/password pairs from a leaked list against test accounts, some of which use a listed password | Accounts with listed passwords cannot exist outside the test setting (blocked at registration); rate limiting slows the script; success measured per account type |

## 7. Proposals for interface v0.2

1. Password `context` keys: `leaked` (bool), already in v0.1.
2. `enroll_finish` returns `{"done": bool, "reason"?: "leaked" | "too_short" | "too_long"}` (same
   proposal as in keystroke DESIGN §10).
3. New LoginContext field `recent_failures` (int): failed password attempts for this user in the last
   15 minutes, filled by the core from Redis, used by the engine's risk rules.
4. Combined password + keystroke payload, see keystroke DESIGN §10.
