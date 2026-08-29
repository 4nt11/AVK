# SPDX-License-Identifier: GPL-3.0-or-later
"""AVK -- Ambiguity Vocoder Kraftwerk. Nocuous-ambiguity triage for standards prose.

Domain-agnostic pipeline (sibling to DCMK -- feeds it case scaffolds):
  stage 1 ingest    -- SpecIngestAdapter (adapters.dicom/fhir/epub/pdf) -> Units
  stage 2 triage    -- cheap lexical/syntactic ambiguity scoring
  stage 3 oracle    -- 4-parser structural disagreement + Chantree nocuous scoring
  stage 4 output    -- ranked CSV/JSON, findings-overlap surfacing
  stage 5 scaffold  -- AVK: oracle rows -> DCMK case-file scaffolds

Stages 2-5 are standard-independent; a new standard = one adapter + one matcher +
one projects.py entry. This produces a PRIORITIZATION SIGNAL, not ground truth.
"""
__all__ = ["model", "triage", "oracle", "disagree", "parsers", "output",
           "scaffold", "projects", "config", "segment"]
