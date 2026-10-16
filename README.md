# Arkham Horror TTS - Campaign Guide Audio Generator

A web app that extracts read-aloud narrative text from **Arkham Horror: The Card Game** campaign guide PDFs and converts them to speech audio files using the ElevenLabs TTS API.

Browse, organize, and play generated audio from a library interface — or attach your own audio files to any entry.

## Features

- **PDF Extraction** -- Upload a campaign guide PDF and automatically extract all read-aloud narrative sections, grouped by scenario
- **Text-to-Speech** -- Generate audio for any entry using ElevenLabs TTS with configurable voice and model
- **Audio Library** -- Browse campaigns, scenarios, and entries with collapsible groups and subgroups
- **Inline Playback** -- Play/pause audio directly from entry cards or the persistent player bar
- **Audio Recycling** -- Keep audio files on disk when deleting entries, then re-attach them to other entries
- **File Attachment** -- Upload your own audio files (MP3, WAV, M4A, OGG) to any entry instead of generating via TTS
- **Drag-and-Drop** -- Reorder entries, move them between scenarios, and drag subgroups across groups
- **ArkhamDB Import** -- Fetch agenda/act card flavor text from ArkhamDB and add it to your campaigns
- **Human-Readable File Names** -- Audio files stored with descriptive paths like `The Dunwich Legacy/Scenario I/Resolutions - Resolution 1.mp3`

## Getting Started

### Prerequisites

- Python 3.8+
- An [ElevenLabs](https://elevenlabs.io) API key (for TTS generation)

### Installation

```bash
git clone https://github.com/Skypsycho/arkham-horror-tts.git
cd arkham-horror-tts
pip install -r requirements.txt
```

### Running

**Linux / macOS:**

```bash
python app.py
```

Open **http://localhost:5000** in your browser.

**Windows:**

Double-click `run.bat` -- it installs dependencies and starts the app automatically.

Or from the command prompt:

```cmd
pip install -r requirements.txt
python app.py
```

If `python` isn't recognized, you may need to install Python from [python.org](https://www.python.org/downloads/) and make sure "Add Python to PATH" is checked during installation.

### Configuration

Go to the **Settings** tab in the app to enter your:
- ElevenLabs API key
- Voice ID
- TTS model (v4, v4 Turbo, v3, Multilingual v2, etc.)

## Usage

1. **Import** -- Go to the Import tab, upload a campaign guide PDF, and click "Extract Sections"
2. **Browse** -- Switch to the Library tab to see your extracted scenarios and entries
3. **Generate** -- Click the lightning bolt on any entry to generate audio, or use bulk generation
4. **Organize** -- Drag entries and subgroups to reorder, rename labels, edit text before generating
5. **Play** -- Click the play button on any entry or use the bottom player bar

### Audio Recycling

When deleting entries, groups, or campaigns, a "Keep audio files on disk" checkbox (checked by default) preserves the audio files. You can later attach those files to new entries using the paperclip button.

### ArkhamDB Integration

Import agenda and act card read-aloud text from ArkhamDB packs. Go to the Import tab, select a campaign and one or more packs, and click "Import Cards".

## Tested Campaign Guides

- The Dunwich Legacy
- The Path to Carcosa
- Brethren of Ash

## Project Structure

```
app.py               - Flask web app (main entry point)
extract.py            - PDF text extraction (font-based italic detection)
generate.py           - ElevenLabs TTS generation
arkham_tts.py         - CLI entry point
templates/index.html  - Full UI (single file, inline CSS/JS)
data/                 - Extracted campaign JSON files (gitignored)
audio/                - Generated audio files (gitignored)
settings.json         - API key and voice config (gitignored)
```

## License

This project is for personal use. Arkham Horror: The Card Game is a product of Fantasy Flight Games.
