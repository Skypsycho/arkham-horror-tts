"""merge.merge_campaign on small synthetic campaigns."""
import copy

from merge import merge_campaign

LOREM = ("the night is dark and the old house groans under the weight of years "
         "while the wind carries whispers from the river below the hill ")
STORY_A = "You awaken in the cellar. " + LOREM * 2
STORY_B = "The professor closes his book. " + LOREM.replace("night", "day") * 2
STORY_C = "Far below the streets a choir begins to chant. " + LOREM.replace("house", "temple") * 2


def entry(label, text, display=None, subgroup=None, page=3, **extra):
    return {"label": label, "display_label": display or label, "text": text,
            "page": page, "subgroup": subgroup, **extra}


def scen(name, *entries):
    return {"scenario": name, "scenario_folder": name.lower(), "entries": list(entries)}


def actions(report, kind):
    return [r for r in report if r["action"] == kind]


def test_relabel_and_trim_unedited_entry():
    existing = [scen("Scenario I", entry("entry_1", STORY_A + " Check Campaign Log. Record that…", "Entry 1"))]
    extracted = [scen("Scenario I", entry("intro", STORY_A, "Intro"))]
    merged, report = merge_campaign(existing, extracted)
    e = merged[0]["entries"][0]
    assert (e["label"], e["display_label"], e["text"]) == ("intro", "Intro", STORY_A)
    assert actions(report, "relabel") and actions(report, "update-text")
    assert existing[0]["entries"][0]["display_label"] == "Entry 1", "input must not be mutated"


def test_user_renamed_label_is_kept():
    existing = [scen("Scenario I", entry("my_name", STORY_A, "The Cellar"))]
    extracted = [scen("Scenario I", entry("intro", STORY_A, "Intro"))]
    merged, report = merge_campaign(existing, extracted)
    assert merged[0]["entries"][0]["display_label"] == "The Cellar"
    assert not report


def test_hand_edited_text_is_kept():
    edited = STORY_A.replace("whispers from the river", "screams from the lake")
    existing = [scen("Scenario I", entry("intro", edited, "Intro"))]
    extracted = [scen("Scenario I", entry("intro", STORY_A, "Intro"))]
    merged, report = merge_campaign(existing, extracted)
    assert merged[0]["entries"][0]["text"] == edited
    assert actions(report, "keep-edited")


def test_audio_protects_text_and_position_but_not_label():
    existing = [scen("Interlude", entry("entry_1", STORY_A + " Draw 1 card.", "Entry 1", audio_file="x.mp3"),
                     entry("other", STORY_B, "Other")),
                scen("Scenario I", entry("r1", STORY_C, "Resolution 1"))]
    extracted = [scen("Scenario I", entry("resolution_2", STORY_A, "Resolution 2"),
                      entry("r1", STORY_C, "Resolution 1")),
                 scen("Interlude", entry("other", STORY_B, "Other"))]
    merged, report = merge_campaign(existing, extracted, has_audio=lambda e: "audio_file" in e)
    e = merged[0]["entries"][0]
    assert e["display_label"] == "Resolution 2"          # label upgraded
    assert e["text"].endswith("Draw 1 card.")             # text kept
    assert actions(report, "text-available") and actions(report, "move-skipped")


def test_move_to_correct_scenario_in_extraction_order():
    existing = [scen("Scenario IV", entry("intro", STORY_B, "Intro"), entry("r1", STORY_C, "Resolution 1")),
                scen("Interlude III", entry("resolution_2", STORY_A, "Resolution 2"),
                     entry("x", LOREM * 3 + "unique interlude text here", "Something"))]
    extracted = [scen("Scenario IV", entry("intro", STORY_B, "Intro"), entry("r1", STORY_C, "Resolution 1"),
                      entry("resolution_2", STORY_A, "Resolution 2")),
                 scen("Interlude III", entry("x", LOREM * 3 + "unique interlude text here", "Something"))]
    merged, report = merge_campaign(existing, extracted)
    assert [e["display_label"] for e in merged[0]["entries"]] == ["Intro", "Resolution 1", "Resolution 2"]
    assert [e["display_label"] for e in merged[1]["entries"]] == ["Something"]
    assert actions(report, "move")


def test_only_entry_in_group_is_not_moved():
    existing = [scen("Intro", entry("entry_1", STORY_A, "Entry 1")), scen("Prologue", entry("p", STORY_B, "P"))]
    extracted = [scen("Prologue", entry("campaign_intro", STORY_A, "Campaign Intro"), entry("p", STORY_B, "P"))]
    merged, report = merge_campaign(existing, extracted)
    assert merged[0]["entries"][0]["display_label"] == "Campaign Intro"
    assert len(merged[0]["entries"]) == 1
    assert actions(report, "move-skipped")


def test_fragment_merged_into_continuation_is_removed():
    first, second = STORY_A[:120], STORY_A[120:]
    existing = [scen("Scenario I", entry("entry_1", first, "Entry 1"), entry("entry_2", second, "Entry 2"))]
    extracted = [scen("Scenario I", entry("intro", STORY_A, "Intro"))]
    merged, report = merge_campaign(existing, extracted)
    assert len(merged[0]["entries"]) == 1
    assert merged[0]["entries"][0]["text"] == STORY_A
    assert actions(report, "remove-fragment")


def test_new_passage_added_after_its_predecessor():
    existing = [scen("Scenario I", entry("intro", STORY_A, "Intro"), entry("r1", STORY_C, "Resolution 1"))]
    extracted = [scen("Scenario I", entry("intro", STORY_A, "Intro"), entry("part_1", STORY_B, "Part 1"),
                      entry("r1", STORY_C, "Resolution 1"))]
    merged, report = merge_campaign(existing, extracted)
    assert [e["display_label"] for e in merged[0]["entries"]] == ["Intro", "Part 1", "Resolution 1"]
    assert actions(report, "add")


def test_glued_entry_split_when_unprotected():
    existing = [scen("Interlude", entry("poison", STORY_A + " " + STORY_B, "The Poison Spreads"))]
    extracted = [scen("Interlude", entry("poison", STORY_A, "The Poison Spreads"),
                      entry("entry_2", STORY_B, "Entry 2"))]
    merged, _ = merge_campaign(existing, extracted)
    assert [e["text"] for e in merged[0]["entries"]] == [STORY_A, STORY_B]


def test_glued_entry_with_audio_not_duplicated():
    existing = [scen("Interlude", entry("poison", STORY_A + " " + STORY_B, "The Poison Spreads", audio_file="p.mp3"))]
    extracted = [scen("Interlude", entry("poison", STORY_A, "The Poison Spreads"),
                      entry("entry_2", STORY_B, "Entry 2"))]
    merged, report = merge_campaign(existing, extracted, has_audio=lambda e: "audio_file" in e)
    assert len(merged[0]["entries"]) == 1
    assert actions(report, "add-skipped")


def test_card_entries_and_unmatched_untouched():
    card = entry("agenda_x_front", STORY_C, "Agenda: X (Front)", subgroup="Agenda Deck", page=0)
    mine = entry("my_note", "Something I typed myself about this scenario for the table " * 3, "My Note")
    existing = [scen("Scenario I", entry("intro", STORY_A, "Intro"), card, mine)]
    extracted = [scen("Scenario I", entry("intro", STORY_A, "Intro"))]
    merged, report = merge_campaign(copy.deepcopy(existing), extracted)
    assert merged == existing
    assert [r["label"] for r in actions(report, "unmatched")] == ["My Note"]


def test_renamed_scenario_still_matched():
    existing = [scen("My Custom Name", entry("entry_1", STORY_A, "Entry 1"), entry("r", STORY_C, "Resolution 1"))]
    extracted = [scen("Scenario I: The Gathering", entry("intro", STORY_A, "Intro"),
                      entry("part", STORY_B, "Part 1"), entry("r", STORY_C, "Resolution 1"))]
    merged, report = merge_campaign(existing, extracted)
    assert len(merged) == 1
    assert [e["display_label"] for e in merged[0]["entries"]] == ["Intro", "Part 1", "Resolution 1"]
    assert not actions(report, "move")
