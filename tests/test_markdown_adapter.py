from pathlib import Path
from avk.adapters.markdown import MarkdownAdapter


def test_markdown_adapter_structure(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/THREAT_MODEL.md").write_text(
        "# Threat Model\n\n"
        "## 3.2 API Key Handling\n\n"
        "Comparison of the client-provided API key against the stored value shall "
        "use a constant-time algorithm to mitigate timing attacks.\n\n"
        "- WHEN a request arrives without an API key THEN the system SHALL respond "
        "with 401.\n"
        "- WHEN a request arrives with an invalid API key THEN the system SHALL "
        "respond with 401 and log the attempt.\n\n"
        "```\ndef example():\n    pass\n```\n\n"
        "| Threat | Mitigation |\n|---|---|\n| Timing attack | constant-time compare |\n",
        encoding="utf-8",
    )
    units = list(MarkdownAdapter(str(tmp_path), "CloudGuard-GitOps",
                                 glob="docs/**/*.md").ingest())
    assert units
    assert all(u.anchor.startswith("CloudGuard-GitOps docs/THREAT_MODEL.md#") for u in units)
    assert all(u.section.startswith("threat-model") for u in units)
    assert not any("```" in u.text or "|" in u.text for u in units), "code/table leaked"
    assert any("WHEN a request arrives without" in u.text for u in units), "EARS bullet dropped"
    assert any("WHEN a request arrives with an invalid" in u.text for u in units), \
        "second list item merged into the first"
    assert len({u.uid for u in units}) == len(units), "uid collision"
