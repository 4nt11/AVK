# SPDX-License-Identifier: GPL-3.0-or-later
"""Project registry -- loads spec targets from targets.toml.

Each [target.NAME] declares a document to analyze (kind + source path(s)) and,
optionally, a findings matcher + casefile dir. This is the only place bound to a
specific standard's files; the pipeline itself never changes. See targets.toml.example.
"""
from __future__ import annotations
import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .model import SpecIngestAdapter, FindingsMatcher, NullMatcher
from .adapters.dicom import DicomDocBookAdapter, DicomFindingsMatcher
from .adapters.fhir import FhirHtmlAdapter, FhirFindingsMatcher
from .adapters.epub import EpubClauseAdapter
from .adapters.pdf import PdfDoclingAdapter

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ROOT / "targets.toml"


@dataclass
class Project:
    name: str
    adapter: SpecIngestAdapter
    matcher: FindingsMatcher
    out_stem: str
    findings_path: Path
    cases: str | None = None
    oracle_lexicons: list[str] = field(default_factory=lambda: ["wordnet"])
    spec_lexicon: str | None = None      # path to this spec's harvested lexicon (for oracle="...,spec")


def _p(path: str) -> str:
    return str(Path(path).expanduser())


def _load_targets() -> dict:
    if not TARGETS.exists():
        raise SystemExit("no targets.toml -- copy targets.toml.example and point it "
                         "at your local spec documents.")
    return tomllib.load(TARGETS.open("rb")).get("target", {})


def _build_adapter(t: dict) -> SpecIngestAdapter:
    kind = t.get("kind")
    if kind == "dicom":
        return DicomDocBookAdapter({_p(k): v for k, v in t["sources"].items()})
    if kind == "fhir":
        return FhirHtmlAdapter(_p(t["site"]), t.get("spec", "FHIR"), t.get("pages"))
    if kind == "epub":
        return EpubClauseAdapter(_p(t["epub"]), t.get("spec", "spec"))
    if kind == "pdf":
        return PdfDoclingAdapter(_p(t["pdf"]), t.get("spec", "spec"),
                                 first_page=t.get("first_page", 1),
                                 chunk=t.get("chunk", 250),
                                 page_batch_size=t.get("page_batch_size", 16),
                                 workers=t.get("workers", 1))
    raise SystemExit(f"target has unknown kind '{kind}' (dicom|fhir|epub|pdf)")


def _parse_oracle(t: dict) -> list[str]:
    """`oracle = "wordnet"` (default) or `oracle = "wordnet,umls"` -> ordered lexicon list."""
    lex = [x.strip().lower() for x in t.get("oracle", "wordnet").split(",") if x.strip()]
    for x in lex:
        if x not in ("wordnet", "bastardized-umls", "umls", "spec"):
            raise SystemExit(f"target oracle '{t.get('oracle')}': unknown lexicon "
                             f"'{x}' (wordnet|bastardized-umls|umls|spec)")
    return lex or ["wordnet"]


def _build_matcher(t: dict, findings_path: Path) -> FindingsMatcher:
    which = t.get("matcher", "none")
    if which == "none" or not findings_path.exists():
        return NullMatcher()
    d = json.loads(findings_path.read_text())
    if which == "dicom":
        return DicomFindingsMatcher(d.get("section_prefixes", []),
                                    d.get("keywords", []), d.get("vrs", []))
    if which == "fhir":
        return FhirFindingsMatcher(d.get("section_numbers", []),
                                   d.get("concepts", []), d.get("invariants", []))
    raise SystemExit(f"target has unknown matcher '{which}' (dicom|fhir|none)")


def get_project(name: str) -> Project:
    targets = _load_targets()
    if name not in targets:
        raise SystemExit(f"unknown project '{name}'. defined in targets.toml: "
                         f"{', '.join(targets) or '(none)'}")
    t = targets[name]
    findings_path = ROOT / f"{name}_findings.json"
    spec_lex = str((ROOT / t["spec_lexicon"]).resolve()) if t.get("spec_lexicon") else None
    return Project(name, _build_adapter(t), _build_matcher(t, findings_path),
                   name, findings_path, t.get("cases"), _parse_oracle(t), spec_lex)


def list_projects() -> list[str]:
    return list(_load_targets()) if TARGETS.exists() else []
