import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path

from flask import Response, render_template_string, request

from TwitchChannelPointsMiner.classes.Settings import Settings
from TwitchChannelPointsMiner.config_editor import (
    NOTIFICATION_SCHEMAS,
    ConfigEditError,
)
from TwitchChannelPointsMiner.eranio import android, config_file, settings_model

logger = logging.getLogger(__name__)

COOKIE_NAME = "miner_settings"
SESSION_IDLE_SECONDS = 12 * 3600
MAX_FAILURES = 5
LOCKOUT_SECONDS = 10 * 60
ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets" / "eranio"
BASE_ONLY = [
    "Update-Prüfung des Programms (wird über run.py gesteuert)",
    "Sicherheitsoptionen wie das Abschalten der SSL-Prüfung",
    "Farbpalette der Logausgabe",
    "Wettfilter je Streamer (Bedingung, Wert)",
    "Eigene Quellenreihenfolge der Streamer-Quellen",
    "Ziel und Anschluss des Dashboards (immer aus run.py)",
]


class Auth:
    def __init__(self, password):
        self.digest = hashlib.sha256(str(password).encode("utf-8")).digest()
        self.lock = threading.Lock()
        self.sessions = {}
        self.failures = {}

    def locked_for(self, client, now=None):
        now = time.time() if now is None else now
        with self.lock:
            entry = self.failures.get(client)
            if entry and entry["until"] > now:
                return int(entry["until"] - now) + 1
            if entry and entry["until"] and entry["until"] <= now:
                del self.failures[client]
        return 0

    def check(self, client, password, now=None):
        now = time.time() if now is None else now
        remaining = self.locked_for(client, now)
        if remaining:
            return None, remaining
        supplied = hashlib.sha256(str(password or "").encode("utf-8")).digest()
        if hmac.compare_digest(supplied, self.digest):
            with self.lock:
                self.failures.pop(client, None)
                token = secrets.token_urlsafe(32)
                self.sessions[token] = now
            return token, 0
        with self.lock:
            entry = self.failures.setdefault(client, {"count": 0, "until": 0})
            entry["count"] += 1
            if entry["count"] >= MAX_FAILURES:
                entry["until"] = now + LOCKOUT_SECONDS
                entry["count"] = 0
        return None, 0

    def valid(self, token, now=None):
        now = time.time() if now is None else now
        if not token:
            return False
        with self.lock:
            for known, seen in list(self.sessions.items()):
                if now - seen > SESSION_IDLE_SECONDS:
                    del self.sessions[known]
            for known in self.sessions:
                if hmac.compare_digest(known.encode("utf-8"), token.encode("utf-8")):
                    self.sessions[known] = now
                    return True
        return False

    def end(self, token):
        with self.lock:
            self.sessions.pop(token, None)


def json_response(payload, status=200):
    response = Response(json.dumps(payload), status=status, mimetype="application/json")
    response.headers["Cache-Control"] = "no-store"
    return response


def read_view(miner_info):
    path = config_file.config_path()
    view = {
        "source": "config.py",
        "config_path": str(path),
        "editable": False,
        "readonly_reason": None,
        "settings": None,
        "spec": settings_model.spec_for_ui(),
        "notification_schemas": NOTIFICATION_SCHEMAS,
        "live": list(settings_model.LIVE_AREAS),
        "base_only": BASE_ONLY,
        "android": android.status(),
        "miner": miner_info,
    }
    if not path.is_file():
        view["readonly_reason"] = (
            "Es gibt keine Datei config.py. Die Einstellungen sind nur sichtbar, "
            "wenn der Miner über die Konfigurationsdatei gestartet wurde."
        )
        return view
    try:
        view["settings"] = settings_model.read_state(path)
        view["editable"] = True
    except Exception as error:
        view["readonly_reason"] = (
            f"Die Datei config.py hat nicht die erwartete Form und wird nur angezeigt, nicht verändert: {error}"
        )
    return view


def install(app, server, password, miner_info=None):
    auth = Auth(password)
    server.eranio_settings_enabled = True
    template = ASSETS_DIR / "settings.html"
    info = miner_info if miner_info is not None else (lambda: {})

    def client():
        return request.remote_addr or "unbekannt"

    def authenticated():
        return auth.valid(request.cookies.get(COOKIE_NAME))

    def require():
        if not authenticated():
            return json_response({"error": "Nicht angemeldet."}, 401)
        return None

    def asset_version():
        newest = 0
        for name in ("settings.js", "settings.css", "dashboard.css", "dark-theme.css"):
            try:
                newest = max(newest, os.path.getmtime(ASSETS_DIR / name))
            except OSError:
                pass
        return int(newest)

    def page():
        response = Response(
            render_template_string(
                template.read_text(encoding="utf-8"),
                server_name=os.environ.get("SERVER_NAME", "Twitch Miner"),
                asset_version=asset_version(),
            ),
            mimetype="text/html",
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    def session_view():
        return json_response({"authenticated": authenticated()})

    def login():
        body = request.get_json(silent=True) or {}
        token, locked = auth.check(client(), body.get("password"))
        if locked:
            return json_response(
                {"error": f"Zu viele Fehlversuche. Bitte in {locked // 60 + 1} Minuten erneut versuchen."},
                429,
            )
        if token is None:
            logger.warning("Fehlgeschlagene Anmeldung an der Einstellungsseite.")
            return json_response({"error": "Das Passwort ist falsch."}, 401)
        response = json_response({"ok": True})
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=SESSION_IDLE_SECONDS,
            httponly=True,
            samesite="Strict",
            path="/",
        )
        return response

    def logout():
        auth.end(request.cookies.get(COOKIE_NAME))
        response = json_response({"ok": True})
        response.delete_cookie(COOKIE_NAME, path="/")
        return response

    def state():
        denied = require()
        if denied:
            return denied
        return json_response(read_view(info()))

    def save():
        denied = require()
        if denied:
            return denied
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return json_response({"error": "Ungültige Anfrage."}, 400)
        try:
            if not config_file.exists():
                return json_response({"error": "Es gibt keine Datei config.py."}, 409)
            settings_model.update(config_file.config_path(), payload)
        except ConfigEditError as error:
            return json_response({"error": str(error)}, 400)
        except Exception as error:
            logger.warning("Einstellungen konnten nicht gespeichert werden: %s", error)
            return json_response(
                {"error": "Die Einstellungen konnten nicht gespeichert werden."}, 500
            )
        logger.info("Einstellung gespeichert (%s).", payload.get("action"))
        view = read_view(info())
        return json_response(view)

    def notification_test(provider):
        denied = require()
        if denied:
            return denied
        if provider not in NOTIFICATION_SCHEMAS:
            return json_response({"error": "Unbekannter Anbieter."}, 404)
        if not config_file.exists():
            return json_response(
                {"error": "Zuerst den Anbieter einrichten und speichern."}, 409
            )
        from TwitchChannelPointsMiner.classes.AnalyticsServer import (
            test_web_notification,
        )

        Settings.config_path = str(config_file.config_dir())
        response = test_web_notification(provider)
        status = response.status_code
        messages = {
            200: "Testnachricht gesendet.",
            409: "Anbieter zuerst einrichten und aktivieren.",
        }
        return json_response(
            {"message": messages.get(status, "Das Senden ist fehlgeschlagen.")}
            if status == 200
            else {"error": messages.get(status, "Das Senden ist fehlgeschlagen.")},
            status if status in (200, 409) else 502,
        )

    def android_submit():
        denied = require()
        if denied:
            return denied
        body = request.get_json(silent=True) or {}
        ok, message = android.submit(body.get("value"))
        return json_response(
            {"ok": ok, "message": message, "android": android.status()},
            200 if ok else 400,
        )

    app.add_url_rule("/settings", "eranio_settings", page, methods=["GET"])
    app.add_url_rule(
        "/settings/api/session", "eranio_settings_session", session_view, methods=["GET"]
    )
    app.add_url_rule(
        "/settings/api/login", "eranio_settings_login", login, methods=["POST"]
    )
    app.add_url_rule(
        "/settings/api/logout", "eranio_settings_logout", logout, methods=["POST"]
    )
    app.add_url_rule(
        "/settings/api/state", "eranio_settings_state", state, methods=["GET"]
    )
    app.add_url_rule(
        "/settings/api/save", "eranio_settings_save", save, methods=["POST"]
    )
    app.add_url_rule(
        "/settings/api/notifications/<string:provider>/test",
        "eranio_settings_notification_test",
        notification_test,
        methods=["POST"],
    )
    app.add_url_rule(
        "/settings/api/android", "eranio_settings_android", android_submit, methods=["POST"]
    )
    return auth
