---
license: odbl
pretty_name: AVK Spec Lexicons (FHIR + DICOM)
language:
  - en
tags:
  - healthcare
  - interoperability
  - fhir
  - dicom
  - hl7
  - terminology
  - ambiguity
  - nlp
size_categories:
  - 10K<n<100K
configs:
  - config_name: fhir_r5
    data_files: fhir_r5_lexicon.jsonl
  - config_name: dicom
    data_files: dicom_lexicon.jsonl
---

# AVK Spec Lexicons

Domain vocabularies **harvested from healthcare standards' own published definitions**, for
resolving terms that general lexicons (WordNet, UMLS) don't contain. Built for
[AVK](https://github.com/4nt11/AVK), an ambiguity-triage tool that flags where standards
prose is ambiguous — but usable standalone as a term → concept resource.

**The idea:** `DiagnosticReport`, `CodeableConcept`, `PixelData`, `StudyInstanceUID` are
defined precisely by FHIR and DICOM themselves, yet are absent from UMLS (they're HL7/DICOM
model classes and data elements, not clinical findings). A standard is its own best lexicon —
so these are harvested straight from what each standard publishes.

## Subsets

| config | terms | source |
|--------|-------|--------|
| `fhir_r5` | 5,095 | FHIR R5 `definitions.json` — StructureDefinitions (resource + datatype names) and CodeSystems |
| `dicom` | 23,316 | DICOM PS3.6 via `pydicom` (data-element keywords + UID/SOP registry) + PS3.16 Code Meanings |

## Schema

One JSON object per line:

| field | meaning |
|-------|---------|
| `norm` | normalized lookup key (camelCase split, lowercased) — `DiagnosticReport` → `diagnostic report` |
| `term` | the term as published |
| `concept_id` | stable id (FHIR StructureDefinition URL, `DICOM-DE:<keyword>`, `DICOM-UID:<uid>`, or `<scheme>:<code>`) |
| `kind` | `resource` / `complex-type` / `primitive-type` / `attribute` / `uid` / `code` |
| `source` | `FHIR-R5` or `DICOM` |
| `definition` | short description where the source provides one |

Two terms sharing a `concept_id` are the same concept (synonyms); distinct `concept_id`s are
distinct concepts.

## Usage

```python
from datasets import load_dataset

fhir = load_dataset("4nt11/avk-datasets", "fhir_r5", split="train")
dcm  = load_dataset("4nt11/avk-datasets", "dicom",   split="train")
```

Each subset also ships as a ready-to-query SQLite index (`*_lexicon.sqlite`, table `terms`,
indexed on `norm`) — what AVK's `spec` oracle backend reads directly.

## Notes & caveats

- **`kind='code'` is lower-precision.** FHIR CodeSystem displays and DICOM Code Meanings
  include generic words (`the`, `request`) that collide with ordinary prose. AVK excludes
  `code` from its similarity scoring by default and trusts only the named concepts; they're
  kept here for completeness.
- **DICOM Code Meanings are best-effort.** Extracted from PS3.16 (`part16.html`) tables, which
  use rowspans — column alignment is approximate, so some `code` rows may be imperfect. The
  6,336 `attribute` + `uid` terms (from `pydicom`) are authoritative and parse-risk-free.

## Provenance & licensing

This is a **derived vocabulary index**, and licensing applies in two layers:

- **The database** (this compilation — the selection, normalization, and `concept_id` scheme)
  is released under the **Open Database License (ODbL) v1.0**.
- **The contents** (the individual terms) retain their **source** licenses:
  - **FHIR R5** © HL7, published under **CC0** — freely redistributable.
  - **DICOM** © NEMA, reproduced under the DICOM Standard's permissive reproduction terms;
    `pydicom` (MIT) supplies the PS3.6 data.

ODbL governs the compilation only; it does not (and cannot) relicense the underlying HL7/NEMA
content. Consult the primary publications ([hl7.org/fhir](https://hl7.org/fhir),
[dicomstandard.org](https://www.dicomstandard.org)) for authoritative, current definitions.
**No UMLS-licensed content is included, by design** — that's what keeps this shareable.
