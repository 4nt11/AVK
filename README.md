# AVK — Ambiguity Vocoder Kraftwerk

A local, free-tooling pipeline built for the documents that break human review:
**large, committee-authored, normative standards** — the hundred-to-thousand-page
specifications that live for decades, where clause 6.2 quietly contradicts clause
2.1.28.0.1 and no single person has ever read both closely. In prose that size,
**nocuous ambiguity** — a passage underspecified enough that independent
implementations could reasonably read it differently — isn't a typo; it's a
conformance liability that ships in real products. AVK finds those passages so
differential-conformance effort can be aimed where the text is actually vague,
instead of testing the whole standard uniformly, and *vocodes* them into test-case
scaffolds (stage 5).

It's standard-agnostic: point an ingest adapter at DICOM, HL7 FHIR, an ITU
Recommendation, ECMA-376, IEEE 11073 — anything shipped as HTML, EPUB, or PDF —
and the same engine runs. A new standard is one adapter + one matcher + one
registry entry. The scale is the point: the bigger and more committee-shaped the
prose, the more it pays off. Smaller documents (design docs, threat models,
requirement files) ingest fine too — there's a Markdown adapter — but they're a
convenience, not the mission.

---

## How it finds ambiguity

A program can't *read* a sentence and feel that it's vague — meaning isn't
something code has access to. So AVK never tries to judge ambiguity directly.
Instead it computes **measurable proxies that correlate with ambiguity**, cheap
first, expensive second.

### Signal 1 — surface cues (cheap, runs on everything)

Certain words and patterns are historical red flags for underspecification — the
prose equivalent of grepping for dangerous function calls:

- **Mixed modal verbs** — "shall" and "may" and "should" in one requirement: which is binding?
- **Vague quantifiers** — "some", "appropriate", "as needed": how much? which?
- **"and/or" scope** — "A and B or C": does a trailing condition cover all three, or just C?
- **Actor-hiding passive** — "shall be encoded" — by whom? sender? receiver?
- **Ambiguous anaphora** — "this value" when three values were just mentioned: which one?

This is pattern-matching. It doesn't *prove* ambiguity, it flags suspicion — and
it's fast, so it scores every sentence and produces a ranked shortlist.

### Signal 2 — the real engine: differential testing, for grammar

This is the core idea, and it's the same instinct behind differential conformance
testing itself. You don't have ground truth for "what does this input mean," so
you run **several independent implementations** on the same input and treat the
places they **disagree** as the places the spec was ambiguous. The disagreement
*is* the finding.

AVK does exactly that — on sentences instead of files.

A grammar **parser** turns a sentence into a tree of "what attaches to what."
The textbook case:

> "I saw the man with the telescope."

Does "with the telescope" attach to **saw** (I used it to see) or to **man** (he
was holding it)? Two trees, two meanings — *structural ambiguity*, exactly the
flavor that makes two implementations of a spec behave differently.

So AVK runs **four independent parsers** on each shortlisted sentence — two using
one grammatical formalism, two using a completely different one, built by
different teams on different training data:

- On a **clear** sentence, all four build the same structure. They agree.
- On an **ambiguous** sentence, they **split** — the sentence genuinely supports
  multiple structures and each parser's bias picks a different one.

Parser disagreement is to a sentence what implementation disagreement is to a file
format. That's the whole trick — and the parsers "understand" nothing; we just got
careful about listening to *when* they argue.

### The catch — not all disagreement matters (nocuous vs innocuous)

Parsers bicker constantly, even about things no human would misread. Two trees can
be structurally different but **mean the same thing**. Those must not flood the
output. So for every disagreement AVK asks a second question: *do the competing
readings actually mean different things?*

When parsers disagree on where a word attaches, it compares the two candidate
attachment points:

- Candidates mean roughly the same thing → readings collapse → **innocuous**, drop it.
- Candidates mean genuinely different things → readings diverge → **nocuous**, flag it.

"Do these two words mean the same thing?" is measured with **WordNet**, a
hand-built map of word relationships — how far apart the two candidates sit in its
tree of concepts. Close = synonyms = ignore; far = distinct = flag. (This follows
Chantree et al.'s nocuous-ambiguity method, with WordNet standing in for their
distributional similarity.)

### The honest limitation

WordNet knows general English, not domain jargon. When both candidates are terms
it doesn't cover, AVK **does not guess** — it marks the sentence `undetermined`
and hands it to a human. That's why the whole tool is a **prioritization signal,
not ground truth**: it points attention; a person and a real differential-test
harness make the call.

**In one sentence:** *AVK makes four independent grammar engines argue about a
sentence and treats the arguments they can't settle — the ones where the rival
readings genuinely mean different things — as the places the standard's prose is
dangerously underspecified.*

---

## What this is and is NOT

- A **prioritization signal, not ground truth.** Ground truth comes from actual
  multi-implementation differential testing; AVK says *where to point it first*.
- Parser disagreement is a **proxy** for prose ambiguity, not proof. False
  positives are **expected and left visible** — every signal records why it fired,
  and the divergent parses are printed side by side so a human can overrule. The
  output is ranked, never hard-cut.

---

## Pipeline & architecture

Domain-agnostic core + a pluggable stage-1 ingest adapter per standard:

```
avk/
  model.py       Unit, SpecIngestAdapter (stage-1 ABC), FindingsMatcher (ABC)
  segment.py     shared sentence segmentation
  triage.py      stage 2  — surface-cue ambiguity scoring
  parsers.py     stage 3a — 4 parsers normalized to comparable decisions
  disagree.py    stage 3b — disagreement + WordNet nocuous scoring
  oracle.py      stage 3 interface (AmbiguityOracle)
  output.py      stage 4  — ranked CSV/JSON, findings-overlap surfacing
  scaffold.py    stage 5  — vocode oracle rows into test-case scaffolds
  projects.py    loads targets.toml -> builds adapter + matcher per standard
  adapters/
    dicom.py     DocBook HTML
    fhir.py      published HTML
    epub.py      EPUB (ITU X-series and similar)
    pdf.py       any spec PDF, via Docling
```

| Stage | Does |
|-------|------|
| 1 ingest | Source (HTML/EPUB/PDF) → sentence `Unit`s, each traceable to a spec anchor (section/clause/table). |
| 2 triage | Surface-cue scoring (signal 1). Scores all units; ranks, never cuts. |
| 3 oracle | Top-N units through the 4-parser disagreement engine + nocuous scoring (signal 2). |
| 4 output | Ranked CSV/JSON with side-by-side divergent parses; known-finding overlaps surfaced on top. |
| 5 scaffold | Turn oracle rows into test-case scaffolds with a synthesized `ambiguity` field. |

Stages 2–5 never change per standard. `Unit` fields (`spec`, `section`, `subref`,
`anchor`, `section_title`, `text`) are spec-neutral.

**The PDF adapter** uses [Docling](https://github.com/docling-project/docling) for
publisher-agnostic structure recovery: an ML layout model labels headings,
`code`/example blocks, and tables, so prose separates cleanly from reference
material — no per-publisher font heuristics. Table-structure recognition and OCR
are disabled (tables are discarded; spec PDFs carry a text layer) for speed, it
runs on GPU when available, and pages convert in parallel workers, so even
multi-thousand-page specs process quickly.

### Adding a standard
- **Same format as an existing adapter** (HTML/EPUB/PDF)? Just add a `[target.NAME]`
  entry to `targets.toml` — no code.
- **A new format?** Write `adapters/<name>.py` (a `SpecIngestAdapter` yielding
  `Unit`s, plus a `FindingsMatcher` for its citation style), register the `kind` in
  `projects.py`, and — if it has casefiles — add an extractor to
  `scripts/gen_findings.py`. The pipeline itself is unchanged.

---

## Install

```bash
git clone https://github.com/4nt11/AVK
cd AVK
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
```

Then fetch the language models once (the parsers don't run without them):

```bash
python3 -m spacy download en_core_web_sm
python3 -m spacy download en_core_web_trf
python3 -c "import stanza; stanza.download('en', processors='tokenize,pos,lemma,depparse,constituency')"
python3 -c "import benepar; benepar.download('benepar_en3')"
python3 -c "import nltk; [nltk.download(p) for p in ['wordnet','omw-1.4','punkt','punkt_tab']]"
```

**GPU (recommended for the PDF adapter):** install the `torch`/`torchvision` build
matching your CUDA from the [PyTorch index](https://pytorch.org/get-started/locally/)
(same index for both), plus `cupy-cuda1Xx` for spaCy's GPU path. CPU works otherwise,
just slower.

---

## Run

First declare what to analyze: copy `targets.toml.example` to `targets.toml` and
point each entry at your local spec documents (and casefile dirs, if any). Then:

```bash
# (optional) build the known-finding overlap set from a standard's casefiles
python scripts/gen_findings.py <project>

# core pipeline, per project
avk ingest   --project <project>
avk triage   --project <project> --sample 12      # peek at the top flags
avk oracle   --project <project> --top-n 1000     # deep-parse the shortlist
avk oracle   --project <project> --top-n 1000 --sequence   # ^ low peak VRAM/RAM

# stage 5 — turn the ranked ambiguities into test-case scaffolds
avk scaffold --project <project> --limit 50       # -> data/scaffold_<project>/*.toml
```

Outputs land in `data/`: `<triage|oracle>_<project>.csv/json`, `*_overlap.csv`, and
`scaffold_<project>/`. A project with no casefiles runs in **cold mode** (pure
triage + oracle ranking) — the ranked output is what you use to *write* the first
cases.

**`--top-n`** sets how far down the triage ranking the expensive oracle runs. Bias
it to cover your high-confidence triage band rather than an arbitrary cutoff;
running the oracle on *everything* is counterproductive (parser disagreement is
near-universal on any complex sentence, which drowns the signal).

**`--sequence`** trades run structure for peak memory. By default the four parsers
(spaCy-trf + Stanza×2 + benepar) load once and stay **co-resident** for the whole
oracle stage — fastest, but peak memory is their sum, which OOMs smaller cards.
With `--sequence` the oracle loads **one parser at a time**, sweeps every unit,
frees it, then loads the next; peak memory holds a single model instead of four.
Output is byte-identical either way. Measured on `dcmk --top-n 50`, RTX 5060 (8 GB):

| mode | peak VRAM | parser-attributable | result |
|------|-----------|---------------------|--------|
| default | 3191 MiB | ~2095 MiB | — |
| `--sequence` | 2308 MiB | ~1212 MiB | identical CSV |

~42% less parser VRAM, no measurable slowdown. Reach for it when the default
stage OOMs at model-load time; leave it off if everything already fits.

**`--batch-size N`** parses N sentences per model call (spaCy `nlp.pipe`, Stanza
bulk) instead of one at a time — a real speedup on a GPU. It implies the
one-model-at-a-time sweep, so you get batched speed *and* single-model peak
memory in one pass; larger N is faster but raises peak activation VRAM (tune it
down if it OOMs). Measured on `dcmk --top-n 200`, RTX 5060 (8 GB):

| mode | wall time | peak VRAM | ranking / verdicts / scores |
|------|-----------|-----------|------------------------------|
| `--sequence` (batch 1) | 58.5 s | ~1212 MiB | reference |
| `--batch-size 32` | 38.3 s | ~2339 MiB | **identical** |

The default is `1` (bit-exact reproducible). Batched transformer inference is not
bit-reproducible on borderline cases: verdicts, scores, `n_loci` and the ranking
came out identical to batch-1, but the display-only `divergent_readings` string
wobbled on ~1% of parsed units (observed: a trailing-token tokenization variant
on identifiers, which scoring drops anyway). Use it for speed on a capable GPU;
keep the default when you need byte-identical output across runs.

---

## Verdict semantics (stage 3)

Each deep-parsed sentence gets a three-valued `verdict`:

- **nocuous** — ≥2 competing attachment points that WordNet knows and scores as far
  apart: readings genuinely differ. Ranked highest, by number of nocuous loci then
  a severity-weighted disagreement score (a tight requirement with two real
  ambiguities outranks a long enumeration — length is not the signal).
- **undetermined** — competing points are domain jargon WordNet can't score; **not**
  silently promoted to nocuous — surfaced for manual review.
- **innocuous** — competing points are near-synonyms (readings coincide): cosmetic
  parser noise, ranked lowest.

On heavily domain-specific prose, `innocuous` is rare and `undetermined` common —
WordNet simply doesn't cover specialized vocabulary. The filter demotes what it
*can* prove cosmetic; the rest is ranked for human review, with the side-by-side
parses included so you can overrule any verdict.

---

## Findings overlap

If a standard has an existing body of differential-test cases,
`scripts/gen_findings.py` extracts the spec anchors those cases cite into a
findings JSON. Units whose clause overlaps a **precise** citation (exact
section/table, deep clause, invariant id, title concept) surface at the top
regardless of score and go to a separate `*_overlap.csv`; **broad** matches
(chapter-level cites) are flagged but rank by score. This tells you where your
existing test coverage is thin — the cold-run output finds ambiguities, the
warm-run output finds the gaps in your own testing.

The oracle is a swappable component: everything else depends only on the
`AmbiguityOracle` interface (`score(unit) -> OracleResult`), so an alternative
scoring engine can be dropped in behind it without touching ingest, triage,
output, or scaffold.

---

## License

GPL-3.0-or-later. See [`LICENSE`](LICENSE).
