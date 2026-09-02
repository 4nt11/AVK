# SPDX-License-Identifier: GPL-3.0-or-later
"""Harvest DICOM's own vocabulary into the 'spec' ambiguity-oracle lexicon.

Two sources, one robust + one best-effort:
  * pydicom (PS3.6): the FULL data-element dictionary (every attribute keyword + name,
    e.g. PatientName, PixelData, StudyInstanceUID) and the UID registry (SOP classes,
    transfer syntaxes). Machine-readable, authoritative, zero HTML parsing.
  * PS3.16 (part16.html): Content Mapping Resource -- coded concept "Code Meaning" cells,
    the DICOM analog of FHIR CodeSystems. Best-effort: DICOM context-group tables use
    rowspans, so column alignment is approximate. These land as kind='code' (excluded
    from oracle sim by default, like FHIR code displays) but stay in the shared dataset.

DICOM is published freely by NEMA -> redistributable dataset. Keywords are camelCase, so
avk.disagree._norm_head-style normalization lets an oracle head 'pixel data' hit 'PixelData'.

  .venv/bin/python scripts/build_dicom_lexicon.py <dir with part*.html> avk-datasets/dicom_lexicon
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

from pydicom.datadict import DicomDictionary
from pydicom.uid import UID_dictionary

DIR = Path(sys.argv[1])
OUT = Path(sys.argv[2])
SOURCE = "DICOM"


def norm(s: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    s = re.sub(r"[^A-Za-z0-9]+", " ", s)
    return " ".join(s.split()).lower()


rows = []   # (norm, term, concept_id, kind, source, definition)

# PS3.6 data elements: (VR, VM, name, isRetired, keyword)
for vr, vm, name, retired, keyword in DicomDictionary.values():
    if keyword:
        rows.append((norm(keyword), keyword, f"DICOM-DE:{keyword}", "attribute", SOURCE, name or ""))
        if name and name != keyword:
            rows.append((norm(name), name, f"DICOM-DE:{keyword}", "attribute", SOURCE, ""))

# PS3.6 UID registry: uid -> (name, type, ...)
for uid, meta in UID_dictionary.items():
    name = meta[0]
    if name:
        rows.append((norm(name), name, f"DICOM-UID:{uid}", "uid", SOURCE, meta[1] if len(meta) > 1 else ""))

# PS3.16 coded concepts -- best-effort Code Meaning extraction
p16 = DIR / "part16.html"
n_codes = 0
if p16.exists():
    import lxml.html
    doc = lxml.html.parse(str(p16)).getroot()
    for t in doc.xpath("//table"):
        heads = [(th.text_content() or "").strip() for th in t.xpath(".//tr[1]//th")]
        im = next((i for i, h in enumerate(heads) if "Code Meaning" in h), None)
        if im is None:
            continue
        iv = next((i for i, h in enumerate(heads) if h == "Code Value"), None)
        isch = next((i for i, h in enumerate(heads) if "Coding Scheme Designator" in h), None)
        for tr in t.xpath(".//tr[td]"):
            tds = tr.xpath("./td")
            if im >= len(tds):
                continue
            meaning = (tds[im].text_content() or "").strip()
            if len(meaning) < 2 or meaning in ("...", "…"):
                continue
            val = (tds[iv].text_content() or "").strip() if iv is not None and iv < len(tds) else ""
            sch = (tds[isch].text_content() or "").strip() if isch is not None and isch < len(tds) else "DCM"
            cid = f"{sch or 'DCM'}:{val}" if val else f"DCM-MEANING:{norm(meaning)}"
            rows.append((norm(meaning), meaning, cid, "code", SOURCE, ""))
            n_codes += 1

# dedup by (norm, concept_id), drop empty norms
seen, uniq = set(), []
for row in rows:
    k = (row[0], row[2])
    if row[0] and k not in seen:
        seen.add(k); uniq.append(row)

OUT.parent.mkdir(parents=True, exist_ok=True)
sq = OUT.with_suffix(".sqlite")
sq.unlink(missing_ok=True)
con = sqlite3.connect(sq)
con.execute("CREATE TABLE terms(norm TEXT, term TEXT, concept_id TEXT, kind TEXT, source TEXT, definition TEXT)")
con.executemany("INSERT INTO terms VALUES(?,?,?,?,?,?)", uniq)
con.execute("CREATE INDEX ix_norm ON terms(norm)")
con.commit(); con.close()

cols = ["norm", "term", "concept_id", "kind", "source", "definition"]
with OUT.with_suffix(".jsonl").open("w", encoding="utf-8") as fh:
    for row in uniq:
        fh.write(json.dumps(dict(zip(cols, row)), ensure_ascii=False) + "\n")

kinds = {}
for row in uniq:
    kinds[row[3]] = kinds.get(row[3], 0) + 1
print(f"harvested {len(uniq):,} terms {kinds} ({n_codes:,} raw code meanings) -> "
      f"{sq.name} + {OUT.with_suffix('.jsonl').name}")
