# SPDX-License-Identifier: GPL-3.0-or-later
"""CLI orchestrator (project-driven).

  python -m avk ingest    --project dcmk|internoop|x509|ooxml
  python -m avk triage    --project internoop [--limit N] [--sample K]
  python -m avk oracle    --project internoop [--top-n 200]
  python -m avk scaffold  --project ooxml [--limit N] [--all-verdicts]
"""
from __future__ import annotations
import argparse

from . import config, triage, output
from .model import load_units
from .projects import get_project, list_projects


def _jsonl(proj):
    return config.DATA_DIR / f"{proj.out_stem}.jsonl"


def cmd_ingest(args):
    proj = get_project(args.project)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = _jsonl(proj)
    n = 0
    with out.open("w", encoding="utf-8") as fh:
        for unit in proj.adapter.ingest():
            fh.write(unit.to_json() + "\n"); n += 1
    print(f"[{proj.name}] {n} sentence units -> {out}")


def cmd_triage(args):
    proj = get_project(args.project)
    units = list(load_units(_jsonl(proj)))
    if args.limit:
        units = units[: args.limit]
    scored = list(triage.score_units(units))
    scored.sort(key=lambda us: us[1].score, reverse=True)
    rows = output.build_rows(scored, matcher=proj.matcher)
    out = output.write(rows, config.DATA_DIR / f"triage_{proj.out_stem}")
    print(f"[{proj.name}] scored {len(scored)} -> {out['csv']}  ({out['n_overlap']} overlap)")
    if args.sample:
        _print_sample(scored[: args.sample])


def cmd_oracle(args):
    from . import disagree
    proj = get_project(args.project)
    units = list(load_units(_jsonl(proj)))
    scored = {u.uid: r for u, r in triage.score_units(units)}
    top = sorted(units, key=lambda u: scored[u.uid].score, reverse=True)[: args.top_n]
    if proj.spec_lexicon:                         # point the 'spec' backend at this spec's lexicon
        config.SPEC_LEXICON_PATH = proj.spec_lexicon
    orc = disagree.ParserDisagreementOracle(lexicons=proj.oracle_lexicons)
    results = {u.uid: orc.score(u) for u in _progress(top)}
    rows = output.build_rows([(u, scored[u.uid]) for u in units],
                             oracle_results=results, matcher=proj.matcher)
    out = output.write(rows, config.DATA_DIR / f"oracle_{proj.out_stem}")
    print(f"[{proj.name}] multi-parsed {len(top)} (lexicons: "
          f"{'+'.join(proj.oracle_lexicons)}) -> {out['csv']}")


def cmd_scaffold(args):
    import csv
    from . import scaffold
    proj = get_project(args.project)
    src = config.DATA_DIR / f"oracle_{proj.out_stem}.csv"
    if not src.exists():
        raise SystemExit(f"no oracle output at {src} -- run `oracle --project {args.project}` first")
    rows = list(csv.DictReader(src.open()))
    out = scaffold.scaffold(rows, proj.name, config.DATA_DIR / f"scaffold_{proj.out_stem}",
                            source=src.name, limit=args.limit, only_nocuous=not args.all_verdicts)
    print(f"[{proj.name}] wrote {out['n']} case scaffolds -> {out['dir']}")


def _progress(seq):
    try:
        from tqdm import tqdm
        return tqdm(seq)
    except Exception:
        return seq


def _print_sample(sample):
    print("\n=== TOP FLAGGED (triage sanity-check) ===")
    for unit, res in sample:
        print(f"\n[{res.score:.1f}] {unit.anchor}  ({unit.uid})")
        print(f"  {unit.text}")
        for name, d in res.signals.items():
            print(f"    - {name} (+{d['points']}): {d['reasons'][0]}")


def main():
    ap = argparse.ArgumentParser(prog="avk")
    sub = ap.add_subparsers(required=True)
    for cmd, fn in [("ingest", cmd_ingest), ("triage", cmd_triage),
                    ("oracle", cmd_oracle), ("scaffold", cmd_scaffold)]:
        p = sub.add_parser(cmd)
        p.add_argument("--project", required=True, choices=list_projects())
        if cmd == "triage":
            p.add_argument("--limit", type=int, default=0)
            p.add_argument("--sample", type=int, default=0)
        if cmd == "oracle":
            p.add_argument("--top-n", type=int, default=config.TOP_N_FOR_ORACLE)
        if cmd == "scaffold":
            p.add_argument("--limit", type=int, default=50)
            p.add_argument("--all-verdicts", action="store_true",
                           help="scaffold all verdicts, not just nocuous")
        p.set_defaults(func=fn)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
