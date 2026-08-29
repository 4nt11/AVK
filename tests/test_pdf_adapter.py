# SPDX-License-Identifier: GPL-3.0-or-later
"""Smoke test for the Docling PDF adapter on an ECMA-376 content slice.

Heavy (loads Docling models) and depends on the local PDF -> skips cleanly if absent.
Run: PYTHONPATH=. .venv/bin/python tests/test_pdf_adapter.py
"""
from pathlib import Path
from avk.adapters.pdf import PdfDoclingAdapter

PDF = (Path.home() / "Documents/Research/standards/ooxml/"
       "Ecma Office Open XML Part 1 - Fundamentals And Markup Language Reference.pdf")


def test_pdf_slice_prose_only_with_clause_traceability():
    if not PDF.exists():
        print("skip: PDF not present"); return
    units = list(PdfDoclingAdapter(str(PDF), "ECMA-376-1",
                                   first_page=120, last_page=125).ingest())
    assert units, "no units from content slice"
    assert all(u.section and u.anchor.startswith("ECMA-376-1") for u in units)
    # Docling labels XML examples as `code`; none must leak into prose units
    assert not [u for u in units if u.text.lstrip().startswith("<") or "xmlns" in u.text]


def test_pdf_rejects_toc_dot_leaders():
    # Regression: TOC entries ("22.9 Shared Simple Types .......") must NOT be treated
    # as clause headings, and Fundamentals clauses must be captured from the front.
    if not PDF.exists():
        print("skip: PDF not present"); return
    units = list(PdfDoclingAdapter(str(PDF), "ECMA-376-1",
                                   first_page=1, last_page=14).ingest())
    assert units, "front pages yielded nothing"
    assert not [u for u in units if "....." in u.text], "TOC dot-leader leaked as prose"
    # no absurd clause on page-5 TOC (e.g. 22.x) -- means a TOC header set the section
    assert not [u for u in units if u.section.split(".")[0].isdigit()
                and int(u.section.split(".")[0]) > 12], "TOC clause number polluted tracking"


if __name__ == "__main__":
    test_pdf_slice_prose_only_with_clause_traceability()
    test_pdf_rejects_toc_dot_leaders()
    print("ok")
