"""Bulk generation endpoint: scoping to a scenario / subgroup, skipping entries
with audio, and keeping edits made while a job runs. TTS is faked."""
import json
import threading
import time

import pytest

import app as appmod


def entry(label, text, subgroup=None):
    e = {"label": label, "display_label": label, "text": text}
    if subgroup:
        e["subgroup"] = subgroup
    return e


CAMPAIGN = [
    {"scenario": "Scenario I: The Gathering", "scenario_folder": "gathering", "entries": [
        entry("Intro", "It is a dark night."),
        entry("Agenda: What's Going On?! (Front)", "Rats in the walls.", "Agenda Deck"),
        entry("Agenda: What's Going On?! (Back)", "They are coming.", "Agenda Deck"),
        entry("Act: Trapped (Front)", "The door is locked.", "Act Deck"),
    ]},
    {"scenario": "Scenario II: The Midnight Masks", "scenario_folder": "masks", "entries": [
        entry("Intro", "The cult is everywhere."),
        entry("Blank", "   "),
    ]},
]


@pytest.fixture
def env(tmp_path, monkeypatch):
    data_dir, audio_dir = tmp_path / "data", tmp_path / "audio"
    data_dir.mkdir()
    audio_dir.mkdir()
    monkeypatch.setattr(appmod, "DATA_DIR", data_dir)
    monkeypatch.setattr(appmod, "AUDIO_DIR", audio_dir)
    monkeypatch.setattr(appmod, "_load_settings", lambda: {"api_key": "k" * 20, "voice_id": "v"})
    monkeypatch.setitem(appmod.app.config, "AUTH_DISABLED", True)
    monkeypatch.setattr(appmod.time, "sleep", lambda s: None)
    appmod.generation_jobs.clear()

    calls = []
    gate = threading.Event()
    gate.set()

    def fake_tts(text, filepath, api_key, voice_id, model_id):
        gate.wait(5)
        calls.append(text)
        with open(filepath, "wb") as f:
            f.write(b"ID3fake")

    monkeypatch.setattr(appmod, "generate_audio_entry", fake_tts)
    (data_dir / "notz.json").write_text(json.dumps(CAMPAIGN), encoding="utf-8")

    class Env:
        client = appmod.app.test_client()

        def read(self):
            return json.loads((data_dir / "notz.json").read_text(encoding="utf-8"))

        def write(self, data):
            (data_dir / "notz.json").write_text(json.dumps(data), encoding="utf-8")

        def wait(self, job_id):
            for _ in range(200):
                job = self.client.get(f"/api/generate/status/{job_id}").json
                if job["status"] == "complete":
                    return job
                threading.Event().wait(0.02)
            raise AssertionError("job did not finish")

    env = Env()
    env.calls, env.gate = calls, gate
    return env


def test_subgroup_scope(env):
    r = env.client.post("/api/generate/notz", json={"scenario_idx": 0, "subgroup": "Agenda Deck"}).json
    assert r["total"] == 2
    job = env.wait(r["job_id"])
    assert job["completed"] == 2 and job["errors"] == 0
    assert job["scope"] == "Agenda Deck"
    assert env.calls == ["Rats in the walls.", "They are coming."]
    entries = env.read()[0]["entries"]
    assert [bool(e.get("audio_file")) for e in entries] == [False, True, True, False]


def test_scenario_scope_then_campaign_skips_existing(env):
    job = env.wait(env.client.post("/api/generate/notz", json={"scenario_idx": 0}).json["job_id"])
    assert job["completed"] == 4
    r = env.client.post("/api/generate/notz", json={}).json
    assert r["total"] == 1, "only Scenario II's intro is left; blank text is skipped"
    env.wait(r["job_id"])
    assert env.calls[-1] == "The cult is everywhere."
    data = env.client.get("/api/campaign/notz").json
    assert [e["has_audio"] for s in data for e in s["entries"]] == [True] * 5 + [False]


def test_edits_during_job_are_kept(env):
    env.gate.clear()  # hold the first TTS call
    job_id = env.client.post("/api/generate/notz", json={"scenario_idx": 1}).json["job_id"]
    threading.Event().wait(0.1)
    data = env.read()
    data[0]["scenario"] = "Renamed while generating"
    data.reverse()  # and move Scenario II to the top
    env.write(data)
    env.gate.set()
    env.wait(job_id)
    data = env.read()
    assert data[1]["scenario"] == "Renamed while generating"
    assert data[0]["entries"][0].get("audio_file"), "moved entry still gets its audio"


def test_one_job_per_campaign(env):
    env.gate.clear()
    first = env.client.post("/api/generate/notz", json={}).json["job_id"]
    r = env.client.post("/api/generate/notz", json={"scenario_idx": 0})
    assert r.status_code == 409 and r.json["job_id"] == first
    assert env.client.get("/api/generate/active/notz").json["job_id"] == first
    env.gate.set()
    env.wait(first)
    assert env.client.get("/api/generate/active/notz").json["job_id"] is None


def test_bad_scope(env):
    assert env.client.post("/api/generate/notz", json={"scenario_idx": 9}).status_code == 400
    assert env.client.post("/api/generate/notz", json={"subgroup": "Act Deck"}).status_code == 400
