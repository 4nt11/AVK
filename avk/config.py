# SPDX-License-Identifier: GPL-3.0-or-later
"""Global, domain-agnostic knobs. Per-standard settings live in projects.py."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True)
class TriageWeights:
    modal_inconsistency: float = 3.0
    vague_term: float = 1.0
    vague_cap: int = 4
    coordination: float = 2.5
    passive_no_actor: float = 2.0
    anaphora: float = 2.5


WEIGHTS = TriageWeights()

TOP_N_FOR_ORACLE = 200
NOCUOUS_SIM_THRESHOLD = 0.50    # WordNet path-sim >= this => readings coincide => innocuous
USE_GPU = True

# --- bastardized-umls backend: scispaCy's license-free UMLS subset (medical.py) ---
# (the full licensed Metathesaurus lives in umls.py and reuses the TUI/min-len gates below)
UMLS_MATCH_THRESHOLD = 0.85    # scispaCy alias char-ngram sim to accept a CUI for a head word
UMLS_CANDIDATES = 5            # top-k CUIs considered per head word
UMLS_MIN_TOKEN_LEN = 4         # skip sub-4-char heads ("for"/"xml"/"r4" alias-match to junk CUIs)

# Trust a CUI only if it carries one of these clinical semantic types (TUIs). DEFAULT-DENY:
# the char-ngram matcher dumps ordinary English into "Qualitative/Functional/Intellectual
# Concept" types (T080/T169/T078...), so an allowlist of real clinical groups is the gate.
UMLS_SEMANTIC_TYPES = frozenset((
    "T047 T048 T191 T046 T033 T034 T184 T037 T190 T019 T020 T049 T050 "   # disorders/findings
    "T116 T121 T109 T103 T104 T197 T200 T195 T123 T125 T126 T129 T131 "
    "T130 T114 T120 T127 T122 T196 T192 "                                 # chemicals & drugs
    "T060 T061 T059 T058 T063 T062 T065 "                                 # procedures
    "T017 T029 T023 T030 T031 T022 T025 T026 T018 T021 T024 "             # anatomy
    "T038 T039 T040 T041 T042 T043 T044 T045 T032 T201 "                  # physiology
    "T074 T075 T007 T004 T005 T204"                                       # devices, organisms
).split())
