"""Fast tests for extract.py helpers (no PDFs needed)."""
import pytest

from extract import (
    _auto_subgroup,
    _cut_trailing_rules_text,
    _detect_entry_label,
    _ends_sentence,
    _entry_sort_key,
    _looks_like_non_narrative,
    _precedes_header,
)


@pytest.mark.parametrize("bold, expected", [
    ("Resolution 1:", "Resolution 1"),
    ("Resolution 2 (read Investigator Defeat first!):", "Resolution 2"),
    ("Armitage’s Fate 2.Armitage’s Fate 1:", "Armitage’s Fate 1"),
    ("Intro 3:", "Intro 3"),
    ("Codex 1: David Renfield", "Codex 1: David Renfield"),
    ("Reality’s Shadow 1:", "Reality’s Shadow 1"),
    ("Sebastien’s Information:", "Sebastien’s Information"),
    ("If Dr. Francis Morgan is not listed under “Sacrificed to Yog‑Sothoth:”", "Dr. Francis Morgan"),
    ("If Earl Sawyer is not listed under “Sacrificed to Yog‑Sothoth:”", "Earl Sawyer"),
    # game-mechanics instructions are not labels
    ("Setup:", None),
    ("Proceed to:", None),
    ("Smoke and Mirrors", None),
    ("Expert:", None),
    ("Note:", None),
    ("):", None),
])
def test_detect_entry_label(bold, expected):
    assert _detect_entry_label(bold) == expected


@pytest.mark.parametrize("text", [
    "For example: If you were playing as Wendy Adams, treat the Body of a Yithian card as if…",
    "Example: Agenda 1a—“Expedition into the Wild” has the following ability…",
    "(Note: Provisions and medicine can each be taken more than once…",
    "(remember to use the versions of Abbey Tower and Chapel of St. Aubert…",
    "The investigators gave custody of the relic to Alejandro.",
    "the investigators killed the Servant of Flame. If there are 6 Elite enemies…",
    "Sebastien Moreau is not listed under VIPs Interviewed or VIPs Slain.",
    "(The Path to Carcosa #59) to their deck.",
    "(Scion of Yig) and Alejandro Vela (Or, Is He?) Note: These cards are double-sided…",
])
def test_non_narrative_filtered(text):
    assert _looks_like_non_narrative(text)


@pytest.mark.parametrize("text", [
    "You awaken with a start, as though shaken by an unseen force.",
    "“Thank you for everything you’ve done,” Dr. Morgan says.",
    "Sunday, June 28th, 1925 It’s been a hell of a day.",
])
def test_narrative_kept(text):
    assert not _looks_like_non_narrative(text)


def test_cut_rules_text_keeps_preceding_narrative():
    text = ("…but I won’t be holding my breath.Night of the Zealot is a campaign "
            "for Arkham Horror: The Card Game for 1–4 players.")
    assert _cut_trailing_rules_text(text) == "…but I won’t be holding my breath."


def test_cut_rules_text_whole_block_is_rules():
    assert _cut_trailing_rules_text(
        "The Path to Carcosa is a campaign for Arkham Horror: The Card Game.") == ""


def test_cut_rules_text_check_campaign_log():
    text = "Tonight is a night for dancing! For celebration!”Check Campaign Log. If the King…"
    assert _cut_trailing_rules_text(text) == "Tonight is a night for dancing! For celebration!”"


def test_ends_sentence():
    assert _ends_sentence("…offering her little comfort.")
    assert _ends_sentence("“Are you ready?”")
    assert _ends_sentence("hoping to find answers…")
    assert not _ends_sentence("though she refuses to tell you how to find")


@pytest.mark.parametrize("block, header, expected", [
    # header in right column: left column belongs to previous scenario
    ({"x0": 54, "top": 300}, (315, 51), True),
    ({"x0": 331, "top": 300}, (315, 51), False),
    # header mid-way down the left column: above it is previous, below is new
    ({"x0": 54, "top": 109}, (99, 272), True),
    ({"x0": 54, "top": 400}, (99, 272), False),
    # right column after a left-column header reads after it
    ({"x0": 331, "top": 60}, (99, 272), False),
    # header at top-left: nothing precedes it
    ({"x0": 54, "top": 80}, (54, 51), False),
    ({"x0": 331, "top": 60}, (54, 51), False),
])
def test_precedes_header(block, header, expected):
    assert _precedes_header(block, header, 612) is expected


def test_auto_subgroup():
    assert _auto_subgroup("Resolution 2") == "Resolutions"
    assert _auto_subgroup("If no resolution was reached") == "Resolutions"
    assert _auto_subgroup("Intro 1") == "Intros"
    assert _auto_subgroup("Codex 1: David Renfield (cont.)") == "Codex Entries"
    assert _auto_subgroup("Intro") is None


def test_sort_key_intros_first():
    entries = [
        {"display_label": "Resolution 1", "page": 4},
        {"display_label": "Intro 2", "page": 3},
        {"display_label": "Intro", "page": 3},
        {"display_label": "Campaign Intro", "page": 2},
        {"display_label": "If no resolution was reached", "page": 4},
        {"display_label": "Part 1", "page": 3},
    ]
    order = [e["display_label"] for e in sorted(entries, key=_entry_sort_key)]
    assert order == ["Campaign Intro", "Intro", "Intro 2", "Part 1",
                     "If no resolution was reached", "Resolution 1"]
