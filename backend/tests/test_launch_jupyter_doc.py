"""docs/INSTALLATION.md documents the bank Jupyter launch (spec bank-jupyter-launch, AC-33)."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_installation_has_bank_section():
    text = (REPO / "docs" / "INSTALLATION.md").read_text()
    assert "\n## Bank Jupyter (Vertex)\n" in text
    section = text.split("\n## Bank Jupyter (Vertex)\n", 1)[1].split("\n## ", 1)[0]
    for needle in ("ARP_GEMINI_USE_VERTEX", "ARP_GCP_PROJECT", "scripts/launch_jupyter.sh up"):
        assert needle in section, needle
