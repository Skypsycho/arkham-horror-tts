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
extract.py              - PDF extraction logic (font-based italic text detection)
generate.py             - ElevenLabs TTS generation (supports model selection)
arkham_tts.py           - CLI entry point
templates/index.html    - Full UI (single file, inline CSS/JS)
data/                   - Campaign JSON files (extracted sections)
data/_arkhamdb_packs.json - Cached ArkhamDB pack list (with cycle grouping)
audio/                  - Generated audio files in human-readable paths (<Campaign>/<Scenario>/<Entry>.ext)
uploads/                - Temporarily stored PDFs uploaded via web UI
settings.json           - ElevenLabs API key, voice ID, model ID
requirements.txt        - Python dependencies (flask, pdfplumber, elevenlabs)
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
- Auto-subgrouping via `_auto_subgroup()`: Resolutions, Intros, Parts, Codex Entries, Armitage's Fate
- Filters via `_looks_like_non_narrative()`: encounter set lists, game state conditions, strategy tips, notes, campaign log instructions
- Entries sorted within scenarios by `_entry_sort_key()`: intros first, then parts, then no-resolution/investigator defeat, then resolutions

### Entry Label Detection (`_detect_entry_label`)
- Three-tier matching on bold text blocks:
  1. Known patterns with colon (Resolution X:, Part X:, Intro X:, Codex X:, etc.) — uses LAST match (handles concatenated labels like "Armitage's Fate 2.Armitage's Fate 1:")
  2. Known patterns without colon — uses FIRST match (handles "Resolution 2 (read Investigator Defeat first!):" where Investigator Defeat appears later)
  3. Generic fallback: any bold text ending with `:` becomes a label if under 50 chars and doesn't start with game-mechanics verbs (Proceed, Check, Setup, etc.)
- Generic fallback catches campaign-specific labels like "Reality's Shadow 1:", "Sebastien's Information:", "Daniel Was Possessed:", "Lola's Prologue:"

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
- **Campaigns**: renameable (pencil icon), drag-and-drop reordering, deleteable; display names and order stored in `_campaign_meta.json`
- **Entries**: play/pause toggle button, drag handle, rename (pencil icon), expand/edit text (auto-saves on collapse or click-away), generate/regenerate audio, attach audio file (paperclip icon), info popover (timestamp + model), delete
- **Subgroups**: collapsible (collapsed by default), renameable, deleteable, draggable for reordering within and across scenarios
- **Groups (scenarios)**: renameable, deleteable, draggable for reordering, add-subgroup button — all action icons appear on hover only
- **Drag-and-drop**: entries within/across scenarios and subgroups; subgroup reordering within and across scenarios; scenario reordering; campaign reordering; entries onto scenario/subgroup headers
  - During drag, `body.is-dragging` / `body.is-dragging-scenario` classes disable `pointer-events` on child elements so drag events reach wrapper/header targets
  - After any drop, `is-dragging` cleared and `dragData` nulled BEFORE re-render
  - After mutations, data re-fetched from server (`refreshAndRender()`) — no local state manipulation
- Open/collapsed state of scenarios and subgroups preserved across re-renders via `getOpenState()`
- **Audio player bar**: fixed at bottom, shows current track, progress bar with seek, play/pause
- **Import tab**: FFG campaign guide download (auto-downloads from FFG CDN) or manual PDF upload, bulk audio generation with progress bar, ArkhamDB card import
- **ArkhamDB import**: multi-select pack list grouped by campaign cycle (`<optgroup>`), packs cached locally with background refresh
- **Settings tab**: API key, voice ID, TTS model dropdown, save button
- **Credits indicator**: in header, shows remaining characters with color-coded bar, refreshes every 60s and after generation
- **Confirmation modal**: used for all delete operations (campaigns, groups, subgroups, entries) with "Keep audio files on disk" checkbox (default: checked)

### ArkhamDB Integration
- Packs cached locally at `data/_arkhamdb_packs.json` with cycle name and position
- Packs endpoint serves from cache instantly, refreshes in background thread
- Cards fetched per-pack from `https://arkhamdb.com/api/public/cards/{pack_code}` (60s timeout)
- Agenda/act cards: `flavor` = front read-aloud, `back_flavor` = back read-aloud
- When `back_flavor` is empty, italic text extracted from `back_text` HTML via `<i>` tag parsing
- Duplicate detection by `label` field before adding entries
- Multi-pack import: frontend loops through selected packs sequentially, shows progress
- Cards matched to existing scenarios by fuzzy encounter_code comparison
- Old campaigns split across multiple packs (e.g., Dunwich: dwl, tmm, tece, bota, uau, wda, litas); newer campaigns have single Campaign Expansion packs (e.g., dwlc)

## Running the App
```bash
pip install -r requirements.txt
python app.py
# Open http://localhost:5000
```

On Windows: double-click `run.bat`

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
- `GET /api/settings` / `PUT /api/settings` - Read/write app settings

## Tested Campaign Guides
- Night of the Zealot (`night_of_the_zealot_campaign_guide.pdf`)
- The Dunwich Legacy (`ahc66_campaign_guide_v6-compressed.pdf`)
- Brethren of Ash (`ahc100_campaign_guide-web.pdf`)
- The Path to Carcosa (`ahc68_campaign_guide_v4-compressed.pdf`)

## Known Extraction Patterns by Campaign
- **Night of the Zealot**: scenarios named "Part I/II/III:" instead of "Scenario", narrative intro on page 1, Campaign Log instructions in italic to filter
- **Dunwich Legacy**: two-column layout, Armitage's Fate interludes, encounter set names in italic within Setup sections
- **Brethren of Ash**: Codex pages (Teutonic size 14 entry headers), resolution pages after Codex pages, Strategy Tips to filter
- **Path to Carcosa**: inline "The King in Yellow" title references in regular font within italic narrative, Lola's Prologue conditional, Reality's Shadow / Daniel conditional labels
