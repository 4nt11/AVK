# SPDX-License-Identifier: GPL-3.0-or-later
"""Persistent UMLS candidate-generation worker -- runs under .venv-umls, NOT the main venv.

Loads scispaCy's UMLS candidate generator once, prints READY, then serves one query per
line on stdin (a bare head word) and replies one line on stdout (JSON list of CUIs whose
alias match clears the threshold). Kept dead simple on purpose; avk/medical.py owns the
caching and the same/different logic. See avk/medical.py for why this is a subprocess.

  argv[1] = match threshold (float)   argv[2] = top-k candidates (int)
  argv[3] = comma-joined allowed semantic-type TUIs, or "" to accept any type
"""
import contextlib
import json
import sys

from scispacy.candidate_generation import CandidateGenerator

_THR = float(sys.argv[1])
_K = int(sys.argv[2])
_ALLOWED = frozenset(sys.argv[3].split(",")) if len(sys.argv) > 3 and sys.argv[3] else None

# scispaCy prints cache/download chatter to STDOUT; keep it off our line protocol by
# routing everything during the (slow, ~1 GB) load to stderr. Only READY + JSON replies
# ever reach real stdout.
with contextlib.redirect_stdout(sys.stderr):
    _cg = CandidateGenerator(name="umls")
    _kb = _cg.kb                               # cui -> entity (carries .types = TUIs)

print("READY", flush=True)                     # handshake after the KB is warm


def _ok(cui):
    if _ALLOWED is None:
        return True
    e = _kb.cui_to_entity.get(cui)
    return bool(e and _ALLOWED.intersection(e.types))


for line in sys.stdin:
    word = line.rstrip("\n")
    if not word:
        print("[]", flush=True)
        continue
    cands = _cg([word], _K)[0]
    cuis = [c.concept_id for c in cands
            if c.similarities and max(c.similarities) >= _THR and _ok(c.concept_id)]
    print(json.dumps(cuis), flush=True)
