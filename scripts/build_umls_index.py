# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the full-UMLS SQLite index for the 'umls' ambiguity-oracle backend.

QuickUMLS won't build (its leveldb dep is dead against modern toolchains) and we don't
need its fuzzy simstring matching -- the oracle only asks "do these two head words map
to the same UMLS concept?". That's a string->CUI + CUI->TUI lookup, i.e. two RRF files
poured into SQLite (stdlib, no deps). English atoms only, suppressed rows dropped.

  .venv/bin/python scripts/build_umls_index.py <.../2026AA/META> <out.sqlite>
"""
import sqlite3
import sys
import time
from pathlib import Path

META = Path(sys.argv[1])
OUT = Path(sys.argv[2])


def rows(fp):
    with open(fp, encoding="utf-8") as fh:
        for line in fh:
            yield line.rstrip("\n").split("|")


def chunked(con, sql, it, n=100_000):
    buf, total = [], 0
    for rec in it:
        buf.append(rec)
        if len(buf) >= n:
            con.executemany(sql, buf); total += len(buf); buf = []
    if buf:
        con.executemany(sql, buf); total += len(buf)
    return total


t0 = time.time()
OUT.unlink(missing_ok=True)
con = sqlite3.connect(OUT)
con.execute("PRAGMA journal_mode=OFF")
con.execute("PRAGMA synchronous=OFF")
con.execute("CREATE TABLE str2cui(norm TEXT, cui TEXT)")
con.execute("CREATE TABLE cui2sty(cui TEXT, tui TEXT)")

# MRSTY: CUI|TUI|...
n_sty = chunked(con, "INSERT INTO cui2sty VALUES(?,?)",
                ((f[0], f[1]) for f in rows(META / "MRSTY.RRF")))

# MRCONSO: CUI|LAT|...|STR(14)|...|SUPPRESS(16)|... -- English, non-suppressed atoms
def conso():
    for f in rows(META / "MRCONSO.RRF"):
        if len(f) < 17 or f[1] != "ENG" or f[16] == "O":
            continue
        norm = f[14].strip().lower()
        if norm:
            yield (norm, f[0])

n_str = chunked(con, "INSERT INTO str2cui VALUES(?,?)", conso())
con.commit()

con.execute("CREATE INDEX ix_norm ON str2cui(norm)")
con.execute("CREATE INDEX ix_cui ON cui2sty(cui)")
con.commit()
con.close()
print(f"built {OUT}  ({n_str:,} ENG atoms, {n_sty:,} semantic-type rows) "
      f"in {time.time()-t0:.0f}s, {OUT.stat().st_size/1e9:.2f} GB")
