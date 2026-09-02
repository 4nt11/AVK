# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 3a -- the four independent parsers, normalized to comparable decisions.

Each adapter parses ONE sentence and returns a `Decisions` object holding:
  * pp    : PP-attachment decisions  -> {prep (text@char) : head (text@char)}
  * coord : coordination scope        -> {coordinator (text@char) : {conjunct heads}}

Dependency parsers (spaCy-trf, Stanza-dep) read these straight off the parse.
Constituency parsers (benepar, Stanza-con) get them via head-percolation over the
bracketing. Everything is keyed by CHARACTER OFFSET so the four tokenizations stay
comparable in disagree.py -- that cross-formalism comparison is the whole point.
"""
from __future__ import annotations
import gc
import warnings
from dataclasses import dataclass, field
from functools import lru_cache

warnings.filterwarnings("ignore")

PARSERS = ["spacy-trf", "stanza-dep", "benepar", "stanza-con"]


@dataclass
class Dep:
    text: str
    start: int          # char offset -- the cross-parser key

    def key(self):
        return (self.text.lower(), self.start)


@dataclass
class Decisions:
    parser: str
    pp: dict = field(default_factory=dict)       # prep_start -> {"prep":Dep,"head":Dep}
    coord: dict = field(default_factory=dict)     # coord_start -> {"cc":Dep,"conj":[Dep,...]}


# ---------------------------------------------------------------------------
# model singletons (all on GPU)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _spacy_trf():
    import spacy
    try:
        spacy.require_gpu()
    except Exception:
        pass
    return spacy.load("en_core_web_trf")


@lru_cache(maxsize=1)
def _benepar():
    import spacy, benepar  # noqa
    nlp = spacy.load("en_core_web_sm", disable=["ner", "lemmatizer"])
    nlp.add_pipe("benepar", config={"model": "benepar_en3"})
    return nlp


@lru_cache(maxsize=1)
def _stanza_dep():
    import stanza
    return stanza.Pipeline("en", processors="tokenize,pos,lemma,depparse",
                           use_gpu=True, verbose=False)


@lru_cache(maxsize=1)
def _stanza_con():
    import stanza
    return stanza.Pipeline("en", processors="tokenize,pos,constituency",
                           use_gpu=True, verbose=False)


# ---------------------------------------------------------------------------
# dependency adapters
# ---------------------------------------------------------------------------
def _spacy_decisions(sent: str) -> Decisions:
    doc = _spacy_trf()(sent)
    d = Decisions("spacy-trf")
    for t in doc:
        if t.dep_ == "prep":                       # PP head = the token prep depends on
            d.pp[t.idx] = {"prep": Dep(t.text, t.idx), "head": Dep(t.head.text, t.head.idx)}
        if t.dep_ == "cc":                          # coordinator: head is first conjunct
            first = t.head
            conj = [first] + [c for c in doc if c.dep_ == "conj" and c.head == first]
            d.coord[t.idx] = {"cc": Dep(t.text, t.idx),
                              "conj": [Dep(c.text, c.idx) for c in conj]}
    return d


def _stanza_dep_decisions(sent: str) -> Decisions:
    s = _stanza_dep()(sent).sentences[0]
    words = s.words
    by_id = {w.id: w for w in words}
    d = Decisions("stanza-dep")
    for w in words:
        head = by_id.get(w.head)
        if w.deprel == "case" and head is not None:   # preposition -> its nominal head
            d.pp[w.start_char] = {"prep": Dep(w.text, w.start_char),
                                  "head": Dep(head.text, head.start_char)}
        if w.deprel == "cc" and head is not None:
            # UD: cc attaches to the FOLLOWING conjunct; the first conjunct is that
            # token's `conj` head (or itself if it is already the first).
            first = by_id.get(head.head) if head.deprel == "conj" else head
            if first is not None:
                conj = [first] + [c for c in words if c.deprel == "conj" and c.head == first.id]
                d.coord[w.start_char] = {"cc": Dep(w.text, w.start_char),
                                         "conj": [Dep(c.text, c.start_char) for c in conj]}
    return d


# ---------------------------------------------------------------------------
# constituency adapters (shared head-percolation)
# ---------------------------------------------------------------------------
class _Node:
    __slots__ = ("label", "children", "leaf_idx", "word")

    def __init__(self, label, children=None, leaf_idx=None, word=None):
        self.label, self.children, self.leaf_idx, self.word = label, children, leaf_idx, word

    def is_leaf(self):
        return self.word is not None


def _from_nltk(tree, counter):
    from nltk import Tree
    if not isinstance(tree, Tree):                 # a bare string leaf
        i = counter[0]; counter[0] += 1
        return _Node("", None, i, str(tree))
    kids = [_from_nltk(c, counter) for c in tree]
    # a preterminal (POS -> single word leaf): collapse tag onto the leaf
    if len(kids) == 1 and kids[0].is_leaf():
        kids[0].label = tree.label()
        return kids[0]
    return _Node(tree.label(), kids)


def _head_child(node: _Node, exclude=None):
    kids = [c for c in node.children if c is not exclude]
    if not kids:
        return None
    lbl = node.label
    def first(*prefixes):
        for c in kids:
            if c.label.startswith(prefixes):
                return c
        return None
    if lbl.startswith("NP") or lbl.startswith("NML"):
        for c in reversed(kids):                    # rightmost nominal head
            if c.label.startswith(("NN", "NP", "NML", "PRP", "CD", "JJ")):
                return c
        return kids[-1]
    if lbl.startswith("VP"):
        return first("VB", "VP", "MD", "AUX") or kids[0]
    if lbl.startswith("PP"):
        return first("NP", "PP", "S", "NML") or kids[-1]
    if lbl in ("S", "SBAR", "SINV", "SQ", "ROOT", "TOP", "FRAG"):
        return first("VP") or first("S") or first("NP") or kids[-1]
    if lbl.startswith("ADJP") or lbl.startswith("ADVP"):
        return first("JJ", "RB", "VBN", "VBG") or kids[-1]
    return kids[-1]


def _head_leaf(node: _Node, exclude=None):
    """Descend head children to a lexical leaf; return that _Node (leaf)."""
    cur = node
    guard = 0
    while cur is not None and not cur.is_leaf() and guard < 60:
        cur = _head_child(cur, exclude if guard == 0 else None)
        guard += 1
    return cur if (cur is not None and cur.is_leaf()) else None


def _leaves(node, out):
    if node.is_leaf():
        out.append(node)
    else:
        for c in node.children:
            _leaves(c, out)


def _walk(node, parent, fn):
    fn(node, parent)
    if node.children:
        for c in node.children:
            _walk(c, node, fn)


def _constituency_decisions(parser_name, root: _Node, offsets: list[int], texts: list[str]):
    """offsets/texts are per-leaf, index-aligned to root's leaves (parser tokens)."""
    d = Decisions(parser_name)

    def off(n):  # leaf _Node -> char offset & text from the parser's own tokens
        i = n.leaf_idx
        return (texts[i] if i < len(texts) else n.word or ""), (offsets[i] if i < len(offsets) else -1)

    def visit(node, parent):
        if node.is_leaf() or parent is None:
            return
        # PP-attachment: PP node attaches to head of its parent (excluding this PP)
        if node.label.startswith("PP"):
            leaves = []; _leaves(node, leaves)
            if leaves:
                prep_leaf = min(leaves, key=lambda n: n.leaf_idx)   # leftmost = the preposition
                head_leaf = _head_leaf(parent, exclude=node)
                if head_leaf is not None and head_leaf is not prep_leaf:
                    pt, ps = off(prep_leaf); ht, hs = off(head_leaf)
                    d.pp[ps] = {"prep": Dep(pt, ps), "head": Dep(ht, hs)}
        # coordination: a node with a CC child -> conjuncts are its phrasal siblings
        cc = [c for c in node.children if c.label == "CC" or
              (c.is_leaf() and c.word and c.word.lower() in ("and", "or"))]
        if cc:
            cc_leaf = cc[0] if cc[0].is_leaf() else _head_leaf(cc[0])
            conj_nodes = [c for c in node.children
                          if c is not cc[0] and c.label not in (",", ":", "CC", ".")]
            conj_leaves = [_head_leaf(c) for c in conj_nodes]
            conj_leaves = [c for c in conj_leaves if c is not None]
            if cc_leaf is not None and len(conj_leaves) >= 2:
                ct, cs = off(cc_leaf)
                d.coord[cs] = {"cc": Dep(ct, cs),
                               "conj": [Dep(*off(cl)) for cl in conj_leaves]}
    _walk(root, None, visit)
    return d


def _benepar_decisions(sent: str) -> Decisions:
    from nltk import Tree
    doc = _benepar()(sent)
    span = list(doc.sents)[0]
    root = _from_nltk(Tree.fromstring(span._.parse_string), [0])
    toks = [span[i] for i in range(len(span))]
    offsets = [t.idx for t in toks]
    texts = [t.text for t in toks]
    return _constituency_decisions("benepar", root, offsets, texts)


def _stanza_con_decisions(sent: str) -> Decisions:
    from nltk import Tree
    s = _stanza_con()(sent).sentences[0]
    root = _from_nltk(Tree.fromstring(str(s.constituency)), [0])
    offsets = [w.start_char for w in s.words]
    texts = [w.text for w in s.words]
    return _constituency_decisions("stanza-con", root, offsets, texts)


_ADAPTERS = {
    "spacy-trf": _spacy_decisions,
    "stanza-dep": _stanza_dep_decisions,
    "benepar": _benepar_decisions,
    "stanza-con": _stanza_con_decisions,
}


def parse_all(sent: str) -> dict[str, Decisions]:
    """Run all four parsers on one sentence. A parser that errors is skipped
    (recorded as absent) rather than sinking the whole sentence."""
    out = {}
    for name, fn in _ADAPTERS.items():
        try:
            out[name] = fn(sent)
        except Exception as e:  # noqa
            out[name] = Decisions(name)
            out[name].error = repr(e)  # type: ignore
    return out


# ---------------------------------------------------------------------------
# low-memory (parser-major) pass -- one model resident at a time
# ---------------------------------------------------------------------------
# The four models are lru_cache singletons; by default all four stay co-resident
# for a whole run (peak RAM/VRAM = their SUM). parse_all_sequential trades that for
# a single-model footprint by loading one parser, sweeping every sentence, then
# evicting it before the next -- for machines that OOM loading all four at once.
_LOADERS = {
    "spacy-trf": _spacy_trf,
    "stanza-dep": _stanza_dep,
    "benepar": _benepar,
    "stanza-con": _stanza_con,
}


def _free_gpu() -> None:
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa -- torch absent / CPU-only: nothing to hand back
        pass


def _unload(name: str) -> None:
    """Drop a parser's cached model and hand its memory back to the OS/GPU."""
    loader = _LOADERS.get(name)
    if loader is not None:
        loader.cache_clear()
    gc.collect()
    _free_gpu()


def parse_all_sequential(sentences, progress=None) -> list[dict]:
    """Parser-MAJOR sweep: load ONE model, parse every sentence, unload it, next.

    Same total parse work as [parse_all(s) for s in sentences] and an identical
    result shape (one {parser: Decisions} dict per sentence, index-aligned to
    `sentences`) -- but peak memory holds a single parser plus the small Decisions
    buffer, not all four models at once. `progress`, if given, is called as
    progress(iterable, desc) -> iterable to wrap each parser's sweep (e.g. tqdm).

    Batching (feeding many sentences per model call) is a separate, orthogonal
    speedup that slots into this per-parser sweep later; kept out here on purpose.
    """
    out: list[dict] = [dict() for _ in sentences]
    for name, fn in _ADAPTERS.items():
        seq = progress(sentences, name) if progress is not None else sentences
        for i, sent in enumerate(seq):
            try:
                out[i][name] = fn(sent)
            except Exception as e:  # noqa -- one parser erroring != sink the sentence
                d = Decisions(name)
                d.error = repr(e)  # type: ignore
                out[i][name] = d
        _unload(name)              # free this model before loading the next
    return out
