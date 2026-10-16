"""
Audio generation module using ElevenLabs TTS API.
"""

import sys
import time
from pathlib import Path

from elevenlabs import ElevenLabs


def list_voices(api_key):
    """List available ElevenLabs voices."""
    client = ElevenLabs(api_key=api_key)
    response = client.voices.get_all()

    print(f"{'Name':<25} {'Voice ID':<25} {'Category':<15}")
    print("-" * 65)
    for voice in response.voices:
        category = getattr(voice, "category", "unknown")
        print(f"{voice.name:<25} {voice.voice_id:<25} {category:<15}")


def _resolve_voice_id(client, voice_name_or_id):
    """Resolve a voice name to its ID, or return the ID if already one."""
    try:
        response = client.voices.get_all()
        for voice in response.voices:
            if voice.name.lower() == voice_name_or_id.lower():
                return voice.voice_id
            if voice.voice_id == voice_name_or_id:
                return voice.voice_id
    except Exception:
        pass

    return voice_name_or_id


def generate_audio(sections, api_key, output_dir, voice="Rachel"):
    """Generate TTS audio files from extracted sections.

    Args:
        sections: List of scenario dicts from extract step
        api_key: ElevenLabs API key
        output_dir: Base directory for audio output
        voice: Voice name or ID
    """
    client = ElevenLabs(api_key=api_key)
    voice_id = _resolve_voice_id(client, voice)

    output_dir = Path(output_dir)
    total_entries = sum(len(s["entries"]) for s in sections)
    generated = 0
    errors = 0

    print(f"Generating audio for {total_entries} entries using voice '{voice}'")
    print(f"Output directory: {output_dir}\n")

    for scenario in sections:
        scenario_dir = output_dir / scenario["scenario_folder"]
        scenario_dir.mkdir(parents=True, exist_ok=True)
        print(f"--- {scenario['scenario']} ---")

        for entry in scenario["entries"]:
            filename = f"{entry['label']}.mp3"
            filepath = scenario_dir / filename

            if filepath.exists():
                print(f"  [skip] {filename} (already exists)")
                generated += 1
                continue

            try:
                audio_generator = client.text_to_speech.convert(
                    voice_id=voice_id,
                    text=entry["text"],
                    model_id="eleven_multilingual_v2",
                    output_format="mp3_44100_128",
                )

                audio_bytes = b"".join(audio_generator)

                with open(filepath, "wb") as f:
                    f.write(audio_bytes)

                generated += 1
                print(f"  [done] {filename} ({len(audio_bytes) / 1024:.1f} KB)")

                time.sleep(0.2)

            except Exception as e:
                errors += 1
                print(f"  [ERROR] {filename}: {e}", file=sys.stderr)

    print(f"\nComplete: {generated}/{total_entries} files generated, {errors} errors.")
    print(f"Audio saved to: {output_dir}")


def generate_audio_entry(text, filepath, api_key, voice_id, model_id=None):
    """Generate a single audio file from text."""
    client = ElevenLabs(api_key=api_key)
    audio_generator = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id=model_id or "eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )
    audio_bytes = b"".join(audio_generator)
    with open(filepath, "wb") as f:
        f.write(audio_bytes)
