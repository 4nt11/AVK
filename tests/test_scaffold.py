# SPDX-License-Identifier: GPL-3.0-or-later
"""AVK scaffold: valid TOML + case block synthesized from a row. No models/GPU.

Run: PYTHONPATH=. .venv/bin/python tests/test_scaffold.py
"""
import json
import tomllib
from avk import scaffold


def test_scaffold_row_is_valid_toml_with_synthesized_ambiguity():
    row = {
        "section": "17.3.1.28", "anchor": "ECMA-376-1 17.3.1.28",
        "section_title": "right (Right Paragraph Border)",
        "text": 'To determine if two adjoining paragraphs should have a border which spans '
                'the full line height, the border shall be drawn between them.',
        "verdict": "nocuous", "semantic_distance": "0.83", "disagreement_score": "14.1",
        "triage_signals": json.dumps({"coordination": {"points": 2.5,
                          "reasons": ["mixed 'and'/'or' -> ambiguous coordination scope"]}}),
        "divergent_readings": json.dumps([
            {"parser": "spacy-trf", "kind": "pp-attach", "locus": "between@90",
             "resolution": "'between' attaches to 'drawn'", "signature": "drawn"},
            {"parser": "stanza-dep", "kind": "pp-attach", "locus": "between@90",
             "resolution": "'between' attaches to 'border'", "signature": "border"},
        ]),
    }
    fname, text = scaffold.scaffold_row(row, "ooxml", "oracle_ooxml.csv")
    assert fname.endswith(".toml")
    parsed = tomllib.loads(text)                 # must be valid TOML
    case = parsed["case"]
    assert case["id"].startswith("ooxml/17.3.1.28")
    assert case["spec"] == ["ECMA-376-1 17.3.1.28 right (Right Paragraph Border)"]
    # ambiguity must carry the actual parse divergence + the triage cue
    assert "STRUCTURAL PARSE DIVERGENCE" in case["ambiguity"]
    assert "drawn" in case["ambiguity"] and "border" in case["ambiguity"]
    assert "coordination" in case["ambiguity"]


if __name__ == "__main__":
    test_scaffold_row_is_valid_toml_with_synthesized_ambiguity()
    print("ok")
