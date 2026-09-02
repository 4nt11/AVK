# SPDX-License-Identifier: GPL-3.0-or-later
"""Markdown adapter -- plain-text specs / design docs (README, EARS requirement
docs, threat models, ADRs, ...) as one or more .md files -> Units.

Markdown carries its own structure in plain syntax (no DOM to walk), so this
adapter is a small line-based state machine rather than a real parser:

  * ATX headings ("#".."######") build a section path, e.g. "3/3.2" or the
    slugged heading chain when headings aren't numbered.
  * Fenced code blocks (``` or ~~~) and table rows ("|...") are reference
    material, not prose -- dropped, same call the PDF/Docling adapter makes
    for tables (see README).
  * List items (EARS-style "- WHEN ... THEN ... SHALL ..." requirements are
    almost always one bullet each) are flushed as their own paragraph so a
    multi-requirement list doesn't get merged into one giant unit.
  * Inline markup (**bold**, `code`, [text](url), ![alt](url)) is stripped
    to plain text before sentence segmentation so it doesn't confuse the
    grammar parsers downstream.

A single file or a directory (walked recursively for *.md) both work.
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Iterator

from ..model import Unit, SpecIngestAdapter
from ..segment import split_sentences

_WS = re.compile(r"\s+")
_ATX = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
_FENCE = re.compile(r"^(```|~~~)")
_TABLE_ROW = re.compile(r"^\s*\|")
_HR = re.compile(r"^\s*([-*_])\1{2,}\s*$")
_LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_BLOCKQUOTE = re.compile(r"^\s*>\s?(.*)$")

_INLINE_CODE = re.compile(r"`([^`]*)`")
_BOLD_ITALIC = re.compile(r"(\*\*\*|___)(.+?)\1")
_BOLD = re.compile(r"(\*\*|__)(.+?)\1")
_ITALIC = re.compile(r"(\*|_)(.+?)\1")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_FOOTNOTE = re.compile(r"\[\^[^\]]*\]")
_SLUG_STRIP = re.compile(r"[^\w\- ]")


def _slug(text: str) -> str:
    s = _SLUG_STRIP.sub("", text.lower()).strip().replace(" ", "-")
    return re.sub(r"-{2,}", "-", s) or "section"


def _clean_inline(t: str) -> str:
    t = _IMAGE.sub("", t)
    t = _FOOTNOTE.sub("", t)
    t = _LINK.sub(r"\1", t)
    t = _INLINE_CODE.sub(r"\1", t)
    t = _BOLD_ITALIC.sub(r"\2", t)
    t = _BOLD.sub(r"\2", t)
    t = _ITALIC.sub(r"\2", t)
    return _WS.sub(" ", t).strip()


class MarkdownAdapter(SpecIngestAdapter):
    name = "markdown"

    def __init__(self, source: str, spec_label: str = "spec", min_chars: int = 25,
                 glob: str = "**/*.md"):
        self.source = Path(source)
        self.spec = spec_label
        self.min_chars = min_chars
        self.glob = glob

    def ingest(self) -> Iterator[Unit]:
        if self.source.is_dir():
            paths = sorted(self.source.glob(self.glob))
        else:
            paths = [self.source]
        for p in paths:
            yield from self._ingest_file(p)

    def _ingest_file(self, path: Path) -> Iterator[Unit]:
        stem = path.stem
        try:
            relname = str(path.relative_to(self.source))
        except ValueError:
            relname = path.name
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

        section, title = "0", stem            # file-level fallback before any heading
        heading_stack: list[str] = []          # slugs, one per heading depth seen so far
        counters: dict[str, int] = {}
        seen: set[tuple[str, str]] = set()
        in_code = False
        buf: list[str] = []

        def flush() -> Iterator[Unit]:
            nonlocal buf
            if not buf:
                return
            txt = _clean_inline(" ".join(buf))
            buf = []
            if len(txt) < self.min_chars:
                return
            anchor = f"{self.spec} {relname}#{section}"
            for sent, cs, ce in split_sentences(txt):
                if len(sent) < self.min_chars or (section, sent) in seen:
                    continue
                seen.add((section, sent))
                counters[section] = counters.get(section, 0) + 1
                slug = self.spec.replace(" ", "-")
                uid = f"{slug}:{stem}:{section}:{counters[section]}"
                yield Unit(uid, self.spec, section, title, relname, anchor, sent, cs, ce)

        for line in lines:
            if _FENCE.match(line):
                in_code = not in_code
                yield from flush()
                continue
            if in_code:
                continue
            if _TABLE_ROW.match(line) or _HR.match(line):
                yield from flush()
                continue

            m = _ATX.match(line)
            if m:
                yield from flush()
                depth = len(m.group(1))
                htext = _clean_inline(m.group(2))
                heading_stack = heading_stack[:depth - 1] + [_slug(htext)]
                section = "/".join(heading_stack)
                title = htext
                continue

            if not line.strip():
                yield from flush()
                continue

            li = _LIST_ITEM.match(line)
            bq = _BLOCKQUOTE.match(line)
            if li:
                yield from flush()               # each list item is its own unit
                buf.append(li.group(3))
                continue
            if bq:
                buf.append(bq.group(1))
                continue
            buf.append(line.strip())

        yield from flush()
