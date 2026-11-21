import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

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


BOXART_URL = "https://static-cdn.jtvnw.net/ttv-boxart/{}-144x192.jpg"
UNKNOWN_GAMES = ("", "Unbekannt")


def game_image(game, stored=None):
    image = safe_image(stored)
    if image:
        return image
    if not isinstance(game, str) or game.strip() in UNKNOWN_GAMES:
        return None
    return BOXART_URL.format(quote(game.strip(), safe=""))


def _image_key(*parts):
    return tuple(str(p or "").strip().casefold() for p in parts)


def drop_image_index(raw_campaigns):
    index = {}
    for campaign in raw_campaigns:
        if not isinstance(campaign, dict):
            continue
        for drop in campaign.get("drops") or []:
            if not isinstance(drop, dict):
                continue
            image = safe_image(drop.get("bild"))
            if not image:
                continue
            for label in (drop.get("name"), drop.get("belohnung")):
                if not label:
                    continue
                index.setdefault(_image_key(campaign.get("kampagne"), label), image)
                index.setdefault(_image_key(campaign.get("spiel"), label), image)
    return index


def history_image(item, index):
    image = safe_image(item.get("item_art_url"))
    if image or not index:
        return image
    for scope in (item.get("campaign"), item.get("category")):
        for label in (item.get("item_name"), item.get("benefit")):
            found = index.get(_image_key(scope, label))
            if found:
                return found
    return None


def clean_campaign(item):
    if not isinstance(item, dict):
        return None
    status = text_or_none(item.get("status")) or ""
    return {
        "id": text_or_none(item.get("id")),
        "spiel": text_or_none(item.get("spiel")) or "",
        "spiel_bild": game_image(item.get("spiel"), item.get("spiel_bild")),
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
        "konto_verbunden": (
            item.get("konto_verbunden")
            if item.get("konto_verbunden") in ("ja", "nein", "unbekannt")
            else "unbekannt"
        ),
        "pausiert": status.startswith("pausiert"),
        "tages_drop": status.startswith("heute erledigt")
        or bool(item.get("naechster_start")),
        "drops": [d for d in (clean_drop(x) for x in item.get("drops") or []) if d],
    }


EXPIRED_STATUS = "abgelaufen"
COMPLETED_STATUS = "alles abgeholt"


def campaign_has_ended(campaign, now=None):
    if campaign["status"] in (EXPIRED_STATUS, COMPLETED_STATUS):
        return True
    end = campaign.get("ende_utc")
    if not end:
        return False
    try:
        ends_at = datetime.strptime(end, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return False
    return ends_at <= (now or datetime.now(timezone.utc))


def ended_campaign_row(campaign):
    drops_list = campaign["drops"]
    return {
        "spiel": campaign["spiel"],
        "spiel_bild": campaign["spiel_bild"],
        "kampagne": campaign["kampagne"],
        "endet": campaign["endet"],
        "ende_utc": campaign["ende_utc"],
        "abgeschlossen": campaign["status"] == COMPLETED_STATUS,
        "drops_gesamt": len(drops_list),
        "drops_abgeholt": sum(1 for d in drops_list if d["abgeholt"]),
    }


def drops_overview():
    data = read_json_file(campaigns_path())
    campaigns = []
    ended = []
    current = None
    updated = None
    images = {}
    if isinstance(data, dict):
        images = drop_image_index(data.get("kampagnen") or [])
        for item in data.get("kampagnen") or []:
            campaign = clean_campaign(item)
            if campaign is None:
                continue
            if campaign_has_ended(campaign):
                ended.append(ended_campaign_row(campaign))
            else:
                campaigns.append(campaign)
        ended.sort(key=lambda r: r["ende_utc"] or "", reverse=True)
        updated = text_or_none(data.get("aktualisiert"))
        raw_current = data.get("jetzt")
        if isinstance(raw_current, dict):
            current = {
                "kanal": text_or_none(raw_current.get("kanal")),
                "spiel": text_or_none(raw_current.get("spiel")),
                "kampagne": text_or_none(raw_current.get("kampagne")),
            }
    history = drop_history(images)
    history["kampagnen"] = ended
    history = remember_history(history)
    return {
        "kampagnen": campaigns,
        "jetzt": current,
        "aktualisiert": updated,
        "verlauf": history,
    }


HISTORY_FILE = "drop_history_eranio.json"
HISTORY_KEEP = 2000
HISTORY_KINDS = ("abgeholt", "abgelaufen", "kampagnen")
HISTORY_LOCK = threading.Lock()


def history_key(kind, row):
    if kind == "kampagnen":
        parts = (row.get("id"), row.get("spiel"), row.get("kampagne"))
        if not row.get("id"):
            parts = (None, row.get("spiel"), row.get("kampagne"), row.get("ende_utc"))
    else:
        parts = (
            row.get("drop_id"),
            row.get("campaign"),
            row.get("item_name"),
            row.get("benefit"),
        )
        if not row.get("drop_id"):
            parts = (row.get("category"),) + parts[1:]
    return kind + ":" + "|".join(str(p or "").casefold() for p in parts)


def history_sort_value(kind, row):
    if kind == "kampagnen":
        return row.get("ende_utc") or ""
    return row.get("datetime") or ""


def remember_history(current):
    analytics_path = getattr(Settings, "analytics_path", None)
    if not analytics_path:
        return {k: list(current.get(k) or [])[:HISTORY_LIMIT] for k in HISTORY_KINDS}
    path = os.path.join(analytics_path, HISTORY_FILE)
    with HISTORY_LOCK:
        stored = read_json_file(path)
        entries = stored.get("eintraege") if isinstance(stored, dict) else None
        known = {}
        changed = False
        for entry in entries if isinstance(entries, list) else []:
            if (
                isinstance(entry, dict)
                and entry.get("art") in HISTORY_KINDS
                and isinstance(entry.get("daten"), dict)
                and isinstance(entry.get("key"), str)
            ):
                key = history_key(entry["art"], entry["daten"])
                if key != entry["key"]:
                    entry = dict(entry, key=key)
                    changed = True
                earlier = known.get(key)
                if earlier is not None:
                    changed = True
                    if history_sort_value(
                        entry["art"], entry["daten"]
                    ) >= history_sort_value(earlier["art"], earlier["daten"]):
                        continue
                known[key] = entry
        for kind in HISTORY_KINDS:
            image_field = "spiel_bild" if kind == "kampagnen" else "item_art_url"
            for row in current.get(kind) or []:
                key = history_key(kind, row)
                entry = known.get(key)
                if entry is None:
                    known[key] = {"key": key, "art": kind, "daten": dict(row)}
                    changed = True
                elif not entry["daten"].get(image_field) and row.get(image_field):
                    entry["daten"][image_field] = row[image_field]
                    changed = True
        ordered = sorted(
            known.values(),
            key=lambda e: history_sort_value(e["art"], e["daten"]),
            reverse=True,
        )
        if len(ordered) > HISTORY_KEEP:
            ordered = ordered[:HISTORY_KEEP]
            changed = True
        if changed:
            try:
                temporary = path + ".tmp"
                with open(temporary, "w", encoding="utf-8") as handle:
                    json.dump({"version": 1, "eintraege": ordered}, handle)
                os.replace(temporary, path)
            except OSError:
                logger.warning("Der Drop-Verlauf konnte nicht gespeichert werden.")
    result = {kind: [] for kind in HISTORY_KINDS}
    for entry in ordered:
        if len(result[entry["art"]]) < HISTORY_LIMIT:
            result[entry["art"]].append(entry["daten"])
    return result


def drop_history(images=None):
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
            "item_art_url": history_image(item, images),
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
    drop_channels = set()
    pick = drops.STATE.drop_pick
    if pick:
        drop_channels.add(str(pick[0]).lower())
    campaigns = read_json_file(campaigns_path())
    if isinstance(campaigns, dict) and isinstance(campaigns.get("jetzt"), dict):
        channel = text_or_none(campaigns["jetzt"].get("kanal"), 60)
        if channel:
            drop_channels.add(channel.lower())
    result = []
    for entry in entries:
        login = text_or_none(entry.get("username"), 60)
        if not login:
            continue
        reasons = []
        if entry.get("reason") == "drops" or login.lower() in drop_channels:
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
            settings_enabled=getattr(server, "eranio_settings_enabled", False),
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
