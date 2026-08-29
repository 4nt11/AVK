# SPDX-License-Identifier: GPL-3.0-or-later
"""DICOM adapter -- NEMA DocBook HTML (PS3.x) -> Units, + DCMK findings matcher.

Ported from the original monolithic ingest. Section/table traceability via the
DocBook `<a id="sect_...">` / `<a id="table_...">` anchors.
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
_SECT_ID = re.compile(r"^sect_(.+)$")
_TABLE_ID = re.compile(r"^table_(.+)$")


def _clean(text: str) -> str:
    return _WS.sub(" ", text.replace("\xa0", " ")).strip()


class DicomDocBookAdapter(SpecIngestAdapter):
    name = "dicom"

    def __init__(self, sources: dict[str, str], min_chars: int = 25):
        """sources: {html_path: spec_label}, e.g. {".../part05.html": "PS3.5"}."""
        self.sources = sources
        self.min_chars = min_chars

    def ingest(self) -> Iterator[Unit]:
        for path, label in self.sources.items():
            yield from self._ingest_one(Path(path), label)

    def _nearest_section(self, el):
        sec = el.find_parent("div", class_="section")
        while sec is not None:
            a = sec.find("a", id=_SECT_ID)
            if a is not None:
                num = _SECT_ID.match(a["id"]).group(1)
                h = sec.find(["h1", "h2", "h3", "h4", "h5", "h6"])
                title = ""
                if h is not None:
                    htxt = _clean(h.get_text(" ", strip=True))
                    title = re.sub(r"^" + re.escape(num) + r"\s*", "", htxt).strip()
                return num, title
            sec = sec.find_parent("div", class_="section")
        return "", ""

    def _nearest_table(self, el):
        tdiv = el.find_parent("div", class_="table")
        if tdiv is None:
            return None
        a = tdiv.find("a", id=_TABLE_ID)
        return _TABLE_ID.match(a["id"]).group(1) if a is not None else None

    def _ingest_one(self, path: Path, label: str) -> Iterator[Unit]:
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "lxml")
        counters: dict[str, int] = {}
        seen: set[tuple[str, str]] = set()
        for el in soup.find_all(["p", "li"]):
            raw = _clean(el.get_text(" ", strip=True))
            if len(raw) < self.min_chars:
                continue
            section, title = self._nearest_section(el)
            if not section:
                continue  # front matter -- not normative, not traceable
            table = self._nearest_table(el)
            anchor = f"{label} Table {table}" if table else f"{label} {section}".strip()
            key = f"{section}|{table}"
            for sent, cs, ce in split_sentences(raw):
                if len(sent) < self.min_chars:
                    continue
                if (section, sent) in seen:
                    continue
                seen.add((section, sent))
                counters[key] = counters.get(key, 0) + 1
                uid = f"{label}:{section}:{table + '.' if table else ''}{counters[key]}"
                yield Unit(uid, label, section, title, table, anchor, sent, cs, ce)


class DicomFindingsMatcher(FindingsMatcher):
    """DCMK overlap: section/table anchor prefix, data-element tag, VR-in-context."""

    def __init__(self, section_prefixes, keywords, vrs):
        self.section_prefixes = list(section_prefixes)
        self.keywords = list(keywords)
        self.vrs = list(vrs)

    @staticmethod
    def _depth(prefix: str):
        rest = prefix.split(" ", 1)[1] if " " in prefix else prefix
        return "table" if rest.startswith("Table") else len(rest.split("."))

    def match(self, unit: Unit):
        for pref in self.section_prefixes:
            rest = pref.split(" ", 1)[1]
            if rest.startswith("Table"):
                if unit.anchor == pref:
                    return f"anchor:{pref}", True
            elif unit.section == rest:
                return f"anchor:{pref}", True
            elif unit.subref is None and unit.section.startswith(rest + "."):
                return f"anchor:{pref}", (self._depth(pref) >= 3)
        low = unit.text.lower()
        for kw in self.keywords:
            if kw.lower() in low:
                return f"kw:{kw}", True
        for vr in self.vrs:
            if re.search(rf"\b{re.escape(vr)}\b", unit.text) and re.search(
                    rf"(?:Value Representation|VRs?)\b[^.]{{0,40}}\b{re.escape(vr)}\b"
                    rf"|\b{re.escape(vr)}\b[^.]{{0,15}}(?:Value Representation|\()", unit.text):
                return f"vr:{vr}", True
        return None, False
