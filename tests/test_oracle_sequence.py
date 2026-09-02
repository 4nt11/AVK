"""parse_all_sequential must produce the SAME per-sentence Decisions as the
default per-sentence path, and must evict each model exactly once. Both tests use
cheap fake parsers -- the loop-inversion + eviction is the new logic under test,
not the heavy GPU models."""
from avk import parsers
from avk.parsers import Decisions


def test_parse_all_sequential_matches_and_evicts(monkeypatch):
    def mk(name):
        def fn(sent):
            d = Decisions(name)
            d.pp = {0: {"n": name, "len": len(sent)}}     # sentinel keyed to sentence
            return d
        return fn
    fake = {n: mk(n) for n in parsers.PARSERS}
    evicted = []
    monkeypatch.setattr(parsers, "_ADAPTERS", fake)
    monkeypatch.setattr(parsers, "_unload", lambda name: evicted.append(name))

    sents = ["alpha beta", "gamma", "delta epsilon zeta"]
    seq = parsers.parse_all_sequential(sents)

    assert len(seq) == len(sents)
    for i, s in enumerate(sents):
        assert set(seq[i]) == set(parsers.PARSERS)                       # all four present
        for n in parsers.PARSERS:
            assert seq[i][n].pp == {0: {"n": n, "len": len(s)}}          # right sentence
    assert evicted == list(parsers.PARSERS)                              # each freed once, in order


def test_parse_all_sequential_isolates_parser_errors(monkeypatch):
    def boom(sent):
        raise RuntimeError("gpu ate it")
    fake = {"spacy-trf": boom,
            "stanza-dep": lambda s: Decisions("stanza-dep"),
            "benepar": lambda s: Decisions("benepar"),
            "stanza-con": lambda s: Decisions("stanza-con")}
    monkeypatch.setattr(parsers, "_ADAPTERS", fake)
    monkeypatch.setattr(parsers, "_unload", lambda name: None)

    seq = parsers.parse_all_sequential(["one sentence"])
    assert set(seq[0]) == set(fake)                    # errored parser still present...
    assert hasattr(seq[0]["spacy-trf"], "error")       # ...recorded as an error, not dropped
