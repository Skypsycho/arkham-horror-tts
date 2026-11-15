"""The "Update from guide" endpoint: preview, apply with backup, campaigns without
a catalog guide. Extraction and the PDF download are faked."""
import json

import pytest

import app as appmod


def entry(label, text, **kw):
    return {"label": label.lower().replace(" ", "_"), "display_label": label, "text": text, **kw}


OLD_TEXT = ("You decide to lay low for some time in the boarding house while the "
            "story of the asylum spreads through the town and the papers.")
NEW_TEXT = OLD_TEXT + " Daniel has written: Carcosa is real, do not let them open the path."
DREAM = "Daniel’s voice calls out to you. “They are opening the path to Carcosa.”"

EXISTING = [{"scenario": "Interlude II: Lost Soul", "scenario_folder": "lost_soul", "entries": [
    entry("Daniel Was Possessed", OLD_TEXT, page=16),
]}]
EXTRACTED = [{"scenario": "Interlude II: Lost Soul", "scenario_folder": "lost_soul", "entries": [
    entry("Daniel Was Possessed", NEW_TEXT, page=16),
    entry("Dream 13", DREAM, page=16),
]}]


@pytest.fixture
def env(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(appmod, "DATA_DIR", data_dir)
    monkeypatch.setattr(appmod, "AUDIO_DIR", tmp_path / "audio")
    monkeypatch.setitem(appmod.app.config, "AUTH_DISABLED", True)
    monkeypatch.setattr(appmod, "_ensure_guide_pdf", lambda guide: tmp_path / "guide.pdf")
    monkeypatch.setattr(appmod, "extract_sections", lambda path: json.loads(json.dumps(EXTRACTED)))
    (data_dir / "the_path_to_carcosa.json").write_text(json.dumps(EXISTING), encoding="utf-8")
    (data_dir / "my_homebrew.json").write_text(json.dumps(EXISTING), encoding="utf-8")
    return appmod.app.test_client(), data_dir


def read(data_dir, cid):
    return json.loads((data_dir / f"{cid}.json").read_text(encoding="utf-8"))


def test_preview_changes_nothing(env):
    client, data_dir = env
    r = client.post("/api/campaign/the_path_to_carcosa/merge-extraction", json={}).json
    assert r["changed"] and not r["applied"]
    actions = {s["action"]: s for s in r["sections"]}
    assert actions["update-text"]["items"][0]["label"] == "Daniel Was Possessed"
    assert actions["add"]["items"][0]["label"] == "Dream 13"
    assert (r["entries_before"], r["entries_after"]) == (1, 2)
    assert read(data_dir, "the_path_to_carcosa") == EXISTING
    assert not (data_dir / "_backups").exists()


def test_apply_saves_with_backup(env):
    client, data_dir = env
    r = client.post("/api/campaign/the_path_to_carcosa/merge-extraction", json={"apply": True}).json
    assert r["applied"] and r["backup"].startswith("data/_backups/the_path_to_carcosa-")
    texts = [e["text"] for e in read(data_dir, "the_path_to_carcosa")[0]["entries"]]
    assert texts == [NEW_TEXT, DREAM]
    backups = list((data_dir / "_backups").glob("the_path_to_carcosa-*.json"))
    assert len(backups) == 1 and json.loads(backups[0].read_text(encoding="utf-8")) == EXISTING
    # a second run has nothing left to do
    again = client.post("/api/campaign/the_path_to_carcosa/merge-extraction", json={"apply": True}).json
    assert not again["changed"] and not again["applied"]


def test_campaign_without_guide(env):
    client, _ = env
    r = client.post("/api/campaign/my_homebrew/merge-extraction", json={})
    assert r.status_code == 400
    library = {c["id"]: c["has_guide"] for c in client.get("/api/library").json}
    assert library == {"the_path_to_carcosa": True, "my_homebrew": False}


def test_unknown_campaign(env):
    client, _ = env
    assert client.post("/api/campaign/nope/merge-extraction", json={}).status_code == 404
