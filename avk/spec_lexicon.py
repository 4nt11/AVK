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
        raise SystemExit(
            "the 'spec' backend needs its lexicon index. Build it from the spec's "
            "published definitions:\n"
            f"  .venv/bin/python scripts/build_spec_lexicon.py <definitions.json.zip> "
            f"{p.with_suffix('')}")
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True, check_same_thread=False)


_KIND_PLACEHOLDERS = ",".join("?" * len(config.SPEC_KINDS))
_KINDS = tuple(sorted(config.SPEC_KINDS))


@lru_cache(maxsize=8192)
def _concepts(term: str) -> frozenset:
    """Concept ids for a term, restricted to trusted kinds (model-class names, not the
    generic code displays). Short heads short-circuit, as in the UMLS backends."""
    if len(term.strip()) < config.UMLS_MIN_TOKEN_LEN:
        return frozenset()
    cur = _db().execute(
        f"SELECT DISTINCT concept_id FROM terms WHERE norm = ? AND kind IN ({_KIND_PLACEHOLDERS})",
        (term.lower(), *_KINDS))
    return frozenset(r[0] for r in cur)


def spec_sim(a: str, b: str):
    ca, cb = _concepts(a.lower()), _concepts(b.lower())
    if not ca or not cb:
        return None
    return 1.0 if ca & cb else 0.0
