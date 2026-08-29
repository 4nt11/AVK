# SPDX-License-Identifier: GPL-3.0-or-later
"""Fast checks for the nocuous classifier core (WordNet only, no parsers/GPU).

Run: PYTHONPATH=. .venv/bin/python tests/test_oracle.py
"""
from avk import disagree


def test_classify_locus_three_valued():
    thr = 0.6
    # semantically FAR known heads -> nocuous (readings genuinely differ)
    v, dist = disagree._classify_locus(["dog", "car"], thr)
    assert v == "nocuous" and dist > 0.3, (v, dist)

    # semantically CLOSE known heads -> innocuous (readings coincide)
    v, _ = disagree._classify_locus(["car", "automobile"], thr)
    assert v == "innocuous", v

    # domain jargon absent from WordNet -> undetermined, NOT silently nocuous
    v, _ = disagree._classify_locus(["uid", "zzqwxfoo"], thr)
    assert v == "undetermined", v

    # only one distinct head -> not a disagreement locus
    v, _ = disagree._classify_locus(["buffer", "buffer"], thr)
    assert v == "none", v


if __name__ == "__main__":
    test_classify_locus_three_valued()
    print("ok")
