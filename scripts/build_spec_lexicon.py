# SPDX-License-Identifier: GPL-3.0-or-later
"""Harvest a spec's OWN vocabulary into the 'spec' ambiguity-oracle lexicon.

The general lexicons (WordNet, UMLS) can't judge terms a standard DEFINES itself --
'DiagnosticReport', 'CodeableConcept' are HL7 model classes, absent from UMLS but
rigorously defined in FHIR. So we harvest the definitions FHIR publishes: resource +
datatype names (StructureDefinitions) and code concepts (CodeSystems). FHIR is HL7/CC0,
so the resulting dataset is freely redistributable (unlike anything UMLS-derived) -> Kaggle/HF.

Names are normalized the SAME way avk.disagree._norm_head normalizes parse heads
(camelCase -> spaced, lowercased), so an oracle head 'diagnostic report' matches the
harvested 'DiagnosticReport'. Two heads share a concept_id => same concept.

  .venv/bin/python scripts/build_spec_lexicon.py <definitions.json.zip> avk-datasets/fhir_r5_lexicon
"""
import json
import re
import sqlite3
import sys
import zipfile
from pathlib import Path

ZIP = Path(sys.argv[1])
OUT = Path(sys.argv[2])           # stem -> .sqlite + .jsonl
SOURCE = "FHIR-R5"


def norm(s: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)   # split camelCase
    s = re.sub(r"[^A-Za-z0-9]+", " ", s)             # punctuation -> space
    return " ".join(s.split()).lower()


rows = []   # (norm, term, concept_id, kind, source, definition)
z = zipfile.ZipFile(ZIP)

# resource + datatype names
for member in ("profiles-resources.json", "profiles-types.json"):
    for e in json.loads(z.read(member)).get("entry", []):
        r = e.get("resource", {})
        if r.get("resourceType") != "StructureDefinition":
            continue
        name, url = r.get("name"), r.get("url")
        if name and url:
            rows.append((norm(name), name, url, r.get("kind", "type"),
                         SOURCE, (r.get("description") or "")[:500]))

# code concepts (CodeSystems can nest concept.concept)
def walk(concepts, sysurl):
    for c in concepts:
        disp = c.get("display") or c.get("code")
        if disp:
            rows.append((norm(disp), disp, f"{sysurl}#{c.get('code')}",
                         "code", SOURCE, (c.get("definition") or "")[:300]))
        if c.get("concept"):
            walk(c["concept"], sysurl)

for e in json.loads(z.read("valuesets.json")).get("entry", []):
    r = e.get("resource", {})
    if r.get("resourceType") == "CodeSystem":
        walk(r.get("concept", []), r.get("url", ""))

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
print(f"harvested {len(uniq):,} terms {kinds} -> {sq.name} + {OUT.with_suffix('.jsonl').name}")
