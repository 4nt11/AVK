# SPDX-License-Identifier: GPL-3.0-or-later
"""PDF adapter -- Docling structure-aware extraction (ECMA/ISO/IEEE/ITU PDFs).

Docling's ML layout model recovers heading hierarchy, reading order, and -- crucially
for spec PDFs -- labels XML/code examples as `code` and tables as `table`, so prose
(`text`/`list_item`) separates cleanly from the reference material we discard. This
is publisher-agnostic (no font heuristics), so once this works on the OOXML beast,
other PDF standards are a page-range away.

Optimizations for THIS use case: table-structure recognition and OCR are disabled
(we drop tables; PDFs have a text layer). GPU. Two throughput levers:
  * page_batch_size -- more pages per layout batch (bigger GPU bursts)
  * workers>1       -- N processes on disjoint page ranges, model copies sharing the
                       GPU, so one process's GPU burst fills another's CPU-prep valley
                       (single-process Docling pulses because inference and page-render
                       are serial). Workers OVERLAP-stitch: each reads a few pages
                       before its range to pick up the in-force clause header, but only
                       EMITS its own pages -- no seam drops, no duplicates.
"""
from __future__ import annotations
import re
import warnings
from typing import Iterator

from ..model import Unit, SpecIngestAdapter
from ..segment import split_sentences

warnings.filterwarnings("ignore")

_CLAUSE = re.compile(r"^([A-Z]?\d+(?:\.\d+)*)\s+(.*)$")   # "13.3.4 Notes Master Part"
_TOC = re.compile(r"(\.\s*){4,}")     # dot leader "......" / ". . . ." -> a TOC entry, not a heading
_PROSE_LABELS = {"text", "list_item"}
_OVERLAP = 12          # pages a worker reads before its range to establish clause context


def _label(it) -> str:
    lab = getattr(it, "label", None)
    return str(getattr(lab, "value", lab))


def _page_of(it):
    prov = getattr(it, "prov", None) or []
    return prov[0].page_no if prov else None


def _make_converter(page_batch_size: int, num_threads: int):
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.settings import settings
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions, AcceleratorOptions, AcceleratorDevice)
    settings.perf.page_batch_size = page_batch_size
    opts = PdfPipelineOptions()
    opts.do_ocr = False
    opts.do_table_structure = False
    try:
        opts.accelerator_options = AcceleratorOptions(
            device=AcceleratorDevice.CUDA, num_threads=num_threads)
    except Exception:
        pass
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})


def _extract_range(pdf, spec, nom_start, end, chunk, page_batch_size, min_chars, num_threads):
    """Convert [nom_start-overlap, end] but emit only raw units on pages >= nom_start.
    Returns list of tuples (page, section, title, subref, anchor, text, cs, ce).
    Module-level so it is picklable for ProcessPoolExecutor (spawn)."""
    conv = _make_converter(page_batch_size, num_threads)
    section, title = "", ""
    start = max(1, nom_start - _OVERLAP)
    out = []
    for cs in range(start, end + 1, chunk):
        ce = min(cs + chunk - 1, end)
        doc = conv.convert(pdf, page_range=(cs, ce)).document
        for it, _lvl in doc.iterate_items():
            lab = _label(it)
            txt = (getattr(it, "text", "") or "").strip()
            if lab == "section_header":
                if _TOC.search(txt):
                    continue                      # TOC entry ("22.9 Shared ... 5"), not a real heading
                m = _CLAUSE.match(txt)
                if m:
                    section, title = m.group(1), m.group(2)
                elif txt:
                    title = txt
                continue
            if lab not in _PROSE_LABELS or not section or len(txt) < min_chars:
                continue
            if _TOC.search(txt):                  # dot-leader TOC/index entry mislabeled as text
                continue
            page = _page_of(it)
            if page is None or page < nom_start:      # overlap pages: context only
                continue
            anchor = f"{spec} {section}"
            for sent, a, b in split_sentences(txt):
                if len(sent) >= min_chars:
                    out.append((page, section, title, f"p{page}", anchor, sent, a, b))
    return out


class PdfDoclingAdapter(SpecIngestAdapter):
    name = "pdf"

    def __init__(self, pdf_path: str, spec_label: str, first_page: int = 1,
                 last_page: int | None = None, chunk: int = 250, min_chars: int = 25,
                 page_batch_size: int = 16, workers: int = 1):
        self.path = pdf_path
        self.spec = spec_label
        self.first_page = first_page
        self.last_page = last_page
        self.chunk = chunk
        self.min_chars = min_chars
        self.page_batch_size = page_batch_size
        self.workers = workers

    def _page_count(self) -> int:
        from pypdf import PdfReader
        return len(PdfReader(self.path).pages)

    def _finalize(self, raws) -> Iterator[Unit]:
        """Global page-order sort + dedup + uid assignment over raw tuples."""
        raws.sort(key=lambda t: (t[0], t[1]))          # (page, section)
        seen: set[tuple[str, str]] = set()
        counters: dict[str, int] = {}
        for page, section, title, subref, anchor, text, cs, ce in raws:
            if (section, text) in seen:
                continue
            seen.add((section, text))
            counters[section] = counters.get(section, 0) + 1
            uid = f"{self.spec}:{section}:{counters[section]}"
            yield Unit(uid, self.spec, section, title, subref, anchor, text, cs, ce)

    def ingest(self) -> Iterator[Unit]:
        import os
        last = self.last_page or self._page_count()
        cpu = os.cpu_count() or 8
        if self.workers <= 1:
            raws = _extract_range(self.path, self.spec, self.first_page, last,
                                  self.chunk, self.page_batch_size, self.min_chars, cpu)
            yield from self._finalize(raws)
            return
        # split [first_page, last] into `workers` contiguous ranges
        n = self.workers
        span = last - self.first_page + 1
        step = (span + n - 1) // n
        ranges = [(self.first_page + i * step, min(self.first_page + (i + 1) * step - 1, last))
                  for i in range(n) if self.first_page + i * step <= last]
        threads_per = max(1, cpu // len(ranges))
        payloads = [(self.path, self.spec, s, e, self.chunk, self.page_batch_size,
                     self.min_chars, threads_per) for s, e in ranges]
        import concurrent.futures as cf
        import multiprocessing as mp
        ctx = mp.get_context("spawn")               # CUDA cannot be forked
        raws = []
        with cf.ProcessPoolExecutor(max_workers=len(ranges), mp_context=ctx) as ex:
            for chunk_res in ex.map(_extract_range_star, payloads):
                raws.extend(chunk_res)
        yield from self._finalize(raws)


def _extract_range_star(payload):
    return _extract_range(*payload)
