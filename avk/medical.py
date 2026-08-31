# SPDX-License-Identifier: GPL-3.0-or-later
"""UMLS lexicon backend for the ambiguity oracle (opt-in: `oracle = "wordnet,umls"`).

WordNet cannot judge biomedical jargon -- every clinical head word is OOV, so those
disagreement loci collapse to "undetermined". This backend answers the SAME yes/no the
oracle asks of WordNet -- "do these two competing heads mean the same concept?" -- but
against UMLS via scispaCy's concept linker, so medical FHIR/clinical specs get a real
verdict instead of a shrug.

scispaCy's linker pins numpy<2, which would fight the main venv's GPU/docling stack, so
it lives in a SEPARATE `.venv-umls` and we talk to it over a long-lived subprocess
(_umls_worker.py) -- one process, KB loaded once, one line per query. First run downloads
scispaCy's UMLS KB (~1 GB) and is slow to warm; progress prints on the worker's stderr.
"""
from __future__ import annotations
import atexit
import json
import subprocess
from functools import lru_cache
from pathlib import Path

from . import config

_ROOT = Path(__file__).resolve().parent.parent
_UMLS_PY = _ROOT / ".venv-umls" / "bin" / "python"
_WORKER = Path(__file__).resolve().parent / "_umls_worker.py"


@lru_cache(maxsize=1)
def _proc():
    if not _UMLS_PY.exists():
        raise SystemExit(
            "the 'umls' ambiguity oracle needs its own isolated env (kept separate so "
            "scispaCy's numpy<2 pin can't touch the GPU venv). Create it once:\n"
            "  uv venv .venv-umls\n"
            "  uv pip install --python .venv-umls scispacy click https://"
            "s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/"
            "en_core_sci_sm-0.5.4.tar.gz\n"
            "  (click is a spaCy-CLI dep uv's scispaCy resolve drops -- install explicitly)")
    p = subprocess.Popen(
        [str(_UMLS_PY), str(_WORKER),
         str(config.UMLS_MATCH_THRESHOLD), str(config.UMLS_CANDIDATES),
         ",".join(sorted(config.UMLS_SEMANTIC_TYPES))],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
    # blocks through the one-time KB load; tolerate any stray stdout before READY
    while True:
        line = p.stdout.readline()
        if line == "":                         # worker died before handshaking
            raise SystemExit("UMLS worker exited before READY; check its stderr.")
        if line.strip() == "READY":
            break
    atexit.register(p.terminate)
    return p


@lru_cache(maxsize=8192)
def _concepts(word: str) -> frozenset:
    """Top UMLS concept ids (CUIs) for a head word, via the worker; empty if OOV.

    Sub-threshold-length tokens are dropped unqueried: short heads ("for", "xml", "r4")
    char-ngram alias-match to junk CUIs, so they never reach the worker.
    """
    if len(word.strip()) < config.UMLS_MIN_TOKEN_LEN:
        return frozenset()
    p = _proc()
    p.stdin.write(word + "\n")
    p.stdin.flush()
    return frozenset(json.loads(p.stdout.readline()))


def umls_sim(a: str, b: str):
    """1.0 if the two heads share a UMLS concept, 0.0 if both link but to disjoint
    concepts, None if either is unknown to UMLS (defer to the next lexicon).

    # ponytail: binary same/different, not graded distance -- UMLS has no metric as
    # cheap as WordNet's path_similarity. If coarseness bites, walk CHD/PAR relations
    # for a hop-distance and map that onto [0,1]; until then 0/1 is enough to split
    # "same concept" (innocuous) from "different concept" (nocuous).
    """
    ca, cb = _concepts(a.lower()), _concepts(b.lower())
    if not ca or not cb:
        return None
    return 1.0 if ca & cb else 0.0
