# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 3 interface -- the AMBIGUITY ORACLE contract.

Stages 1/2/4/5 depend only on this interface, never on how the signal is produced.
The default (and only) implementation is ParserDisagreementOracle (disagree.py):
free, local, 4-parser structural disagreement + WordNet nocuous scoring. An
alternative scorer can be dropped in behind `AmbiguityOracle` without changes
elsewhere -- keep OracleResult stable.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Protocol, runtime_checkable


@dataclass
class Reading:
    """One parser's structural resolution of the ambiguous construction."""
    parser: str                     # "spacy-trf" | "stanza-dep" | "benepar" | "stanza-con"
    kind: str                       # "pp-attach" | "coord-scope" | "modifier-attach"
    locus: str                      # the trigger token/phrase, e.g. "in" @7
    resolution: str                 # human-readable resolved structure
    signature: str                  # canonical comparable key (heads/indices)


# Three-valued verdict -- WordNet cannot judge domain jargon, so "nocuous" is
# reserved for disagreements PROVEN semantically distinct; OOV-only evidence is
# "undetermined" (a human should look), not silently promoted to nocuous.
VERDICT_RANK = {"nocuous": 3, "undetermined": 2, "innocuous": 1, "none": 0}


@dataclass
class OracleResult:
    uid: str
    disagreement_score: float = 0.0     # raw structural divergence (grows with #loci)
    verdict: str = "none"               # nocuous | undetermined | innocuous | none
    n_loci: int = 0                     # comparable ambiguity loci that actually disagreed
    n_nocuous_loci: int = 0             # loci proven semantically distinct
    innocuous_reason: str = ""
    max_semantic_distance: float = 0.0  # 1 - WordNet sim, from KNOWN heads only
    readings: list[Reading] = field(default_factory=list)  # side-by-side structures

    @property
    def nocuous(self) -> bool:
        return self.verdict == "nocuous"

    @property
    def rank_score(self):
        """Verdict dominates; disagreement breaks ties within a verdict class."""
        return (VERDICT_RANK[self.verdict], self.disagreement_score)

    def to_dict(self):
        return asdict(self)


@runtime_checkable
class AmbiguityOracle(Protocol):
    def score(self, unit) -> OracleResult: ...
