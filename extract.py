"""
PDF extraction module for Arkham Horror LCG campaign guides.

Identifies read-aloud sections (italic narrative text at body font size)
and organizes them by scenario and entry.
"""

import re
import pdfplumber

MIN_BODY_FONT_SIZE = 7.0
MIN_BLOCK_LENGTH = 100


def _char_style(char):
    font = char.get("fontname", "").lower()
    size = char.get("size", 0)

    if size < MIN_BODY_FONT_SIZE:
        return "skip"
    if "bolton" in font or "bodoni" in font:
        return "skip"
    if "teutonic" in font:
        if size >= 16:
            return "header"
        return "sub_header"
    if "bolditalic" in font:
        return "bold_italic"
    if "italic" in font or "oblique" in font:
        return "italic"
    if "bold" in font:
        return "bold"
    return "regular"


def _is_narrative(style):
    return style in ("italic", "bold_italic")


def _looks_like_encounter_list(text):
    """Detect encounter set name lists (comma-separated Title Case items)."""
    clean = text.strip().rstrip(".")
    if "," not in clean:
        return False
    parts = [p.strip() for p in re.split(r",\s*(?:and\s+)?", clean) if p.strip()]
    if len(parts) < 3:
        return False
    titled = sum(1 for p in parts if p and p[0].isupper() and len(p.split()) <= 5)
    return titled / len(parts) > 0.7


def _looks_like_non_narrative(text):
    """Detect text that looks italic but is not read-aloud narrative."""
    stripped = text.strip()
    indicators = [
        r"^The investigators (were not|did not)",
        r"^The Campaign Log",
        r"^Naomi does not have",
        r"^No Brood of",
        r"^None of these events happened",
        r"^Strategy Tip:",
        r"^Note:",
        r"^\.\s*\(",
        r"^\(Add that card",
        r"^\(Record this",
        r"^see next page",
        r"^Note: During this scenario",
        r"^for more information",
        r"^.There are horrors beyond",
    ]
    for pattern in indicators:
        if re.search(pattern, stripped, re.IGNORECASE):
            return True
    return False


def _strip_encounter_prefix(text):
    """Strip leading encounter set names from text that continues into narrative."""
    m = re.match(
        r"^((?:[A-Z][A-Za-z‐-―\s']+,\s*(?:and\s+)?){2,}[A-Z][A-Za-z‐-―\s']+?)\s*"
        r"([A-Z][a-z])",
        text,
    )
    if m and len(m.group(1)) < len(text) * 0.5:
        return text[m.start(2):]
    return text


def _prescan_scenarios(pdf):
    """Build a mapping of page_number → scenario name from Teutonic headers."""
    page_scenarios = {}

    stop = r"(?:Setup|Standalone|DO NOT|Design|Moving|Location|Credits|Quick|Encounter|Campaign|Keywords|Expanded|The End)"

    for page_num, page in enumerate(pdf.pages, start=1):
        header_chars = [
            c for c in page.chars
            if "teutonic" in c.get("fontname", "").lower() and c.get("size", 0) >= 16
        ]
        if not header_chars:
            continue

        full_text = "".join(c["text"] for c in header_chars)

        patterns = [
            r"(Scenario\s+[IVXLC\d]+[A-Za-z‐-―]*\s*[::–—]\s*(?:(?!" + stop + r").)+)",
            r"(Part\s+[IVXLC\d]+\s*[::–—]\s*(?:(?!" + stop + r").)+)",
            r"(Interlude\s+[IVXLC\d]+\s*[::–—]\s*(?:(?!" + stop + r").)+)",
            r"(Interlude[::]\s*(?:(?!" + stop + r").)+)",
            r"(Codex[::]\s*(?:(?!" + stop + r").)+)",
            r"(Prologue)",
            r"(Epilogue)",
            r"(Design Notes)",
        ]

        for pattern in patterns:
            m = re.search(pattern, full_text)
            if m:
                name = re.sub(r"\s+", " ", m.group(1)).strip()
                page_scenarios[page_num] = name
                break

    return page_scenarios


def _extract_page_blocks(page):
    """Extract text blocks from a page in native PDF order (no reordering)."""
    chars = [c for c in page.chars if _char_style(c) not in ("skip", "header")]
    if not chars:
        return []

    # Build style runs
    raw_runs = []
    current_chars = []
    current_style = _char_style(chars[0])

    def flush_run():
        if not current_chars:
            return
        text = "".join(c["text"] for c in current_chars)
        raw_runs.append({
            "text": text,
            "style": current_style,
            "is_narrative": _is_narrative(current_style),
        })

    for char in chars:
        style = _char_style(char)
        if style != current_style:
            flush_run()
            current_chars = [char]
            current_style = style
        else:
            current_chars.append(char)

    flush_run()

    # Merge runs into blocks, absorbing short non-narrative gaps between narrative runs
    blocks = []
    i = 0
    while i < len(raw_runs):
        run = raw_runs[i]

        if run["is_narrative"]:
            parts = [run["text"]]
            j = i + 1
            while j < len(raw_runs):
                next_run = raw_runs[j]
                if next_run["is_narrative"]:
                    parts.append(next_run["text"])
                    j += 1
                elif next_run["style"] == "regular" and len(next_run["text"].strip()) < 30:
                    # Look ahead past consecutive short regular gaps (inline title references)
                    k = j
                    gap_parts = []
                    while k < len(raw_runs) and not raw_runs[k]["is_narrative"] \
                            and raw_runs[k]["style"] == "regular" \
                            and len(raw_runs[k]["text"].strip()) < 30:
                        gap_parts.append(raw_runs[k]["text"])
                        k += 1
                    if k < len(raw_runs) and raw_runs[k]["is_narrative"]:
                        parts.extend(gap_parts)
                        j = k
                    else:
                        break
                else:
                    break

            text = "".join(parts)
            text = re.sub(r"\s+", " ", text).strip()

            if text and not _looks_like_encounter_list(text) and not _looks_like_non_narrative(text):
                text = _strip_encounter_prefix(text)
                if len(text) >= MIN_BLOCK_LENGTH:
                    blocks.append({"text": text, "type": "narrative"})

            i = j
            continue

        if run["style"] in ("bold", "sub_header"):
            text = re.sub(r"\s+", " ", run["text"]).strip()
            if text:
                blocks.append({"text": text, "type": "bold"})
            i += 1
            continue

        # Regular text — just record it as a separator
        blocks.append({"text": "", "type": "regular"})
        i += 1

    return blocks


def _detect_entry_label(text):
    """Check if bold text contains an entry label.

    Uses the LAST match in the text, since labels appear at the end of
    bold blocks while references to other labels appear earlier.
    Only matches labels followed by a colon to distinguish from references.
    """
    text_norm = text.replace("’", "’").replace("’", "’").replace("Φ", "Phi")
    patterns = [
        r"(Resolution\s+\d+)",
        r"(Investigator Defeat)",
        r"(If no resolution was reached[^:.]*)",
        r"(Armitage.?s\s+Fate\s+\d+)",
        r"(Part\s+\d+)",
        r"(Intro\s+\d+)",
        r"(Codex\s+[\dPhi\w]+\s*:.+?)(?:\s*$|\s*Codex)",
        r"(Epilogue\s+\d+)",
    ]

    # Prefer patterns followed by colon (actual labels vs. references)
    for pattern in patterns:
        last_colon = None
        for m in re.finditer(pattern + r"\s*:", text_norm, re.IGNORECASE):
            last_colon = m.group(1).strip()
        if last_colon:
            return last_colon

    # Fallback: first match without colon requirement
    for pattern in patterns:
        m = re.search(pattern, text_norm, re.IGNORECASE)
        if m:
            return m.group(1).strip()

    # Generic fallback: any bold text ending with ":" is a label
    # Match text like "Reality's Shadow 1:" or "Sebastien's Information:"
    m = re.search(r"^(.+?)\s*:\s*$", text_norm.strip())
    if m:
        label = m.group(1).strip()
        skip = ("proceed", "check", "otherwise", "setup", "each ", "if ", "in your",
                "remove", "add ", "shuffle", "gather", "put ", "set ", "based on",
                "record", "the story", "you are now")
        if not any(label.lower().startswith(s) for s in skip) and len(label) < 50:
            return label

    return None


def _sanitize_filename(name):
    name = re.sub(r"[^\w\s\-]", "", name)
    name = re.sub(r"\s+", "_", name.strip())
    return name.lower()[:60]


def extract_sections(pdf_path):
    """Extract read-aloud sections from an Arkham Horror campaign guide PDF."""
    with pdfplumber.open(pdf_path) as pdf:
        page_scenarios = _prescan_scenarios(pdf)

        current_scenario = "Ungrouped"
        last_main_scenario = "Ungrouped"
        pending_label = None
        pending_parts = []
        pending_page = None
        entries = []

        def flush():
            nonlocal pending_parts, pending_label, pending_page
            if not pending_parts:
                return
            text = " ".join(pending_parts)
            text = re.sub(r"\s+", " ", text).strip()
            text = re.sub(r"^[:\s]+", "", text)
            min_len = 40 if pending_label else MIN_BLOCK_LENGTH
            if len(text) >= min_len:
                entries.append({
                    "scenario": current_scenario,
                    "label": pending_label,
                    "text": text,
                    "page": pending_page,
                })
            pending_parts = []
            pending_label = None
            pending_page = None

        last_page = max(page_scenarios.keys()) + 1 if page_scenarios else len(pdf.pages)

        has_page1_narrative = False
        if pdf.pages:
            p1_blocks = _extract_page_blocks(pdf.pages[0])
            has_page1_narrative = any(b["type"] == "narrative" for b in p1_blocks)

        for page_num, page in enumerate(pdf.pages, start=1):
            if page_num == 1 and not has_page1_narrative:
                continue
            if page_num > last_page:
                continue

            if page_num in page_scenarios:
                flush()
                pending_label = None
                new_scenario = page_scenarios[page_num]
                if new_scenario == "Design Notes":
                    pass
                else:
                    current_scenario = new_scenario
                    if not new_scenario.startswith("Codex"):
                        last_main_scenario = new_scenario

            blocks = _extract_page_blocks(page)

            for block in blocks:
                if block["type"] == "bold":
                    label = _detect_entry_label(block["text"])
                    # Resolution/no-resolution on a Codex page belongs to the parent scenario
                    if label and current_scenario.startswith("Codex"):
                        is_resolution = any(k in label.lower() for k in ["resolution", "no resolution", "investigator defeat"])
                        if is_resolution:
                            flush()
                            current_scenario = last_main_scenario
                    if label:
                        flush()
                        pending_label = label

                elif block["type"] == "narrative":
                    if pending_page is None:
                        pending_page = page_num
                    pending_parts.append(block["text"])

                elif block["type"] == "regular":
                    flush()

        flush()

    # Move "Ungrouped" entries to the first real scenario
    first_scenario = None
    for entry in entries:
        if entry["scenario"] != "Ungrouped":
            first_scenario = entry["scenario"]
            break
    if first_scenario:
        for entry in entries:
            if entry["scenario"] == "Ungrouped":
                entry["scenario"] = first_scenario

    # Group entries by scenario
    scenarios = {}
    counters = {}

    for entry in entries:
        scen = entry["scenario"]
        if scen not in scenarios:
            scenarios[scen] = {
                "scenario": scen,
                "scenario_folder": _sanitize_filename(scen),
                "entries": [],
            }
            counters[scen] = 0

        counters[scen] += 1
        display = entry["label"] or f"Entry {counters[scen]}"
        slug = _sanitize_filename(display) or f"entry_{counters[scen]:03d}"

        scenarios[scen]["entries"].append({
            "label": slug,
            "display_label": display,
            "text": entry["text"],
            "page": entry["page"],
            "subgroup": _auto_subgroup(display),
        })

    # Sort entries within each scenario into logical reading order
    for scen_data in scenarios.values():
        scen_data["entries"].sort(key=_entry_sort_key)

    return list(scenarios.values())


def _auto_subgroup(label):
    """Assign a subgroup based on the entry label."""
    l = label.lower()
    if any(k in l for k in ["resolution", "no resolution", "investigator defeat"]):
        return "Resolutions"
    if re.match(r"intro\s+\d+", l):
        return "Intros"
    if re.match(r"part\s+\d+", l):
        return "Parts"
    if re.match(r"codex\s+[\d\w]", l):
        return "Codex Entries"
    if "armitage" in l and "fate" in l:
        return "Armitage's Fate"
    return None


def _entry_sort_key(entry):
    """Sort key for ordering entries within a scenario.

    Order: intro entries (by page), then special labels in gameplay order.
    """
    label = entry["display_label"]
    page = entry["page"]

    m = re.match(r"Entry\s+(\d+)", label)
    if m:
        return (0, page, int(m.group(1)))

    m = re.match(r"Part\s+(\d+)", label)
    if m:
        return (1, 0, int(m.group(1)))

    m = re.match(r"Armitage.{0,3}s\s+Fate\s+(\d+)", label)
    if m:
        return (1, 0, int(m.group(1)))

    if "no resolution" in label.lower():
        return (2, 0, 0)

    if "investigator defeat" in label.lower():
        return (2, 0, 1)

    m = re.match(r"Resolution\s+(\d+)", label)
    if m:
        return (3, 0, int(m.group(1)))

    return (4, page, 0)
