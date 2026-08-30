# SPDX-License-Identifier: GPL-3.0-or-later
"""Read an oracle/triage CSV and print the ranked findings -- anchor + FULL text,
without the JSON columns that make a raw `cat` unreadable.

  python scripts/view.py <project>            # data/oracle_<project>.csv, top 50
  python scripts/view.py <project> --triage    # data/triage_<project>.csv instead
  python scripts/view.py <project> -n 200      # more rows (0 = all)
  python scripts/view.py <project> --grep TLS  # only rows whose text matches (case-insensitive)
  python scripts/view.py <project> --spec PS3.18
  python scripts/view.py path/to/some.csv      # or point straight at a file
"""
from __future__ import annotations
import argparse, csv, re, sys, textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="project name or a .csv path")
    ap.add_argument("-n", "--limit", type=int, default=50, help="rows to show (0 = all)")
    ap.add_argument("--triage", action="store_true", help="view triage_<project>.csv")
    ap.add_argument("--grep", help="only rows whose text matches (case-insensitive)")
    ap.add_argument("--spec", help="only rows for this spec label, e.g. PS3.18")
    ap.add_argument("--width", type=int, default=100)
    a = ap.parse_args()

    if a.target.endswith(".csv"):
        path = Path(a.target)
    else:
        kind = "triage" if a.triage else "oracle"
        path = ROOT / "data" / f"{kind}_{a.target}.csv"
    if not path.exists():
        sys.exit(f"no such file: {path}")

    rows = list(csv.DictReader(path.open()))
    if a.spec:
        rows = [r for r in rows if r.get("spec") == a.spec]
    if a.grep:
        rx = re.compile(re.escape(a.grep), re.I)
        rows = [r for r in rows if rx.search(r.get("text", ""))]
    if a.limit:
        rows = rows[: a.limit]

    for i, r in enumerate(rows, 1):
        if r.get("verdict"):                    # oracle row
            head = (f"[{i:>3}] {r['anchor']}  {r['verdict']}  "
                    f"nnoc={r['n_nocuous_loci']} dis={r['disagreement_score']} tri={r['triage_score']}")
        else:                                   # triage row
            head = f"[{i:>3}] {r['anchor']}  score={r['triage_score']}"
        print("\n" + head)
        if r.get("section_title"):
            print(f"      · {r['section_title']}")
        print(textwrap.fill(r["text"], width=a.width,
                            initial_indent="      ", subsequent_indent="      "))


if __name__ == "__main__":
    main()
