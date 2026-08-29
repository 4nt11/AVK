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
