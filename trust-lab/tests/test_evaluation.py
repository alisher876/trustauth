"""Tests for trustlab.evaluation and scripts/evaluate.py, on small data where the answer is known."""

import csv
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from trustlab.evaluation import (
    det_inputs,
    evaluate_log,
    load_attempts,
    plot_det,
    score_report,
    threshold_at_far,
)

GENUINE = [0.9, 0.8, 0.7, 0.6, 0.3]
IMPOSTER = [0.1, 0.2, 0.4, 0.5, 0.65]

# The exact column order of GET /admin/attempts.csv (backend/app/core/admin_routes.py CSV_COLUMNS)
EXPORT_COLUMNS = ["attempt_id", "login_id", "user_id", "timestamp", "factor", "accepted", "score", "duration_ms",
                  "error", "is_genuine", "attack_type", "study_session_id", "condition", "context", "risk_level",
                  "selected_factors", "selector"]


def attempt(factor="face", condition="laptop_normal", score=0.9, accepted=True, is_genuine=True,
            attack_type=None, error=None):
    return {"factor": factor, "condition": condition, "score": score, "accepted": accepted, "duration_ms": 2000,
            "error": error, "is_genuine": is_genuine, "attack_type": attack_type}


# --- operating points ------------------------------------------------------------------------------


def test_threshold_at_far_takes_the_lowest_threshold_that_is_low_enough():
    # Imposters 0.1 .. 0.65: FAR <= 20 % needs a threshold above 0.5 -> 0.6 (genuine score) lets 0.65 in.
    threshold, far_there = threshold_at_far(IMPOSTER, 0.2, GENUINE)
    assert (threshold, far_there) == (0.6, pytest.approx(0.2))


def test_zero_far_uses_the_next_observed_score_not_infinity():
    # Rejecting every imposter must not reject every genuine user too.
    threshold, far_there = threshold_at_far(IMPOSTER, 0.0, GENUINE)
    assert (threshold, far_there) == (0.7, 0.0)
    assert threshold_at_far(IMPOSTER, 0.0)[0] == np.inf  # without genuine scores there is no better choice


def test_threshold_at_far_checks_its_input():
    with pytest.raises(ValueError):
        threshold_at_far(IMPOSTER, 1.5)
    with pytest.raises(ValueError):
        threshold_at_far([], 0.1)


def test_score_report():
    report = score_report(GENUINE, IMPOSTER, target_fars=(0.2, 0.0))
    assert report["n_genuine"] == 5 and report["eer"] == pytest.approx(0.2)
    assert report["threshold_at_far_0.2"] == 0.6 and report["frr_at_far_0.2"] == pytest.approx(0.2)
    assert report["threshold_at_far_0"] == 0.7 and report["frr_at_far_0"] == pytest.approx(0.4)  # 0.6, 0.3 rejected


# --- the attempt log ----------------------------------------------------------------------------------


def small_log() -> pd.DataFrame:
    rows = [attempt(score=s, accepted=s >= 0.5) for s in GENUINE]
    rows += [attempt(score=s, accepted=s >= 0.5, is_genuine=False) for s in IMPOSTER]
    rows += [attempt(score=0.0, accepted=False, error="unavailable")]  # does not count for accuracy
    rows += [attempt(score=0.7, accepted=True, is_genuine=False, attack_type="printed_photo")]
    rows += [attempt(score=0.2, accepted=False, is_genuine=False, attack_type="printed_photo")]
    rows += [attempt(score=0.2, accepted=False, is_genuine=False, attack_type="screen_replay")]
    rows += [attempt(condition="phone_dim", score=s, accepted=s >= 0.5) for s in (0.5, 0.4)]
    rows += [attempt(condition="phone_dim", score=0.1, accepted=False, is_genuine=False)]
    rows += [attempt(score=0.9, is_genuine=None)]  # normal use, not a study row: ignored
    rows += [attempt("password", score=1.0), attempt("password", score=1.0),
             attempt("password", score=0.0, accepted=False, is_genuine=False),
             attempt("password", score=1.0, accepted=True, is_genuine=False, attack_type="credential_stuffing")]
    return pd.DataFrame(rows)


def test_evaluate_log_face_laptop():
    table = evaluate_log(small_log())
    cell = table[(table["factor"] == "face") & (table["condition"] == "laptop_normal")].iloc[0]
    assert (cell["n_genuine"], cell["n_imposter"]) == (5, 5)  # error row and unlabelled row left out
    assert cell["far"] == pytest.approx(2 / 5)  # 0.5 and 0.65 accepted
    assert cell["frr"] == pytest.approx(1 / 5)  # 0.3 rejected
    assert cell["eer"] == pytest.approx(0.2)
    assert (cell["n_attack"], cell["worst_attack"], cell["worst_attack_success"]) == (3, "printed_photo", 0.5)


def test_evaluate_log_has_an_all_row_and_handles_binary_factors():
    table = evaluate_log(small_log())
    assert list(table[table["factor"] == "face"]["condition"]) == ["laptop_normal", "phone_dim", "all"]
    face_all = table[(table["factor"] == "face") & (table["condition"] == "all")].iloc[0]
    assert (face_all["n_genuine"], face_all["n_imposter"]) == (7, 6)

    password = table[(table["factor"] == "password") & (table["condition"] == "all")].iloc[0]
    assert np.isnan(password["eer"])  # binary: EER is not meaningful (metrics.md §2)
    assert (password["far"], password["frr"]) == (0.0, 0.0)
    assert password["worst_attack_success"] == 1.0  # the stuffed password was correct


def test_keystroke_imposter_typing_counts_for_accuracy_and_attacks():
    rows = [attempt("keystroke", score=0.8), attempt("keystroke", score=0.3, accepted=False, is_genuine=False,
                                                     attack_type="imposter_typing")]
    cell = evaluate_log(pd.DataFrame(rows)).iloc[0]
    assert (cell["n_imposter"], cell["n_attack"]) == (1, 1)  # metrics.md §1, the one exception


def test_det_inputs_per_condition():
    curves = det_inputs(small_log(), "face")
    assert set(curves) == {"laptop_normal", "phone_dim"}
    genuine, imposter = curves["phone_dim"]
    assert sorted(genuine) == [0.4, 0.5] and list(imposter) == [0.1]


# --- loading the real export format --------------------------------------------------------------------


def test_load_attempts_reads_the_admin_export(tmp_path):
    # Written the same way as admin_routes.export_attempts: "" for null, True/False, JSON strings.
    path = tmp_path / "attempts.csv"
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(EXPORT_COLUMNS)
        base = ["a1", "l1", "u_1", "2026-12-01 10:00:00+00:00"]
        context = json.dumps({"login": {"device_type": "laptop"}, "factor": {"light": "normal"}})
        writer.writerow(base + ["face", True, 0.81, 2400, "", True, "", "S01", "laptop_normal", context, "medium",
                                json.dumps(["password", "face"]), "fixed"])
        writer.writerow(base + ["face", False, 0.0, 900, "unavailable", False, "printed_photo", "S01", "laptop_dim",
                                context, "high", json.dumps(["face"]), "fixed"])
        writer.writerow(base + ["password", True, 1.0, 3000, "", "", "", "", "laptop_normal", context, "low",
                                json.dumps(["password"]), "fixed"])

    df = load_attempts(path)
    assert list(df["accepted"]) == [True, False, True]
    assert list(df["is_genuine"]) == [True, False, None]
    assert df["error"].tolist() == [None, "unavailable", None]
    assert df["attack_type"].tolist() == [None, "printed_photo", None]
    table = evaluate_log(df)  # the unlabelled password row is left out
    assert set(table["factor"]) == {"face"}


# --- DET plot and the script -------------------------------------------------------------------------------


def test_plot_det_writes_a_png(tmp_path):
    path = plot_det({"laptop_normal": (GENUINE, IMPOSTER), "perfect": ([0.9, 0.95], [0.1, 0.2])},
                    tmp_path / "det.png", "test")
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def _load_script():
    script = Path(__file__).resolve().parents[1] / "scripts" / "evaluate.py"
    spec = importlib.util.spec_from_file_location("evaluate_script", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_runs_end_to_end(tmp_path, capsys):
    script = _load_script()
    table = script.run_log(script.synthetic_attempts(), tmp_path, synthetic=True)
    assert {"face", "keystroke", "password", "passkey"} == set(table["factor"])
    face_dim = table[(table["factor"] == "face") & (table["condition"] == "phone_dim")].iloc[0]
    face_ok = table[(table["factor"] == "face") & (table["condition"] == "laptop_normal")].iloc[0]
    assert face_dim["eer"] > face_ok["eer"]  # the synthetic data is built that way
    assert (tmp_path / "det_face.png").exists() and (tmp_path / "det_keystroke.png").exists()
    assert not (tmp_path / "det_password.png").exists()  # binary factors get no DET curve


def test_scores_mode(tmp_path):
    scores = tmp_path / "lfw.csv"
    pd.DataFrame({"label": ["genuine"] * 5 + ["Imposter"] * 5, "score": GENUINE + IMPOSTER}).to_csv(scores, index=False)
    _load_script().run_scores(scores, "face-lfw", tmp_path / "out")
    table = pd.read_csv(tmp_path / "out" / "evaluation.csv")
    assert table.loc[0, "eer"] == pytest.approx(0.2) and table.loc[0, "condition"] == "all"
    assert (tmp_path / "out" / "det_face-lfw.png").exists()
