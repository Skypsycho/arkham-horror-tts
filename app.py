#!/usr/bin/env python3
"""
Arkham Horror LCG — Campaign Guide TTS App

A web-based app for extracting read-aloud sections from Arkham Horror
campaign guide PDFs and converting them to speech audio files.
"""

import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory

from extract import extract_sections
from generate import generate_audio_entry

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
AUDIO_DIR = BASE_DIR / "audio"
SETTINGS_FILE = BASE_DIR / "settings.json"

DATA_DIR.mkdir(exist_ok=True)
AUDIO_DIR.mkdir(exist_ok=True)

generation_jobs = {}

AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.ogg'}


def _sanitize_for_path(name):
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', ' ', name).strip().strip('.')
    return name[:120]


def _build_audio_path(campaign_id, scenario, entry, ext='mp3'):
    campaign_name = _sanitize_for_path(campaign_id.replace("_", " ").title())
    scenario_name = _sanitize_for_path(scenario["scenario"])
    subgroup = entry.get("subgroup")
    display = entry.get("display_label", entry["label"])
    if subgroup:
        filename = _sanitize_for_path(f"{subgroup} - {display}")
    else:
        filename = _sanitize_for_path(display)
    return f"{campaign_name}/{scenario_name}/{filename}.{ext}"


def _resolve_audio_path(campaign_id, scenario, entry):
    af = entry.get("audio_file")
    if af:
        return AUDIO_DIR / af
    return AUDIO_DIR / campaign_id / scenario["scenario_folder"] / f"{entry['label']}.mp3"


def _migrate_campaign_audio(campaign_id, data):
    changed = False
    for scenario in data:
        for entry in scenario["entries"]:
            if "audio_file" in entry:
                continue
            old_path = AUDIO_DIR / campaign_id / scenario["scenario_folder"] / f"{entry['label']}.mp3"
            new_rel = _build_audio_path(campaign_id, scenario, entry, ext='mp3')
            new_path = AUDIO_DIR / new_rel
            if old_path.exists() and old_path != new_path:
                if not new_path.exists():
                    new_path.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.move(str(old_path), str(new_path))
                    except (OSError, FileNotFoundError):
                        pass
            entry["audio_file"] = new_rel
            changed = True
    if changed:
        path = DATA_DIR / f"{campaign_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        old_campaign_dir = AUDIO_DIR / campaign_id
        if old_campaign_dir.exists():
            _cleanup_empty_dirs(old_campaign_dir)


def _cleanup_empty_dirs(root):
    for dirpath, dirnames, filenames in os.walk(str(root), topdown=False):
        if not filenames and not dirnames:
            try:
                os.rmdir(dirpath)
            except OSError:
                pass


def _load_settings():
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    return {"api_key": "", "voice_id": "", "voice_name": ""}


def _save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)


CAMPAIGN_META_FILE = DATA_DIR / "_campaign_meta.json"


def _load_campaign_meta():
    if CAMPAIGN_META_FILE.exists():
        with open(CAMPAIGN_META_FILE) as f:
            return json.load(f)
    return {}


def _save_campaign_meta(meta):
    with open(CAMPAIGN_META_FILE, "w") as f:
        json.dump(meta, f, indent=2)


def _get_campaigns():
    meta = _load_campaign_meta()
    campaigns = []
    for path in sorted(DATA_DIR.glob("*.json")):
        if path.name.startswith("_"):
            continue
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, list):
            continue
        campaign_id = path.stem
        _migrate_campaign_audio(campaign_id, data)

        total = 0
        generated = 0
        for scenario in data:
            for entry in scenario["entries"]:
                total += 1
                audio_path = _resolve_audio_path(campaign_id, scenario, entry)
                entry["has_audio"] = audio_path.exists()
                if entry["has_audio"]:
                    generated += 1

        cm = meta.get(campaign_id, {})
        display_name = cm.get("name", campaign_id.replace("_", " ").title())

        campaigns.append({
            "id": campaign_id,
            "name": display_name,
            "full_name": display_name,
            "scenarios": data,
            "total_entries": total,
            "generated_entries": generated,
        })

    order = meta.get("_order", [])
    if order:
        order_map = {cid: i for i, cid in enumerate(order)}
        campaigns.sort(key=lambda c: order_map.get(c["id"], 9999))

    return campaigns


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/library")
def api_library():
    return jsonify(_get_campaigns())


@app.route("/api/campaign/<campaign_id>/rename", methods=["POST"])
def api_rename_campaign(campaign_id):
    path = DATA_DIR / f"{campaign_id}.json"
    if not path.exists():
        return jsonify({"error": "Campaign not found"}), 404

    body = request.json
    new_name = body.get("name", "").strip()
    if not new_name:
        return jsonify({"error": "Name required"}), 400

    meta = _load_campaign_meta()
    if campaign_id not in meta:
        meta[campaign_id] = {}
    meta[campaign_id]["name"] = new_name
    _save_campaign_meta(meta)
    return jsonify({"ok": True})


@app.route("/api/reorder-campaigns", methods=["POST"])
def api_reorder_campaigns():
    body = request.json
    order = body.get("order", [])
    meta = _load_campaign_meta()
    meta["_order"] = order
    _save_campaign_meta(meta)
    return jsonify({"ok": True})


FFG_CAMPAIGN_GUIDES = [
    {"name": "Night of the Zealot", "url": "https://cdn.svc.asmodee.net/production-fantasyflightgames/uploads/2026/09/night_of_the_zealot_campaign_guide.pdf"},
    {"name": "The Dunwich Legacy", "url": "https://cdn.svc.asmodee.net/production-fantasyflightgames/uploads/2026/09/ahc66_campaign_guide_v6-compressed.pdf"},
    {"name": "The Path to Carcosa", "url": "https://cdn.svc.asmodee.net/production-fantasyflightgames/uploads/2026/09/ahc68_campaign_guide_v4-compressed.pdf"},
    {"name": "The Forgotten Age", "url": "https://cdn.svc.asmodee.net/production-fantasyflightgames/uploads/2026/09/ahc73_campaign_guide_v2-compressed.pdf"},
    {"name": "The Circle Undone", "url": "https://cdn.svc.asmodee.net/production-fantasyflightgames/uploads/2026/09/ahc75_campaign_guide-compressed.pdf"},
    {"name": "The Dream-Eaters (Campaign A)", "url": "https://cdn.svc.asmodee.net/production-fantasyflightgames/uploads/2026/09/ahc79_campaign_guide_a-web.pdf"},
    {"name": "The Dream-Eaters (Campaign B)", "url": "https://cdn.svc.asmodee.net/production-fantasyflightgames/uploads/2026/09/ahc79_campaign_guide_b-web.pdf"},
    {"name": "The Innsmouth Conspiracy", "url": "https://cdn.svc.asmodee.net/production-fantasyflightgames/uploads/2026/09/ahc82_campaign_guide-web_1.pdf"},
    {"name": "Edge of the Earth", "url": "https://cdn.svc.asmodee.net/production-fantasyflightgames/uploads/2026/09/ahc64_edge_of_the_earth_campaign_guide-compressed.pdf"},
    {"name": "The Scarlet Keys", "url": "https://cdn.svc.asmodee.net/production-fantasyflightgames/uploads/2026/09/ahc70_the_scarlet_keys_campaign_guide-compressed.pdf"},
    {"name": "The Feast of Hemlock Vale", "url": "https://cdn.svc.asmodee.net/production-fantasyflightgames/uploads/2026/09/ahc77_campaign_guide_web-compressed.pdf"},
    {"name": "The Drowned City", "url": "https://cdn.svc.asmodee.net/production-fantasyflightgames/uploads/2026/09/ahc84_campaign_guide-web_1.pdf"},
    {"name": "Brethren of Ash", "url": "https://cdn.svc.asmodee.net/production-fantasyflightgames/uploads/2026/09/ahc100_campaign_guide-web.pdf"},
    {"name": "Children of Blood", "url": "https://cdn.svc.asmodee.net/production-fantasyflightgames/uploads/2026/09/ahc106_campaign_guide-web.pdf"},
]


@app.route("/api/ffg-campaigns")
def api_ffg_campaigns():
    return jsonify(FFG_CAMPAIGN_GUIDES)


@app.route("/api/ffg-download", methods=["POST"])
def api_ffg_download():
    body = request.json
    campaign_name = body.get("name")
    url = body.get("url")

    guide = next((g for g in FFG_CAMPAIGN_GUIDES if g["url"] == url), None)
    if not guide:
        return jsonify({"error": "Unknown campaign guide URL"}), 400

    campaign_id = re.sub(r"[^\w\s\-]", "", campaign_name)
    campaign_id = re.sub(r"\s+", "_", campaign_id).lower()[:60]

    filename = url.rsplit("/", 1)[-1]
    pdf_path = BASE_DIR / "uploads" / filename
    pdf_path.parent.mkdir(exist_ok=True)

    if not pdf_path.exists():
        import urllib.request
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ArkhamTTS/1.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                with open(pdf_path, "wb") as f:
                    f.write(r.read())
        except Exception as e:
            return jsonify({"error": f"Download failed: {e}"}), 500

    try:
        sections = extract_sections(str(pdf_path))
    except Exception as e:
        return jsonify({"error": f"Extraction failed: {e}"}), 500

    output_path = DATA_DIR / f"{campaign_id}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sections, f, indent=2, ensure_ascii=False)

    total = sum(len(s["entries"]) for s in sections)
    return jsonify({
        "campaign_id": campaign_id,
        "scenarios": len(sections),
        "entries": total,
    })


@app.route("/api/extract", methods=["POST"])
def api_extract():
    if "pdf" not in request.files:
        return jsonify({"error": "No PDF file uploaded"}), 400

    pdf_file = request.files["pdf"]
    if not pdf_file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "File must be a PDF"}), 400

    campaign_name = request.form.get("campaign_name", "").strip()
    if not campaign_name:
        campaign_name = Path(pdf_file.filename).stem

    campaign_id = re.sub(r"[^\w\s\-]", "", campaign_name)
    campaign_id = re.sub(r"\s+", "_", campaign_id).lower()[:60]

    pdf_path = BASE_DIR / "uploads" / pdf_file.filename
    pdf_path.parent.mkdir(exist_ok=True)
    pdf_file.save(str(pdf_path))

    try:
        sections = extract_sections(str(pdf_path))
    except Exception as e:
        return jsonify({"error": f"Extraction failed: {e}"}), 500

    output_path = DATA_DIR / f"{campaign_id}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sections, f, indent=2, ensure_ascii=False)

    total = sum(len(s["entries"]) for s in sections)
    return jsonify({
        "campaign_id": campaign_id,
        "scenarios": len(sections),
        "entries": total,
    })


@app.route("/api/campaign/<campaign_id>")
def api_campaign(campaign_id):
    path = DATA_DIR / f"{campaign_id}.json"
    if not path.exists():
        return jsonify({"error": "Campaign not found"}), 404

    with open(path) as f:
        data = json.load(f)

    _migrate_campaign_audio(campaign_id, data)
    for scenario in data:
        for entry in scenario["entries"]:
            audio_path = _resolve_audio_path(campaign_id, scenario, entry)
            entry["has_audio"] = audio_path.exists()

    return jsonify(data)


@app.route("/api/campaign/<campaign_id>/reorder-scenario", methods=["POST"])
def api_reorder_scenario(campaign_id):
    path = DATA_DIR / f"{campaign_id}.json"
    if not path.exists():
        return jsonify({"error": "Campaign not found"}), 404

    body = request.json
    from_idx = body.get("from_idx")
    to_idx = body.get("to_idx")

    with open(path) as f:
        data = json.load(f)

    if (from_idx is None or to_idx is None
            or from_idx >= len(data) or to_idx >= len(data)):
        return jsonify({"error": "Invalid indices"}), 400

    scenario = data.pop(from_idx)
    data.insert(to_idx, scenario)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return jsonify({"ok": True})


@app.route("/api/campaign/<campaign_id>", methods=["PUT"])
def api_update_campaign(campaign_id):
    path = DATA_DIR / f"{campaign_id}.json"
    if not path.exists():
        return jsonify({"error": "Campaign not found"}), 404

    data = request.json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return jsonify({"ok": True})


@app.route("/api/campaign/<campaign_id>/scenario", methods=["PATCH"])
def api_update_scenario(campaign_id):
    path = DATA_DIR / f"{campaign_id}.json"
    if not path.exists():
        return jsonify({"error": "Campaign not found"}), 404

    body = request.json
    scenario_idx = body.get("scenario_idx")
    new_name = body.get("scenario")

    with open(path) as f:
        data = json.load(f)

    if scenario_idx is None or scenario_idx >= len(data):
        return jsonify({"error": "Invalid scenario_idx"}), 400

    if new_name is not None:
        data[scenario_idx]["scenario"] = new_name

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return jsonify({"ok": True})


@app.route("/api/campaign/<campaign_id>/scenario", methods=["DELETE"])
def api_delete_scenario(campaign_id):
    path = DATA_DIR / f"{campaign_id}.json"
    if not path.exists():
        return jsonify({"error": "Campaign not found"}), 404

    body = request.json
    scenario_idx = body.get("scenario_idx")

    with open(path) as f:
        data = json.load(f)

    if scenario_idx is None or scenario_idx >= len(data):
        return jsonify({"error": "Invalid scenario_idx"}), 400

    scenario = data[scenario_idx]
    keep_audio = body.get("keep_audio", False)
    if not keep_audio:
        for entry in scenario["entries"]:
            audio_path = _resolve_audio_path(campaign_id, scenario, entry)
            if audio_path.exists():
                audio_path.unlink()

    data.pop(scenario_idx)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return jsonify({"ok": True})


@app.route("/api/campaign/<campaign_id>/subgroup", methods=["DELETE"])
def api_delete_subgroup(campaign_id):
    path = DATA_DIR / f"{campaign_id}.json"
    if not path.exists():
        return jsonify({"error": "Campaign not found"}), 404

    body = request.json
    si = body.get("scenario_idx")
    sg_name = body.get("subgroup")

    with open(path) as f:
        data = json.load(f)

    if si is None or si >= len(data):
        return jsonify({"error": "Invalid scenario_idx"}), 400

    entries = data[si]["entries"]
    keep_audio = body.get("keep_audio", False)
    if not keep_audio:
        for entry in entries:
            if entry.get("subgroup") == sg_name:
                audio_path = _resolve_audio_path(campaign_id, data[si], entry)
                if audio_path.exists():
                    audio_path.unlink()

    data[si]["entries"] = [e for e in entries if e.get("subgroup") != sg_name]

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return jsonify({"ok": True})


@app.route("/api/campaign/<campaign_id>/reorder-subgroup", methods=["POST"])
def api_reorder_subgroup(campaign_id):
    path = DATA_DIR / f"{campaign_id}.json"
    if not path.exists():
        return jsonify({"error": "Campaign not found"}), 404

    body = request.json
    si = body.get("scenario_idx")
    sg_name = body.get("subgroup")
    direction = body.get("direction")  # "before" or "after"
    target_sg = body.get("target_subgroup")  # None for ungrouped

    with open(path) as f:
        data = json.load(f)

    if si is None or si >= len(data):
        return jsonify({"error": "Invalid scenario_idx"}), 400

    entries = data[si]["entries"]
    sg_entries = [e for e in entries if e.get("subgroup") == sg_name]
    other_entries = [e for e in entries if e.get("subgroup") != sg_name]

    if target_sg is None:
        # Move before all subgroups (to ungrouped area)
        data[si]["entries"] = sg_entries + other_entries
    else:
        # Find first entry of target subgroup and insert before/after
        result = []
        inserted = False
        for e in other_entries:
            if not inserted and e.get("subgroup") == target_sg:
                if direction == "before":
                    result.extend(sg_entries)
                    inserted = True
            result.append(e)
            if not inserted and e.get("subgroup") == target_sg:
                # Check if next entry is different subgroup
                idx = other_entries.index(e)
                if idx + 1 >= len(other_entries) or other_entries[idx + 1].get("subgroup") != target_sg:
                    if direction == "after":
                        result.extend(sg_entries)
                        inserted = True
        if not inserted:
            result.extend(sg_entries)
        data[si]["entries"] = result

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return jsonify({"ok": True})


@app.route("/api/campaign/<campaign_id>/move-subgroup", methods=["POST"])
def api_move_subgroup(campaign_id):
    path = DATA_DIR / f"{campaign_id}.json"
    if not path.exists():
        return jsonify({"error": "Campaign not found"}), 404

    body = request.json
    from_si = body.get("from_si")
    to_si = body.get("to_si")
    sg_name = body.get("subgroup")
    target_sg = body.get("target_subgroup")

    with open(path) as f:
        data = json.load(f)

    if (from_si is None or to_si is None
            or from_si >= len(data) or to_si >= len(data)):
        return jsonify({"error": "Invalid indices"}), 400

    sg_entries = [e for e in data[from_si]["entries"] if e.get("subgroup") == sg_name]
    data[from_si]["entries"] = [e for e in data[from_si]["entries"] if e.get("subgroup") != sg_name]

    if target_sg is not None:
        insert_idx = None
        for i, e in enumerate(data[to_si]["entries"]):
            if e.get("subgroup") == target_sg:
                insert_idx = i
                break
        if insert_idx is not None:
            for j, e in enumerate(sg_entries):
                data[to_si]["entries"].insert(insert_idx + j, e)
        else:
            data[to_si]["entries"].extend(sg_entries)
    else:
        data[to_si]["entries"].extend(sg_entries)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return jsonify({"ok": True})


@app.route("/api/campaign/<campaign_id>/entry", methods=["PATCH"])
def api_update_entry(campaign_id):
    path = DATA_DIR / f"{campaign_id}.json"
    if not path.exists():
        return jsonify({"error": "Campaign not found"}), 404

    body = request.json
    scenario_idx = body.get("scenario_idx")
    entry_idx = body.get("entry_idx")
    new_label = body.get("display_label")
    new_text = body.get("text")
    new_subgroup = body.get("subgroup")

    with open(path) as f:
        data = json.load(f)

    if scenario_idx is None or entry_idx is None:
        return jsonify({"error": "scenario_idx and entry_idx required"}), 400
    if scenario_idx >= len(data) or entry_idx >= len(data[scenario_idx]["entries"]):
        return jsonify({"error": "Invalid index"}), 400

    entry = data[scenario_idx]["entries"][entry_idx]
    if new_label is not None:
        entry["display_label"] = new_label
    if new_subgroup is not None:
        entry["subgroup"] = new_subgroup if new_subgroup else None
    if new_text is not None:
        entry["text"] = new_text

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return jsonify({"ok": True})


@app.route("/api/campaign/<campaign_id>/reorder", methods=["POST"])
def api_reorder_entry(campaign_id):
    path = DATA_DIR / f"{campaign_id}.json"
    if not path.exists():
        return jsonify({"error": "Campaign not found"}), 404

    body = request.json
    si = body.get("scenario_idx")
    from_idx = body.get("from_idx")
    to_idx = body.get("to_idx")

    with open(path) as f:
        data = json.load(f)

    if si is None or from_idx is None or to_idx is None:
        return jsonify({"error": "scenario_idx, from_idx, and to_idx required"}), 400

    entries = data[si]["entries"]
    if from_idx >= len(entries) or to_idx >= len(entries):
        return jsonify({"error": "Invalid index"}), 400

    entry = entries.pop(from_idx)
    entries.insert(to_idx, entry)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return jsonify({"ok": True})


@app.route("/api/campaign/<campaign_id>/move-entry", methods=["POST"])
def api_move_entry(campaign_id):
    path = DATA_DIR / f"{campaign_id}.json"
    if not path.exists():
        return jsonify({"error": "Campaign not found"}), 404

    body = request.json
    from_si = body.get("from_si")
    from_ei = body.get("from_ei")
    to_si = body.get("to_si")
    to_ei = body.get("to_ei")

    with open(path) as f:
        data = json.load(f)

    if (from_si is None or from_ei is None or to_si is None
            or from_si >= len(data) or to_si >= len(data)
            or from_ei >= len(data[from_si]["entries"])):
        return jsonify({"error": "Invalid indices"}), 400

    entry = data[from_si]["entries"].pop(from_ei)

    if to_ei is None or to_ei >= len(data[to_si]["entries"]):
        data[to_si]["entries"].append(entry)
    else:
        data[to_si]["entries"].insert(to_ei, entry)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return jsonify({"ok": True})


@app.route("/api/campaign/<campaign_id>/generate-entry", methods=["POST"])
def api_generate_single_entry(campaign_id):
    path = DATA_DIR / f"{campaign_id}.json"
    if not path.exists():
        return jsonify({"error": "Campaign not found"}), 404

    settings = _load_settings()
    api_key = settings.get("api_key") or os.environ.get("ELEVENLABS_API_KEY")
    voice_id = settings.get("voice_id")
    model_id = settings.get("model_id", "eleven_multilingual_v2")

    if not api_key:
        return jsonify({"error": "No API key configured"}), 400
    if not voice_id:
        return jsonify({"error": "No voice selected"}), 400

    body = request.json
    si = body.get("scenario_idx")
    ei = body.get("entry_idx")

    with open(path) as f:
        data = json.load(f)

    if si is None or ei is None or si >= len(data) or ei >= len(data[si]["entries"]):
        return jsonify({"error": "Invalid index"}), 400

    scenario = data[si]
    entry = scenario["entries"][ei]

    old_audio = _resolve_audio_path(campaign_id, scenario, entry)
    if old_audio.exists():
        old_audio.unlink()

    new_rel = _build_audio_path(campaign_id, scenario, entry, ext='mp3')
    filepath = AUDIO_DIR / new_rel
    filepath.parent.mkdir(parents=True, exist_ok=True)

    try:
        generate_audio_entry(
            text=entry["text"],
            filepath=str(filepath),
            api_key=api_key,
            voice_id=voice_id,
            model_id=model_id,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    from datetime import datetime, timezone
    entry["audio_file"] = new_rel
    entry["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry["generated_model"] = model_id

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return jsonify({"ok": True, "size_kb": round(filepath.stat().st_size / 1024, 1)})


@app.route("/api/campaign/<campaign_id>/attach-audio", methods=["POST"])
def api_attach_audio(campaign_id):
    path = DATA_DIR / f"{campaign_id}.json"
    if not path.exists():
        return jsonify({"error": "Campaign not found"}), 404

    if "audio" not in request.files:
        return jsonify({"error": "No audio file uploaded"}), 400

    audio_file = request.files["audio"]
    ext = Path(audio_file.filename).suffix.lower()
    if ext not in AUDIO_EXTENSIONS:
        return jsonify({"error": f"Unsupported format. Use: {', '.join(AUDIO_EXTENSIONS)}"}), 400

    si = int(request.form.get("scenario_idx", -1))
    ei = int(request.form.get("entry_idx", -1))

    with open(path) as f:
        data = json.load(f)

    if si < 0 or si >= len(data) or ei < 0 or ei >= len(data[si]["entries"]):
        return jsonify({"error": "Invalid index"}), 400

    scenario = data[si]
    entry = scenario["entries"][ei]

    old_audio = _resolve_audio_path(campaign_id, scenario, entry)
    if old_audio.exists():
        old_audio.unlink()

    new_rel = _build_audio_path(campaign_id, scenario, entry, ext=ext.lstrip('.'))
    filepath = AUDIO_DIR / new_rel
    filepath.parent.mkdir(parents=True, exist_ok=True)
    audio_file.save(str(filepath))

    from datetime import datetime, timezone
    entry["audio_file"] = new_rel
    entry["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry["generated_model"] = "uploaded"

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return jsonify({"ok": True, "size_kb": round(filepath.stat().st_size / 1024, 1)})


@app.route("/api/campaign/<campaign_id>/entry", methods=["DELETE"])
def api_delete_entry(campaign_id):
    path = DATA_DIR / f"{campaign_id}.json"
    if not path.exists():
        return jsonify({"error": "Campaign not found"}), 404

    body = request.json
    scenario_idx = body.get("scenario_idx")
    entry_idx = body.get("entry_idx")

    with open(path) as f:
        data = json.load(f)

    if scenario_idx is None or entry_idx is None:
        return jsonify({"error": "scenario_idx and entry_idx required"}), 400
    if scenario_idx >= len(data) or entry_idx >= len(data[scenario_idx]["entries"]):
        return jsonify({"error": "Invalid index"}), 400

    entry = data[scenario_idx]["entries"][entry_idx]
    keep_audio = body.get("keep_audio", False)
    if not keep_audio:
        audio_path = _resolve_audio_path(campaign_id, data[scenario_idx], entry)
        if audio_path.exists():
            audio_path.unlink()

    data[scenario_idx]["entries"].pop(entry_idx)

    if len(data[scenario_idx]["entries"]) == 0:
        data.pop(scenario_idx)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return jsonify({"ok": True})


@app.route("/api/campaign/<campaign_id>", methods=["DELETE"])
def api_delete_campaign(campaign_id):
    body = request.get_json(silent=True) or {}
    keep_audio = body.get("keep_audio", False)
    path = DATA_DIR / f"{campaign_id}.json"
    if path.exists():
        path.unlink()
    if not keep_audio:
        old_dir = AUDIO_DIR / campaign_id
        if old_dir.exists():
            shutil.rmtree(old_dir)
        new_dir = AUDIO_DIR / _sanitize_for_path(campaign_id.replace("_", " ").title())
        if new_dir.exists():
            shutil.rmtree(new_dir)
    return jsonify({"ok": True})


@app.route("/api/generate/<campaign_id>", methods=["POST"])
def api_generate(campaign_id):
    path = DATA_DIR / f"{campaign_id}.json"
    if not path.exists():
        return jsonify({"error": "Campaign not found"}), 404

    settings = _load_settings()
    api_key = request.json.get("api_key") or settings.get("api_key") or os.environ.get("ELEVENLABS_API_KEY")
    voice_id = request.json.get("voice_id") or settings.get("voice_id")
    model_id = settings.get("model_id", "eleven_multilingual_v2")

    if not api_key:
        return jsonify({"error": "No API key configured"}), 400
    if not voice_id:
        return jsonify({"error": "No voice selected"}), 400

    with open(path) as f:
        sections = json.load(f)

    job_id = str(uuid.uuid4())[:8]

    total = sum(len(s["entries"]) for s in sections)
    generation_jobs[job_id] = {
        "status": "running",
        "total": total,
        "completed": 0,
        "errors": 0,
        "current": "",
    }

    def run_generation():
        job = generation_jobs[job_id]
        for scenario in sections:
            for entry in scenario["entries"]:
                existing = _resolve_audio_path(campaign_id, scenario, entry)
                if existing.exists():
                    job["completed"] += 1
                    continue

                new_rel = _build_audio_path(campaign_id, scenario, entry, ext='mp3')
                filepath = AUDIO_DIR / new_rel
                filepath.parent.mkdir(parents=True, exist_ok=True)

                job["current"] = f"{scenario['scenario']} / {entry['display_label']}"
                try:
                    generate_audio_entry(
                        text=entry["text"],
                        filepath=str(filepath),
                        api_key=api_key,
                        voice_id=voice_id,
                        model_id=model_id,
                    )
                    from datetime import datetime, timezone
                    entry["audio_file"] = new_rel
                    entry["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                    entry["generated_model"] = model_id
                    job["completed"] += 1
                except Exception as e:
                    job["errors"] += 1
                    job["current"] = f"Error: {e}"

                time.sleep(0.2)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(sections, f, indent=2, ensure_ascii=False)

        job["status"] = "complete"
        job["current"] = ""

    thread = threading.Thread(target=run_generation, daemon=True)
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/generate/status/<job_id>")
def api_generate_status(job_id):
    job = generation_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    s = _load_settings()
    return jsonify(s)


@app.route("/api/settings", methods=["PUT"])
def api_update_settings():
    settings = _load_settings()
    settings.update(request.json)
    _save_settings(settings)
    return jsonify({"ok": True})


@app.route("/api/credits")
def api_credits():
    settings = _load_settings()
    api_key = settings.get("api_key") or os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        return jsonify({"error": "No API key configured"}), 400

    import urllib.request
    req = urllib.request.Request(
        "https://api.elevenlabs.io/v1/user/subscription",
        headers={"xi-api-key": api_key},
    )
    try:
        with urllib.request.urlopen(req) as r:
            data = json.loads(r.read())
            return jsonify({
                "tier": data.get("tier"),
                "character_limit": data.get("character_limit"),
                "character_count": data.get("character_count"),
                "remaining": data.get("character_limit", 0) - data.get("character_count", 0),
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/arkhamdb/packs")
def api_arkhamdb_packs():
    cache_path = DATA_DIR / "_arkhamdb_packs.json"

    cycle_names = {
        1: "Core Set",
        2: "The Dunwich Legacy",
        3: "The Path to Carcosa",
        4: "The Forgotten Age",
        5: "The Circle Undone",
        6: "The Dream-Eaters",
        7: "The Innsmouth Conspiracy",
        8: "Edge of the Earth",
        9: "The Scarlet Keys",
        10: "The Feast of Hemlock Vale",
        11: "The Drowned City",
        12: "Core Set (2026)",
        13: "Children of Blood",
        50: "Return To...",
        60: "Investigator Starter Decks",
        61: "Investigator Starter Decks (2)",
        70: "Standalone Scenarios",
        80: "Promo / Books",
        90: "Challenge Scenarios",
    }

    def build_pack_list(raw_packs):
        return [
            {
                "code": p["code"],
                "name": p["name"],
                "cycle": cycle_names.get(p.get("cycle_position", 0), "Other"),
                "cycle_position": p.get("cycle_position", 99),
            }
            for p in raw_packs
        ]

    if cache_path.exists():
        with open(cache_path) as f:
            cached = json.load(f)
        def refresh_cache():
            import urllib.request
            try:
                req = urllib.request.Request(
                    "https://arkhamdb.com/api/public/packs/",
                    headers={"User-Agent": "ArkhamTTS/1.0"},
                )
                with urllib.request.urlopen(req, timeout=30) as r:
                    packs = json.loads(r.read())
                    with open(cache_path, "w") as fw:
                        json.dump(build_pack_list(packs), fw)
            except Exception:
                pass
        threading.Thread(target=refresh_cache, daemon=True).start()
        return jsonify(cached)

    import urllib.request
    req = urllib.request.Request(
        "https://arkhamdb.com/api/public/packs/",
        headers={"User-Agent": "ArkhamTTS/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            packs = json.loads(r.read())
            result = build_pack_list(packs)
            with open(cache_path, "w") as f:
                json.dump(result, f)
            return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"Could not reach ArkhamDB: {e}"}), 500


@app.route("/api/arkhamdb/import/<campaign_id>", methods=["POST"])
def api_arkhamdb_import(campaign_id):
    path = DATA_DIR / f"{campaign_id}.json"
    if not path.exists():
        return jsonify({"error": "Campaign not found"}), 404

    pack_code = request.json.get("pack_code")
    if not pack_code:
        return jsonify({"error": "Pack code required"}), 400

    import urllib.request
    import html as html_mod
    req = urllib.request.Request(
        f"https://arkhamdb.com/api/public/cards/{pack_code}",
        headers={"User-Agent": "ArkhamTTS/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            cards = json.loads(r.read())
    except Exception as e:
        return jsonify({"error": f"Failed to fetch from ArkhamDB: {e}"}), 500

    agenda_act = sorted(
        [c for c in cards if c.get("type_code") in ("agenda", "act")],
        key=lambda c: c.get("position", 0),
    )

    if not agenda_act:
        return jsonify({"error": "No agenda/act cards found in this pack"}), 404

    with open(path) as f:
        data = json.load(f)

    existing_scenarios = {
        s["scenario"].lower().replace(" ", ""): i for i, s in enumerate(data)
    }

    def clean_html(text):
        if not text:
            return ""
        text = re.sub(r"<[^>]+>", "", text)
        return html_mod.unescape(text).strip()

    def extract_italic_from_html(text):
        if not text:
            return ""
        parts = re.findall(r"<i>(.*?)</i>", text, re.DOTALL)
        if not parts:
            return ""
        cleaned = " ".join(clean_html(p) for p in parts if len(clean_html(p)) > 20)
        return cleaned

    def match_scenario(encounter_code):
        enc_clean = encounter_code.replace("_", "").lower()
        for name, idx in existing_scenarios.items():
            name_clean = re.sub(r"[^a-z0-9]", "", name)
            if enc_clean in name_clean or name_clean in enc_clean:
                return idx
        return None

    added = 0
    skipped = 0
    for card in agenda_act:
        card_type = card["type_code"].title()
        enc = card.get("encounter_code", "")
        si = match_scenario(enc)

        if si is None:
            scenario_name = enc.replace("_", " ").title()
            data.append({
                "scenario": scenario_name,
                "scenario_folder": re.sub(r"\s+", "_", scenario_name).lower()[:60],
                "entries": [],
            })
            si = len(data) - 1
            existing_scenarios[scenario_name.lower().replace(" ", "")] = si

        front_flavor = clean_html(card.get("flavor", ""))
        back_flavor = clean_html(card.get("back_flavor", ""))
        if not back_flavor:
            back_flavor = extract_italic_from_html(card.get("back_text", ""))

        sanitized = re.sub(r"[^\w\s\-]", "", card["name"])
        sanitized = re.sub(r"\s+", "_", sanitized).lower()[:60]

        existing_labels = {e["label"] for e in data[si]["entries"]}

        front_label = f"{card_type.lower()}_{sanitized}_front"
        if front_flavor and len(front_flavor) > 20:
            if front_label in existing_labels:
                skipped += 1
            else:
                data[si]["entries"].append({
                    "label": front_label,
                    "display_label": f"{card_type}: {card['name']} (Front)",
                    "text": front_flavor,
                    "page": 0,
                    "subgroup": f"{card_type} Deck",
                })
                added += 1

        back_label = f"{card_type.lower()}_{sanitized}_back"
        if back_flavor and len(back_flavor) > 20:
            if back_label in existing_labels:
                skipped += 1
            else:
                data[si]["entries"].append({
                    "label": back_label,
                    "display_label": f"{card_type}: {card['name']} (Back)",
                    "text": back_flavor,
                    "page": 0,
                    "subgroup": f"{card_type} Deck",
                })
                added += 1

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return jsonify({"ok": True, "added": added, "skipped": skipped, "cards": len(agenda_act)})


@app.route("/audio/<path:filepath>")
def serve_audio(filepath):
    return send_from_directory(str(AUDIO_DIR), filepath)


if __name__ == "__main__":
    print("\n  Arkham Horror TTS App")
    print("  Open http://localhost:5000 in your browser\n")
    app.run(debug=False, port=5000)
