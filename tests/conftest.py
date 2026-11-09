import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Campaign guide PDFs aren't checked in (uploads/ is gitignored). Point
# ARKHAM_PDF_DIR elsewhere to run the guide tests against another folder.
PDF_DIR = Path(os.environ.get("ARKHAM_PDF_DIR", ROOT / "uploads"))

GUIDES = {
    "zealot": "night_of_the_zealot_campaign_guide.pdf",
    "dunwich": "ahc66_campaign_guide_v6-compressed.pdf",
    "carcosa": "ahc68_campaign_guide_v4-compressed.pdf",
    "forgotten": "ahc73_campaign_guide_v2-compressed.pdf",
    "brethren": "ahc100_campaign_guide-web.pdf",
}

_cache = {}


@pytest.fixture(scope="session")
def guide():
    """guide("forgotten") -> Guide wrapper around extract_sections output.

    Each PDF is extracted once per test session.
    """
    from extract import extract_sections

    def load(key):
        if key not in _cache:
            path = PDF_DIR / GUIDES[key]
            if not path.exists():
                pytest.skip(f"{path.name} not found in {PDF_DIR}")
            _cache[key] = Guide(extract_sections(str(path)))
        return _cache[key]

    return load


class Guide:
    def __init__(self, scenarios):
        self.scenarios = scenarios

    @property
    def names(self):
        return [s["scenario"] for s in self.scenarios]

    def scenario(self, name_part):
        matches = [s for s in self.scenarios if name_part in s["scenario"]]
        assert len(matches) == 1, f"expected one scenario matching {name_part!r}, got {[s['scenario'] for s in matches]}"
        return matches[0]

    def labels(self, name_part):
        return [e["display_label"] for e in self.scenario(name_part)["entries"]]

    def entries(self):
        for s in self.scenarios:
            for e in s["entries"]:
                yield s["scenario"], e

    def find(self, text_start):
        """(scenario name, entry) for the single entry whose text starts with text_start."""
        hits = [(s, e) for s, e in self.entries() if e["text"].startswith(text_start)]
        assert len(hits) == 1, f"expected one entry starting {text_start!r}, got {len(hits)}"
        return hits[0]

    def unlabeled(self):
        return [(s, e) for s, e in self.entries() if e["display_label"].startswith("Entry ")]
