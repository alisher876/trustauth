"""Tests for trustlab.attempts and trustlab.trust on a small synthetic attempt log."""

import json

import pandas as pd
import pytest

from trustlab.attempts import attack_rows, genuine_rows, imposter_rows, validate_attempts
from trustlab.trust import (
    UNKNOWN,
    accuracy,
    attack_resistance,
    build_trust_table,
    sub_scores,
    trust_from_rows,
    usability,
    write_trust_table,
)


def row(factor="face", accepted=True, score=0.9, duration_ms=3000, error=None,
        is_genuine=True, attack_type=None, condition="laptop_normal"):
    return dict(factor=factor, accepted=accepted, score=score, duration_ms=duration_ms, error=error,
                is_genuine=is_genuine, attack_type=attack_type, condition=condition)


def face_log() -> pd.DataFrame:
    """10 rows for face / laptop_normal where every sub-score is easy to compute by hand."""
    return pd.DataFrame([
        # 4 genuine: 3 accepted (3 s each), 1 rejected
        row(score=0.80), row(score=0.70), row(score=0.75), row(accepted=False, score=0.30),
        # 3 imposters (different person, normal attempt): 1 scores high
        row(accepted=False, score=0.10, is_genuine=False), row(accepted=False, score=0.20, is_genuine=False),
        row(accepted=True, score=0.72, is_genuine=False),
        # attacks: printed_photo 0/2, screen_replay 1/2 -> worst attack success 0.5
        row(accepted=False, is_genuine=False, attack_type="printed_photo"),
        row(accepted=False, is_genuine=False, attack_type="printed_photo"),
        row(accepted=True, is_genuine=False, attack_type="screen_replay"),
        row(accepted=False, is_genuine=False, attack_type="screen_replay", error="unavailable"),
        # outside a study session: no label -> ignored
        row(is_genuine=None),
    ])


def test_validate_requires_columns_and_drops_unlabelled_rows():
    with pytest.raises(ValueError):
        validate_attempts(pd.DataFrame([{"factor": "face"}]))
    assert len(validate_attempts(face_log())) == 11


def test_row_splitting():
    rows = validate_attempts(face_log())
    assert len(genuine_rows(rows)) == 4
    assert len(imposter_rows(rows, "face")) == 3
    assert len(attack_rows(rows)) == 4


def test_keystroke_imposter_typing_counts_as_imposter_and_attack():
    rows = pd.DataFrame([row(factor="keystroke", is_genuine=False, attack_type="imposter_typing")])
    assert len(imposter_rows(rows, "keystroke")) == 1
    assert len(imposter_rows(rows, "face")) == 0
    assert len(attack_rows(rows)) == 1


def test_sub_scores_by_hand():
    rows = validate_attempts(face_log())
    # EER: genuine {0.8, 0.7, 0.75, 0.3}, imposter {0.1, 0.2, 0.72}.
    # At threshold 0.70: FAR 1/3 (0.72), FRR 1/4 (0.3) is the closest pair -> EER (1/3 + 1/4) / 2.
    assert accuracy(rows, "face") == pytest.approx(1 - (1 / 3 + 1 / 4) / 2)
    assert attack_resistance(rows) == pytest.approx(0.5)  # screen_replay: 1 of 2 accepted
    # speed = 1 - 3000/30000 = 0.9; genuine success = 3/4 -> (0.9 + 0.75) / 2
    assert usability(rows) == pytest.approx((0.9 + 0.75) / 2)
    assert sub_scores(rows, "face")["availability"] == pytest.approx(10 / 11)  # one "unavailable"


def test_binary_factor_accuracy_uses_accept_rates():
    rows = pd.DataFrame([
        row(factor="password", score=1.0), row(factor="password", score=1.0),
        row(factor="password", accepted=False, score=0.0, is_genuine=False),
        row(factor="password", accepted=True, score=1.0, is_genuine=False),
    ])
    # FAR = 1/2, FRR = 0 -> accuracy 1 - 0.25
    assert accuracy(rows, "password") == pytest.approx(0.75)


def test_missing_sub_scores_count_as_unknown():
    rows = pd.DataFrame([row(), row(score=0.8)])  # genuine only: no imposters, no attacks
    subs = sub_scores(rows, "face")
    assert subs["accuracy"] is None and subs["attack_resistance"] is None
    expected = 0.35 * UNKNOWN + 0.35 * UNKNOWN + 0.15 * subs["usability"] + 0.15 * subs["availability"]
    assert trust_from_rows(rows, "face") == pytest.approx(expected)


def test_trust_table_format_and_ci(tmp_path):
    log = pd.concat([face_log(), face_log().assign(condition="phone_dim")], ignore_index=True)
    table = build_trust_table(log, n_resamples=200, seed=1, version="test")

    assert table["version"] == "test"
    assert set(table["factors"]["face"]) == {"laptop_normal", "phone_dim"}
    cell = table["factors"]["face"]["laptop_normal"]
    assert set(cell) == {"trust", "ci", "n"}
    assert cell["n"] == 11
    assert 0 <= cell["ci"][0] <= cell["trust"] <= cell["ci"][1] <= 1

    path = tmp_path / "trust_table.json"
    write_trust_table(table, path)
    assert json.loads(path.read_text(encoding="utf-8")) == table
