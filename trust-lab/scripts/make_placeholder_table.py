"""Write a placeholder trust table until real measurements exist (week 11).

The engine needs a trust_table.json from day one. Without attempt-log data, only the
ACCURACY sub-score can be filled, from public sources and our own dataset baseline;
the other three sub-scores are UNKNOWN (0.5). Every value below has its source.

Run from the repository root:
    python trust-lab/scripts/make_placeholder_table.py
Output: trust-lab/output/trust_table.json  (n = 0 marks a placeholder value)
"""

import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB / "src"))  # so this script can import trustlab without installing it

from trustlab.metrics import trust_score  # noqa: E402
from trustlab.trust import UNKNOWN, write_trust_table  # noqa: E402

CONDITIONS = ["laptop_normal", "laptop_dim", "phone_normal", "phone_dim"]
LAPTOP_ONLY = ["laptop_normal", "laptop_dim"]  # factors not available on phones in v1

# factor: (accuracy, conditions, source)
PLACEHOLDER_ACCURACY = {
    "password": (1.0, CONDITIONS, "exact match: no false accepts or rejects by design; weakness is attacks, not accuracy"),
    "passkey": (1.0, CONDITIONS, "cryptographic signature check: no false accepts or rejects by design"),
    "phone_approval": (1.0, LAPTOP_ONLY, "explicit approve/deny: no false accepts or rejects by design"),
    "face": (0.998, CONDITIONS, "ArcFace verification accuracy 99.83% on LFW (Deng et al., 2019)"),
    "keystroke": (0.771, LAPTOP_ONLY, "our CMU baseline: scaled Manhattan, 10 enrollment samples, EER 0.229"),
}


def placeholder_table() -> dict:
    factors = {}
    for factor, (accuracy, conditions, _source) in PLACEHOLDER_ACCURACY.items():
        trust = trust_score({"accuracy": accuracy, "attack_resistance": UNKNOWN,
                             "usability": UNKNOWN, "availability": UNKNOWN})
        value = round(trust, 3)
        factors[factor] = {c: {"trust": value, "ci": [value, value], "n": 0} for c in conditions}
    return {"version": "placeholder-v0", "factors": factors}


if __name__ == "__main__":
    out = LAB / "output" / "trust_table.json"
    write_trust_table(placeholder_table(), out)
    for factor, (accuracy, _, source) in PLACEHOLDER_ACCURACY.items():
        print(f"{factor:<15} accuracy {accuracy:.3f}  ({source})")
    print(f"\nwritten: {out}")
