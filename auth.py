"""
Single-user login for the web app.

Credentials and the session secret live in a JSON file (data/_auth.json by
default). With no account yet, every request is sent to /setup, which only
accepts a one-time token printed in the server console — so a freshly
started instance on the internet can't be claimed by a stranger.

Reset a forgotten password from the command line:
    python arkham_tts.py set-password
"""

import json
import os
import secrets
import sys
import threading
import time
from datetime import timedelta

from flask import (jsonify, redirect, render_template, request, session,
                   url_for)
from werkzeug.security import check_password_hash, generate_password_hash

MIN_PASSWORD_LEN = 8
MAX_FAILURES = 5                 # failed logins per IP …
LOCKOUT_SECONDS = 15 * 60        # … within this window → locked out for it

# Reachable without logging in (login page and its artwork)
PUBLIC_ENDPOINTS = {"auth_login", "auth_setup", "auth_logout", "static",
                    "serve_banner", "serve_background"}

_lock = threading.Lock()
_failures = {}                   # ip -> [count, first_failure_ts]
_setup_token = None


# ── Credential file ──

def load_auth(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_auth(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def has_account(path):
    data = load_auth(path)
    return bool(data.get("username") and data.get("password_hash"))


def set_credentials(path, username, password):
    data = load_auth(path)
    data["username"] = username
    data["password_hash"] = generate_password_hash(password)
    # Changing the password signs out every existing session
    data["session_version"] = secrets.token_hex(8)
    data.setdefault("secret_key", secrets.token_hex(32))
    save_auth(path, data)
    return data


def _secret_key(path):
    data = load_auth(path)
    if not data.get("secret_key"):
        data["secret_key"] = secrets.token_hex(32)
        save_auth(path, data)
    return data["secret_key"]


def _validate(username, password, confirm=None):
    if not username:
        return "Choose a username."
    if len(password) < MIN_PASSWORD_LEN:
        return f"The password needs at least {MIN_PASSWORD_LEN} characters."
    if confirm is not None and password != confirm:
        return "The passwords don't match."
    return None


# ── Brute-force throttle ──

def _locked_out(ip):
    with _lock:
        rec = _failures.get(ip)
        if not rec:
            return False
        if time.time() - rec[1] > LOCKOUT_SECONDS:
            del _failures[ip]
            return False
        return rec[0] >= MAX_FAILURES


def _record_failure(ip):
    with _lock:
        rec = _failures.get(ip)
        if not rec or time.time() - rec[1] > LOCKOUT_SECONDS:
            _failures[ip] = [1, time.time()]
        else:
            rec[0] += 1


def _clear_failures(ip):
    with _lock:
        _failures.pop(ip, None)


def _get_setup_token():
    global _setup_token
    if _setup_token is None:
        _setup_token = secrets.token_urlsafe(24)
        print("\n  No login account yet. Open /setup?token=... on the app's address")
        print(f"  to create it (one-time link), e.g. http://localhost:5000/setup?token={_setup_token}\n", flush=True)
    return _setup_token


# ── Flask wiring ──

def init_app(app, auth_path_fn):
    """auth_path_fn() returns the credentials file path (called per request,
    so tests can point it somewhere else)."""
    app.secret_key = _secret_key(auth_path_fn())
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    # "auto" (default): HTTPS-only cookie when the request came in over HTTPS
    # (e.g. via the reverse proxy), plain cookie on the home network over HTTP
    secure_mode = os.environ.get("ARKHAM_SECURE_COOKIES", "auto")
    app.config["SESSION_COOKIE_SECURE"] = secure_mode == "1"
    if secure_mode == "auto":
        from flask.sessions import SecureCookieSessionInterface

        class _AutoSecureSessions(SecureCookieSessionInterface):
            def get_cookie_secure(self, app):
                return request.is_secure

        app.session_interface = _AutoSecureSessions()
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

    if os.environ.get("ARKHAM_TRUST_PROXY") == "1":
        # Behind a reverse proxy: take the client IP / scheme from its headers
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    if not has_account(auth_path_fn()):
        _get_setup_token()

    def logged_in():
        data = load_auth(auth_path_fn())
        return (session.get("user")
                and session.get("user") == data.get("username")
                and session.get("v") == data.get("session_version"))

    @app.before_request
    def require_login():
        if app.config.get("AUTH_DISABLED") or request.endpoint in PUBLIC_ENDPOINTS:
            return None
        if logged_in():
            return None
        if request.path.startswith("/api/"):
            return jsonify({"error": "Not logged in"}), 401
        if not has_account(auth_path_fn()):
            return redirect(url_for("auth_setup"))
        return redirect(url_for("auth_login", next=request.full_path.rstrip("?")))

    def _start_session(data):
        session.clear()
        session.permanent = True
        session["user"] = data["username"]
        session["v"] = data.get("session_version")

    def _safe_next(target):
        # Only redirect back within this site
        if target and target.startswith("/") and not target.startswith("//"):
            return target
        return url_for("index")

    @app.route("/login", methods=["GET", "POST"], endpoint="auth_login")
    def login():
        path = auth_path_fn()
        if not has_account(path):
            return redirect(url_for("auth_setup"))
        if logged_in():
            return redirect(url_for("index"))
        error, status = None, 200
        ip = request.remote_addr or "?"
        if request.method == "POST":
            if _locked_out(ip):
                error, status = "Too many failed attempts. Try again in 15 minutes.", 429
            else:
                data = load_auth(path)
                username = request.form.get("username", "").strip()
                password = request.form.get("password", "")
                # Always check the hash so a wrong username takes as long as a wrong password
                ok = check_password_hash(data["password_hash"], password)
                if ok and secrets.compare_digest(username.lower(), data["username"].lower()):
                    _clear_failures(ip)
                    _start_session(data)
                    return redirect(_safe_next(request.args.get("next")))
                _record_failure(ip)
                error, status = "Wrong username or password.", 401
        return render_template("login.html", mode="login", error=error,
                               username=request.form.get("username", "")), status

    @app.route("/setup", methods=["GET", "POST"], endpoint="auth_setup")
    def setup():
        path = auth_path_fn()
        if has_account(path):
            return redirect(url_for("auth_login"))
        token = request.values.get("token", "")
        if not secrets.compare_digest(token, _get_setup_token()):
            return render_template("login.html", mode="need-token"), 403
        error = None
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            error = _validate(username, password, request.form.get("confirm", ""))
            if not error:
                data = set_credentials(path, username, password)
                _start_session(data)
                return redirect(url_for("index"))
        return render_template("login.html", mode="setup", error=error, token=token,
                               username=request.form.get("username", ""))

    @app.route("/logout", methods=["POST"], endpoint="auth_logout")
    def logout():
        session.clear()
        return redirect(url_for("auth_login"))

    @app.route("/api/me")
    def api_me():
        return jsonify({"username": session.get("user")})


# ── CLI ──

def cli_set_password(path):
    import getpass
    current = load_auth(path).get("username", "")
    prompt = f"Username [{current}]: " if current else "Username: "
    username = input(prompt).strip() or current
    password = getpass.getpass("New password: ")
    confirm = getpass.getpass("Repeat password: ")
    error = _validate(username, password, confirm)
    if error:
        print(error)
        sys.exit(1)
    set_credentials(path, username, password)
    print(f"Saved. Log in as '{username}'. Existing sessions are signed out.")
