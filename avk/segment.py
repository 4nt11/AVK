# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared sentence segmentation (spaCy sm parser -> statistical boundaries).

More robust than punctuation rules on standards prose (version tokens, "e.g.",
tag/section notation like 7.1.1 or 2.1.28.0.1).
"""
from __future__ import annotations
from functools import lru_cache


@lru_cache(maxsize=1)
def _segmenter():
    import spacy
    return spacy.load("en_core_web_sm", disable=["ner", "lemmatizer"])


def split_sentences(text: str):
    doc = _segmenter()(text)
    for s in doc.sents:
        yield s.text.strip(), s.start_char, s.start_char + len(s.text)
