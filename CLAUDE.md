# Arkham Horror TTS - Campaign Guide Audio Generator

## What This Project Does
A web app that extracts read-aloud narrative text from Arkham Horror LCG campaign guide PDFs and converts them to speech audio files using ElevenLabs TTS API. Includes a library to organize, browse, and play the generated audio, plus ArkhamDB integration for importing agenda/act card text.

## Tech Stack
- **Backend**: Python 3 + Flask (`app.py`)
- **Frontend**: Single-page HTML/CSS/JS (`templates/index.html`)
- **PDF Extraction**: pdfplumber (`extract.py`)
- **TTS**: ElevenLabs API (`generate.py`)
- **CLI**: `arkham_tts.py` (extract/generate commands, also works standalone)

## Project Structure
```
app.py                  - Flask web app (main entry point)
auth.py                 - Single-user login (setup token, sessions, lockout, set-password CLI)
extract.py              - PDF extraction logic (font-based italic text detection)
generate.py             - ElevenLabs TTS generation (supports model selection)
arkham_tts.py           - CLI entry point (extract / generate / voices / merge)
merge.py                - Merge a fresh extraction into an existing, user-edited campaign
templates/index.html    - Full UI (single file, inline CSS/JS)
templates/login.html    - Login / first-run account setup page
data/                   - Campaign JSON files (extracted sections)
data/_arkhamdb_packs.json - Cached ArkhamDB pack list (with cycle grouping)
data/_auth.json         - Login account (username, password hash), session secret — never commit
audio/                  - Generated audio files in human-readable paths (<Campaign>/<Scenario>/<Entry>.ext)
uploads/                - Temporarily stored PDFs uploaded via web UI
settings.json           - ElevenLabs API key, voice ID, model ID
requirements.txt        - Python dependencies (flask, pdfplumber, elevenlabs)
requirements-dev.txt    - Adds pytest
tests/                  - pytest suite (see Tests below); tests/fixtures/ holds saved ArkhamDB responses
static/                 - Served by Flask at /static/: cthulhu-profile.png (selected-campaign head art), cthulhu-arms.svg (its tentacles)
tools/cthulhu_svg.py    - Generates static/cthulhu-arms.svg (tapered tentacles with suckers and curls)
tools/cutout_checkerboard.py - Removes a baked-in "transparency" checkerboard from generated art → real transparent PNG
tools/art_src/          - Original head art (front + profile) the static PNG was cut from
run.bat                 - Windows launcher
CLAUDE.md               - This file (project context for Claude Code)
```

## Key Architecture Decisions

### PDF Extraction (`extract.py`)
- Uses font analysis: ArnoPro-Italic (size 9) = read-aloud narrative, ArnoPro-Bold = labels, Teutonic = headers
- Teutonic size >= 16 = scenario headers (Scenario, Part, Interlude, Codex, Prologue, Epilogue, Design Notes)
- Teutonic size 12-15 = sub-headers (Codex entries), treated as bold/label blocks in `_extract_page_blocks`
- Two-column PDF layouts: blocks processed in native pdfplumber order (NOT sorted by Y-position — sorting interleaves columns)
- Scenario headers pre-scanned from Teutonic font chars (`_prescan_scenarios`), then blocks processed page-by-page
- Page 1 is processed if it contains narrative blocks (e.g., Night of the Zealot intro); otherwise skipped (cover page)
- "Ungrouped" entries (narrative before the first detected scenario) are reassigned to the first real scenario
- Resolution pages after Codex pages auto-associate back to parent scenario via `last_main_scenario` tracking
- Design Notes pages: scenario switch is skipped so resolutions sharing the page are still captured
- Gap absorption: consecutive non-narrative `regular` runs under 30 chars between narrative runs are merged (handles inline title references like "The King in Yellow"). Only `regular` gaps absorbed — `bold` gaps always break narrative since they're labels/headers
- Spatial checks: style runs are split when text jumps columns (`COLUMN_JUMP`), and narrative runs are only merged when on the same/next line (`MAX_LINE_GAP`). Stops card subtitles like "(Repossess the Past)" or campaign-log phrases gluing onto narrative elsewhere on the page
- Header position: `_prescan_scenarios` also returns each header's (x0, top). On a page whose header starts in the right column or mid-column, blocks before it (earlier column, or above it in the same column) stay with the previous scenario (`_precedes_header`) — e.g. a resolution in the left column of an Interlude's first page
- Page-break continuations: an unlabeled narrative block starting lowercase is appended to the latest entry in the scenario that ends mid-sentence
- "continue reading": when regular text between two narrative blocks says "continue reading" (Brethren Codex entries), the second half is labeled "<label> (cont.)"
- Unlabeled intros: narrative before the first header → "Campaign Intro"; the first unlabeled entry by reading position in a scenario → "Intro" (or "Prologue"/"Epilogue"); skipped for Codex groups
- `_cut_trailing_rules_text`: truncates narrative at "… is a campaign for Arkham Horror", "Check Campaign Log", "Congratulations on completing" (rules text sharing an italic text box)
- AnkeCalligraphicFG (handwriting font for journal dates, Forgotten Age) is treated as narrative (`journal` style)
- Auto-subgrouping via `_auto_subgroup()`: Resolutions, Intros, Parts, Codex Entries, Armitage's Fate
- Filters via `_looks_like_non_narrative()`: encounter set lists, game state conditions, strategy tips, notes, campaign log instructions
- Entries sorted within scenarios by `_entry_sort_key()`: intros first, then parts, then no-resolution/investigator defeat, then resolutions

### Re-extraction merge (`merge.py`, `arkham_tts.py merge <campaign_id> [--pdf] [--apply]`)
- Lets extractor improvements reach an existing library without losing edits. Dry run by default; `--apply` backs up to `data/_backups/<id>-<timestamp>.json` first
- Matches old ↔ new entries by shared 6-word shingles (greedy one-to-one by overlap); extracted scenarios map to library scenarios by majority of matched entries, so renamed scenarios still match
- Label changes only for generic "Entry N" labels, and only when the old text corresponds to the new entry. Text changes only when one text contains the other (≥90% shingles) — otherwise treated as hand-edited
- Entries with audio on disk: text and scenario never changed (reported instead); labels may still upgrade
- Moves entries to the scenario the extractor now assigns, except audio entries and the only entry of a group (likely deliberate grouping)
- Removes old fragments now contained in a merged entry (no audio only); adds new passages after their extraction-order predecessor; never touches ArkhamDB card entries (Deck subgroups / page 0); unmatched entries are reported, not deleted
- Note: `/api/ffg-download` still **overwrites** the campaign file — use merge for an existing campaign

### Entry Label Detection (`_detect_entry_label`)
- Three-tier matching on bold text blocks:
  1. Known patterns with colon (Resolution X:, Part X:, Intro X:, Codex X:, etc.) — uses LAST match (handles concatenated labels like "Armitage's Fate 2.Armitage's Fate 1:")
  2. Known patterns without colon — uses FIRST match (handles "Resolution 2 (read Investigator Defeat first!):" where Investigator Defeat appears later)
  3. Generic fallback: any bold text ending with `:` becomes a label if under 50 chars and doesn't start with game-mechanics verbs (Proceed, Check, Setup, etc.)
- Generic fallback catches campaign-specific labels like "Reality's Shadow 1:", "Sebastien's Information:", "Daniel Was Possessed:", "Lola's Prologue:"
- Checked before the tiers: `If <Name> is not listed under "...:"` (Dunwich Interlude II survivors) → label `<Name>`

### Authentication (`auth.py`)
- One account. Every route requires login except `/login`, `/setup`, `/logout`, `/static/*`, `/banner.jpg`, `/background.jpg`; `/api/*` → 401 JSON, pages → redirect to `/login?next=…`
- No account yet → everything redirects to `/setup`, which needs the one-time token printed in the server console (safe even if the instance is already public)
- `python arkham_tts.py set-password` creates/resets the account; changing the password bumps `session_version`, signing out all sessions
- Passwords hashed with werkzeug; sessions are permanent cookies (30 days, HttpOnly, SameSite=Lax); 5 failed logins per IP → 15 min lockout
- Env: `ARKHAM_SECURE_COOKIES=1` (HTTPS only cookies), `ARKHAM_TRUST_PROXY=1` (take client IP from X-Forwarded-For behind a reverse proxy, needed for the lockout)
- `GET /api/settings` never returns the ElevenLabs key — only `api_key_set` and `api_key_hint` (last 4 chars); `PUT` with a blank key keeps the saved one
- Frontend wraps `fetch`: any 401 sends the page to `/login`. "Log out" sits next to the credits indicator
- Tests set `app.config["AUTH_DISABLED"] = True` to bypass login (`tests/test_arkhamdb_import.py`); `tests/test_auth.py` covers the login rules

### Web App (`app.py`)
- Campaign data stored as JSON arrays of scenario objects in `data/`
- Campaign metadata (display names, sort order) stored in `data/_campaign_meta.json`
- Files starting with `_` in data/ are skipped (cache files); non-list JSON also skipped
- FFG campaign guide catalog (`FFG_CAMPAIGN_GUIDES`): auto-download PDFs from Fantasy Flight Games CDN via `/api/ffg-download`
- Audio organized as `audio/<Campaign Name>/<Scenario Name>/<[Subgroup - ]Display Label>.<ext>` (human-readable paths)
- Legacy audio paths (`audio/<campaign_id>/<scenario_folder>/<label>.mp3`) auto-migrated on first load
- Each entry stores `audio_file` field with relative path from audio dir (supports mp3/wav/m4a/ogg)
- Delete operations accept optional `keep_audio` flag to preserve audio files on disk for reuse
- Entries can have audio attached via file upload (attach-audio endpoint) instead of TTS generation
- Settings in `settings.json` (API key, voice ID, model ID)
- TTS model is configurable in Settings (supports eleven_v4, eleven_v4_turbo, eleven_v3, eleven_multilingual_v2, etc.)
- Background thread for bulk TTS generation with job status polling
- Single-entry generation/regeneration via `/api/campaign/<id>/generate-entry`
- Entry metadata: `generated_at` timestamp and `generated_model` saved per entry on generation
- Credits indicator via ElevenLabs `/v1/user/subscription` endpoint (requires `user_read` API key permission)

### Frontend (`templates/index.html`)
- Three tabs: Library, Import, Settings
- **Library tab**: campaign sidebar (renameable, reorderable via drag-and-drop), scenario groups with collapsible subgroups, entry cards with inline audio player
- **Campaigns**: renameable (pencil icon), drag-and-drop reordering, deleteable; display names and order stored in `_campaign_meta.json`. The sidebar shows names only; the audio count is in the library toolbar
- **Selected campaign marker**: the active row (70px tall) shows the painted side-view Cthulhu head (`static/cthulhu-profile.png`) emerging from the left edge (1.5× the row height with the crown and eyes in view, shoulders cut off below, ~35% past the left edge), with pulsing eye glows (positions are % of the image in `CTHULHU_ART`) and five tentacle arms inlined from `static/cthulhu-arms.svg`. Everything is clipped to the row (`.cthulhu-mark { overflow: hidden }`). Entrance animation (head rises, arms grow) plays only when switching campaigns (`no-grow` class on re-render); honours `prefers-reduced-motion`. To change the arms edit `ARMS` in `tools/cthulhu_svg.py` and run it; to re-cut art run `tools/cutout_checkerboard.py <src> static/cthulhu-profile.png`
- **Play / Edit modes** (toolbar switch, remembered in localStorage `viewMode`): Edit mode shows the full scenario/subgroup tree with all tools plus a 2-line text preview. Play mode (`renderPlayMode`) shows a list of scenarios; clicking one (`playScenario`) fills the panel with: intro button(s) (ungrouped + `Intros` entries), one big Agenda card and one big Act card, then the other subgroups (Resolutions, Codex…) as collapsible play rows. "‹ Previous" / "Next ›" in the header step to the neighbouring scenario
- **Act/agenda cards**: entries in `* Deck` subgroups labelled `Agenda: Name (Front|Back)` (optionally `– Variant`) are parsed by `parseCard`; `buildDeck` turns them into ordered steps (each card's front, then back). The card shows the current side with play button(s) (one per variant) and "Flip to back" / "Next card", plus ‹ to step back. Position per deck is stored in localStorage (`deckPos|<campaign>|<scenario name>|<Agenda|Act>`); "Reset decks" returns both to the first card. In Edit mode backs are indented under their front with a "↳ flip side" marker
- **Entries**: play/pause toggle button, drag handle, rename (pencil icon), expand/edit text (auto-saves on collapse or click-away), generate/regenerate audio, attach audio file (paperclip icon), info popover (timestamp + model), delete
- **Subgroups**: collapsible (collapsed by default), renameable, deleteable, draggable for reordering within and across scenarios
- **Groups (scenarios)**: renameable, deleteable, draggable for reordering, add-subgroup button — all action icons appear on hover only
- **Drag-and-drop**: entries within/across scenarios and subgroups; subgroup reordering within and across scenarios; scenario reordering; campaign reordering; entries onto scenario/subgroup headers
  - During drag, `body.is-dragging` / `body.is-dragging-scenario` classes disable `pointer-events` on child elements so drag events reach wrapper/header targets
  - After any drop, `is-dragging` cleared and `dragData` nulled BEFORE re-render
  - After mutations, data re-fetched from server (`refreshAndRender()`) — no local state manipulation
- Open/collapsed state of scenarios and subgroups preserved across re-renders via `getOpenState()`
- **Audio player bar**: fixed at bottom, shows current track, progress bar with seek, play/pause
- **Import tab**: FFG campaign guide download (auto-downloads from FFG CDN) or manual PDF upload; ArkhamDB card import with cycle-based accordion pack picker
- **ArkhamDB import**: accordion pack picker grouped by cycle with select-all cycle checkboxes; packs without agenda/act cards filtered out; imported Act/Agenda Deck subgroups auto-positioned before Resolutions
- **Settings tab**: API key, voice ID, TTS model dropdown, save button
- **Credits indicator**: below tab buttons, shows remaining characters with color-coded bar and days until reset countdown, refreshes every 60s and after generation
- **Custom banner and background**: Banner5.jpg header image, Background.jpg full-page background with semi-transparent UI panels
- **Entry text auto-save**: text saves automatically on collapse or click-away (no Save button needed)
- **Confirmation modal**: used for all delete operations (campaigns, groups, subgroups, entries) with "Keep audio files on disk" checkbox (default: checked)

### ArkhamDB Integration
- Packs cached locally at `data/_arkhamdb_packs.json` with cycle name and position
- Packs without agenda/act cards filtered out via hardcoded exclude set (36 packs: investigator expansions, promos, books, starter decks)
- Packs endpoint serves from cache instantly, refreshes in background thread
- After import, Act/Agenda Deck subgroups reordered before Resolutions subgroup in each scenario
- Cards fetched per-pack from `https://arkhamdb.com/api/public/cards/{pack_code}` (60s timeout)
- Agenda/act cards: `flavor` = front read-aloud, `back_flavor` = back read-aloud
- When `back_flavor` is empty, italic text extracted from `back_text` HTML via `<i>` tag parsing
- Duplicate detection by `label` field before adding entries
- Multi-pack import: frontend loops through selected packs sequentially, shows progress
- Cards matched to existing scenarios by fuzzy encounter_code comparison, with `ENCOUNTER_ALIASES` in `app.py` for sub-encounter sets whose names aren't in the scenario title (e.g. Heart of the Elders: `pillars_of_judgment` → Part 1, `knyan` → Part 2)
- Fallback: if a pack has exactly one `scenario` card, unmatched encounter codes go to that scenario (e.g. Black Stars Rise's `vortex`/`flood` agendas)
- Cards sharing a name (alternate agenda decks) get the encounter set name appended (label + display) on whichever side's text differs; identical sides are imported once
- Old campaigns split across multiple packs (e.g., Dunwich: dwl, tmm, tece, bota, uau, wda, litas); newer campaigns have single Campaign Expansion packs (e.g., dwlc)

## Running the App
```bash
pip install -r requirements.txt
python app.py
# Open http://localhost:5000
```

On Windows: double-click `run.bat`

## Tests
```bash
pip install -r requirements-dev.txt
python -m pytest            # everything (~25s)
python -m pytest -m "not pdf"   # fast unit + ArkhamDB tests only
```
- `tests/test_extract_units.py` — extract.py helpers (labels, filters, header position, sort order)
- `tests/test_extract_guides.py` (`pdf` marker) — runs extraction on the real guides in `uploads/` (or `$ARKHAM_PDF_DIR`); skipped if a PDF is missing. Pins verified behaviors per campaign; unlabeled counts are upper bounds — tighten them when extraction improves
- `tests/test_arkhamdb_import.py` — import endpoint with saved pack responses in `tests/fixtures/` (no network)
- `tests/test_auth.py` — login, setup token, lockout, logout, API key never returned
- `tests/test_merge.py` — merge rules on synthetic campaigns (edits/audio/cards protected, moves, fragments, additions)
- Run the suite after any change to `extract.py`; fixes for one campaign often regress another

## API Endpoints
- `GET /api/library` - List all campaigns with entry/audio counts (respects custom names/order)
- `GET /api/campaign/<id>` - Get campaign data with audio status per entry
- `POST /api/campaign/<id>/rename` - Rename campaign display name
- `POST /api/reorder-campaigns` - Set campaign display order
- `GET /api/ffg-campaigns` - List available FFG campaign guide PDFs
- `POST /api/ffg-download` - Download FFG campaign guide PDF and extract sections
- `POST /api/extract` - Upload PDF and extract sections (multipart form)
- `POST /api/generate/<id>` - Bulk generate audio (background job, returns job_id)
- `GET /api/generate/status/<job_id>` - Poll bulk generation progress
- `POST /api/campaign/<id>/generate-entry` - Generate/regenerate single entry audio
- `POST /api/campaign/<id>/attach-audio` - Upload/attach audio file to entry (multipart form, accepts mp3/wav/m4a/ogg)
- `PUT /api/campaign/<id>` - Replace full campaign data
- `PATCH /api/campaign/<id>/entry` - Update entry label/text/subgroup
- `DELETE /api/campaign/<id>/entry` - Delete entry (optional `keep_audio` flag preserves audio file)
- `PATCH /api/campaign/<id>/scenario` - Rename scenario
- `DELETE /api/campaign/<id>/scenario` - Delete scenario and entries (optional `keep_audio` flag)
- `DELETE /api/campaign/<id>/subgroup` - Delete subgroup and entries (optional `keep_audio` flag)
- `POST /api/campaign/<id>/reorder` - Reorder entry within scenario
- `POST /api/campaign/<id>/move-entry` - Move entry between scenarios
- `POST /api/campaign/<id>/reorder-scenario` - Reorder scenarios within campaign
- `POST /api/campaign/<id>/reorder-subgroup` - Reorder subgroups within scenario
- `POST /api/campaign/<id>/move-subgroup` - Move subgroup between scenarios
- `DELETE /api/campaign/<id>` - Delete entire campaign and audio (optional `keep_audio` flag)
- `POST /api/arkhamdb/import/<id>` - Import agenda/act cards from ArkhamDB pack
- `GET /api/arkhamdb/packs` - List ArkhamDB packs (cached, grouped by cycle)
- `GET /api/credits` - ElevenLabs credit/character usage
- `GET /api/settings` / `PUT /api/settings` - Read/write app settings (API key write-only)
- `GET|POST /login`, `GET|POST /setup?token=…`, `POST /logout`, `GET /api/me` - Authentication

## Tested Campaign Guides
- Night of the Zealot (`night_of_the_zealot_campaign_guide.pdf`)
- The Dunwich Legacy (`ahc66_campaign_guide_v6-compressed.pdf`)
- Brethren of Ash (`ahc100_campaign_guide-web.pdf`)
- The Path to Carcosa (`ahc68_campaign_guide_v4-compressed.pdf`)
- The Forgotten Age (`ahc73_campaign_guide_v2-compressed.pdf`)

## Known Extraction Patterns by Campaign
- **Night of the Zealot**: scenarios named "Part I/II/III:" instead of "Scenario", narrative intro on page 1, Campaign Log instructions in italic to filter
- **Dunwich Legacy**: two-column layout, Armitage's Fate interludes, encounter set names in italic within Setup sections
- **Brethren of Ash**: Codex pages (Teutonic size 14 entry headers), resolution pages after Codex pages, Strategy Tips to filter
- **Path to Carcosa**: inline "The King in Yellow" title references in regular font within italic narrative, Lola's Prologue conditional, Reality's Shadow / Daniel conditional labels
- **Forgotten Age**: journal entries with handwriting-font date lines, text frames that flow from the bottom of the right column back to the top-left (Boundary Beyond intro) and across pages, scenario headers in the right column with the previous scenario's resolutions in the left column, many unlabeled single intros
