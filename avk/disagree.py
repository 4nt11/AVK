# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 3b -- ParserDisagreementOracle + Chantree nocuous scoring.

Structural disagreement between the four parsers is a PROXY for prose ambiguity.
But parsers also disagree on things a human would not (cosmetic parse variants) --
that noise must be filtered, or the output drowns. Following Chantree et al., a
disagreement is *nocuous* only if the divergent readings are semantically
DISTINGUISHABLE; here that is estimated with WordNet similarity between the
competing attachment/coordination heads:

  * competing heads semantically CLOSE (sim >= threshold)  -> readings collapse -> INNOCUOUS
  * competing heads semantically FAR  (sim <  threshold)   -> genuinely different -> NOCUOUS
  * heads are domain jargon with no WordNet synset          -> cannot prove sameness ->
    kept NOCUOUS (conservative: a human should look). This is visible in the output.

Only nocuous disagreements rank high. False positives stay visible, never hidden.
"""
from __future__ import annotations
import re
from functools import lru_cache

from . import config, parsers
from .oracle import OracleResult, Reading

_KIND_W = {"pp-attach": 1.0, "coord-scope": 1.3}   # coord scope errors tend to matter more

# --- head-shape normalization ----------------------------------------------
# A parse head is only real prose ambiguity if it's a real word. Spec text is full of
# identifiers that look like disagreements but aren't: camelCase resource names
# (DiagnosticReport), versions (R4), formats, qualified paths (a.b). We tell them apart
# by ORTHOGRAPHY, not a per-spec word list -- prose is lowercase-alphabetic, identifiers
# violate that -- so this generalizes to any standard. camelCase is SPLIT to its words
# (so the lexicons can resolve "diagnostic report"); pure identifiers are DROPPED.
_ID_PUNCT = re.compile(r"[._/]")
_CAMEL = re.compile(r"[a-z][A-Z]")
_CAMEL_SPLIT = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])")


def _norm_head(text: str):
    """Raw parse-head token -> comparable prose head (lowercased), or None to drop it."""
    t = (text or "").strip()
    if not t or not any(c.isalpha() for c in t):        # bare punctuation ("-")
        return None
    if _ID_PUNCT.search(t) or any(c.isdigit() for c in t):   # a.b path, R4 version
        return None
    if _CAMEL.search(t):                                 # DiagnosticReport -> diagnostic report
        return " ".join(_CAMEL_SPLIT.findall(t)).lower()
    return t.lower()


# --- WordNet semantic similarity ------------------------------------------
@lru_cache(maxsize=1)
def _wn():
    from nltk.corpus import wordnet as wn
    try:
        wn.ensure_loaded()
    except Exception:
        pass
    return wn


@lru_cache(maxsize=8192)
def _wordnet_sim(a: str, b: str):
    """Max WordNet path similarity over synset pairs. None if either is OOV (jargon).

    path_similarity (not wu-palmer): wu-palmer's baseline is inflated -- almost any
    two nouns share a high hypernym, so it labels distinct words 'similar'. path
    similarity scores ~1.0 only for near-synonyms and collapses to <0.35 otherwise,
    which is the right shape for 'do these two readings mean the SAME thing?'.
    """
    a, b = a.lower(), b.lower()
    if a == b:
        return 1.0
    wn = _wn()
    sa, sb = wn.synsets(a), wn.synsets(b)
    if not sa or not sb:
        return None                              # domain jargon -> unknown
    best = 0.0
    for x in sa[:6]:
        for y in sb[:6]:
            s = x.path_similarity(y) or 0.0
            if s > best:
                best = s
    return best


# --- pluggable lexicon chain ----------------------------------------------
# A lexicon backend answers ONE question: sim(a, b) in [0,1], or None if it does
# not know the pair. Backends are tried in the target's declared order; the first
# that returns non-None wins. WordNet handles general English; UMLS (opt-in) only
# gets asked about the medical jargon WordNet returns None for.
def _lexicon_backends(names):
    out = []
    for n in names:
        if n == "wordnet":
            out.append(_wordnet_sim)
        elif n == "bastardized-umls":
            from .medical import umls_sim      # scispaCy subset: license-free, ~1GB, lazy import
            out.append(umls_sim)
        elif n == "umls":
            try:
                from .umls import umls_sim     # full licensed Metathesaurus via QuickUMLS
            except ImportError:
                raise SystemExit("the full 'umls' backend isn't wired yet -- use "
                                 "'bastardized-umls' (license-free scispaCy subset) for now.")
            out.append(umls_sim)
        elif n == "spec":
            from .spec_lexicon import spec_sim   # the standard's own published vocabulary
            out.append(spec_sim)
        else:
            raise SystemExit(f"unknown ambiguity-oracle lexicon '{n}' "
                             f"(wordnet|bastardized-umls|umls)")
    return out


def _compose_sim(backends):
    def sim(a, b):
        for fn in backends:
            s = fn(a, b)
            if s is not None:
                return s
        return None
    return sim


_wordnet_only = _compose_sim([_wordnet_sim])


def _classify_locus(heads: list[str], threshold: float, sim=_wordnet_only):
    """Judge one disagreement locus from its competing heads via a lexicon `sim`.

    Returns (verdict, distance):
      * "nocuous"      -- >=2 heads some lexicon KNOWS and they are far apart
                          (closest known pair sim < threshold): readings truly differ.
      * "innocuous"    -- distinct known heads that are close (some pair sim >= threshold):
                          the readings coincide -> cosmetic parser noise.
      * "undetermined" -- no pair is judgeable by any lexicon (domain jargon): cannot
                          judge, a human should look. NOT silently promoted to nocuous.
    distance = 1 - closest-judgeable-pair similarity (0.0 when undetermined).
    """
    uniq = sorted(set(h.lower() for h in heads if h))
    if len(uniq) < 2:
        return "none", 0.0
    best = None
    for i in range(len(uniq)):
        for j in range(i + 1, len(uniq)):
            s = sim(uniq[i], uniq[j])
            if s is not None and (best is None or s > best):
                best = s
    if best is None:
        return "undetermined", 0.0
    return ("innocuous" if best >= threshold else "nocuous"), (1.0 - best)


# --- the oracle ------------------------------------------------------------
class ParserDisagreementOracle:
    """Default free/local AmbiguityOracle (satisfies oracle.AmbiguityOracle)."""

    def __init__(self, sim_threshold: float | None = None, lexicons=None):
        self.threshold = sim_threshold if sim_threshold is not None else config.NOCUOUS_SIM_THRESHOLD
        self.lexicons = list(lexicons) if lexicons else ["wordnet"]
        self._sim = _compose_sim(_lexicon_backends(self.lexicons))

    def score(self, unit) -> OracleResult:
        return self.score_from_decisions(unit, parsers.parse_all(unit.text))

    def score_sequential(self, units, progress=None) -> dict:
        """Low-memory oracle pass: one parser model resident at a time
        (see parsers.parse_all_sequential). Returns {uid: OracleResult},
        identical to {u.uid: self.score(u) ...} but at single-model peak memory."""
        units = list(units)
        decs = parsers.parse_all_sequential([u.text for u in units], progress=progress)
        return {u.uid: self.score_from_decisions(u, d) for u, d in zip(units, decs)}

    def score_from_decisions(self, unit, dec) -> OracleResult:
        """Score one unit from already-computed parser Decisions (the comparison
        logic; shared by the default per-sentence path and the sequential path)."""
        res = OracleResult(uid=unit.uid)
        loci_scores = []

        # ---- PP-attachment disagreement (group competing heads by prep offset) ----
        prep_offsets = {}
        for name, d in dec.items():
            for off, v in d.pp.items():
                prep_offsets.setdefault(off, {})[name] = v
        for off, per in prep_offsets.items():
            if len(per) < 2:
                continue
            heads = {name: v["head"].text for name, v in per.items()}
            norm = {name: _norm_head(t) for name, t in heads.items()}
            distinct = sorted({v for v in norm.values() if v})
            if len(distinct) < 2:
                continue                          # parsers agree, or heads are identifiers
            prep_txt = next(iter(per.values()))["prep"].text
            verdict, dist = _classify_locus(distinct, self.threshold, self._sim)
            loci_scores.append((_KIND_W["pp-attach"] * (len(distinct) - 1), verdict, dist))
            for name, h in heads.items():
                res.readings.append(Reading(
                    parser=name, kind="pp-attach", locus=f"{prep_txt}@{off}",
                    resolution=f"'{prep_txt}' attaches to '{h}'",
                    signature=(norm[name] or h.lower())))
            res.max_semantic_distance = max(res.max_semantic_distance, dist)

        # ---- coordination-scope disagreement (group by coordinator offset) ----
        cc_offsets = {}
        for name, d in dec.items():
            for off, v in d.coord.items():
                cc_offsets.setdefault(off, {})[name] = v
        for off, per in cc_offsets.items():
            # a real coordination reading has >=2 conjuncts; drop degenerate extractions
            sets = {name: frozenset(h for x in v["conj"] if (h := _norm_head(x.text)))
                    for name, v in per.items() if len(v["conj"]) >= 2}
            sets = {name: s for name, s in sets.items() if len(s) >= 2}
            if len(sets) < 2 or len(set(sets.values())) < 2:
                continue
            cc_txt = next(iter(per.values()))["cc"].text
            # semantic distance between the heads that differ across the scope readings
            all_heads = set().union(*sets.values())
            common = set.intersection(*[set(s) for s in sets.values()])
            differing = list(all_heads - common) or list(all_heads)
            verdict, dist = _classify_locus(differing, self.threshold, self._sim)
            loci_scores.append((_KIND_W["coord-scope"] * (len(set(sets.values())) - 1), verdict, dist))
            for name, s in sets.items():
                res.readings.append(Reading(
                    parser=name, kind="coord-scope", locus=f"{cc_txt}@{off}",
                    resolution=f"'{cc_txt}' conjoins {{{', '.join(sorted(s))}}}",
                    signature="|".join(sorted(s))))
            res.max_semantic_distance = max(res.max_semantic_distance, dist)

        # ---- aggregate ----
        # Weight PROVEN-nocuous loci fully, OOV/undetermined lightly, innocuous zero,
        # so the score reflects severity, not raw sentence length (#PPs).
        _mult = {"nocuous": 1.0, "undetermined": 0.3, "innocuous": 0.0, "none": 0.0}
        res.disagreement_score = round(sum(w * _mult[v] for w, v, _ in loci_scores), 3)
        res.n_loci = len(loci_scores)
        res.n_nocuous_loci = sum(1 for _, v, _ in loci_scores if v == "nocuous")
        res.max_semantic_distance = max((d for _, _, d in loci_scores), default=0.0)
        verdicts = {v for _, v, _ in loci_scores}
        if "nocuous" in verdicts:
            res.verdict = "nocuous"
        elif "undetermined" in verdicts:
            res.verdict = "undetermined"
            res.innocuous_reason = ("parsers diverged but the competing heads are domain "
                                    "jargon absent from WordNet -> similarity undetermined; "
                                    "inspect manually")
        elif "innocuous" in verdicts:
            res.verdict = "innocuous"
            res.innocuous_reason = ("parsers diverged but competing heads are semantically "
                                    f"close (WordNet sim >= {self.threshold}) -> readings coincide")
        return res
