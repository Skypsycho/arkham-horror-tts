"""
PDF extraction module for Arkham Horror LCG campaign guides.

Identifies read-aloud sections (italic narrative text at body font size)
and organizes them by scenario and entry.
"""

import re
import pdfplumber

MIN_BODY_FONT_SIZE = 7.0
MIN_BLOCK_LENGTH = 100
# Vertical gap (pt) between two text runs above which they are treated as
# separate paragraphs/columns rather than one flowing block. Body text is
# ~9pt on an ~11pt line pitch, so consecutive lines are ~2pt apart.
MAX_LINE_GAP = 8
# A run that starts on the same line as the previous run ended can have a
# top above that run's last bottom by up to about one line height.
MAX_SAME_LINE_OVERLAP = 14
# Vertical jump (pt) within one style run that means the text moved to
# another column/frame rather than the next line or paragraph.
COLUMN_JUMP = 30
# Handwritten notes (journal dates, notes scrawled in a book) are set off
# from the surrounding narrative by about a blank line.
MAX_JOURNAL_GAP = 16
# Short italic text right after its own label ("Dream 13: …") is still a passage
MIN_LABELED_BLOCK_LENGTH = 40


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
    # Handwriting font used for journal date lines (Forgotten Age) — read aloud
    if "calligraphic" in font and size < 11:
        return "journal"
    # Handwriting at body size: notes scrawled in a book or on a wall
    # (Path to Carcosa). Larger sizes are Campaign Log decorations.
    if "wolgast" in font and 8 <= size < 11:
        return "journal"
    if "bolditalic" in font:
        return "bold_italic"
    if "italic" in font or "oblique" in font:
        return "italic"
    if "bold" in font:
        return "bold"
    return "regular"


def _is_narrative(style):
    return style in ("italic", "bold_italic", "journal")


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
        r"^For example:",
        r"^Example:",
        r"^\(remember to",
        r"^\(Note:",
        r"^The investigators \w+",                  # Campaign Log statements
        r"^.{0,80}\bNote:",                         # setup notes after card subtitles
        r"^.{0,120}\bis (?:not )?listed under\b",   # Campaign Log conditions
        r"^\([^)]*#\d+\)",                          # card references "(Set #59)"
    ]
    for pattern in indicators:
        if re.search(pattern, stripped, re.IGNORECASE):
            return True
    return False


def _cut_trailing_rules_text(text):
    """Drop game/rules text that shares an italic text box with narrative.

    Narrative is kept up to the boilerplate; everything from it onward goes.
    """
    # "The Forgotten Age is a campaign for Arkham Horror: The Card Game…" —
    # cut at the start of that sentence
    m = re.search(r"is a campaign for Arkham Horror", text)
    if m:
        prefix = text[:m.start()]
        cut = max(prefix.rfind(c) for c in ".!?”…") + 1
        text = text[:cut]
    m = re.search(r"Check Campaign Log|Congratulations on completing", text)
    if m:
        text = text[:m.start()]
    return text.strip()


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
    """Build a mapping of page_number → [(scenario name, (x0, top)), …] from
    Teutonic headers, in reading order (a page can hold two, e.g. the end of
    the Epilogue and the start of a secret scenario). The positions let
    content that precedes a header stay with the scenario before it.
    """
    page_headers = {}

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

        found = []  # (start, end, name)
        for pattern in patterns:
            for m in re.finditer(pattern, full_text):
                if any(m.start(1) < e and s < m.end(1) for s, e, _ in found):
                    continue  # overlaps a header already found
                name = re.sub(r"\s+", " ", m.group(1)).strip()
                found.append((m.start(1), m.end(1), name))

        headers = []
        for start, _, name in found:
            first = header_chars[start]
            headers.append((name, (first["x0"], first["top"])))
        mid = page.width / 2
        headers.sort(key=lambda h: (0 if h[1][0] < mid - 20 else 1, h[1][1]))
        if headers:
            page_headers[page_num] = headers

    return page_headers


def _precedes_header(block, header_pos, page_width):
    """True if a block sits before the page's scenario header in reading
    order: in an earlier column, or above the header in the same column."""
    if block.get("x0") is None:
        return False
    hx, htop = header_pos
    mid = page_width / 2
    block_col = 0 if block["x0"] < mid - 20 else 1
    header_col = 0 if hx < mid - 20 else 1
    if block_col != header_col:
        return block_col < header_col
    return block["top"] < htop - 2


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
        if current_style == "journal":
            text = text.replace("*", "")  # "*Carcosa is real" — a scribble mark
        raw_runs.append({
            "text": text,
            "style": current_style,
            "is_narrative": _is_narrative(current_style),
            "top": current_chars[0]["top"],
            "bottom": current_chars[-1]["bottom"],
            "x0": current_chars[0]["x0"],
        })

    def jumps(prev_char, char):
        """A text frame can flow from one column into another (or back up the
        page) without a style change; split runs there."""
        return (char["top"] < prev_char["top"] - COLUMN_JUMP
                or char["top"] - prev_char["bottom"] > COLUMN_JUMP)

    def spatially_continues(prev, nxt):
        """True if `nxt` plausibly continues `prev` in the same paragraph.

        Runs adjacent in the PDF stream can be far apart on the page (a card
        subtitle at the bottom of one column followed by narrative at the top
        of the next). Within a paragraph the next run starts on the same line
        or the line directly below.
        """
        gap = nxt["top"] - prev["bottom"]
        limit = MAX_JOURNAL_GAP if "journal" in (prev["style"], nxt["style"]) else MAX_LINE_GAP
        return -MAX_SAME_LINE_OVERLAP <= gap <= limit

    def is_condition(k):
        """Campaign Log condition set in italic, e.g. "If the investigators
        found the missing relic, proceed to Intro 4" — the italic part ends
        where regular text picks up with "," or ":". Not narrative."""
        if not raw_runs[k]["text"].lstrip().startswith("If "):
            return False
        length = 0
        while k < len(raw_runs):
            r = raw_runs[k]
            t = r["text"].strip()
            if not r["is_narrative"]:
                if r["style"] != "regular":
                    return False
                if t[:1] in (",", ":"):
                    return length < 160
                if len(t) >= 30:
                    return False
            length += len(t)
            k += 1
        return False

    def continues_sentence(k):
        """Run k (narrative) carries on the sentence before it: starts with
        punctuation or lowercase, e.g. the ',” you say.' after a bold 'Dream 1'."""
        t = raw_runs[k]["text"]
        return bool(re.match(r"^[\s,.;:!?’”\"…—–-]*[a-z,.;:!?’”\"…]", t))

    for char in chars:
        style = _char_style(char)
        if style != current_style or (current_chars and jumps(current_chars[-1], char)):
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
            last_narr = run
            j = i + 1
            while j < len(raw_runs):
                next_run = raw_runs[j]
                if next_run["is_narrative"]:
                    if not spatially_continues(last_narr, next_run):
                        break
                    if next_run["top"] > last_narr["bottom"] - 3 and is_condition(j):
                        break
                    # Next run starts on a new line (e.g. a journal date line)
                    if next_run["top"] > last_narr["bottom"] - 3 \
                            and not parts[-1][-1:].isspace() and not next_run["text"][:1].isspace():
                        parts.append(" ")
                    parts.append(next_run["text"])
                    last_narr = next_run
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
                    # A card subtitle in italics after rules text ("Remove
                    # Relic of Ages (Forestalling the Future)") isn't narrative
                    if (k < len(raw_runs) and raw_runs[k]["is_narrative"]
                            and spatially_continues(last_narr, raw_runs[k])
                            and not raw_runs[k]["text"].lstrip().startswith("(")):
                        parts.extend(gap_parts)
                        j = k
                    else:
                        break
                elif (next_run["style"] == "bold" and len(next_run["text"].strip()) < 30
                        and not next_run["text"].rstrip().endswith(":")
                        and j + 1 < len(raw_runs) and raw_runs[j + 1]["is_narrative"]
                        and spatially_continues(last_narr, raw_runs[j + 1])
                        and continues_sentence(j + 1)):
                    # A bold reference inside a sentence: '“…this isn’t Dream 1,” you say.'
                    parts.append(next_run["text"])
                    j += 1
                else:
                    break

            text = "".join(parts)
            text = re.sub(r"\s+", " ", text).strip()
            text = _cut_trailing_rules_text(text)
            # The same italic run can carry on into a condition: "…natural
            # light.If the investigators found the missing relic, proceed to…"
            if (j < len(raw_runs) and raw_runs[j]["style"] == "regular"
                    and raw_runs[j]["text"].lstrip()[:1] in (",", ":")):
                text = re.sub(r"(?<=[.!?”…])\s*If [^.!?”]{3,120}$", "", text)
            condition = is_condition(i) or bool(
                re.match(r"^If\b", text) and text.endswith(":") and len(text) < 160)
            # A note inside a label, e.g. "Resolution 2 (each defeated
            # investigator should resolve Investigator Defeat first):"
            aside = bool(re.fullmatch(r"\([^()]*\)", text))

            if (text and not condition and not aside and not _looks_like_encounter_list(text)
                    and not _looks_like_non_narrative(text)):
                text = _strip_encounter_prefix(text)
                if len(text) >= MIN_LABELED_BLOCK_LENGTH:
                    # Short blocks only count right after their own label
                    blocks.append({"text": text, "type": "narrative",
                                   "x0": run["x0"], "top": run["top"],
                                   "bottom": last_narr["bottom"],
                                   "short": len(text) < MIN_BLOCK_LENGTH})

            i = j
            continue

        if run["style"] in ("bold", "sub_header"):
            text = re.sub(r"\s+", " ", run["text"]).strip()
            if text:
                blocks.append({"text": text, "type": "bold",
                               "x0": run["x0"], "top": run["top"],
                               "sub_header": run["style"] == "sub_header"})
            i += 1
            continue

        # Regular text — a separator; keep the text so callers can spot
        # instructions like "continue reading"
        blocks.append({"text": run["text"], "type": "regular",
                       "x0": run["x0"], "top": run["top"]})
        i += 1

    return blocks


def _detect_entry_label(text):
    """Check if bold text contains an entry label.

    Uses the LAST match in the text, since labels appear at the end of
    bold blocks while references to other labels appear earlier.
    Only matches labels followed by a colon to distinguish from references.
    """
    text_norm = text.replace("’", "’").replace("’", "’").replace("Φ", "Phi")

    # Conditional character sections, e.g. Dunwich's
    # 'If Dr. Francis Morgan is not listed under "Sacrificed to Yog-Sothoth:"'
    m = re.match(r"^If (.{3,40}?) is (?:not )?listed under\b", text_norm.strip())
    if m:
        return m.group(1).strip()

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
        # A reference glued to the label: "Dream 8.Dream 11:" → "Dream 11"
        glued = re.match(r"^.*\b\w+ \d+[.!]\s*(\S.*)$", label)
        if glued:
            label = glued.group(1).strip()
        # Table rows like "4 investigators:" (supply points) aren't sections
        if re.match(r"^\d", label):
            return None
        skip = ("proceed", "check", "otherwise", "setup", "each ", "if ", "in your",
                "remove", "add ", "shuffle", "gather", "put ", "set ", "based on",
                "record", "the story", "you are now",
                # difficulty levels / setup notes, not story section names
                "easy", "standard", "hard", "expert", "note", "standalone")
        if (not any(label.lower().startswith(s) for s in skip) and len(label) < 50
                and re.search(r"[A-Za-z]{2}", label)):
            return label

    return None


def _merge_column_continuations(entries, column_tops):
    """Join an unlabeled passage that opens a column to the passage that
    closes the column before it (same page's left column, or the previous
    page's right column): one passage flowing on, a new paragraph rather than
    a new passage (Phantom of Truth's Intro 1). The PDF can list the second
    column first, so this runs after everything is read."""
    def first_in_column(pos):
        tops = column_tops.get(pos[:2])
        return bool(tops) and pos[2] <= min(tops) + 1

    def last_in_column(pos):
        tops = column_tops.get(pos[:2])
        return bool(tops) and pos[2] >= max(tops) - 1

    for cont in list(entries):
        pos = cont.get("pos")
        if cont["label"] is not None or not pos or not first_in_column(pos):
            continue
        page, col = pos[0], pos[1]
        before = (page, 0) if col == 1 else (page - 1, 1)
        for head in entries:
            end = head.get("end")
            if (head is not cont and head["scenario"] == cont["scenario"] and end
                    and end[:2] == before and last_in_column(end)):
                head["text"] = f"{head['text']} {cont['text']}"
                head["end"] = cont.get("end")
                entries.remove(cont)
                break


def _ends_sentence(text):
    return bool(re.search(r"[.!?…”\"’)\]—–-]\s*$", text))


def _sanitize_filename(name):
    name = re.sub(r"[^\w\s\-]", "", name)
    name = re.sub(r"\s+", "_", name.strip())
    return name.lower()[:60]


def extract_sections(pdf_path):
    """Extract read-aloud sections from an Arkham Horror campaign guide PDF."""
    with pdfplumber.open(pdf_path) as pdf:
        page_headers = _prescan_scenarios(pdf)

        current_scenario = "Ungrouped"
        last_main_scenario = "Ungrouped"
        pending_label = None
        pending_parts = []
        pending_page = None
        entries = []
        # Label of the last labeled entry, kept while game text says to
        # "continue reading" so the second half of e.g. a Codex entry keeps it
        continue_label = None
        last_flushed_label = None
        # Label of the section being read, kept across its game text so a
        # conditional passage inside it ("If there are four or more tally
        # marks…: <narrative>") can be named after it
        section_label = None
        # Reading position (page, column, top) of the pending entry's first
        # block or label, of its last narrative block, and the bottom of the
        # last narrative block added
        pending_pos = None
        pending_end = None
        last_narr_block = None
        # (page, column) → tops of every block there, to spot passages that
        # carry on from the bottom of one column to the top of the next
        column_tops = {}

        def flush():
            nonlocal pending_parts, pending_label, pending_page, last_flushed_label, pending_pos, pending_end
            if not pending_parts:
                pending_pos = None
                pending_end = None
                return
            text = " ".join(pending_parts)
            text = re.sub(r"\s+", " ", text).strip()
            text = re.sub(r"^[:\s]+", "", text)
            min_len = MIN_LABELED_BLOCK_LENGTH if pending_label else MIN_BLOCK_LENGTH
            if len(text) >= min_len:
                entries.append({
                    "scenario": current_scenario,
                    "label": pending_label,
                    "text": text,
                    "page": pending_page,
                    "pos": pending_pos,
                    "end": pending_end,
                })
                last_flushed_label = pending_label
            pending_parts = []
            pending_label = None
            pending_page = None
            pending_pos = None
            pending_end = None

        def reading_pos(page_num, page, block):
            if block.get("x0") is None:
                return (page_num, 0, 0)
            return (page_num, 0 if block["x0"] < page.width / 2 - 20 else 1, block["top"])

        def append_to_unfinished_entry(text):
            """Attach a block that starts mid-sentence (e.g. at the top of a
            page) to the latest entry in this scenario that ends mid-sentence."""
            for entry in reversed(entries[-15:]):
                if entry["scenario"] != current_scenario:
                    break
                if not _ends_sentence(entry["text"]):
                    entry["text"] = f"{entry['text']} {text}"
                    return True
            return False

        last_page = max(page_headers.keys()) + 1 if page_headers else len(pdf.pages)

        has_page1_narrative = False
        if pdf.pages:
            p1_blocks = _extract_page_blocks(pdf.pages[0])
            has_page1_narrative = any(b["type"] == "narrative" for b in p1_blocks)

        for page_num, page in enumerate(pdf.pages, start=1):
            if page_num == 1 and not has_page1_narrative:
                continue
            if page_num > last_page:
                continue

            # When a header starts partway through a page (right column, or
            # mid-column), blocks before it still belong to the old scenario;
            # with two headers, blocks between them belong to the first.
            prev_scenario = current_scenario
            prev_main_scenario = last_main_scenario
            headers = []
            if page_num in page_headers:
                flush()
                pending_label = None
                continue_label = None
                last_flushed_label = None
                section_label = None
                headers = [h for h in page_headers[page_num] if h[0] != "Design Notes"]
                for name, _ in headers:
                    if not name.startswith("Codex"):
                        last_main_scenario = name
                if headers:
                    current_scenario = headers[-1][0]
            page_scenario = current_scenario

            blocks = _extract_page_blocks(page)
            prev_block = None

            for block in blocks:
                if headers:
                    target = prev_scenario
                    for name, pos in headers:
                        if _precedes_header(block, pos, page.width):
                            break
                        target = name
                    if target != current_scenario:
                        flush()
                        pending_label = None
                        continue_label = None
                        last_flushed_label = None
                        section_label = None
                        current_scenario = target

                if block["type"] == "narrative" and block.get("short") \
                        and (pending_parts or pending_label is None):
                    continue  # too short to be a passage unless it follows its label

                if block.get("x0") is not None:
                    col_key = reading_pos(page_num, page, block)[:2]
                    column_tops.setdefault(col_key, []).append(block["top"])

                if block["type"] == "bold":
                    label = _detect_entry_label(block["text"])
                    # "…Go to Resolution 2." names another section; it isn't a label
                    if (label and not block["text"].rstrip().endswith(":")
                            and prev_block is not None and prev_block["type"] == "regular"
                            and re.search(r"(?:\b(?:go|proceed|skip|continue|move|return|refer|turn)\s+to|\bread)\s*$",
                                          prev_block["text"], re.IGNORECASE)):
                        label = None
                    # Resolution/no-resolution on a Codex page belongs to the parent scenario
                    if label and current_scenario.startswith("Codex"):
                        is_resolution = any(k in label.lower() for k in ["resolution", "no resolution", "investigator defeat"])
                        if is_resolution:
                            flush()
                            before_header = headers and _precedes_header(block, headers[0][1], page.width)
                            current_scenario = prev_main_scenario if before_header else last_main_scenario
                            headers = []  # explicit reassignment wins
                    if label:
                        flush()
                        pending_label = label
                        section_label = label
                        pending_pos = reading_pos(page_num, page, block)
                        continue_label = None
                    elif block.get("sub_header"):
                        section_label = None

                elif block["type"] == "narrative":
                    text = block["text"]
                    # A frame that jumped back up the page mid-sentence into a
                    # capitalized passage: the two are separate passages
                    if (pending_parts and last_narr_block is not None
                            and last_narr_block[0] == page_num
                            and block.get("top") is not None
                            and block["top"] < last_narr_block[1] - COLUMN_JUMP
                            and not _ends_sentence(pending_parts[-1])
                            and re.match(r"^[A-Z“\"]", text)):
                        flush()
                    if not pending_parts and pending_label is None:
                        # Mid-sentence start: continuation across a page/column break
                        if re.match(r"^[a-z]", text) and append_to_unfinished_entry(text):
                            continue
                        if continue_label:
                            pending_label = f"{continue_label} (cont.)"
                            continue_label = None
                        elif section_label and prev_block is not None and prev_block["type"] == "regular":
                            # "If there are four or more tally marks under “Yig’s Fury”: <narrative>"
                            m = re.search(r"\bIf ([^.:]{5,80}?)\s*:\s*$", prev_block["text"])
                            if m:
                                pending_label = f"{section_label} (if {m.group(1).strip()})"
                    if pending_page is None:
                        pending_page = page_num
                    if pending_pos is None:
                        pending_pos = reading_pos(page_num, page, block)
                    pending_end = reading_pos(page_num, page, block)
                    pending_parts.append(text)
                    last_narr_block = (page_num, block.get("bottom") or block.get("top") or 0)

                elif block["type"] == "regular":
                    flush()
                    if re.search(r"continue reading", block["text"], re.IGNORECASE):
                        base = last_flushed_label or continue_label
                        if base:
                            continue_label = re.sub(r" \(cont\.\)$", "", base)

                prev_block = block

            # Following pages belong to the scenario whose (last) header was on this page
            if headers and current_scenario != page_scenario:
                flush()
                pending_label = None
                continue_label = None
                last_flushed_label = None
                section_label = None
                current_scenario = page_scenario

        flush()

    _merge_column_continuations(entries, column_tops)

    # Narrative before the first scenario header is the campaign's own intro
    for entry in entries:
        if entry["scenario"] == "Ungrouped" and entry["label"] is None:
            entry["label"] = "Campaign Intro"
            break

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

    # A scenario that opens with unlabeled narrative is almost always its
    # introduction (FFG often omits an "Intro:" label when there's only one).
    # "First" means first in reading position, not PDF stream order.
    by_scenario = {}
    for entry in entries:
        if entry["label"] != "Campaign Intro":
            by_scenario.setdefault(entry["scenario"], []).append(entry)
    for scen, scen_entries in by_scenario.items():
        if scen.startswith("Codex"):
            continue
        first = min(scen_entries, key=lambda e: e.get("pos") or (e["page"] or 0, 0, 0))
        if first["label"] is None:
            if scen in ("Prologue", "Epilogue"):
                first["label"] = scen
            elif not any(e["label"] == "Intro" for e in scen_entries):
                first["label"] = "Intro"

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

    if label == "Campaign Intro":
        return (0, -2, 0)

    if label in ("Intro", "Prologue", "Epilogue"):
        return (0, -1, 0)

    m = re.match(r"Intro\s+(\d+)", label)
    if m:
        return (0, -1, int(m.group(1)))

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
