import json

import pytest

import app as appmod
import auth


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DATA_DIR", tmp_path)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"api_key": "sk_secret_value_1234", "voice_id": "v1"}))
    monkeypatch.setattr(appmod, "SETTINGS_FILE", settings)
    monkeypatch.setattr(auth, "_failures", {})
    monkeypatch.setattr(auth, "_setup_token", "tok")
    return tmp_path


@pytest.fixture
def account(env):
    auth.set_credentials(env / "_auth.json", "sky", "correct horse")
    return env


def login(client, username="sky", password="correct horse"):
    return client.post("/login", data={"username": username, "password": password})


def test_no_account_redirects_to_setup(env):
    c = appmod.app.test_client()
    assert c.get("/").headers["Location"].endswith("/setup")
    assert c.get("/api/library").status_code == 401


def test_setup_requires_token(env):
    c = appmod.app.test_client()
    assert c.get("/setup").status_code == 403
    assert c.get("/setup?token=wrong").status_code == 403
    r = c.post("/setup", data={"token": "wrong", "username": "x", "password": "longenough", "confirm": "longenough"})
    assert r.status_code == 403
    assert not auth.has_account(env / "_auth.json")


def test_setup_creates_account_and_logs_in(env):
    c = appmod.app.test_client()
    assert c.get("/setup?token=tok").status_code == 200
    short = c.post("/setup", data={"token": "tok", "username": "sky", "password": "short", "confirm": "short"})
    assert b"at least 8" in short.data
    r = c.post("/setup", data={"token": "tok", "username": "sky", "password": "correct horse", "confirm": "correct horse"})
    assert r.status_code == 302
    assert c.get("/api/library").status_code == 200
    # Setup is closed once an account exists
    assert c.get("/setup?token=tok").headers["Location"].endswith("/login")


def test_password_stored_hashed(account):
    data = json.loads((account / "_auth.json").read_text())
    assert "correct horse" not in json.dumps(data)


def test_locked_until_login(account):
    c = appmod.app.test_client()
    assert c.get("/api/library").status_code == 401
    assert c.get("/audio/x.mp3").status_code == 302
    assert "/login" in c.get("/").headers["Location"]
    # Login page and its artwork stay public
    assert c.get("/login").status_code == 200
    assert c.get("/banner.jpg").status_code == 200


def test_wrong_password_then_right(account):
    c = appmod.app.test_client()
    assert login(c, password="nope").status_code == 401
    assert login(c, username="someone").status_code == 401
    assert login(c).status_code == 302
    assert c.get("/api/library").status_code == 200


def test_username_case_insensitive(account):
    c = appmod.app.test_client()
    assert login(c, username="SKY").status_code == 302


def test_lockout_after_repeated_failures(account):
    c = appmod.app.test_client()
    for _ in range(auth.MAX_FAILURES):
        login(c, password="nope")
    # Even the right password is refused while locked out
    assert login(c).status_code == 429
    assert c.get("/api/library").status_code == 401


def test_logout(account):
    c = appmod.app.test_client()
    login(c)
    c.post("/logout")
    assert c.get("/api/library").status_code == 401


def test_password_change_signs_out_sessions(account):
    c = appmod.app.test_client()
    login(c)
    auth.set_credentials(account / "_auth.json", "sky", "another password")
    assert c.get("/api/library").status_code == 401


def test_next_redirect_stays_on_site(account):
    c = appmod.app.test_client()
    r = c.post("/login?next=//evil.example", data={"username": "sky", "password": "correct horse"})
    assert r.headers["Location"] == "/"
    c2 = appmod.app.test_client()
    r = c2.post("/login?next=/api/library", data={"username": "sky", "password": "correct horse"})
    assert r.headers["Location"] == "/api/library"


def test_settings_never_return_api_key(account):
    c = appmod.app.test_client()
    login(c)
    s = c.get("/api/settings").json
    assert "api_key" not in s
    assert s["api_key_set"] is True and s["api_key_hint"] == "1234"
    assert "sk_secret" not in c.get("/api/settings").get_data(as_text=True)


def test_settings_blank_key_keeps_saved_key(account):
    c = appmod.app.test_client()
    login(c)
    c.put("/api/settings", json={"api_key": "", "voice_id": "v2"})
    saved = json.loads(appmod.SETTINGS_FILE.read_text())
    assert saved["api_key"] == "sk_secret_value_1234" and saved["voice_id"] == "v2"
    c.put("/api/settings", json={"api_key": "sk_new_key_9999"})
    assert json.loads(appmod.SETTINGS_FILE.read_text())["api_key"] == "sk_new_key_9999"
