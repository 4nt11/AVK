# SPDX-License-Identifier: GPL-3.0-or-later
"""FHIR adapter -- HL7 FHIR published HTML (R4/R5) -> Units, + interNOOP matcher.

FHIR prose pages carry numbered headings ("2.1.28.0.1 Primitive Types") and keep
their normative text under <div id="segment-content">; the rest is site chrome
(nav/header/footer/breadcrumb) and must be dropped. The publish tree also contains
~11k auto-generated resource/valueset/*.json.html pages -- those are NOT prose and
are excluded by the curated page list, not walked blindly.
"""
from __future__ import annotations
import re
import warnings
from pathlib import Path
from typing import Iterator

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from ..model import Unit, SpecIngestAdapter, FindingsMatcher
from ..segment import split_sentences

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

_WS = re.compile(r"\s+")
_HDR_NUM = re.compile(r"^([\d]+(?:\.[\d]+)+)\s+(.*)$")   # "2.1.28.0.1 Primitive Types"

# Foundation prose pages interNOOP casefiles actually cite (data types, wire
# formats, search, references). Resource pages can be added but are mostly
# generated tables. Tune per project.
DEFAULT_PAGES = [
    "datatypes.html", "json.html", "xml.html", "formats.html", "search.html",
    "http.html", "references.html", "extensibility.html", "terminologies.html",
    "narrative.html", "resource.html", "element.html", "datatypes-definitions.html",
    "search_filter.html", "codesystem.html", "valueset.html", "bundle.html",
]


def _clean(t: str) -> str:
    return _WS.sub(" ", t.replace("\xa0", " ")).strip()


class FhirHtmlAdapter(SpecIngestAdapter):
    name = "fhir"

    def __init__(self, site_dir: str, spec_label: str = "FHIR R5",
                 pages: list[str] | None = None, min_chars: int = 25):
        self.site = Path(site_dir)
        self.spec = spec_label
        self.pages = pages or DEFAULT_PAGES
        self.min_chars = min_chars

    def ingest(self) -> Iterator[Unit]:
        for page in self.pages:
            p = self.site / page
            if p.exists():
                yield from self._ingest_page(p, page)

    def _ingest_page(self, path: Path, page: str) -> Iterator[Unit]:
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "lxml")
        content = soup.find(id="segment-content") or soup
        stem = page.replace(".html", "")
        section, title = "0", stem              # page-level fallback
        counters: dict[str, int] = {}
        seen: set[tuple[str, str]] = set()
        for el in content.find_all(["h1", "h2", "h3", "h4", "h5", "p", "li"]):
            txt = _clean(el.get_text(" ", strip=True))
            if not txt:
                continue
            if el.name.startswith("h"):
                m = _HDR_NUM.match(txt)
                if m:
                    section, title = m.group(1), m.group(2)
                else:
                    title = txt[:80]            # unnumbered heading: keep last number
                continue
            if len(txt) < self.min_chars:
                continue
            anchor = f"{self.spec} {page}#{section}"
            for sent, cs, ce in split_sentences(txt):
                if len(sent) < self.min_chars or (section, sent) in seen:
                    continue
                seen.add((section, sent))
                key = section
                counters[key] = counters.get(key, 0) + 1
                slug = self.spec.replace(" ", "-")
                uid = f"{slug}:{stem}:{section}:{counters[key]}"
                yield Unit(uid, self.spec, section, title, page, anchor, sent, cs, ce)


class FhirFindingsMatcher(FindingsMatcher):
    """interNOOP overlap: FHIR section number, section-title concept, or invariant id.

    Findings are free-text citations ("FHIR R5 3.2.1.5.6 Prefixes", "§JSON
    Representation", "invariant ref-1"), so we match on all three shapes.
    """

    def __init__(self, section_numbers, concepts, invariants):
        self.section_numbers = list(section_numbers)
        self.concepts = [c.lower() for c in concepts]
        self.invariants = list(invariants)

    def match(self, unit: Unit):
        sec = unit.section
        for n in self.section_numbers:            # exact clause hit -> precise
            if sec == n:
                return f"sect:{n}", True
        for n in self.section_numbers:            # unit inside a cited subtree
            if sec.startswith(n + "."):
                # FHIR numbering is deep (page.ch.sec.sub...); a clause-level cite is
                # >=4 components -> precise, a chapter-level cite -> broad.
                return f"sect>:{n}", (len(n.split(".")) >= 4)
        for n in self.section_numbers:            # unit is only an ancestor container -> broad
            if n.startswith(sec + "."):
                return f"sect<:{n}", False
        tl = unit.section_title.lower()
        for c in self.concepts:
            if c and c in tl:
                return f"concept:{c}", True          # concept in the heading -> precise
        low = unit.text.lower()
        for inv in self.invariants:
            if re.search(rf"\b{re.escape(inv)}\b", unit.text):
                return f"inv:{inv}", True
        for c in self.concepts:
            if c and len(c) > 4 and c in low:
                return f"concept~:{c}", False        # concept only in body -> broad
        return None, False
