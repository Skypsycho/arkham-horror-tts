"""ArkhamDB import endpoint, using saved pack responses (no network)."""
import io
import json
from pathlib import Path

import pytest

import app as appmod

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DATA_DIR", tmp_path)

    def fake_urlopen(req, timeout=None):
        pack = req.full_url.rsplit("/", 1)[-1]
        return io.BytesIO((FIXTURES / f"arkhamdb_{pack}.json").read_bytes())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return appmod.app.test_client()


def write_campaign(tmp_path, cid, scenario_names):
    data = [{"scenario": n, "scenario_folder": n.lower(), "entries": []} for n in scenario_names]
    (tmp_path / f"{cid}.json").write_text(json.dumps(data), encoding="utf-8")


def read_campaign(tmp_path, cid):
    return json.loads((tmp_path / f"{cid}.json").read_text(encoding="utf-8"))


def test_heart_of_the_elders_aliases(client, tmp_path):
    write_campaign(tmp_path, "tfa", [
        "Scenario IV: The Boundary Beyond",
        "Scenario V–A: Heart of the Elders, Part 1",
        "Scenario V–B: Heart of the Elders, Part 2",
    ])
    r = client.post("/api/arkhamdb/import/tfa", json={"pack_code": "hote"}).json
    assert r["ok"]
    data = read_campaign(tmp_path, "tfa")
    assert len(data) == 3, "no stray scenario groups"
    part1 = [e["display_label"] for e in data[1]["entries"]]
    part2 = [e["display_label"] for e in data[2]["entries"]]
    assert "Agenda: The Jungle's Heart (Front)" in part1
    assert "Act: Opening the Maw (Back)" in part1
    assert "Agenda: The Lonely Caverns (Front)" in part2
    assert "Act: Descent into Dark (Back)" in part2
    assert not data[0]["entries"]


def test_black_stars_rise_alternate_decks(client, tmp_path):
    write_campaign(tmp_path, "ptc", ["Scenario VII: Black Stars Rise", "Scenario VIII: Dim Carcosa"])
    r = client.post("/api/arkhamdb/import/ptc", json={"pack_code": "bsr"}).json
    assert r["ok"]
    data = read_campaign(tmp_path, "ptc")
    assert len(data) == 2, "vortex/flood must not become their own groups"
    entries = data[0]["entries"]
    labels = [e["label"] for e in entries]
    assert len(labels) == len(set(labels))
    displays = [e["display_label"] for e in entries]
    # shared front imported once, differing backs suffixed with the deck name
    assert displays.count("Agenda: Let The Storm Rage (Front)") == 1
    assert "Agenda: Let The Storm Rage – The Vortex Above (Back)" in displays
    assert "Agenda: Let The Storm Rage – The Flood Below (Back)" in displays
    assert "Agenda: The Entity Above – The Vortex Above (Back)" in displays
    assert "Agenda: The Entity Above – The Flood Below (Back)" in displays
    assert all(e["subgroup"] in ("Agenda Deck", "Act Deck") for e in entries)


def test_reimport_skips_everything(client, tmp_path):
    write_campaign(tmp_path, "ptc", ["Scenario VII: Black Stars Rise"])
    first = client.post("/api/arkhamdb/import/ptc", json={"pack_code": "bsr"}).json
    second = client.post("/api/arkhamdb/import/ptc", json={"pack_code": "bsr"}).json
    assert first["added"] > 0
    assert second["added"] == 0
    assert second["skipped"] == first["added"] + first["skipped"]


def test_deck_entries_placed_before_resolutions(client, tmp_path):
    data = [{"scenario": "Scenario VII: Black Stars Rise", "scenario_folder": "bsr", "entries": [
        {"label": "intro", "display_label": "Intro", "text": "x" * 50, "page": 1, "subgroup": None},
        {"label": "resolution_1", "display_label": "Resolution 1", "text": "y" * 50, "page": 2,
         "subgroup": "Resolutions"},
    ]}]
    (tmp_path / "ptc.json").write_text(json.dumps(data), encoding="utf-8")
    client.post("/api/arkhamdb/import/ptc", json={"pack_code": "bsr"})
    subgroups = [e.get("subgroup") for e in read_campaign(tmp_path, "ptc")[0]["entries"]]
    assert subgroups[0] is None
    assert subgroups[-1] == "Resolutions"
    assert set(subgroups[1:-1]) == {"Agenda Deck", "Act Deck"}
