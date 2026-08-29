# SPDX-License-Identifier: GPL-3.0-or-later
"""Adapter traceability + matcher + triage checks.

Run: PYTHONPATH=. .venv/bin/python tests/test_ingest.py
"""
from pathlib import Path
from avk import triage
from avk.adapters.dicom import DicomDocBookAdapter, DicomFindingsMatcher
from avk.adapters.fhir import FhirHtmlAdapter, FhirFindingsMatcher
from avk.adapters.epub import EpubClauseAdapter

HOME = Path.home()


def test_dicom_adapter_traceability_and_dedup():
    src = HOME / "Documents/Research/medvulns/research/dicom-standard/part05.html"
    units = list(DicomDocBookAdapter({str(src): "PS3.5"}).ingest())
    assert units
    assert all(u.anchor.startswith("PS3.5") and u.section for u in units)
    assert len({(u.section, u.text) for u in units}) == len(units), "dedup failed"


def test_fhir_adapter_traceability():
    site = HOME / "Documents/Research/interNOOP/research/hl7-standard/spec-R5/site"
    units = list(FhirHtmlAdapter(str(site), "FHIR R5", pages=["datatypes.html"]).ingest())
    assert units
    u = units[0]
    assert u.spec == "FHIR R5" and u.subref == "datatypes.html"
    assert u.anchor.startswith("FHIR R5 datatypes.html#")


def test_epub_covers_prose_annexes():
    # Regression: annex titled with <p class="tit2a"> (no sec_/hN) must NOT be
    # silently dropped -- Annex K carries a real X.509 keyUsage ambiguity.
    epub = HOME / "Documents/Research/standards/T-REC-X.509-201910-I!!EPB-E.epub"
    if not epub.exists():
        return
    units = list(EpubClauseAdapter(str(epub), "X.509").ingest())
    subrefs = {u.subref for u in units}
    assert "17_AnnexK.xhtml" in subrefs, "prose annex silently dropped again"
    assert all(u.section for u in units), "unit with no clause reference"


def test_matchers_precise_vs_broad():
    dm = DicomFindingsMatcher(["PS3.5 8"], [], [])
    class U:  # noqa
        anchor, section, subref, section_title, text = "PS3.5 8.3.2", "8.3.2", None, "", "x"
    tag, precise = dm.match(U())
    assert tag and precise is False, (tag, precise)   # broad-section subtree -> not precise

    fm = FhirFindingsMatcher(["3.2.1.5.6"], ["Prefixes"], ["ref-1"])
    class F:  # noqa
        section, section_title, text = "3.2.1.5.6", "", "x"
    assert fm.match(F()) == ("sect:3.2.1.5.6", True)


def test_triage_signals_fire():
    class U:  # noqa
        uid, text = "t", ("The Value shall be encoded and may be padded or truncated, and "
                          "some implementations process it while others do not.")
    r = triage.score_unit(U())
    assert "modal_inconsistency" in r.signals and "coordination" in r.signals


if __name__ == "__main__":
    test_dicom_adapter_traceability_and_dedup()
    test_fhir_adapter_traceability()
    test_epub_covers_prose_annexes()
    test_matchers_precise_vs_broad()
    test_triage_signals_fire()
    print("ok")
