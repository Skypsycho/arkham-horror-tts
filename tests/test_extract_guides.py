"""Regression tests against the real campaign guide PDFs.

Each assertion pins a behavior verified by hand against the PDF. Counts use
upper bounds (``<=``) so improvements don't fail the suite — tighten them
when extraction gets better.
"""
import re

import pytest

pytestmark = pytest.mark.pdf

JUNK = [
    r"is a campaign for Arkham Horror",
    r"Check Campaign Log",
    r"Congratulations on completing",
    r"^For example:",
    r"^Example:",
    r"^\(Note:",
    r"^\(remember to",
    r"^The investigators \w+",
    r"Draw 1 card\.",
    r"Place 1 resource",
]


# ---------------------------------------------------------------- all guides

@pytest.mark.parametrize("key, scenarios, max_unlabeled", [
    ("zealot", 3, 0),
    ("dunwich", 12, 4),
    ("carcosa", 12, 2),
    ("forgotten", 16, 8),
    ("brethren", 5, 7),
])
def test_shape(guide, key, scenarios, max_unlabeled):
    g = guide(key)
    assert len(g.scenarios) == scenarios, g.names
    unlabeled = g.unlabeled()
    assert len(unlabeled) <= max_unlabeled, [(s, e["text"][:60]) for s, e in unlabeled]


@pytest.mark.parametrize("key", ["zealot", "dunwich", "carcosa", "forgotten", "brethren"])
def test_no_rules_text_in_narrative(guide, key):
    bad = []
    for scen, e in guide(key).entries():
        for pat in JUNK:
            if re.search(pat, e["text"], re.IGNORECASE):
                bad.append((scen, e["display_label"], pat, e["text"][:80]))
    assert not bad


@pytest.mark.parametrize("key", ["zealot", "dunwich", "carcosa", "forgotten", "brethren"])
def test_no_stray_card_groups_or_ungrouped(guide, key):
    names = guide(key).names
    assert "Ungrouped" not in names
    for n in names:
        assert re.match(r"(Scenario|Part|Interlude|Codex|Prologue|Epilogue)", n), n


@pytest.mark.parametrize("key", ["zealot", "dunwich", "carcosa", "forgotten", "brethren"])
def test_labels_unique_within_scenario(guide, key):
    for s in guide(key).scenarios:
        labels = [e["label"] for e in s["entries"]]
        dupes = {l for l in labels if labels.count(l) > 1}
        # Known PDF quirks: duplicated label text in the guide itself
        dupes -= {"resolution_2", "intro_5"}
        assert not dupes, (s["scenario"], dupes)


# ---------------------------------------------------------- Night of the Zealot

def test_zealot_intros(guide):
    g = guide("zealot")
    assert g.labels("Part I:")[:2] == ["Campaign Intro", "Intro"]
    _, e = g.find("Friday, September 18, 1925.")
    assert e["display_label"] == "Campaign Intro"
    assert e["text"].endswith("I won’t be holding my breath.")
    assert g.labels("Part III")[0] == "Intro"


def test_zealot_resolutions_stay_in_their_part(guide):
    # Regression: rules text above the Part II header once dragged page 5's
    # Midnight Masks resolutions into Part I.
    g = guide("zealot")
    assert g.find("You’ve managed to obtain some useful information")[0].startswith("Part II")
    assert g.find("Twelve bells ring out")[0].startswith("Part II")


# ------------------------------------------------------------ Dunwich Legacy

def test_dunwich_survivor_labels(guide):
    labels = guide("dunwich").labels("Interlude II")
    for name in ["Dr. Francis Morgan", "Zebulon Whateley", "Earl Sawyer",
                 "Dr. Henry Armitage", "Professor Warren Rice"]:
        assert name in labels
    assert labels[0] == "Intro"


def test_dunwich_scenario_intros(guide):
    g = guide("dunwich")
    for scen in ["I–A", "II:", "III:", "IV:", "V:", "VII:"]:
        assert g.labels(f"Scenario {scen}")[0] == "Intro", scen


# ---------------------------------------------------------- Path to Carcosa

def test_carcosa_prologue(guide):
    labels = guide("carcosa").labels("Prologue")
    assert labels[:2] == ["Campaign Intro", "Prologue"]
    assert "Lola’s Prologue" in labels


def test_carcosa_dream_2_kept(guide):
    # Shares a text box with "Check Campaign Log…"; must be truncated, not dropped
    _, e = guide("carcosa").find("Constance takes your hand")
    assert e["display_label"] == "Dream 2"
    assert e["text"].endswith("For celebration!”")


def test_carcosa_inline_title_absorbed(guide):
    _, e = guide("carcosa").find("There are no coincidences when it comes to")
    assert "The King in Yellow" in e["text"][:80]


# ---------------------------------------------------------- Forgotten Age

def test_forgotten_journal_dates(guide):
    g = guide("forgotten")
    _, e = g.find("Sunday, June 28th, 1925 It’s been a hell of a day.")
    assert e["display_label"] == "Intro"
    dated = [e["text"] for _, e in g.entries() if re.match(r"\w+day, \w+ \d+\w\w, 1925", e["text"])]
    assert len(dated) >= 10
    assert all(re.match(r"\w+day, \w+ \d+\w\w, 1925 ", t) for t in dated), "date glued to text"


def test_forgotten_boundary_beyond_frames(guide):
    # p17's text frame starts bottom-right ("After arriving…"), jumps to the
    # top-left (the real intro), and continues on p18 ("it. “It is a fool’s errand…")
    g = guide("forgotten")
    scen, intro = g.find("Rays of hot yellow sunlight")
    assert scen.startswith("Scenario IV") and intro["display_label"] == "Intro"
    assert intro["text"].endswith("offering her little comfort.")
    scen, cont = g.find("After arriving in Mexico City")
    assert scen.startswith("Scenario IV")
    assert "how to find it. “It is a fool’s errand,”" in cont["text"]
    assert not any(e["text"].startswith("it. ") for _, e in g.entries())


@pytest.mark.parametrize("text_start, scenario", [
    # previous scenario's resolutions in the left column of a header page
    ("The boundary along the horizon shimmers", "Scenario IV"),
    ("Somehow, despite the odds stacked against you", "Scenario VII"),
    ("The hazards of the jungle are too dangerous", "Scenario V–A"),
    ("There is only one way to stop all of this", "Scenario VIII"),
    ("Though you long for a proper bed", "Interlude IV"),
    # and the new scenario's own content stays put
    ("Once more, you venture south", "Interlude III"),
    ("You descend down miles of steep, cold stone", "Scenario V–B"),
])
def test_forgotten_header_position(guide, text_start, scenario):
    scen, _ = guide("forgotten").find(text_start)
    assert scen.startswith(scenario)


def test_forgotten_card_subtitles_not_glued(guide):
    g = guide("forgotten")
    assert not any(e["text"].startswith(("(Repossess", "(Scion of Yig)", "the braziers"))
                   for _, e in g.entries())
    assert "Ichtaca’s Quest" in g.labels("Boundary Beyond")


# ---------------------------------------------------------- Brethren of Ash

def test_brethren_codex_continuations(guide):
    labels = guide("brethren").labels("Codex: Smoke and Mirrors")
    for codex in ["Codex 1: David Renfield", "Codex 2: Cornelia Akely",
                  "Codex 3: Naomi O’Bannion", "Codex 4: Sgt. Earl Monroe"]:
        assert codex in labels
        assert f"{codex} (cont.)" in labels


def test_brethren_codex_rules_text_trimmed(guide):
    _, e = guide("brethren").find("The junior librarian waves your questions away")
    assert e["text"].endswith("whatever she is looking for.")


def test_brethren_intros(guide):
    g = guide("brethren")
    assert g.labels("Spreading Flames")[:2] == ["Campaign Intro", "Intro"]
    assert g.labels("Scenario II:")[0] == "Intro"
    # Codex groups never get an "Intro"
    assert "Intro" not in g.labels("Codex: Queen of Ash")
