import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests
from flask import Response, abort, render_template_string, request, send_from_directory

from TwitchChannelPointsMiner import __version__
from TwitchChannelPointsMiner.classes.Settings import Settings
from TwitchChannelPointsMiner.eranio import drops, streak
from TwitchChannelPointsMiner.utils.Utils import is_newer_version

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets" / "eranio"
IMAGE_HOST_SUFFIXES = ("jtvnw.net", "twitchcdn.net", "twitch.tv", "ttvnw.net")
UPDATE_SOURCE = (
    "https://raw.githubusercontent.com/Erani0/Twitch-Channel-Points-Miner-v2/"
    "master/TwitchChannelPointsMiner/__init__.py"
)
UPDATE_TTL_SECONDS = 6 * 3600
UPDATE_FAILURE_TTL_SECONDS = 30 * 60
HISTORY_LIMIT = 200
STATIC_EXTENSIONS = {".css", ".js", ".png", ".ico", ".svg", ".jpg", ".jpeg", ".gif"}
VERSION_PATTERN = re.compile(r'__version__\s*=\s*"(\d+\.\d+\.\d+)"')


def safe_image(url):
    if not isinstance(url, str) or not url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        return None
    for suffix in IMAGE_HOST_SUFFIXES:
        if host == suffix or host.endswith("." + suffix):
            return url
    return None


def text_or_none(value, limit=300):
    if value is None:
        return None
    return str(value)[:limit]


def number_or_zero(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return value


def json_response(payload, status=200):
    return Response(json.dumps(payload), status=status, mimetype="application/json")


def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def campaigns_path():
    file = getattr(drops.STATE, "file", None)
    path = getattr(file, "path", None)
    return str(path) if path else drops.DEFAULT_PATH


def clean_drop(item):
    if not isinstance(item, dict):
        return None
    return {
        "name": text_or_none(item.get("name")),
        "belohnung": text_or_none(item.get("belohnung")),
        "bild": safe_image(item.get("bild")),
        "minuten_noetig": number_or_zero(item.get("minuten_noetig")),
        "minuten_aktuell": number_or_zero(item.get("minuten_aktuell")),
        "abo_noetig": item.get("abo_noetig") is True,
        "abgeholt": item.get("abgeholt") is True,
    }


def clean_campaign(item):
    if not isinstance(item, dict):
        return None
    status = text_or_none(item.get("status")) or ""
    return {
        "id": text_or_none(item.get("id")),
        "spiel": text_or_none(item.get("spiel")) or "",
        "spiel_bild": safe_image(item.get("spiel_bild")),
        "kampagne": text_or_none(item.get("kampagne")) or "",
        "aktiv": item.get("aktiv") is not False,
        "status": status,
        "endet": text_or_none(item.get("endet")),
        "ende_utc": text_or_none(item.get("ende_utc")),
        "offen": text_or_none(item.get("offen")),
        "naechster_drop": text_or_none(item.get("naechster_drop")),
        "naechster_start": text_or_none(item.get("naechster_start")),
        "art": "Quest" if item.get("art") == "Quest" else "Drop-Kampagne",
        "abo_noetig": item.get("abo_noetig") == "ja",
        "konto_verbunden": item.get("konto_verbunden")
        if item.get("konto_verbunden") in ("ja", "nein", "unbekannt")
        else "unbekannt",
        "pausiert": status.startswith("pausiert"),
        "tages_drop": status.startswith("heute erledigt")
        or bool(item.get("naechster_start")),
        "drops": [d for d in (clean_drop(x) for x in item.get("drops") or []) if d],
    }


def drops_overview():
    data = read_json_file(campaigns_path())
    campaigns = []
    current = None
    updated = None
    if isinstance(data, dict):
        campaigns = [
            c
            for c in (clean_campaign(x) for x in data.get("kampagnen") or [])
            if c is not None
        ]
        updated = text_or_none(data.get("aktualisiert"))
        raw_current = data.get("jetzt")
        if isinstance(raw_current, dict):
            current = {
                "kanal": text_or_none(raw_current.get("kanal")),
                "spiel": text_or_none(raw_current.get("spiel")),
                "kampagne": text_or_none(raw_current.get("kampagne")),
            }
    return {
        "kampagnen": campaigns,
        "jetzt": current,
        "aktualisiert": updated,
        "verlauf": drop_history(),
    }


def drop_history():
    analytics_path = getattr(Settings, "analytics_path", None)
    if not analytics_path:
        return {"abgeholt": [], "abgelaufen": []}
    data = read_json_file(os.path.join(analytics_path, "drops_by_category.json"))
    entries = data.get("drops") if isinstance(data, dict) else None
    claimed = []
    expired = []
    for item in entries if isinstance(entries, list) else []:
        if not isinstance(item, dict):
            continue
        row = {
            "x": number_or_zero(item.get("x")),
            "datetime": text_or_none(item.get("datetime")),
            "category": text_or_none(item.get("category")) or "",
            "campaign": text_or_none(item.get("campaign")),
            "item_name": text_or_none(item.get("item_name")),
            "benefit": text_or_none(item.get("benefit")),
            "streamer": text_or_none(item.get("streamer")),
            "minutes_required": number_or_zero(item.get("minutes_required")),
            "current_minutes_watched": number_or_zero(
                item.get("current_minutes_watched")
            ),
            "item_art_url": safe_image(item.get("item_art_url")),
        }
        if item.get("status") == "captured":
            claimed.append(row)
        elif item.get("status") == "failed" or item.get("failed_to_achieve") is True:
            expired.append(row)
    claimed.sort(key=lambda r: r["x"], reverse=True)
    expired.sort(key=lambda r: r["x"], reverse=True)
    return {"abgeholt": claimed[:HISTORY_LIMIT], "abgelaufen": expired[:HISTORY_LIMIT]}


def streak_days_of(login):
    track = streak.STATE.tracks.get(login)
    if track is not None and track.value is not None:
        return track.value
    return streak.STATE.known_length.get(login)


def now_watching_overview():
    analytics_path = getattr(Settings, "analytics_path", None)
    entries = []
    if analytics_path:
        data = read_json_file(os.path.join(analytics_path, "now_watching.json"))
        if isinstance(data, list):
            entries = [e for e in data if isinstance(e, dict)]
    result = []
    for entry in entries:
        login = text_or_none(entry.get("username"), 60)
        if not login:
            continue
        reasons = []
        if entry.get("reason") == "drops":
            reasons.append("Drop")
        elif entry.get("reason") == "badge":
            reasons.append("Badge")
        track = streak.STATE.tracks.get(login)
        if track is not None and not track.done and not track.gave_up:
            reasons.append("Streak")
        if not reasons:
            reasons.append("Points")
        result.append(
            {
                "username": login,
                "reasons": reasons,
                "game": text_or_none(entry.get("game")),
                "channel_points": number_or_zero(entry.get("channel_points")),
                "streak_days": streak_days_of(login),
            }
        )
    info = streak.loan_info()
    return {
        "channels": result,
        "streak_loan": {
            "active": info.active,
            "login": info.login,
            "expires_at": info.expires_at,
        },
    }


def last_streak_days(analytics_file):
    data = read_json_file(analytics_file)
    series = data.get("streak") if isinstance(data, dict) else None
    if isinstance(series, list) and series and isinstance(series[-1], dict):
        value = series[-1].get("y")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    return None


class UpdateInfo:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.latest = None
        self.checked_at = None
        self.failed = False


UPDATE = UpdateInfo()


def fetch_latest_version():
    response = requests.get(UPDATE_SOURCE, timeout=(5, 10))
    response.raise_for_status()
    found = VERSION_PATTERN.search(response.text)
    return found.group(1) if found else None


def update_info(now=None):
    now = time.time() if now is None else now
    with UPDATE.lock:
        ttl = UPDATE_FAILURE_TTL_SECONDS if UPDATE.failed else UPDATE_TTL_SECONDS
        if UPDATE.checked_at is None or now - UPDATE.checked_at >= ttl:
            UPDATE.checked_at = now
            try:
                UPDATE.latest = fetch_latest_version()
                UPDATE.failed = UPDATE.latest is None
            except Exception:
                UPDATE.latest = None
                UPDATE.failed = True
        latest = UPDATE.latest
    available = latest is not None and is_newer_version(latest, __version__)
    return {"available": available, "latest": latest if available else None}


def install(app, server):
    from TwitchChannelPointsMiner.classes import AnalyticsServer as base

    template_path = ASSETS_DIR / "index.html"

    def asset_version():
        newest = 0
        for name in ("dashboard.js", "dashboard.css", "dark-theme.css"):
            try:
                newest = max(newest, os.path.getmtime(ASSETS_DIR / name))
            except OSError:
                pass
        return int(newest)

    def index(refresh=5, days_ago=7, log_poll_interval=5):
        source = template_path.read_text(encoding="utf-8")
        return render_template_string(
            source,
            refresh=refresh * 60 * 1000,
            daysAgo=days_ago,
            logPollInterval=log_poll_interval * 1000,
            server_name=os.environ.get("SERVER_NAME", "Twitch Miner"),
            asset_version=asset_version(),
        )

    def streamers():
        cached = base.response_cache.get("streamers_eranio")
        if cached is not None:
            return Response(cached, status=200, mimetype="application/json")
        rows = []
        for name in sorted(base.streamers_available()):
            summary = base.get_streamer_summary(name)
            rows.append(
                {
                    "name": name,
                    **summary,
                    "watch_streak_days": last_streak_days(
                        os.path.join(Settings.analytics_path, name)
                    ),
                }
            )
        payload = json.dumps(rows)
        base.response_cache.set("streamers_eranio", payload)
        return Response(payload, status=200, mimetype="application/json")

    def static(filename):
        if os.path.splitext(filename)[1].lower() not in STATIC_EXTENSIONS:
            abort(404)
        return send_from_directory(ASSETS_DIR, filename, max_age=0)

    def not_available(*args, **kwargs):
        abort(404)

    def guard():
        if request.path.startswith("/config"):
            abort(404)
        if (
            server.host in base.LOOPBACK_HOSTS
            and base._request_hostname(request.host) not in base.LOOPBACK_HOSTS
        ):
            return json_response({"error": "Unrecognized Host header."}, 403)
        return None

    def drops_view():
        return json_response(drops_overview())

    def watching_view():
        return json_response(now_watching_overview())

    def update_view():
        return json_response(update_info())

    functions = app.view_functions
    functions["streamers"] = streamers
    functions["static"] = static
    functions["web_config"] = not_available
    functions["test_web_notification"] = not_available
    functions["index"] = index
    app.before_request_funcs.setdefault(None, []).insert(0, guard)
    app.add_url_rule("/drops", "eranio_drops", drops_view, methods=["GET"])
    app.add_url_rule("/watching", "eranio_watching", watching_view, methods=["GET"])
    app.add_url_rule("/update_info", "eranio_update", update_view, methods=["GET"])
