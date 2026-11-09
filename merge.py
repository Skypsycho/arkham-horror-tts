"""
Merge a fresh PDF extraction into an existing (user-edited) campaign.

Existing entries are matched to newly extracted ones by text overlap
(shared 6-word shingles), then:

- unedited entries get the new label (only if theirs is still a generic
  "Entry N") and the new text (only if one text contains the other — i.e.
  the extractor trimmed rules text or added a continuation/journal date);
- entries whose text differs in the middle are treated as user-edited and
  left alone;
- entries with audio on disk never get their text changed (the audio would
  no longer match) — new text is reported instead; labels can still change;
- entries now extracted into a different scenario are moved (no audio only);
- old fragments now merged into a bigger entry are removed (no audio only);
- passages that are new in the extraction are added;
- ArkhamDB card entries (Act/Agenda Deck, page 0) are never touched;
- entries with no match are only reported (rules text or added by hand).

merge_campaign() never writes anything; callers decide whether to save.
"""

import copy
import re

from extract import _auto_subgroup, _sanitize_filename

SHINGLE = 6
QUALIFY = 0.5      # min share of the shorter text's shingles to count as a match
CONTAINED = 0.9    # share of shingles for "this text is contained in that one"


def _words(text):
    return re.findall(r"[a-z0-9]+", text.lower().replace("’", "").replace("'", ""))


def _shingles(text):
    w = _words(text)
    if len(w) < SHINGLE:
        return {tuple(w)}
    return {tuple(w[i:i + SHINGLE]) for i in range(len(w) - SHINGLE + 1)}


def _is_card_entry(entry):
    return (entry.get("subgroup") or "").endswith("Deck") or entry.get("page") == 0


def _is_generic_label(display):
    return bool(re.match(r"^Entry \d+$", display or ""))


def _unique_slug(base, taken):
    slug, n = base, 2
    while slug in taken:
        slug = f"{base}_{n}"
        n += 1
    return slug


def merge_campaign(existing, extracted, has_audio=lambda entry: False):
    """Return (merged_data, report). `existing` is not modified.

    has_audio(entry) -> True if the entry's audio file exists on disk.
    report is a list of dicts: {"action", "scenario", "label", "detail"}.
    """
    data = copy.deepcopy(existing)
    report = []

    def log(action, scenario, label, detail=""):
        report.append({"action": action, "scenario": scenario, "label": label, "detail": detail})

    # --- candidates -------------------------------------------------------
    old = []   # (scenario_index, entry, shingles)
    for si, s in enumerate(data):
        for e in s["entries"]:
            if not _is_card_entry(e):
                old.append((si, e, _shingles(e["text"])))
    new = []   # (scenario_name, order_index, entry, shingles)
    for s in extracted:
        for i, e in enumerate(s["entries"]):
            new.append((s["scenario"], i, e, _shingles(e["text"])))

    pairs = []
    for oi, (_, oe, os_) in enumerate(old):
        for ni, (_, _, ne, ns) in enumerate(new):
            inter = len(os_ & ns)
            if not inter:
                continue
            cover_old, cover_new = inter / len(os_), inter / len(ns)
            if max(cover_old, cover_new) >= QUALIFY:
                pairs.append((inter, oi, ni, cover_old, cover_new))
    pairs.sort(reverse=True)

    match_old, match_new = {}, {}
    for inter, oi, ni, co, cn in pairs:
        if oi not in match_old and ni not in match_new:
            match_old[oi] = (ni, co, cn)
            match_new[ni] = oi

    # --- map extracted scenario names -> existing scenario index ----------
    # by majority of matched entries (survives scenario renames), else by name
    votes = {}
    for oi, (ni, _, _) in match_old.items():
        key = new[ni][0]
        votes.setdefault(key, {}).setdefault(old[oi][0], 0)
        votes[key][old[oi][0]] += 1
    scen_map = {}
    for s in extracted:
        name = s["scenario"]
        if name in votes:
            scen_map[name] = max(votes[name], key=votes[name].get)
        else:
            exact = [i for i, d in enumerate(data) if d["scenario"] == name]
            if exact:
                scen_map[name] = exact[0]

    # --- matched pairs: label / text / move -------------------------------
    moves = []        # (entry, from_si, to_si, ni)
    kept_text = set()  # indexes of old entries whose (longer) text was kept
    for oi, (ni, cover_old, cover_new) in match_old.items():
        si, oe, _ = old[oi]
        new_scen, _, ne, _ = new[ni]
        scen_name = data[si]["scenario"]
        label = oe.get("display_label", oe["label"])
        audio = has_audio(oe)

        # Decide the text first: a new label only fits if the text matches it
        text_action = None
        if _words(oe["text"]) != _words(ne["text"]):
            unedited = cover_old >= CONTAINED or cover_new >= CONTAINED
            text_action = "text-available" if audio else ("update-text" if unedited else "keep-edited")
        text_matches_new = text_action in (None, "update-text") or cover_old >= 0.8

        if (_is_generic_label(label) and not _is_generic_label(ne["display_label"])
                and text_matches_new):
            taken = {e["label"] for e in data[si]["entries"]} - {oe["label"]}
            oe["label"] = _unique_slug(ne["label"], taken)
            oe["display_label"] = ne["display_label"]
            if not oe.get("subgroup"):
                oe["subgroup"] = ne.get("subgroup") or _auto_subgroup(ne["display_label"])
            log("relabel", scen_name, f"{label} → {ne['display_label']}")
            label = ne["display_label"]

        if text_action == "text-available":
            kept_text.add(oi)
            log("text-available", scen_name, label,
                "new extraction differs but this entry has audio — regenerate to use it")
        elif text_action == "update-text":
            delta = len(ne["text"]) - len(oe["text"])
            oe["text"] = ne["text"]
            log("update-text", scen_name, label,
                f"{'+' if delta >= 0 else ''}{delta} chars ({'extended' if delta >= 0 else 'trimmed'})")
        elif text_action == "keep-edited":
            kept_text.add(oi)
            log("keep-edited", scen_name, label, "text differs from extraction; looks hand-edited")

        target = scen_map.get(new_scen)
        if target is not None and target != si:
            where = f"extraction puts it in {data[target]['scenario']!r}"
            movable_here = [e for e in data[si]["entries"] if not _is_card_entry(e)]
            if audio:
                log("move-skipped", scen_name, label, f"{where}, but it has audio")
            elif len(movable_here) == 1:
                log("move-skipped", scen_name, label,
                    f"{where}, but it's the only entry in its group (kept your grouping)")
            else:
                moves.append((oe, si, target, ni))

    # --- fragments now merged into a matched entry ------------------------
    fragments = []
    for oi, (si, oe, os_) in enumerate(old):
        if oi in match_old:
            continue
        best = max(((len(os_ & new[ni][3]) / len(os_), ni) for ni in match_new), default=(0, None))
        label = oe.get("display_label", oe["label"])
        if best[0] >= CONTAINED:
            host = new[best[1]][2]["display_label"]
            if has_audio(oe):
                log("fragment-kept", data[si]["scenario"], label, f"now part of {host!r}, but has audio")
            else:
                fragments.append((si, oe))
                log("remove-fragment", data[si]["scenario"], label, f"now part of {host!r}")
        else:
            log("unmatched", data[si]["scenario"], label,
                "not in new extraction — rules text, or added by hand? (left as is)")

    # --- new passages ------------------------------------------------------
    additions = []   # (entry, to_si, ni)
    for ni, (scen, _, ne, ns) in enumerate(new):
        if ni in match_new:
            continue
        # Part of an existing entry that keeps its longer text? Then skip.
        covering = [oi for oi in kept_text if len(ns & old[oi][2]) / len(ns) >= CONTAINED]
        if covering:
            log("add-skipped", scen, ne["display_label"],
                f"already inside {old[covering[0]][1].get('display_label')!r}")
            continue
        target = scen_map.get(scen)
        if target is None:
            log("add-skipped", scen, ne["display_label"], "no matching scenario in this campaign")
            continue
        additions.append((dict(ne), target, ni))

    # --- apply structural changes -----------------------------------------
    def remove(entries, entry):
        del entries[next(i for i, x in enumerate(entries) if x is entry)]

    for si, oe in fragments:
        remove(data[si]["entries"], oe)
    for oe, from_si, to_si, ni in moves:
        remove(data[from_si]["entries"], oe)
        log("move", data[from_si]["scenario"], oe.get("display_label", oe["label"]),
            f"→ {data[to_si]['scenario']!r}")
    placed = {match_new_ni: old[oi][1] for match_new_ni, oi in match_new.items()}

    def index_of(entries, entry):
        return next((i for i, x in enumerate(entries) if x is entry), None)

    def insert(entry, to_si, ni):
        """Insert after the entry that precedes it in extraction order."""
        entries = data[to_si]["entries"]
        scen, order = new[ni][0], new[ni][1]
        anchor = None
        for nj, (s2, o2, _, _) in enumerate(new):
            if (s2 == scen and o2 < order and nj in placed
                    and index_of(entries, placed[nj]) is not None):
                if anchor is None or o2 > new[anchor][1]:
                    anchor = nj
        pos = index_of(entries, placed[anchor]) + 1 if anchor is not None else 0
        entries.insert(pos, entry)
        placed[ni] = entry

    for oe, from_si, to_si, ni in moves:
        oe["label"] = _unique_slug(oe["label"], {e["label"] for e in data[to_si]["entries"]})
        insert(oe, to_si, ni)
    for ne, to_si, ni in additions:
        taken = {e["label"] for e in data[to_si]["entries"]}
        ne["label"] = _unique_slug(ne["label"], taken)
        insert(ne, to_si, ni)
        log("add", data[to_si]["scenario"], ne["display_label"], f"{len(ne['text'])} chars")

    return data, report


ACTION_TITLES = [
    ("relabel", "Labels upgraded"),
    ("update-text", "Text updated (rules text trimmed / continuation added)"),
    ("move", "Moved to the correct scenario"),
    ("add", "New passages added"),
    ("remove-fragment", "Old fragments removed (now part of a larger entry)"),
    ("keep-edited", "Kept — looks hand-edited"),
    ("text-available", "Kept — has audio; newer text available"),
    ("move-skipped", "Not moved"),
    ("fragment-kept", "Fragment kept — has audio"),
    ("add-skipped", "Not added"),
    ("unmatched", "Not in new extraction (review; left as is)"),
]


def format_report(report):
    lines = []
    for action, title in ACTION_TITLES:
        items = [r for r in report if r["action"] == action]
        if not items:
            continue
        lines.append(f"\n{title} ({len(items)}):")
        for r in items:
            detail = f"  — {r['detail']}" if r["detail"] else ""
            lines.append(f"  [{r['scenario']}] {r['label']}{detail}")
    return "\n".join(lines) if lines else "Nothing to change."
