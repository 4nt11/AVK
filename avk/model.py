# SPDX-License-Identifier: GPL-3.0-or-later
"""Domain-agnostic core types.

The pipeline (stages 2-4) knows nothing about DICOM or FHIR -- it operates on
`Unit`s produced by a `SpecIngestAdapter` and asks a `FindingsMatcher` whether a
unit overlaps a known differential-testing finding. Adding a new standard
(IEEE 11073/BICEPS, HL7 v2, ...) means writing one adapter + one matcher, not
touching the core.
"""
from __future__ import annotations
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import Iterator


@dataclass
class Unit:
    """One sentence-level prose unit with traceability back to a spec anchor."""
    uid: str                 # stable id, e.g. "PS3.5:6.2:3" or "FHIR-R5:datatypes:2.1.28.0.1:4"
    spec: str                # spec + version label, e.g. "PS3.5" / "FHIR R5"
    section: str             # section number, e.g. "6.2" / "2.1.28.0.1"
    section_title: str
    subref: str | None       # optional sub-anchor: a table id ("6.2-1") or page ("datatypes.html")
    anchor: str              # human spec reference, e.g. "PS3.5 Table 6.2-1" / "FHIR R5 datatypes.html#2.1.28.0.1"
    text: str
    char_start: int          # offset within the source paragraph
    char_end: int

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class SpecIngestAdapter(ABC):
    """Stage 1 plug point: turn a standard's local sources into `Unit`s.

    Implementations: adapters.dicom.DicomDocBookAdapter, adapters.fhir.FhirHtmlAdapter.
    """
    name: str = "spec"

    @abstractmethod
    def ingest(self) -> Iterator[Unit]:
        ...


class FindingsMatcher(ABC):
    """Decides whether a unit overlaps a known differential-testing finding.

    Matching differs per standard (DICOM: section-prefix + tag + VR; FHIR:
    section-number + title-concept), so each project supplies its own.
    """

    @abstractmethod
    def match(self, unit: Unit) -> tuple[str | None, bool]:
        """Return (tag, precise). tag is a short match label or None; precise=True
        means force-surface at the top, False means flag-only (broad match)."""
        ...


class NullMatcher(FindingsMatcher):
    def match(self, unit): return (None, False)


def load_units(jsonl_path) -> Iterator[Unit]:
    from pathlib import Path
    with Path(jsonl_path).open(encoding="utf-8") as fh:
        for line in fh:
            yield Unit(**json.loads(line))
