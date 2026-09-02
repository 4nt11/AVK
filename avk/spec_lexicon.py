# SPDX-License-Identifier: GPL-3.0-or-later
"""'spec' lexicon backend: a standard's OWN published vocabulary (opt-in via
`oracle = "wordnet,spec"`). Resolves terms the standard DEFINES itself -- FHIR resource
and datatype names, code concepts -- which general lexicons (WordNet, UMLS) lack because
they're HL7 model classes, not medical findings.

Built by scripts/build_spec_lexicon.py from FHIR's freely-redistributable definitions
(HL7/CC0), so the dataset ships on Kaggle/HuggingFace with no license wall. Pure stdlib
sqlite3, in-process. Same same/different contract as every backend; heads arrive already
normalized by disagree._norm_head (camelCase -> spaced), matching the harvested keys.
"""
from __future__ import annotations
import sqlite3
from functools import lru_cache
from pathlib import Path

from . import config


@lru_cache(maxsize=1)
def _db():
    p = Path(config.SPEC_LEXICON_PATH)
    if not p.exists():
        # not built locally -> pull from the HF dataset repo (cached in the HF cache)
        try:
            from huggingface_hub import hf_hub_download
        except ImportError:
            raise SystemExit(
                f"{p} not found. Either build it (scripts/build_spec_lexicon.py / "
                "build_dicom_lexicon.py) or `pip install huggingface_hub` to fetch it "
                f"from {config.SPEC_HF_REPO}.")
        p = Path(hf_hub_download(config.SPEC_HF_REPO, p.name, repo_type="dataset"))
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True, check_same_thread=False)


_EXCL_PLACEHOLDERS = ",".join("?" * len(config.SPEC_EXCLUDE_KINDS))
_EXCL = tuple(sorted(config.SPEC_EXCLUDE_KINDS))


@lru_cache(maxsize=8192)
def _concepts(term: str) -> frozenset:
    """Concept ids for a term, excluding the noisy code-display kind (see config).
    Short heads short-circuit, as in the UMLS backends."""
    if len(term.strip()) < config.UMLS_MIN_TOKEN_LEN:
        return frozenset()
    cur = _db().execute(
        f"SELECT DISTINCT concept_id FROM terms WHERE norm = ? AND kind NOT IN ({_EXCL_PLACEHOLDERS})",
        (term.lower(), *_EXCL))
    return frozenset(r[0] for r in cur)


def spec_sim(a: str, b: str):
    ca, cb = _concepts(a.lower()), _concepts(b.lower())
    if not ca or not cb:
        return None
    return 1.0 if ca & cb else 0.0
