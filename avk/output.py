# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 4 -- OUTPUT (domain-agnostic).

Ranked CSV + JSON. Precise findings-overlap units surface at the top regardless of
score; broad overlaps are flagged but rank by score. Overlap is decided by the
project's FindingsMatcher, not by any standard-specific logic here.
"""
from __future__ import annotations
import csv
import json
from dataclasses import asdict
from pathlib import Path

from .oracle import VERDICT_RANK
from .model import NullMatcher


def build_rows(scored, oracle_results=None, matcher=None):
    """scored: iterable of (unit, TriageResult). oracle_results: {uid: OracleResult}."""
    matcher = matcher or NullMatcher()
    oracle_results = oracle_results or {}
    rows = []
    for unit, tri in scored:
        orc = oracle_results.get(unit.uid)
        tag, precise = matcher.match(unit)
        rows.append({
            "uid": unit.uid,
            "spec": unit.spec,
            "section": unit.section,
            "subref": unit.subref or "",
            "anchor": unit.anchor,
            "section_title": unit.section_title,
            "triage_score": round(tri.score, 3),
            "triage_signals": json.dumps(tri.signals, ensure_ascii=False),
            "disagreement_score": round(orc.disagreement_score, 3) if orc else "",
            "verdict": orc.verdict if orc else "",
            "n_loci": orc.n_loci if orc else "",
            "n_nocuous_loci": orc.n_nocuous_loci if orc else "",
            "semantic_distance": round(orc.max_semantic_distance, 3) if orc else "",
            "divergent_readings": json.dumps([asdict(r) for r in orc.readings],
                                             ensure_ascii=False) if orc else "",
            "overlap": tag or "",
            "overlap_precise": "yes" if precise else ("broad" if tag else ""),
            "text": unit.text,
        })
    return rows


def _sort_key(row):
    precise = 1 if row["overlap_precise"] == "yes" else 0
    if row["disagreement_score"] != "":
        return (precise, 1, VERDICT_RANK.get(row["verdict"], 0),
                row["n_nocuous_loci"] or 0, row["disagreement_score"], 0.0)
    return (precise, 0, 0, 0, 0.0, row["triage_score"])


def write(rows, out_prefix: Path):
    out_prefix = Path(out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=_sort_key, reverse=True)
    cols = list(rows[0].keys()) if rows else []

    with out_prefix.with_suffix(".csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader(); w.writerows(rows)
    out_prefix.with_suffix(".json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))

    overlap_rows = [r for r in rows if r["overlap"]]
    overlap_path = out_prefix.parent / (out_prefix.stem + "_overlap.csv")
    if overlap_rows:
        with overlap_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader(); w.writerows(overlap_rows)
    return {"csv": out_prefix.with_suffix(".csv"), "n": len(rows),
            "overlap": overlap_path if overlap_rows else None, "n_overlap": len(overlap_rows)}
