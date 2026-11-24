# Decisions

Project decisions that change the plan in `CLAUDE.md`, with the reason. Newest first.

---

## D2: Datasets are used for evaluation and tuning only (2026-11-24)

**Decision.** Datasets are used **before** the system runs, to test the pretrained models and choose
their settings (method, number of enrollment samples, threshold). They are never stored as users, never
used at runtime, and never used to train models (see D1).

| Factor | Dataset | Used for | Owner |
|---|---|---|---|
| Face recognition | **LFW** (Labeled Faces in the Wild): 13,233 photos, 5,749 people, public | FAR / FRR / EER of ArcFace on our pipeline; choose the face threshold | M2 + M1, week 6 |
| Face liveness (optional) | **CelebA-Spoof** (public); CASIA-FASD, Replay-Attack, OULU-NPU only if the licence request is signed in time | Attack success of a pretrained anti-spoofing model; its threshold | M2 + M1, weeks 8–15 |
| Keystroke | **CMU Keystroke Benchmark** (Killourhy & Maxion 2009): 51 people × 400 typings of one password | Compare detectors, choose number of enrollment typings and threshold (baseline done: EER 0.096) | M3 + M1 |

Password, passkey and phone approval need no dataset. (Password keeps its leaked-password list check; that is
a list lookup, not a model or an evaluation dataset.)

**How datasets are used:** run the dataset through **our own factor code** (e.g. LFW photos through the face
`verify()` pipeline), not only through the bare model, so the numbers describe our system. Volunteer results
(weeks 16–19) are then compared with the dataset results.

**Rules:** datasets live in `datasets/` (git-ignored) and are never committed; every dataset is cited in the
report and used under its licence.

---

## D1: Pretrained models only, no model training (2026-11-24)

**Decision.** The team does not train or fine-tune neural networks. Biometric factors use **pretrained**
models, run as they are.

| Factor | Model | Pretrained by | Runs |
|---|---|---|---|
| Face | Face detector (RetinaFace, InsightFace `buffalo_l`) | InsightFace | at enrollment and login |
| Face | **ArcFace** (ResNet-50), 512-number face embedding | InsightFace | at enrollment and login |
| Face | MediaPipe Face Landmarker (478 face points → eye aspect ratio → blink) | Google | at login |
| Face (optional) | Pretrained anti-spoofing model (e.g. MiniFASNet, or InsightFace 2.1's built-in liveness if suitable) | its authors | at login |
| Keystroke | No pretrained model. A per-user statistical profile (scaled Manhattan: mean and spread of each timing), computed from the user's 10 enrollment typings | — | profile made at enrollment, compared at login |

**Why.** Training needs large datasets, GPUs and time the team does not have (4 students, part-time,
21 weeks), and our own model would not beat published pretrained ones. The project's contribution is
*measuring* trustworthiness on a working system, which pretrained models support fully.

**Note on keystroke.** Computing a user's own typing profile at enrollment is not model training: it takes
milliseconds, needs no dataset, and plays the same role as storing a face template.

**Supervisor request (week 3).** The supervisor asked for ML / neural networks and datasets in face
recognition and keystroke. This is covered by: two pretrained neural networks in face (ArcFace, MediaPipe),
optionally a third for anti-spoofing; classical ML for keystroke (One-Class SVM and Isolation Forest are
compared in the CMU experiment); and the datasets in D2 for evaluation.
