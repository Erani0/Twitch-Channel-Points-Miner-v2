import json
import logging
import os
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DEFAULT_PATH = "drop_campaigns.json"

HINT = [
    "Diese Datei pflegt der Miner selbst: neue Drop-Kampagnen kommen dazu, beendete fallen weg.",
    "Bearbeiten darfst du nur 'reihenfolge' und 'aktiv', bei Spielen und bei einzelnen Kampagnen.",
    "reihenfolge: 1 = zuerst, 2 = danach und so weiter. 0 = automatisch (angefangene Drops zuerst, dann was am schnellsten fertig wird).",
    "aktiv: false = wird ignoriert. Eine Einstellung bei einer Kampagne geht vor der Einstellung beim Spiel.",
    "Änderungen gelten ohne Neustart, spätestens nach 5 Minuten. Ist die Datei fehlerhaft, bleibt sie unverändert und der Miner arbeitet mit dem letzten gültigen Stand weiter.",
]


def _local(dt):
    if dt is None:
        return ""
    aware = dt.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        aware = aware.astimezone(ZoneInfo("Europe/Berlin"))
    except Exception:
        aware = aware.astimezone()
    return aware.strftime("%d.%m.%Y %H:%M")


def _as_int(value, default=0):
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value, default=True):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("false", "nein", "aus", "0", "no", "off"):
            return False
        if lowered in ("true", "ja", "an", "1", "yes", "on"):
            return True
    return default


def game_name(campaign):
    game = campaign.game if isinstance(campaign.game, dict) else {}
    return game.get("displayName") or game.get("name") or "Unbekannt"


class DropCampaignFile:
    """Keeps drop_campaigns.json in sync with the currently active campaigns and
    reads the user's priorities back from it. User values (reihenfolge, aktiv) are
    never overwritten; a file the user broke while editing is left untouched and
    the last valid settings stay in effect until it parses again."""

    def __init__(self, path: str = DEFAULT_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._settings = {"games": {}, "campaigns": {}}
        self.broken = False

    def read_settings(self) -> dict:
        with self._lock:
            if not os.path.exists(self.path):
                self.broken = False
                return self._settings
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("top level is not an object")
            except Exception as e:
                if not self.broken:
                    logger.warning(
                        "drop_campaigns.json kann nicht gelesen werden (%s). Die Datei bleibt unverändert, es gilt der letzte gueltige Stand.",
                        e,
                    )
                self.broken = True
                return self._settings

            self.broken = False
            games = {}
            for entry in data.get("spiele") or []:
                if isinstance(entry, dict) and entry.get("spiel"):
                    games[str(entry["spiel"])] = {
                        "order": max(0, _as_int(entry.get("reihenfolge"))),
                        "active": _as_bool(entry.get("aktiv")),
                    }
            campaigns = {}
            for entry in data.get("kampagnen") or []:
                if isinstance(entry, dict) and entry.get("id"):
                    campaigns[str(entry["id"])] = {
                        "order": max(0, _as_int(entry.get("reihenfolge"))),
                        "active": _as_bool(entry.get("aktiv")),
                    }
            self._settings = {"games": games, "campaigns": campaigns}
            return self._settings

    @staticmethod
    def effective(campaign, settings) -> tuple:
        game = settings["games"].get(game_name(campaign), {})
        own = settings["campaigns"].get(campaign.id, {})
        active = own.get("active", True) and game.get("active", True)
        order = own.get("order") or game.get("order") or 0
        return active, order

    @classmethod
    def rank(cls, campaigns, settings) -> list:
        """Campaigns the miner should work on, best first."""
        usable = []
        for campaign in campaigns:
            active, order = cls.effective(campaign, settings)
            if not active or not campaign.is_earnable():
                continue
            usable.append((campaign, order))

        def key(item):
            campaign, order = item
            remaining = campaign.remaining_minutes()
            return (
                0 if order > 0 else 1,
                order if order > 0 else 0,
                0 if campaign.has_progress() else 1,
                1 if campaign.account_connected is False else 0,
                remaining if remaining is not None else 10**9,
                campaign.end_at,
            )

        return [campaign for campaign, _ in sorted(usable, key=key)]

    def write(self, campaigns, settings, active_campaign=None, active_login=None) -> bool:
        with self._lock:
            if self.broken:
                return False
            games_seen = []
            for campaign in campaigns:
                name = game_name(campaign)
                if name not in games_seen:
                    games_seen.append(name)
            for name in settings["games"]:
                if name not in games_seen:
                    games_seen.append(name)

            data = {
                "hinweis": HINT,
                "aktualisiert": _local(datetime.now(timezone.utc).replace(tzinfo=None)),
                "jetzt": (
                    {
                        "kanal": active_login,
                        "spiel": game_name(active_campaign),
                        "kampagne": active_campaign.name,
                    }
                    if active_campaign is not None and active_login
                    else None
                ),
                "spiele": [
                    {
                        "spiel": name,
                        "reihenfolge": settings["games"].get(name, {}).get("order", 0),
                        "aktiv": settings["games"].get(name, {}).get("active", True),
                    }
                    for name in games_seen
                ],
                "kampagnen": [self._campaign_entry(c, settings) for c in campaigns],
            }

            tmp = f"{self.path}.tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
            except Exception as e:
                logger.warning("drop_campaigns.json konnte nicht geschrieben werden: %s", e)
                return False
            return True

    @staticmethod
    def _campaign_entry(campaign, settings) -> dict:
        own = settings["campaigns"].get(campaign.id, {})
        open_drops = [d for d in campaign.drops if not d.is_claimed]
        remaining = campaign.remaining_minutes()
        next_drop = None
        if remaining is not None:
            candidates = [d for d in open_drops if not d.requires_subscription]
            closest = min(candidates, key=lambda d: d.minutes_required - d.current_minutes_watched)
            next_drop = f"{closest.current_minutes_watched} von {closest.minutes_required} Minuten ({closest.name})"
        connected = {True: "ja", False: "nein", None: "unbekannt"}[campaign.account_connected]
        return {
            "id": campaign.id,
            "spiel": game_name(campaign),
            "kampagne": campaign.name,
            "endet": _local(campaign.end_at),
            "offen": f"{len(open_drops)} von {campaign.total_drops} Drops",
            "naechster_drop": next_drop or "nur mit Abo oder schon alles abgeholt",
            "kanaele": "nur bestimmte Kanäle" if campaign.channels else "alle Kanäle mit Drops für dieses Spiel",
            "konto_verbunden": connected,
            "reihenfolge": own.get("order", 0),
            "aktiv": own.get("active", True),
        }
