# SPDX-License-Identifier: GPL-3.0-or-later
"""EPUB adapter -- ITU-T X-series Recommendations (X.509, ...) as EPUB.

An EPUB is a ZIP: META-INF/container.xml -> .opf (spine = reading order) -> XHTML.
ITU EPUBs mark clauses as <p class="hN" id="sec_3_5_1">3.5.1 Title</p> and body
prose as <p class="noindent|hang1|...">. Clause number comes from the sec_ id
(unambiguous), falling back to the leading number in the heading text.

No <hN> tags, so headings are detected by class (^h\\d) or a sec_ id. Front-matter
spine docs (cover/title/foreword/contents) are skipped by filename.
"""
from __future__ import annotations
import re
import warnings
import zipfile
from posixpath import dirname, join, normpath
from typing import Iterator

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from ..model import Unit, SpecIngestAdapter
from ..segment import split_sentences

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

_WS = re.compile(r"\s+")
_SEC_ID = re.compile(r"^sec_([\w]+)$")          # sec_3_5_1 -> 3.5.1 ; sec_A_1 -> A.1
_HCLASS = re.compile(r"^h\d")                    # h1, h2, h3, h3a ...
_TITLECLASS = re.compile(r"^tit\d?")            # tit, tit2, tit2a -- annex/page titles
_LEADNUM = re.compile(r"^([A-Z]?\d+(?:\.\d+)*)\s+(.*)$")  # "3.5.1 Title" / "A.1 Title"
_ANNEX = re.compile(r"Annex([A-Z])")            # 12_AnnexF -> F
_DEFAULT_SKIP = re.compile(
    r"(cover|title|language|recommendation|foreword|contents|intro|biblio|series)", re.I)


def _clean(t: str) -> str:
    return _WS.sub(" ", t.replace("\xa0", " ")).strip()


class EpubClauseAdapter(SpecIngestAdapter):
    name = "epub"

    def __init__(self, epub_path: str, spec_label: str,
                 skip_re: re.Pattern = _DEFAULT_SKIP, min_chars: int = 25):
        self.path = epub_path
        self.spec = spec_label
        self.skip_re = skip_re
        self.min_chars = min_chars

    def _spine_docs(self, z: zipfile.ZipFile):
        cont = z.read("META-INF/container.xml").decode("utf-8", "replace")
        opf_path = re.search(r'full-path="([^"]+)"', cont).group(1)
        opf = BeautifulSoup(z.read(opf_path).decode("utf-8", "replace"), "xml")
        manifest = {it.get("id"): (it.get("href"), it.get("media-type") or "")
                    for it in opf.find_all("item")}
        base = dirname(opf_path)
        for ref in opf.find_all("itemref"):
            iid = ref.get("idref")
            if iid in manifest and "html" in manifest[iid][1]:
                yield normpath(join(base, manifest[iid][0]))

    def ingest(self) -> Iterator[Unit]:
        z = zipfile.ZipFile(self.path)
        for doc in self._spine_docs(z):
            fname = doc.split("/")[-1]
            if self.skip_re.search(fname):
                continue
            yield from self._ingest_doc(z.read(doc).decode("utf-8", "replace"), fname)

    def _heading(self, p):
        """Return (section, title) for a numbered clause heading, ("KEEP", title) for
        a title-only heading (keeps the current section), or None if not a heading."""
        classes = p.get("class") or []
        pid = p.get("id") or ""
        m_id = _SEC_ID.match(pid)
        txt = _clean(p.get_text(" ", strip=True))
        if m_id:
            m = _LEADNUM.match(txt)
            return (m_id.group(1).replace("_", "."), m.group(2) if m else txt)
        if any(_HCLASS.match(c) for c in classes):
            m = _LEADNUM.match(txt)
            return (m.group(1), m.group(2)) if m else ("KEEP", txt)
        if any(_TITLECLASS.match(c) for c in classes):   # tit2a etc: annex/page title
            return ("KEEP", re.split(r"\s*\(", txt, 1)[0])  # drop "(This annex ...)" tail
        return None

    def _ingest_doc(self, html: str, fname: str) -> Iterator[Unit]:
        soup = BeautifulSoup(html, "lxml")
        # Seed the section from the filename (AnnexF -> "F") so a doc whose only
        # heading is an unnumbered title still yields traceable, non-dropped prose.
        m = _ANNEX.search(fname)
        default_section = m.group(1) if m else fname.replace(".xhtml", "")
        section, title = default_section, default_section
        counters: dict[str, int] = {}
        seen: set[tuple[str, str]] = set()
        for p in soup.find_all("p"):
            head = self._heading(p)
            if head is not None:
                if head[0] == "KEEP":
                    title = head[1]
                else:
                    section, title = head
                continue
            if not section:
                continue
            raw = _clean(p.get_text(" ", strip=True))
            if len(raw) < self.min_chars:
                continue
            anchor = f"{self.spec} {section}"
            for sent, cs, ce in split_sentences(raw):
                if len(sent) < self.min_chars or (section, sent) in seen:
                    continue
                seen.add((section, sent))
                counters[section] = counters.get(section, 0) + 1
                uid = f"{self.spec}:{section}:{counters[section]}"
                yield Unit(uid, self.spec, section, title, fname, anchor, sent, cs, ce)
