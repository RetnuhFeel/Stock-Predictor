"""Guards for docs/FINDINGS.md: it must match what the saved analysis results produce, and its charts must exist."""
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS = ROOT / "analysis"

pytestmark = pytest.mark.skipif(
    not (ANALYSIS / "build_findings.py").exists(), reason="analysis/ not present (e.g. Docker context)")


def _builder():
    spec = importlib.util.spec_from_file_location("build_findings", ANALYSIS / "build_findings.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_findings_doc_matches_saved_results():
    b = _builder()
    assert (ROOT / "docs" / "FINDINGS.md").read_text() == b.render(), (
        "docs/FINDINGS.md is stale: run `python analysis/build_findings.py` "
        "(edit analysis/findings_template.md, not the doc)")


def test_findings_doc_has_no_unfilled_placeholders_and_charts_exist():
    text = (ROOT / "docs" / "FINDINGS.md").read_text()
    assert "{{" not in text and "<!-- table" not in text
    images = re.findall(r"!\[[^\]]*\]\(([^)]+\.png)\)", text)
    assert 3 <= len(images) <= 5
    for rel in images:
        assert (ROOT / "docs" / rel).resolve().is_file(), rel


def test_findings_doc_makes_no_market_beating_claim_and_keeps_live_log_placeholder():
    text = (ROOT / "docs" / "FINDINGS.md").read_text()
    assert "placeholder: no results yet" in text
    assert "does *not* show:** that the model beats the market" in text


def test_readme_links_to_findings():
    assert "docs/FINDINGS.md" in (ROOT / "README.md").read_text().split("## Screenshots")[0]
