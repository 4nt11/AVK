# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 2 -- CHEAP LEXICAL/SYNTACTIC TRIAGE (QuARS/SREE-style).

Five ambiguity signals scored per sentence with spaCy POS + dependency parse:
  1. RFC-2119 modal inconsistency  (mixing obligation/recommendation/permission)
  2. vague quantifiers / weasel terms
  3. coordination-scope ambiguity   (mixed and/or, shared modifiers, long lists)
  4. actor-hiding passive voice      (passive with no `by`-agent)
  5. ambiguous anaphora              (pronoun/demonstrative with >1 candidate antecedent)

We SCORE and RANK -- never hard-filter. Each signal returns points + reasons so
the output is auditable (false positives must be visible, not hidden).
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from functools import lru_cache

from . import config

# --- lexicons --------------------------------------------------------------
MODAL_CLASSES = {
    "OBLIGATION": {"shall", "must", "required", "requires", "mandatory"},
    "RECOMMENDATION": {"should", "recommended", "encouraged", "discouraged"},
    "PERMISSION": {"may", "optional", "can", "optionally", "permitted", "allowed"},
}
_MODAL_LOOKUP = {w: cls for cls, ws in MODAL_CLASSES.items() for w in ws}

VAGUE_TERMS = [
    "appropriate", "as appropriate", "as needed", "as necessary", "as required",
    "if applicable", "if present", "if necessary", "where appropriate",
    "some", "certain", "sufficient", "adequate", "reasonable", "suitable",
    "typically", "generally", "normally", "usually", "in general",
    "and so on", "etc", "such as", "among others", "including but not limited to",
    "may be", "might be", "could be", "as defined elsewhere", "unspecified",
]
_VAGUE_RE = re.compile(
    r"\b(" + "|".join(sorted((re.escape(t) for t in VAGUE_TERMS), key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

ANAPHORS = {"it", "its", "they", "them", "their", "these", "those", "this",
            "that", "such", "former", "latter"}
ANAPHOR_PHRASES = ["this value", "the above", "the former", "the latter",
                   "the following", "said value", "the same"]
_ANAPHOR_PHRASE_RE = re.compile(r"\b(" + "|".join(ANAPHOR_PHRASES) + r")\b", re.IGNORECASE)


@dataclass
class TriageResult:
    uid: str
    score: float
    signals: dict = field(default_factory=dict)   # signal_name -> {points, reasons}

    def add(self, name: str, points: float, reasons):
        if points:
            self.signals[name] = {"points": round(points, 3), "reasons": list(reasons)}
            self.score += points


@lru_cache(maxsize=1)
def _nlp():
    import spacy
    return spacy.load("en_core_web_sm", disable=["ner", "lemmatizer"])


# --- individual signals ----------------------------------------------------
def _modal_inconsistency(doc, w):
    found = {}
    for t in doc:
        cls = _MODAL_LOOKUP.get(t.text.lower())
        if cls:
            found.setdefault(cls, []).append(t.text.lower())
    if len(found) >= 2:
        reasons = [f"{cls}:{sorted(set(v))}" for cls, v in found.items()]
        return w.modal_inconsistency, [f"mixed requirement classes -> {'; '.join(reasons)}"]
    # lone informal "should" in an otherwise normative document is itself weak-ambiguous
    if "RECOMMENDATION" in found:
        return w.modal_inconsistency * 0.4, [f"weak/ambiguous strength: {found['RECOMMENDATION']}"]
    return 0.0, []


def _vague(doc, w):
    hits = _VAGUE_RE.findall(doc.text)
    if not hits:
        return 0.0, []
    n = min(len(hits), w.vague_cap)
    return w.vague_term * n, [f"vague terms ({len(hits)}): {sorted(set(h.lower() for h in hits))}"]


def _coordination(doc, w):
    text_l = doc.text.lower()
    has_and = bool(re.search(r"\band\b", text_l))
    has_or = bool(re.search(r"\bor\b", text_l))
    reasons = []
    pts = 0.0
    if has_and and has_or:
        pts += w.coordination
        reasons.append("mixed 'and'/'or' -> ambiguous coordination scope")
    # coordination followed by a shared prepositional/clausal modifier
    cc = [t for t in doc if t.dep_ == "cc"]
    conj = [t for t in doc if t.dep_ == "conj"]
    if conj:
        # a PP or relcl after the last conjunct may attach to one or all conjuncts
        last = max(conj, key=lambda t: t.i)
        tail = [t for t in doc if t.i > last.i and t.dep_ in ("prep", "relcl", "acl")]
        if tail:
            pts += w.coordination * 0.6
            reasons.append(
                f"coordination + trailing modifier '{tail[0].text}' -> attachment scope unclear")
    if len(conj) >= 3:
        pts += w.coordination * 0.4
        reasons.append(f"long coordination ({len(conj)+1} conjuncts)")
    return pts, reasons


def _passive_no_actor(doc, w):
    passives = [t for t in doc if t.dep_ in ("nsubjpass", "auxpass")]
    if not passives:
        return 0.0, []
    has_agent = any(t.dep_ == "agent" or (t.text.lower() == "by" and t.dep_ == "prep")
                    for t in doc)
    if has_agent:
        return 0.0, []
    verbs = sorted({t.head.text for t in passives if t.head.text.strip()})
    return w.passive_no_actor, [f"passive with no explicit actor: {verbs}"]


def _anaphora(doc, w):
    # candidate antecedents = noun-chunk heads
    chunks = list(doc.noun_chunks)
    phrase_hit = _ANAPHOR_PHRASE_RE.search(doc.text)
    reasons = []
    pts = 0.0
    for t in doc:
        if t.text.lower() in ANAPHORS and t.pos_ in ("PRON", "DET"):
            # count distinct candidate NP heads occurring before this anaphor
            cands = [c.root.text for c in chunks if c.root.i < t.i and c.root.pos_ in ("NOUN", "PROPN")]
            distinct = sorted(set(cands))
            if len(distinct) >= 2:
                pts += w.anaphora
                reasons.append(f"'{t.text}' has {len(distinct)} candidate antecedents: {distinct[:4]}")
                break
    if phrase_hit and not reasons:
        pts += w.anaphora * 0.6
        reasons.append(f"referential phrase '{phrase_hit.group(0)}' with underspecified referent")
    return pts, reasons


_SIGNALS = [
    ("modal_inconsistency", _modal_inconsistency),
    ("vague", _vague),
    ("coordination", _coordination),
    ("passive_no_actor", _passive_no_actor),
    ("anaphora", _anaphora),
]


def score_unit(unit, w=None) -> TriageResult:
    w = w or config.WEIGHTS
    doc = _nlp()(unit.text)
    res = TriageResult(uid=unit.uid, score=0.0)
    for name, fn in _SIGNALS:
        pts, reasons = fn(doc, w)
        res.add(name, pts, reasons)
    return res


def score_units(units, w=None):
    """Batched scoring (uses nlp.pipe for throughput)."""
    w = w or config.WEIGHTS
    units = list(units)
    docs = _nlp().pipe((u.text for u in units), batch_size=256)
    for unit, doc in zip(units, docs):
        res = TriageResult(uid=unit.uid, score=0.0)
        for name, fn in _SIGNALS:
            pts, reasons = fn(doc, w)
            res.add(name, pts, reasons)
        yield unit, res
