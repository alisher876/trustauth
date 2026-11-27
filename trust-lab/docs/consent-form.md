# Participant information sheet and consent form (M1, week 4)

| | |
|---|---|
| **Status** | Draft for the supervisor. Check the university's ethics procedure before using it; fill in the `[...]` fields |
| **Used in** | User study, weeks 16–19 (pilot in weeks 8–11) |
| **Print** | Two copies per volunteer: one signed copy for the team, one for the volunteer |

---

## Part A: Information sheet (the volunteer keeps this)

**Study title:** TrustAuth: measuring how trustworthy different login methods are

**Researchers:** Sayfiddinov Doniyor, Anvarova Sevinch, To'lqunov Nurmuhammad, Kurashev Alisher
(final-year students, Cyber Security, New Uzbekistan University, Faculty of Computing)
**Supervisor:** Dr. Arunava Roy
**Contact:** [team e-mail address] · [supervisor's university e-mail address]
**Ethics reference:** [number, if the university gives one]

### What is the study about?
We built a login system that can use five methods: a password, a passkey (fingerprint / face / PIN on your
device), approving a login on your phone, face recognition, and the rhythm of your typing. We want to
measure how accurate, secure and easy each method is, on laptops and phones, in normal and dim light.

### What will I do?
- **Session 1 (laptop, about 45 minutes):** create a test account, set up the login methods, then log in
  many times in normal light and in dim light.
- **Session 2 (phone, about 30 minutes):** the same on a phone.
- In some rounds you will try to log in to **another volunteer's test account** (for example, typing their
  study password, or showing your face). This tells us how often a wrong person is let in.
- At the end, a short questionnaire about how easy the system was (10 questions, about 3 minutes).
- Some login requests in the study may be **simulated attacks** (for example, a request on your phone that
  was not started by you). You will be told which ones after the session.

You will use a **study password that we give you**. Never use one of your real passwords.

### What data is collected?
| Data | Kept as | Why |
|---|---|---|
| Face | A list of 512 numbers computed from the camera (a "face template"). **Camera images are not stored** | To check your face at login |
| Typing rhythm | Key timings in milliseconds, **not the characters you typed** | To check your typing rhythm at login |
| Passkey | A public key created by your device (your fingerprint/face never leaves your device) | To check the passkey at login |
| Login attempts | Pass/fail, score, time taken, device type, light condition, date and time | To measure each method |
| Questionnaire | Your answers | To measure ease of use |

Your name is **not** stored with this data. You get a code (for example, `V07`); only the signed consent
forms link codes to names, and they are kept separately and locked away.

### Optional: photos and videos for attack tests
To test whether the system can be fooled, we would like to take **a photo and a short video of your face**
and show them to the camera (printed and on a phone screen). This is **optional**. You can take part in the
study without it. If you agree, the photo and video are kept on one offline team computer, used only for
these tests on our own system, and deleted at the end of the project.

### Where is the data kept, and for how long?
On team computers only, never on GitHub or any online service. All study data, including face templates,
typing timings, photos and videos, is **deleted by [date, e.g. 30 June 2027]**, after the project is graded.
Results are published only as group statistics (for example, "face recognition rejected 3% of genuine
logins"). No result identifies you.

### Do I have to take part?
No. Taking part is voluntary. You can stop at any time, without giving a reason and without any
consequence. You can ask us to delete your data at any time until **[date, e.g. 1 May 2027]**, when the
results are combined. To do so, contact us with your code.

### Are there any risks?
The risks are minimal. You will look at a screen and type for about 75 minutes in total; you can take
breaks at any time. Dim-light rounds use ordinary room lighting with the lights partly off.

---

## Part B: Consent form (signed copy kept by the team)

Volunteer code: **V____**  (filled in by the researcher)

Please tick each box you agree with.

| | Statement |
|---|---|
| ☐ | I have read the information sheet (Part A), and I had the chance to ask questions. |
| ☐ | I understand that taking part is voluntary and that I can stop at any time without giving a reason. |
| ☐ | I agree that a face template, typing timings, a passkey public key and my login attempts are recorded as described, under my volunteer code. |
| ☐ | I agree to try to log in to other volunteers' test accounts, and that other volunteers try to log in to mine. |
| ☐ | I understand that some login requests in the study may be simulated attacks, and that this will be explained to me after the session. |
| ☐ | I agree to fill in a short questionnaire about ease of use. |
| ☐ | I agree that anonymous group results are used in the project report and its presentation. |
| ☐ | **Optional:** I agree that a photo and a short video of my face are taken and used for attack tests on the study system, and deleted at the end of the project. |

| | |
|---|---|
| Volunteer name | ______________________________ |
| Signature / date | ______________________________ |
| Researcher name | ______________________________ |
| Signature / date | ______________________________ |

---

## Notes for the team (not printed)

- Ask the supervisor whether the university needs an **ethics approval** form for a study with
  biometric data, and fill in the reference number above.
- **Debrief** after any session that included a `qr_relay` or `mfa_fatigue` trial
  (`attack-protocol.md`): explain what was simulated and why.
- Keep signed forms on paper (or as a scan on one offline computer), **separately** from the study data.
  The code ↔ name list lives only there.
- The study passwords are generated per volunteer by the researcher, are never reused, and are not in any
  leaked-password list (the password factor refuses those).
- Store the data under `data/` (git-ignored). Never commit it.
