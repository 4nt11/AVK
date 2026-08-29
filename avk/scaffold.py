# SPDX-License-Identifier: GPL-3.0-or-later
"""Ambiguity Vocoder Kraftwerk (AVK) -- turn oracle rows into DCMK case scaffolds.

Demodulates the oracle's structured signal (parse divergence + triage cues) into
the skeleton of a differential-testing casefile: [case] filled in, the `ambiguity`
field SYNTHESIZED from what each parser actually disagreed on, and the test-mechanics
sections ([build]/[deliver]/[observe]) left as TODO stubs for the human to design.

It scaffolds, it does not decide: the human writes the actual differential test.
"""
from __future__ import annotations
import json
import re
from collections import defaultdict
from pathlib import Path


def _tstr(s: str) -> str:
    """A safe TOML basic string (single line)."""
    s = (s or "").replace("\\", "\\\\").replace('"', '\\"')
    s = re.sub(r"\s+", " ", s).strip()
    return '"' + s + '"'


def _slug(s: str, n: int = 5) -> str:
    words = re.findall(r"[A-Za-z0-9]+", s.lower())
    return "-".join(words[:n]) or "case"


def _describe_ambiguity(row: dict) -> str:
    """Synthesize the ambiguity description from oracle divergence + triage cues."""
    parts = []
    reads = json.loads(row.get("divergent_readings") or "[]")
    loci = defaultdict(list)
    for rd in reads:
        loci[(rd["kind"], rd["locus"])].append((rd["parser"], rd["resolution"]))
    struct = []
    for (kind, locus), rs in loci.items():
        if len({res for _, res in rs}) > 1:              # a real disagreement locus
            reading = "; ".join(f"{p} -> [{res}]" for p, res in rs)
            struct.append(f"{kind} at {locus}: {reading}")
    if struct:
        parts.append("STRUCTURAL PARSE DIVERGENCE -- " + " || ".join(struct[:2]))
    sigs = json.loads(row.get("triage_signals") or "{}")
    cues = [d["reasons"][0] for d in sigs.values() if d.get("reasons")]
    if cues:
        parts.append("LEXICAL/SYNTACTIC CUES -- " + "; ".join(cues))
    parts.append(f"[auto: verdict={row.get('verdict','?')}, semantic_distance="
                 f"{row.get('semantic_distance','?')}, disagreement={row.get('disagreement_score','?')}] "
                 "REVIEW: state the two divergent readings in plain English and which "
                 "implementations would resolve them differently.")
    return "  ".join(parts)


def _readings_comment(row: dict) -> str:
    reads = json.loads(row.get("divergent_readings") or "[]")
    loci = defaultdict(list)
    for rd in reads:
        loci[(rd["kind"], rd["locus"])].append((rd["parser"], rd["resolution"]))
    lines = ["# --- parser evidence (side by side) ---"]
    for (kind, locus), rs in loci.items():
        if len({res for _, res in rs}) > 1:
            lines.append(f"#   {kind} @ {locus}")
            for p, res in rs:
                lines.append(f"#       {p:11} {res}")
    return "\n".join(lines)


_TEMPLATE = '''# AVK scaffold -- generated from {source}. Fill the TODO sections; the [case]
# block is pre-filled, but VERIFY it. The differential test itself is yours to design.
{evidence}

[case]
id        = {id}
title     = {title}
spec      = [{spec}]
ambiguity = {ambiguity}
# cwe        = "CWE-???"          # TODO: classify (e.g. CWE-1284 improper validation of specified quantity)
# obligation = "receiver"         # TODO: receiver | sender

# [build]                          # TODO: how to construct the divergent input
# builder = "..."
# params  = {{ }}

# [deliver]                        # TODO: how to route it to the implementations
# requires = "..."

# [observe]                        # TODO: what to compare across implementations

# [expect]                         # TODO: the conformant vs divergent outcomes
'''


def scaffold_row(row: dict, project: str, source: str) -> tuple[str, str]:
    """Return (filename, toml_text) for one oracle row."""
    section = row.get("section", "?")
    anchor = row.get("anchor", "")
    title = row.get("section_title", "")
    slug = _slug(row.get("text", ""))
    case_id = f"{project}/{section}-{slug}"
    fname = f"{project}_{section.replace('.', '_')}_{slug}.toml"
    spec_entry = _tstr(f"{anchor} {title}".strip())
    text = _TEMPLATE.format(
        source=source,
        evidence=_readings_comment(row),
        id=_tstr(case_id),
        title=_tstr(row.get("text", "")),
        spec=spec_entry,
        ambiguity=_tstr(_describe_ambiguity(row)),
    )
    return fname, text


def scaffold(rows, project: str, out_dir: Path, source: str,
             limit: int = 50, only_nocuous: bool = True) -> dict:
    """Write case scaffolds for the top oracle rows. rows must be oracle-scored,
    already ranked (as written by output.write)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    picked = [r for r in rows if r.get("disagreement_score", "") != ""]
    if only_nocuous:
        picked = [r for r in picked if r.get("verdict") == "nocuous"]
    picked = picked[:limit]
    seen_names: set[str] = set()
    for r in picked:
        fname, text = scaffold_row(r, project, source)
        while fname in seen_names:                        # avoid collisions on same section+slug
            fname = fname.replace(".toml", "_.toml")
        seen_names.add(fname)
        (out_dir / fname).write_text(text)
    return {"n": len(picked), "dir": out_dir}
