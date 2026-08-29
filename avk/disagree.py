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
from functools import lru_cache

from . import config, parsers
from .oracle import OracleResult, Reading

_KIND_W = {"pp-attach": 1.0, "coord-scope": 1.3}   # coord scope errors tend to matter more


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
def _similarity(a: str, b: str):
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


def _classify_locus(heads: list[str], threshold: float):
    """Judge one disagreement locus from its competing heads.

    Returns (verdict, distance):
      * "nocuous"      -- >=2 distinct heads WordNet KNOWS and they are far apart
                          (closest known pair sim < threshold): readings truly differ.
      * "innocuous"    -- distinct known heads that are close (some pair sim >= threshold):
                          the readings coincide -> cosmetic parser noise.
      * "undetermined" -- too few heads are in WordNet (domain jargon): cannot judge,
                          a human should look. NOT silently promoted to nocuous.
    distance = 1 - closest-known-pair similarity (0.0 when undetermined).
    """
    uniq = sorted(set(h.lower() for h in heads if h))
    if len(uniq) < 2:
        return "none", 0.0
    known = [u for u in uniq if _wn().synsets(u)]
    if len(known) < 2:
        return "undetermined", 0.0
    best = 0.0
    for i in range(len(known)):
        for j in range(i + 1, len(known)):
            s = _similarity(known[i], known[j])
            if s and s > best:
                best = s
    return ("innocuous" if best >= threshold else "nocuous"), (1.0 - best)


# --- the oracle ------------------------------------------------------------
class ParserDisagreementOracle:
    """Default free/local AmbiguityOracle (satisfies oracle.AmbiguityOracle)."""

    def __init__(self, sim_threshold: float | None = None):
        self.threshold = sim_threshold if sim_threshold is not None else config.NOCUOUS_SIM_THRESHOLD

    def score(self, unit) -> OracleResult:
        dec = parsers.parse_all(unit.text)
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
            if len(set(h.lower() for h in heads.values())) < 2:
                continue                          # all parsers agree -> not a locus
            prep_txt = next(iter(per.values()))["prep"].text
            verdict, dist = _classify_locus(list(heads.values()), self.threshold)
            n_readings = len(set(h.lower() for h in heads.values()))
            loci_scores.append((_KIND_W["pp-attach"] * (n_readings - 1), verdict, dist))
            for name, h in heads.items():
                res.readings.append(Reading(
                    parser=name, kind="pp-attach", locus=f"{prep_txt}@{off}",
                    resolution=f"'{prep_txt}' attaches to '{h}'", signature=h.lower()))
            res.max_semantic_distance = max(res.max_semantic_distance, dist)

        # ---- coordination-scope disagreement (group by coordinator offset) ----
        cc_offsets = {}
        for name, d in dec.items():
            for off, v in d.coord.items():
                cc_offsets.setdefault(off, {})[name] = v
        for off, per in cc_offsets.items():
            # a real coordination reading has >=2 conjuncts; drop degenerate extractions
            sets = {name: frozenset(x.text.lower() for x in v["conj"])
                    for name, v in per.items() if len(v["conj"]) >= 2}
            if len(sets) < 2 or len(set(sets.values())) < 2:
                continue
            cc_txt = next(iter(per.values()))["cc"].text
            # semantic distance between the heads that differ across the scope readings
            all_heads = set().union(*sets.values())
            common = set.intersection(*[set(s) for s in sets.values()])
            differing = list(all_heads - common) or list(all_heads)
            verdict, dist = _classify_locus(differing, self.threshold)
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
