# Threat model (M1)

| | |
|---|---|
| **Status** | Week 2 draft (week 1 attack list + week 2 threat model) |
| **Used by** | [`attack-protocol.md`](attack-protocol.md) (how each attack is tested), [`metrics.md`](metrics.md) (attack success rate) |

## 1. What we protect (assets)

| Asset | Why it matters |
|---|---|
| **User accounts / sessions** | The goal of the attacker: log in as someone else |
| **Enrollment data**: password hashes, face embeddings, keystroke models, passkey public keys, registered phones | Stolen biometric templates cannot be changed like a password; hashes can be cracked offline |
| **Volunteer study data**: face images, keystroke recordings, attempt logs | Personal data under informed consent; must stay local and pseudonymised |
| **The trust table and selection logic** | If an attacker can predict which factors will be asked, they can prepare only for those |

## 2. Attacker types

| ID | Attacker | Knows / has | Example |
|---|---|---|---|
| A1 | **Remote, no knowledge** | Username only, a leaked-password list | Credential stuffing bot |
| A2 | **Remote phisher** | Can make the victim open a fake login page | QR relay, passkey phishing |
| A3 | **Close to the victim** (friend, colleague) | Victim's password (shoulder-surfed), photos of the victim from social media, may watch them type | Imposter typing, printed photo |
| A4 | **Holds a device for a short time** | Unlocked laptop or a phone with the victim's face photo/video | Screen replay |
| A5 | **Annoyer** | Victim's password | MFA fatigue: sends many approval requests hoping the victim taps Approve |

## 3. Assumptions and scope

**In scope:** attacks on the login, factor by factor, run against **our own local system only**.

**Out of scope** (stated in the report as limitations):
- Server compromise, database theft, attacks on PostgreSQL / Redis / Docker.
- Malware on the user's device, stolen *unlocked* phone with working biometrics.
- Network man-in-the-middle (we assume HTTPS works; in development it is localhost).
- Advanced presentation attacks: 3D masks, deepfake video injection into the camera stream.
- Denial of service, social engineering of the help desk / account recovery (no recovery flow yet).
- Attacks on the adaptive engine itself (e.g. faking context to lower risk) are **noted** as a threat
  (T-E1 below) but only tested through the simulator, not as a live attack round.

## 4. Threats per factor

Every tested attack has an `attack_type` code (team-plan §5; proposed, owned by M1; official once in
`docs/interface.md`).

| Factor | ID | Threat | Attacker | `attack_type` | Tested? | Defence in TrustAuth |
|---|---|---|---|---|---|---|
| face | T-F1 | Show a **printed photo** of the victim | A3 | `printed_photo` | yes | Blink liveness (eye aspect ratio) |
| face | T-F2 | Replay a **photo or video on a phone screen** | A3, A4 | `screen_replay` | yes | Blink liveness; videos that contain a blink may pass → expected weak point, measured |
| face | T-F3 | Different person who looks similar (imposter) | A3 | (imposter row, no code) | yes, for FAR | Threshold at low FAR (LFW) |
| phone_approval | T-P1 | **QR relay**: fake login page shows the real QR from our server to the victim, victim approves the attacker's login | A2 | `qr_relay` | yes | Phone page shows the browser, IP and time of the login; short expiry (60 s) |
| phone_approval | T-P2 | **MFA fatigue**: attacker with the password triggers many approval requests | A5 | `mfa_fatigue` | yes | Rate limit on requests; push needs a scanned QR (phone must be near the login screen) |
| password | T-W1 | **Credential stuffing** with a leaked list | A1 | `credential_stuffing` | yes | Leaked-password block at registration, rate limiting, adaptive extra factors |
| password | T-W2 | Shoulder surfing / known password | A3 | (enables T-K1, T-P2) | indirectly | Second factor |
| keystroke | T-K1 | **Imposter types the correct password** | A3 | `imposter_typing` | yes | Per-user rhythm model |
| keystroke | T-K2 | Imposter trains to imitate the rhythm after watching | A3 | `imposter_typing` (subtype in notes) | optional | Same; reported separately if done |
| passkey | T-K3 | **Phishing on a different domain** | A2 | `passkey_phishing` | yes | WebAuthn origin / RP ID binding (should fail by design) |
| engine | T-E1 | Predict the factors that will be asked and prepare only those | A2, A3 | — | simulator | Randomised selection; measured by entropy |
| engine | T-E2 | Fake context (known device cookie, VPN to a known network) to lower risk | A1, A2 | — | noted only | Cookie bound to user; future work |

## 5. Expected results (hypotheses)

| `attack_type` | Expected success | Reason |
|---|---|---|
| `printed_photo` | ≤ 5% | Static photo cannot blink |
| `screen_replay` | may exceed 5% with a video that contains a blink | Blink-only liveness is a known limit; this justifies a lower trust value for face |
| `qr_relay` | depends on whether volunteers read the login details on the phone | Measures a human factor |
| `mfa_fatigue` | ≤ 5% | QR must be scanned for each request, so spam is hard |
| `credential_stuffing` | 0% for accounts with blocked leaked passwords | Registration check |
| `imposter_typing` | well above 5% (CMU baseline EER ≈ 0.2 with 10 enrollment samples) | Keystroke is a weak factor; this is why it is combined with others |
| `passkey_phishing` | 0% | Origin binding in the browser |

These hypotheses are written **before** testing so the report can compare expected and measured results.
