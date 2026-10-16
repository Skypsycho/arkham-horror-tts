#!/usr/bin/env python3
"""
Arkham Horror LCG Campaign Guide → TTS Audio Generator

Usage:
  1. Extract read-aloud sections:
     python arkham_tts.py extract <pdf_path> [--output <sections.json>]

  2. Review the generated JSON, edit as needed.

  3. Generate audio:
     python arkham_tts.py generate <sections.json> [--output-dir <audio/>] [--voice <voice_id>]

  4. List available ElevenLabs voices:
     python arkham_tts.py voices
"""

import argparse
import json
import os
import sys
from pathlib import Path

from extract import extract_sections
from generate import generate_audio, list_voices


def cmd_extract(args):
    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"Error: PDF not found: {pdf_path}")
        sys.exit(1)

    output = Path(args.output) if args.output else pdf_path.with_suffix(".sections.json")

    print(f"Extracting read-aloud sections from: {pdf_path}")
    sections = extract_sections(str(pdf_path))

    with open(output, "w", encoding="utf-8") as f:
        json.dump(sections, f, indent=2, ensure_ascii=False)

    total = sum(len(s["entries"]) for s in sections)
    print(f"\nExtracted {total} entries across {len(sections)} scenario(s).")
    print(f"Saved to: {output}")
    print(f"\nReview the JSON file and edit as needed.")
    print(f"  - Remove entries you don't want converted")
    print(f"  - Fix any text extraction errors")
    print(f"  - Adjust scenario/entry names")
    print(f"\nThen run:  python arkham_tts.py generate {output}")


def cmd_generate(args):
    sections_path = Path(args.sections)
    if not sections_path.exists():
        print(f"Error: Sections file not found: {sections_path}")
        sys.exit(1)

    api_key = args.api_key or os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        print("Error: ElevenLabs API key required.")
        print("  Set ELEVENLABS_API_KEY env var or pass --api-key")
        sys.exit(1)

    with open(sections_path, "r", encoding="utf-8") as f:
        sections = json.load(f)

    output_dir = Path(args.output_dir) if args.output_dir else Path("audio")
    voice = args.voice or "Rachel"

    generate_audio(sections, api_key, output_dir, voice)


def cmd_voices(args):
    api_key = args.api_key or os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        print("Error: ElevenLabs API key required.")
        print("  Set ELEVENLABS_API_KEY env var or pass --api-key")
        sys.exit(1)

    list_voices(api_key)


def main():
    parser = argparse.ArgumentParser(
        description="Arkham Horror LCG Campaign Guide → TTS Audio"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_extract = sub.add_parser("extract", help="Extract read-aloud sections from a PDF")
    p_extract.add_argument("pdf", help="Path to the campaign guide PDF")
    p_extract.add_argument("--output", "-o", help="Output JSON path (default: <pdf>.sections.json)")

    p_generate = sub.add_parser("generate", help="Generate audio from reviewed sections")
    p_generate.add_argument("sections", help="Path to the reviewed sections JSON")
    p_generate.add_argument("--output-dir", "-o", default="audio", help="Output directory (default: audio/)")
    p_generate.add_argument("--voice", "-v", help="ElevenLabs voice name or ID (default: Rachel)")
    p_generate.add_argument("--api-key", help="ElevenLabs API key (or set ELEVENLABS_API_KEY)")

    p_voices = sub.add_parser("voices", help="List available ElevenLabs voices")
    p_voices.add_argument("--api-key", help="ElevenLabs API key (or set ELEVENLABS_API_KEY)")

    args = parser.parse_args()

    commands = {
        "extract": cmd_extract,
        "generate": cmd_generate,
        "voices": cmd_voices,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
