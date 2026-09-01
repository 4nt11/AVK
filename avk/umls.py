# SPDX-License-Identifier: GPL-3.0-or-later
"""'umls' lexicon backend: the FULL licensed UMLS Metathesaurus (opt-in via
`oracle = "wordnet,umls"`). Needs a UTS license + local install -> a prebuilt SQLite
index (scripts/build_umls_index.py). The license-free counterpart is 'bastardized-umls'
(medical.py, scispaCy subset).

Unlike bastardized-umls this needs no scispaCy/numpy, so it runs in-process on stdlib
sqlite3 -- no isolated venv, no worker. DICOM/HL7v2/FHIR are UMLS source vocabularies,
so the full set actually covers the jargon in AVK's own specs. Same same/different
contract as every backend: 1.0 shared concept / 0.0 both link but disjoint / None OOV.
Reuses the config.UMLS_MIN_TOKEN_LEN + config.UMLS_SEMANTIC_TYPES gates.
"""
from __future__ import annotations
import sqlite3
from functools import lru_cache
from pathlib import Path

from . import config


@lru_cache(maxsize=1)
def _db():
    p = Path(config.UMLS_INDEX_PATH)
    if not p.exists():
        raise SystemExit(
            "the full 'umls' backend needs its SQLite index. Build it once from your "
            "licensed UMLS install:\n"
            f"  .venv/bin/python scripts/build_umls_index.py <.../META> {p}\n"
            "(or select 'bastardized-umls' for the license-free scispaCy subset).")
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True, check_same_thread=False)


_TUI_PLACEHOLDERS = ",".join("?" * len(config.UMLS_SEMANTIC_TYPES))
_TUIS = tuple(sorted(config.UMLS_SEMANTIC_TYPES))


@lru_cache(maxsize=8192)
def _concepts(word: str) -> frozenset:
    """CUIs whose English atom == word AND that carry an allowed clinical TUI; empty if
    OOV. Short heads short-circuit (see medical.py for why 'for'/'xml' are dropped)."""
    if len(word.strip()) < config.UMLS_MIN_TOKEN_LEN:
        return frozenset()
    cur = _db().execute(
        "SELECT DISTINCT s.cui FROM str2cui s JOIN cui2sty t ON s.cui = t.cui "
        f"WHERE s.norm = ? AND t.tui IN ({_TUI_PLACEHOLDERS})",
        (word.lower(), *_TUIS))
    return frozenset(r[0] for r in cur)


def umls_sim(a: str, b: str):
    ca, cb = _concepts(a.lower()), _concepts(b.lower())
    if not ca or not cb:
        return None
    return 1.0 if ca & cb else 0.0
