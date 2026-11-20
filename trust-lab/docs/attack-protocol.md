# Attack-test protocol (M1)

| | |
|---|---|
| **Status** | Week 2 draft; attack kit built weeks 8–11, attack rounds 1–2 in weeks 12–15 |
| **Based on** | [`threat-model.md`](threat-model.md), metric definitions in [`metrics.md`](metrics.md) |

## 1. General rules (all tests)

- **Only against our own system**, running locally (or our own ngrok tunnel for phone tests). Never
  against any real service.
- Victims and attackers are **team members or consenting volunteers**. A volunteer's photo / video /
  typing is only used as attack material with their written consent.
- Before each block of trials, the researcher sets the label in the admin dashboard (genuine / imposter /
  attack code); the core writes it into every attempt row (metrics.md §5, Q5).
- Conditions: `laptop_normal`, `laptop_dim`, `phone_normal`, `phone_dim`.
  **Normal light** = ordinary room lighting (measure and note the lux with a phone light-meter app, aim
  300–500 lux). **Dim** = one lamp or screen light only (aim below 50 lux). Write the measured value in the
  session sheet.
- Each trial = one factor attempt that produces one attempt row. A trial that ends in an error (crash,
  no camera) is **repeated** and the error row stays in the log (it counts for availability).
- Attack material (photos, videos, recordings) is stored in `data/attack-material/` (git-ignored) and
  deleted after the project.
- Order of trials within a session is randomised (genuine and attack blocks alternate) to avoid
  learning or fatigue effects all falling on one kind of trial.

## 2. Genuine and imposter protocol (accuracy)

**Genuine trials:** each volunteer, after enrollment, makes **10 attempts per factor per condition** in
which they could enroll (e.g. no keystroke on phone in v1). Normal behaviour, no coaching beyond the
on-screen instructions. Logged as `is_genuine=true, attack_type=null`.

**Imposter trials (face, keystroke only):** each volunteer acts as imposter for **2 other volunteers**
(rotation: volunteer i attacks i+1 and i+2), **5 attempts per victim per condition**.
- Face: the imposter simply tries with their own face on the victim's account.
- Keystroke: see `imposter_typing` below (needs the password).
Logged as `is_genuine=false, attack_type=null` (face) / `"imposter_typing"` (keystroke).

**Datasets** add the bulk of the genuine/imposter pairs: LFW for face (week 6), CMU for keystroke
(week 7). Volunteer data checks whether those results hold on our real system and conditions.

## 3. Attack cards

### printed_photo
- Factor: face
- Attacker capability: has a printed photo of the victim's face (e.g. from social media), physical access to a laptop / phone
- Setup: A4 colour print, 300 dpi, frontal photo taken in normal light; held 30–50 cm from the camera, held still and also slightly moved/tilted
- Conditions: laptop_normal, laptop_dim, phone_normal, phone_dim
- Trials: 20 per condition per victim (minimum), at least 3 victims
- Success = the factor returns accepted=true
- Logged as: is_genuine=false, attack_type="printed_photo"
- Expected result / target: success ≤ 5%
- Safety: only against our local system; prints shredded after the project

### screen_replay
- Factor: face
- Attacker capability: has a photo or short video of the victim and a second device to show it
- Setup: (a) a still photo on a phone screen at full brightness; (b) a 10 s video of the victim **that contains natural blinks**, played in a loop. Screen 20–40 cm from the camera
- Conditions: laptop_normal, laptop_dim, phone_normal, phone_dim
- Trials: 20 per condition per victim for (a) and for (b), at least 3 victims; note sub-type (photo / video) in the session sheet
- Success = the factor returns accepted=true
- Logged as: is_genuine=false, attack_type="screen_replay"
- Expected result / target: (a) ≤ 5%; (b) may be higher (blink liveness limitation), measured and reported honestly
- Safety: only against our local system; videos deleted after the project

### qr_relay
- Factor: phone_approval
- Attacker capability: makes the victim open a fake login page (phishing link); the fake page starts a real login on our server as the attacker and shows the victim the real QR code
- Setup: a simple local relay page on a different port (e.g. `localhost:5174`) that copies the QR from a real login started by the attacker script. The victim (a volunteer, briefed that "this session tests a login page", not told which pages are fake) scans and decides to approve or deny. The phone page shows the attacker's browser / IP / time
- Conditions: laptop_normal, phone_normal (light does not matter)
- Trials: 1–2 per volunteer, mixed among normal genuine approvals (a volunteer who knows the trick cannot be tested again)
- Success = the attacker's login receives accepted=true
- Logged as: is_genuine=false, attack_type="qr_relay"
- Expected result / target: success ≤ 5% is the target, but this measures a human decision; also record whether the volunteer looked at the login details
- Safety: relay page only on localhost, never published; ethics: debrief the volunteer after the session (explained in the consent form as "some login requests may be simulated attacks")

### mfa_fatigue
- Factor: phone_approval
- Attacker capability: knows the victim's password, can start many logins
- Setup: a script starts a new login every 10 s for 5 minutes (30 requests) against the victim's account
- Conditions: laptop_normal
- Trials: 30 requests per victim, at least 3 victims; record how many approval requests actually reach the phone (rate limit) and whether any is approved
- Success = any request is approved (accepted=true); also report requests delivered / sent
- Logged as: is_genuine=false, attack_type="mfa_fatigue"
- Expected result / target: success ≤ 5%; because approval needs a fresh QR scan, requests should not even reach the phone
- Safety: only against our local system and test accounts

### credential_stuffing
- Factor: password
- Attacker capability: a leaked username/password list (public list, no real people's credentials)
- Setup: create 20 test accounts: 10 with a password from the leaked list (created with the test-only setting that skips the registration block), 10 with strong random passwords. The script tries the top 1,000 leaked passwords against each account
- Conditions: laptop_normal (script, not a device condition)
- Trials: 20 accounts × up to 1,000 attempts; record attempts until success, and when rate limiting kicks in
- Success = password factor accepted=true for an account (report per account group)
- Logged as: is_genuine=false, attack_type="credential_stuffing"
- Expected result / target: 0% for strong-password accounts; listed-password accounts show why the registration check matters (in normal registration they cannot exist)
- Safety: only test accounts on our local system; never use real breached credentials of real people beyond public common-password lists

### imposter_typing
- Factor: keystroke
- Attacker capability: knows the victim's password (told by the researcher)
- Setup: (a) the imposter types the password in their own style; (b) optional: the imposter first watches the victim type it 3 times and tries to imitate the rhythm
- Conditions: laptop_normal, laptop_dim (phone if keystroke works on phones in week 7)
- Trials: 10 per victim per sub-type, each volunteer imposter for 2 victims
- Success = the keystroke factor returns accepted=true (the password factor passes by construction)
- Logged as: is_genuine=false, attack_type="imposter_typing"; used for both FAR/EER and attack success (metrics.md §1)
- Expected result / target: higher than 5% expected (weak factor); target is to measure it precisely
- Safety: volunteers use a study-only password, never a real one

### passkey_phishing
- Factor: passkey
- Attacker capability: makes the victim open a look-alike login page on a different origin, relays the WebAuthn challenge from our real server
- Setup: copy of the login page on `http://127.0.0.1:5174` (different origin from `localhost:5173`) and, for phones, on a second ngrok domain. The page calls `navigator.credentials.get()` with (a) the challenge as-is and (b) `rpId` changed to its own domain
- Conditions: laptop_normal, phone_normal
- Trials: 10 per condition per sub-type, at least 2 victims and 2 authenticator types (e.g. Windows Hello, Android)
- Success = the passkey factor returns accepted=true for the attacker's login
- Logged as: is_genuine=false, attack_type="passkey_phishing"; also record what the browser did (refused / error name)
- Expected result / target: 0% (by design)
- Safety: only against our local system

## 4. Session sheet (per study session)

Paper or spreadsheet, stored with the data (not in git):

| Field | Example |
|---|---|
| Session ID, date, researcher | S07, 2027-03-02, M1 |
| Pseudonymous volunteer ID | V07 |
| Device + browser | Lenovo laptop, Chrome 131 |
| Condition + measured lux | laptop_dim, 35 lux |
| Block label set in dashboard | `printed_photo`, victim V03 |
| Trials done / notes | 20, "photo slightly tilted from trial 11" |
