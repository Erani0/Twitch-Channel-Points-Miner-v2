import json
import logging
import os
import re
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DEFAULT_PATH = "drop_campaigns.json"

HINT = [
    "Diese Datei pflegt der Miner selbst. Abgelaufene oder komplett abgeholte Kampagnen fallen raus, neue kommen dazu (unter die letzte Kampagne desselben Spiels, sonst ans Ende).",
    "Die Reihenfolge in 'kampagnen' ist die Arbeitsreihenfolge: was oben steht, wird zuerst abgearbeitet. Zum Umsortieren einen Eintrag einfach nach oben oder unten verschieben.",
    "aktiv: false = wird ausgelassen, bei einer Kampagne oder unter 'spiele' für ein ganzes Spiel.",
    "Die Datei wird jede Minute gelesen, Änderungen gelten ohne Neustart. Speicherst du sie fehlerhaft ab, repariert der Miner sie selbst und legt die fehlerhafte Fassung als drop_campaigns.fehlerhaft.json daneben.",
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


def empty_settings():
    return {"games": {}, "campaigns": {}, "order": []}


class DropCampaignFile:
    """Keeps drop_campaigns.json in sync with the active campaigns. The position of
    a campaign in the file is its working order; the user's order and 'aktiv'
    flags are never overwritten. A file broken while editing is left untouched and
    the last valid settings stay in effect until it parses again."""

    def __init__(self, path: str = DEFAULT_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._settings = empty_settings()
        self._seen_mtime = None
        self.broken = False

    def _mtime(self):
        try:
            return os.path.getmtime(self.path)
        except OSError:
            return None

    def changed(self) -> bool:
        return self._mtime() != self._seen_mtime

    def read_settings(self) -> dict:
        """Reads the user's order. A file broken while editing repairs itself: small
        syntax slips are fixed, otherwise order and 'aktiv' values are salvaged from
        the text, and only if nothing is recognisable the last valid state is used.
        The broken text is kept as drop_campaigns.fehlerhaft.json and the next write
        puts a clean file back, so no restart is ever needed."""
        with self._lock:
            mtime = self._mtime()
            self._seen_mtime = mtime
            if mtime is None:
                self.broken = False
                return self._settings
            try:
                with open(self.path, "r", encoding="utf-8-sig") as f:
                    text = f.read()
            except OSError as e:
                logger.warning("drop_campaigns.json kann nicht gelesen werden: %s", e)
                return self._settings

            data, fixed = self._parse(text)
            if data is not None:
                self.broken = fixed
                if fixed:
                    self._keep_broken_copy(text)
                    logger.warning("drop_campaigns.json hatte einen kleinen Fehler und wurde repariert, deine Reihenfolge bleibt.")
                self._settings = self._from_data(data)
                return self._settings

            self.broken = True
            self._keep_broken_copy(text)
            salvaged = self._salvage(text)
            if salvaged is not None:
                logger.warning("drop_campaigns.json war fehlerhaft und wurde repariert, Reihenfolge und aktiv-Werte wurden übernommen.")
                self._settings = salvaged
            else:
                logger.warning("drop_campaigns.json war nicht lesbar und wird mit dem letzten gültigen Stand neu geschrieben.")
            return self._settings

    @staticmethod
    def _from_data(data) -> dict:
        games = {}
        for entry in data.get("spiele") or []:
            if isinstance(entry, dict) and entry.get("spiel"):
                games[str(entry["spiel"])] = {"active": _as_bool(entry.get("aktiv"))}
        campaigns = {}
        order = []
        for entry in data.get("kampagnen") or []:
            if isinstance(entry, dict) and entry.get("id"):
                cid = str(entry["id"])
                if cid in campaigns:
                    continue
                campaigns[cid] = {"active": _as_bool(entry.get("aktiv"))}
                order.append(cid)
        return {"games": games, "campaigns": campaigns, "order": order}

    @staticmethod
    def _parse(text):
        try:
            data = json.loads(text)
            return (data, False) if isinstance(data, dict) else (None, False)
        except ValueError:
            pass
        fixed = re.sub(r",(\s*[\]}])", r"\1", text)
        stack = []
        in_string = False
        escaped = False
        for char in fixed:
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char in "{[":
                stack.append("}" if char == "{" else "]")
            elif char in "}]" and stack and stack[-1] == char:
                stack.pop()
        if in_string:
            fixed += '"'
        fixed = fixed.rstrip().rstrip(",") + "".join(reversed(stack))
        try:
            data = json.loads(fixed)
        except ValueError:
            return None, False
        return (data, True) if isinstance(data, dict) else (None, False)

    @staticmethod
    def _salvage(text):
        flag = r'"aktiv"\s*:\s*(true|false|"[^"]*")'
        start = text.find('"kampagnen"')
        games_part = text[text.find('"spiele"'):start] if '"spiele"' in text and start > 0 else ""
        games = {}
        for name, value in re.findall(r'"spiel"\s*:\s*"([^"]+)"[^{}]*?' + flag, games_part):
            games[name] = {"active": _as_bool(value.strip('"'))}
        part = text[start:] if start >= 0 else text
        campaigns = {}
        order = []
        previous_end = 0
        for match in re.finditer(r'"id"\s*:\s*"([^"]+)"', part):
            cid = match.group(1)
            values = re.findall(flag, part[previous_end:match.start()])
            previous_end = match.end()
            if cid in campaigns:
                continue
            campaigns[cid] = {"active": _as_bool(values[-1].strip('"')) if values else True}
            order.append(cid)
        if not order and not games:
            return None
        return {"games": games, "campaigns": campaigns, "order": order}

    def _keep_broken_copy(self, text) -> None:
        copy_path = re.sub(r"\.json$", "", self.path) + ".fehlerhaft.json"
        try:
            with open(copy_path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass

    @staticmethod
    def is_active(campaign, settings) -> bool:
        own = settings["campaigns"].get(campaign.id, {})
        game = settings["games"].get(game_name(campaign), {})
        return own.get("active", True) and game.get("active", True)

    @staticmethod
    def _auto_key(campaign):
        remaining = campaign.remaining_minutes()
        return (
            0 if campaign.has_progress() else 1,
            1 if campaign.account_connected is False else 0,
            remaining if remaining is not None else 10**9,
            campaign.end_at,
        )

    @classmethod
    def ordered(cls, campaigns, settings) -> list:
        """All campaigns in working order: the user's order from the file, with new
        campaigns placed below the last listed campaign of the same game, or at the
        end (new ones among themselves sorted automatically)."""
        by_id = {c.id: c for c in campaigns}
        result = [by_id[cid] for cid in settings.get("order", []) if cid in by_id]
        known = {c.id for c in result}
        for new in sorted((c for c in campaigns if c.id not in known), key=cls._auto_key):
            name = game_name(new)
            position = None
            for index, existing in enumerate(result):
                if game_name(existing) == name:
                    position = index + 1
            if position is None:
                result.append(new)
            else:
                result.insert(position, new)
        return result

    @classmethod
    def rank(cls, campaigns, settings) -> list:
        """Campaigns the miner should work on, best first."""
        return [
            c
            for c in cls.ordered(campaigns, settings)
            if cls.is_active(c, settings) and c.is_earnable()
        ]

    def write(self, campaigns, settings, active_campaign=None, active_login=None) -> bool:
        with self._lock:
            ordered = self.ordered(campaigns, settings)
            games_seen = []
            for campaign in ordered:
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
                    {"spiel": name, "aktiv": settings["games"].get(name, {}).get("active", True)}
                    for name in games_seen
                ],
                "kampagnen": [self._campaign_entry(c, settings) for c in ordered],
            }

            tmp = f"{self.path}.tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
            except Exception as e:
                logger.warning("drop_campaigns.json konnte nicht geschrieben werden: %s", e)
                return False
            self._seen_mtime = self._mtime()
            self.broken = False
            self._settings = {
                "games": {n: {"active": settings["games"].get(n, {}).get("active", True)} for n in games_seen},
                "campaigns": {c.id: {"active": settings["campaigns"].get(c.id, {}).get("active", True)} for c in ordered},
                "order": [c.id for c in ordered],
            }
            return True

    @staticmethod
    def _campaign_entry(campaign, settings) -> dict:
        own = settings["campaigns"].get(campaign.id, {})
        open_drops = [d for d in campaign.drops if not d.is_claimed]
        next_drop = "nur mit Abo oder schon alles abgeholt"
        candidates = [d for d in open_drops if not d.requires_subscription]
        if candidates:
            closest = min(candidates, key=lambda d: d.minutes_required - d.current_minutes_watched)
            next_drop = f"{closest.current_minutes_watched} von {closest.minutes_required} Minuten ({closest.name})"
        connected = {True: "ja", False: "nein", None: "unbekannt"}[campaign.account_connected]
        return {
            "spiel": game_name(campaign),
            "kampagne": campaign.name,
            "aktiv": own.get("active", True),
            "endet": _local(campaign.end_at),
            "offen": f"{len(open_drops)} von {campaign.total_drops} Drops",
            "naechster_drop": next_drop,
            "kanaele": "nur bestimmte Kanäle" if campaign.channels else "alle Kanäle mit Drops für dieses Spiel",
            "konto_verbunden": connected,
            "id": campaign.id,
        }
