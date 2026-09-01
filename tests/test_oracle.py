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


def test_lexicon_chain_fallback():
    """A second lexicon rescues jargon WordNet can't judge -- without a real UMLS KB."""
    thr = 0.5
    MED = {"loinc", "snomed", "hl7v2"}         # all OOV in WordNet -> WN chain defers here

    def fake_umls(a, b):                        # stand-in for medical.umls_sim
        if a in MED and b in MED:
            return 1.0 if a == b else 0.0       # both known; distinct concepts here
        return None                             # OOV -> defer

    sim = disagree._compose_sim([disagree._wordnet_sim, fake_umls])

    # WordNet-OOV jargon the second lexicon knows as DISTINCT -> nocuous, not undetermined
    v, dist = disagree._classify_locus(["loinc", "snomed"], thr, sim)
    assert v == "nocuous" and dist == 1.0, (v, dist)

    # one head unknown to BOTH lexicons -> still undetermined (never bluffed to nocuous)
    v, _ = disagree._classify_locus(["loinc", "zzqwxfoo"], thr, sim)
    assert v == "undetermined", v

    # WordNet still owns general English even with a second lexicon in the chain
    v, _ = disagree._classify_locus(["car", "automobile"], thr, sim)
    assert v == "innocuous", v


def test_umls_min_token_len_guard():
    """Short heads short-circuit before the worker spawns -- no scispaCy/KB needed."""
    from avk import medical, config
    assert medical._concepts("for") == frozenset()    # 3 chars -> dropped unqueried
    assert medical._concepts("xml") == frozenset()
    assert config.UMLS_MIN_TOKEN_LEN <= len("code")   # 4-char content heads still reach UMLS


def test_norm_head_shape():
    """Identifiers are told from prose by ORTHOGRAPHY, no per-spec word list."""
    nh = disagree._norm_head
    assert nh("DiagnosticReport") == "diagnostic report"   # camelCase -> split, resolvable
    assert nh("FamilyMemberHistory") == "family member history"
    assert nh("R4") is None and nh("r4b") is None           # version tokens dropped
    assert nh("a.b") is None and nh("-") is None            # path / punctuation dropped
    assert nh("modality") == "modality" and nh("turtle") == "turtle"   # prose kept


def test_spec_lexicon():
    """The spec's own vocabulary resolves the FHIR resource names UMLS/WordNet lack."""
    from pathlib import Path
    from avk import config
    if not Path(config.SPEC_LEXICON_PATH).exists():
        return                                             # dataset not built here; skip
    from avk import spec_lexicon as s
    assert s.spec_sim("diagnostic report", "observation") == 0.0   # distinct FHIR resources
    assert s.spec_sim("observation", "observation") == 1.0
    assert s._concepts("qwzznotaterm") == frozenset()              # OOV -> empty


if __name__ == "__main__":
    test_classify_locus_three_valued()
    test_lexicon_chain_fallback()
    test_umls_min_token_len_guard()
    test_norm_head_shape()
    test_spec_lexicon()
    print("ok")
