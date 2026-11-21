import json
import logging
import os
import re
import threading
import time
import unicodedata
from datetime import datetime, timedelta, timezone

from TwitchChannelPointsMiner.classes.entities.Drop import utc_now
from TwitchChannelPointsMiner.classes.entities.Streamer import is_drop_discovered
from TwitchChannelPointsMiner.eranio import quests, selfcheck

logger = logging.getLogger(__name__)

DEFAULT_PATH = "drop_campaigns.json"
RETENTION_DAYS = 14
STATUS_INTERVAL_SECONDS = 15 * 60
WRITE_INTERVAL_SECONDS = 15 * 60
UNRANKED = 10**6
DAILY_STATUS = "heute erledigt, wird täglich neu geprüft"
TOP_GAMES_SEARCHED = 5

HINT = [
    "Diese Datei pflegt der Miner selbst. Er trägt die Drop-Kampagnen ein, die er bei deinen Kanälen, in deinem Inventar und bei den Spielen findet, die er kennt (neue unter die letzte Kampagne desselben Spiels, sonst ans Ende).",
    "status zeigt den Stand: läuft, gerade kein Live-Kanal, heute erledigt (nächster Drop ab ...), pausiert (kein Fortschritt beim Zuschauen), nur mit Abo, Konto nicht verbunden, alles abgeholt oder abgelaufen. Abgelaufene und fertige Einträge löscht der Miner 14 Tage nach Kampagnenende von selbst.",
    "Die Reihenfolge in 'kampagnen' ist die Arbeitsreihenfolge: was oben steht, wird zuerst abgearbeitet. Zum Umsortieren einen Eintrag einfach nach oben oder unten verschieben.",
    "aktiv: false = wird ausgelassen, bei einer Kampagne oder unter 'spiele' für ein ganzes Spiel. Ein Spiel unter 'spiele' mit 'slug' (der Teil der Twitch-Adresse, z. B. grand-theft-auto-vi) wird bei jedem Durchlauf gezielt nach Drop-Kanälen durchsucht.",
    "Die Datei wird jede Minute gelesen, Änderungen gelten ohne Neustart. Speicherst du sie fehlerhaft ab, repariert der Miner sie selbst und legt die fehlerhafte Fassung als drop_campaigns.fehlerhaft.json daneben.",
]


def slugify(value):
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").replace("'", "")
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")


def local_text(dt):
    if dt is None:
        return ""
    aware = dt.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        aware = aware.astimezone(ZoneInfo("Europe/Berlin"))
    except Exception:
        aware = aware.astimezone()
    return aware.strftime("%d.%m.%Y %H:%M")


def as_bool(value, default=True):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("false", "nein", "aus", "0", "no", "off"):
            return False
        if lowered in ("true", "ja", "an", "1", "yes", "on"):
            return True
    return default


def day_key():
    utc = datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        local = utc.astimezone(ZoneInfo("Europe/Berlin"))
    except Exception:
        local = utc.astimezone()
    return (utc.date(), local.date())


class DropInfo:
    def __init__(self, drop):
        self.id = getattr(drop, "id", None)
        self.name = getattr(drop, "name", None)
        self.benefit = getattr(drop, "benefit", None)
        self.minutes_required = getattr(drop, "minutes_required", 0) or 0
        self.current_minutes_watched = getattr(drop, "current_minutes_watched", 0) or 0
        self.is_claimed = getattr(drop, "is_claimed", False) is True
        needs = getattr(drop, "needs_subscription", None)
        self.requires_subscription = bool(needs()) if callable(needs) else False
        self.has_preconditions_met = getattr(drop, "has_preconditions_met", None)
        self.start_at = getattr(drop, "start_at", None)
        self.image = getattr(drop, "item_art_url", None)


class DropView:
    def __init__(self, campaign, connected=None, total=None, future=0, next_start=None):
        game = campaign.game if isinstance(campaign.game, dict) else {}
        categories = getattr(campaign, "reward_categories", None) or []
        self.quest = bool(categories)
        name = game.get("displayName") or game.get("name")
        if not name and categories:
            name = categories[0].get("displayName") or categories[0].get("name")
        self.game_name = name or "Unbekannt"
        self.game_slug = game.get("slug") or slugify(self.game_name)
        self.game_image = game.get("boxArtURL") or game.get("boxArtUrl")
        self.id = str(campaign.id)
        self.name = campaign.name
        self.end_at = campaign.end_at
        self.start_at = campaign.start_at
        self.drops = [DropInfo(d) for d in campaign.drops]
        self.channels = [str(c) for c in (campaign.channels or [])]
        self.total_drops = total if total is not None else len(self.drops)
        self.future_drops = future
        self.next_start = next_start
        self.account_connected = connected
        self.quest_channel = False
        self.quest_slugs = []
        self.sub_hint = None
        self.channel_logins = []
        self.creator_off = False
        self.repeating = any("(repeat " in str(d.name or "") for d in self.drops)

    @property
    def daily(self):
        if self.repeating:
            return True
        if self.start_at and self.end_at:
            return (self.end_at - self.start_at) <= timedelta(hours=DAILY_HOURS)
        return False

    def open_drops(self):
        return [d for d in self.drops if not d.is_claimed]

    def open_count(self):
        return len(self.open_drops()) + self.future_drops

    def watchable(self):
        return [
            d
            for d in self.drops
            if not d.is_claimed
            and not d.requires_subscription
            and d.minutes_required > 0
            and d.has_preconditions_met is not False
        ]

    def remaining_minutes(self):
        open_drops = self.watchable()
        if not open_drops:
            return None
        return min(
            max(0, d.minutes_required - d.current_minutes_watched) for d in open_drops
        )

    def has_progress(self):
        return any(d.current_minutes_watched > 0 for d in self.open_drops())

    def is_earnable(self):
        return self.remaining_minutes() is not None

    def only_subscription(self):
        open_drops = self.open_drops()
        return bool(open_drops) and all(d.requires_subscription for d in open_drops)

    def needs_subscription(self):
        return any(d.requires_subscription for d in self.open_drops())


DEFAULT_OPTIONS = {"creator_quests": True, "auto_within_game": True}
DAILY_HOURS = 26
CREATOR_OFF_STATUS = "Creator-Quest ausgeschaltet"


def empty_settings():
    return {
        "games": {},
        "campaigns": {},
        "order": [],
        "game_order": [],
        "options": dict(DEFAULT_OPTIONS),
    }


def read_options(data):
    raw = data.get("einstellungen") if isinstance(data, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    return {
        "creator_quests": as_bool(raw.get("creator_quests"), True),
        "auto_within_game": as_bool(raw.get("innerhalb_spiel_automatisch"), True),
    }


def write_options(options):
    return {
        "creator_quests": bool(options.get("creator_quests", True)),
        "innerhalb_spiel_automatisch": bool(options.get("auto_within_game", True)),
    }


def acronym(name):
    words = re.findall(r"[A-Za-z]+", str(name or ""))
    letters = "".join(word[0] for word in words[:3]).upper()
    return letters if len(letters) >= 3 else None


def guess_game(campaign_name, game_names):
    text = str(campaign_name or "")
    upper = text.upper()
    for game in game_names:
        if not game or game in ("Quest", "Unbekannt"):
            continue
        if game.lower() in text.lower():
            return game
        short = acronym(game)
        if short and re.search(r"(?<![A-Z])" + re.escape(short) + r"(?![A-Z])", upper):
            return game
    return None


class DropFile:
    def __init__(self, path=DEFAULT_PATH):
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

    def changed(self):
        return self._mtime() != self._seen_mtime

    def read_settings(self):
        with self._lock:
            mtime = self._mtime()
            self._seen_mtime = mtime
            if mtime is None:
                self.broken = False
                return self._settings
            try:
                with open(self.path, "r", encoding="utf-8-sig") as handle:
                    text = handle.read()
            except OSError as error:
                logger.warning(
                    "drop_campaigns.json kann nicht gelesen werden: %s", error
                )
                return self._settings
            data, fixed = self._parse(text)
            if data is not None:
                self.broken = fixed
                if fixed:
                    self._keep_broken_copy(text)
                    logger.warning(
                        "drop_campaigns.json hatte einen kleinen Fehler und wurde repariert, deine Reihenfolge bleibt."
                    )
                self._settings = self._from_data(data)
                return self._settings
            self.broken = True
            self._keep_broken_copy(text)
            salvaged = self._salvage(text)
            if salvaged is not None:
                for cid, info in salvaged["campaigns"].items():
                    previous = self._settings["campaigns"].get(cid, {})
                    info.setdefault("game", previous.get("game", ""))
                    if previous.get("entry"):
                        info["entry"] = previous["entry"]
                logger.warning(
                    "drop_campaigns.json war fehlerhaft und wurde repariert, Reihenfolge und aktiv-Werte wurden übernommen."
                )
                self._settings = salvaged
            else:
                logger.warning(
                    "drop_campaigns.json war nicht lesbar und wird mit dem letzten gültigen Stand neu geschrieben."
                )
            return self._settings

    @staticmethod
    def _from_data(data):
        games = {}
        game_order = []
        for entry in data.get("spiele") or []:
            if isinstance(entry, dict) and entry.get("spiel"):
                games[str(entry["spiel"])] = {
                    "active": as_bool(entry.get("aktiv")),
                    "slug": entry.get("slug") or None,
                }
                if str(entry["spiel"]) not in game_order:
                    game_order.append(str(entry["spiel"]))
        campaigns = {}
        order = []
        for entry in data.get("kampagnen") or []:
            if isinstance(entry, dict) and entry.get("id"):
                cid = str(entry["id"])
                if cid in campaigns:
                    continue
                campaigns[cid] = {
                    "active": as_bool(entry.get("aktiv")),
                    "game": str(entry.get("spiel") or ""),
                    "entry": entry,
                }
                order.append(cid)
        return {
            "games": games,
            "campaigns": campaigns,
            "order": order,
            "game_order": game_order,
            "options": read_options(data),
        }

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
        games_part = (
            text[text.find('"spiele"') : start]
            if '"spiele"' in text and start > 0
            else ""
        )
        games = {}
        for name, value in re.findall(
            r'"spiel"\s*:\s*"([^"]+)"[^{}]*?' + flag, games_part
        ):
            games[name] = {"active": as_bool(value.strip('"'))}
        part = text[start:] if start >= 0 else text
        campaigns = {}
        order = []
        previous_end = 0
        for match in re.finditer(r'"id"\s*:\s*"([^"]+)"', part):
            cid = match.group(1)
            values = re.findall(flag, part[previous_end : match.start()])
            previous_end = match.end()
            if cid in campaigns:
                continue
            campaigns[cid] = {
                "active": as_bool(values[-1].strip('"')) if values else True
            }
            order.append(cid)
        if not order and not games:
            return None
        return {
            "games": games,
            "campaigns": campaigns,
            "order": order,
            "game_order": list(games),
            "options": dict(DEFAULT_OPTIONS),
        }

    def _keep_broken_copy(self, text):
        copy_path = re.sub(r"\.json$", "", self.path) + ".fehlerhaft.json"
        try:
            with open(copy_path, "w", encoding="utf-8") as handle:
                handle.write(text)
        except OSError:
            pass

    @staticmethod
    def is_active(view, settings):
        own = settings["campaigns"].get(view.id, {})
        game = settings["games"].get(view.game_name, {})
        return (
            own.get("active", True)
            and game.get("active", True)
            and not getattr(view, "creator_off", False)
        )

    @staticmethod
    def arrange(order, info, settings):
        options = settings.get("options") or DEFAULT_OPTIONS
        if not options.get("auto_within_game", True):
            return list(order)
        games = []
        for cid in order:
            game = info.get(cid, ("", False, None))[0]
            if game not in games:
                games.append(game)
        position = {game: index for index, game in enumerate(games)}
        manual = {cid: index for index, cid in enumerate(order)}

        def key(cid):
            game, daily, remaining = info.get(cid, ("", False, None))
            return (
                position.get(game, len(games)),
                0 if daily else 1,
                remaining if remaining is not None else 10**9,
                manual[cid],
            )

        return sorted(order, key=key)

    @staticmethod
    def _auto_key(view):
        remaining = view.remaining_minutes()
        return (
            0 if view.has_progress() else 1,
            1 if view.account_connected is False else 0,
            remaining if remaining is not None else 10**9,
            view.end_at,
        )

    @staticmethod
    def merge_order(order, items):
        by_id = {item[0]: item for item in items}
        result = [cid for cid in order if cid in by_id]
        known = set(result)
        new = [item for item in items if item[0] not in known]
        new.sort(
            key=lambda item: (item[2] is None, item[2] if item[2] is not None else 0)
        )
        for cid, game, _ in new:
            position = None
            for index, existing in enumerate(result):
                if by_id[existing][1] == game:
                    position = index + 1
            if position is None:
                result.append(cid)
            else:
                result.insert(position, cid)
            known.add(cid)
        return result

    @classmethod
    def _items(cls, views, settings):
        items = [(v.id, v.game_name, cls._auto_key(v)) for v in views]
        present = {v.id for v in views}
        for cid in settings.get("order", []):
            if cid not in present:
                items.append(
                    (cid, settings["campaigns"].get(cid, {}).get("game", ""), None)
                )
        return items

    @classmethod
    def ordered(cls, views, settings):
        by_id = {v.id: v for v in views}
        order = [
            cid
            for cid in cls.merge_order(
                settings.get("order", []), cls._items(views, settings)
            )
            if cid in by_id
        ]
        info = {v.id: (v.game_name, v.daily, v.remaining_minutes()) for v in views}
        return [by_id[cid] for cid in cls.arrange(order, info, settings)]

    @classmethod
    def rank(cls, views, settings):
        return [
            v
            for v in cls.ordered(views, settings)
            if cls.is_active(v, settings)
            and v.is_earnable()
            and not selfcheck.is_blocked(v.id)
        ]

    def write(self, views, settings, statuses=None, finished=None, active=None):
        with self._lock:
            statuses = statuses or {}
            now = utc_now()
            entries = {}
            items = []
            for view in views:
                entries[view.id] = self._entry(
                    view, settings, statuses.get(view.id, "gerade kein Live-Kanal")
                )
                items.append((view.id, view.game_name, self._auto_key(view)))
            for view, status in finished or []:
                if view.id in entries:
                    continue
                entries[view.id] = self._entry(view, settings, status)
                items.append((view.id, view.game_name, None))
            for cid in settings.get("order", []):
                if cid in entries:
                    continue
                old = settings["campaigns"].get(cid, {}).get("entry")
                if not isinstance(old, dict):
                    continue
                end = self._parse_end(old.get("ende_utc"))
                if end is not None and now > end + timedelta(days=RETENTION_DAYS):
                    continue
                carried = dict(old)
                carried["aktiv"] = (
                    settings["campaigns"].get(cid, {}).get("active", True)
                )
                if end is not None and now > end:
                    if carried.get("status") != "alles abgeholt":
                        carried["status"] = "abgelaufen"
                elif str(carried.get("status") or "").startswith(
                    ("heute erledigt", "alles abgeholt")
                ):
                    carried["status"] = DAILY_STATUS
                else:
                    carried["status"] = "gerade kein Live-Kanal"
                entries[cid] = carried
                items.append((cid, str(carried.get("spiel") or ""), None))
            order = self.merge_order(settings.get("order", []), items)
            live = {v.id: v for v in views}
            info = {
                cid: (
                    entries[cid].get("spiel") or "Unbekannt",
                    live[cid].daily if cid in live else False,
                    live[cid].remaining_minutes() if cid in live else None,
                )
                for cid in order
            }
            order = self.arrange(order, info, settings)
            games_seen = []
            for cid in order:
                name = entries[cid].get("spiel") or "Unbekannt"
                if name not in games_seen:
                    games_seen.append(name)
            for name in settings["games"]:
                if name not in games_seen:
                    games_seen.append(name)
            data = {
                "hinweis": HINT,
                "aktualisiert": local_text(now),
                "einstellungen": write_options(settings.get("options") or {}),
                "hinweise_selbstkontrolle": selfcheck.warnings_for_file(),
                "jetzt": active,
                "spiele": [
                    self._game_entry(name, settings, entries) for name in games_seen
                ],
                "kampagnen": [entries[cid] for cid in order],
            }
            tmp = f"{self.path}.tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
            except Exception as error:
                logger.warning(
                    "drop_campaigns.json konnte nicht geschrieben werden: %s", error
                )
                return False
            self._seen_mtime = self._mtime()
            self.broken = False
            self._settings = self._from_data(data)
            return True

    @staticmethod
    def _game_entry(name, settings, entries):
        info = settings["games"].get(name, {})
        slug = info.get("slug")
        if not slug:
            slug = next(
                (
                    e.get("slug")
                    for e in entries.values()
                    if e.get("spiel") == name and e.get("slug")
                ),
                None,
            )
        entry = {"spiel": name, "aktiv": info.get("active", True)}
        if slug:
            entry["slug"] = slug
        return entry

    @staticmethod
    def _parse_end(value):
        if not value:
            return None
        try:
            return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return None

    def known_slugs(self):
        slugs = []
        for info in self._settings["games"].values():
            slug = info.get("slug") if isinstance(info, dict) else None
            if slug and info.get("active", True) and slug not in slugs:
                slugs.append(slug)
        return slugs

    @staticmethod
    def _entry(view, settings, status):
        own = settings["campaigns"].get(view.id, {})
        open_drops = view.open_drops()
        next_drop = "nichts mehr offen"
        candidates = view.watchable()
        if candidates:
            closest = min(
                candidates, key=lambda d: d.minutes_required - d.current_minutes_watched
            )
            label = closest.name or closest.benefit or "Drop"
            next_drop = f"{closest.current_minutes_watched} von {closest.minutes_required} Minuten ({label})"
        elif open_drops:
            next_drop = (
                "nur mit Abo"
                if view.only_subscription()
                else "nichts per Zuschauen machbar"
            )
        elif view.future_drops:
            next_drop = (
                f"ab {local_text(view.next_start)}"
                if view.next_start
                else "nächster Drop folgt"
            )
        connected = {True: "ja", False: "nein", None: "unbekannt"}[
            view.account_connected
        ]
        return {
            "spiel": view.game_name,
            "kampagne": view.name,
            "aktiv": own.get("active", True),
            "status": status,
            "endet": local_text(view.end_at),
            "offen": f"{view.open_count()} von {view.total_drops} Drops",
            "naechster_drop": next_drop,
            "kanaele": (
                "nur " + ", ".join(view.channel_logins)
                if view.channel_logins
                else (
                    "nur bestimmte Kanäle"
                    if view.channels
                    else "alle Kanäle mit Drops für dieses Spiel"
                )
            ),
            "abo_hinweis": view.sub_hint,
            "taeglich": view.daily,
            "creator_quest": view.quest_channel,
            "konto_verbunden": connected,
            "art": "Quest" if view.quest else "Drop-Kampagne",
            "spiel_bild": view.game_image,
            "naechster_start": local_text(view.next_start) if view.next_start else None,
            "drops": [
                {
                    "name": d.name,
                    "belohnung": d.benefit,
                    "bild": d.image,
                    "minuten_noetig": d.minutes_required,
                    "minuten_aktuell": d.current_minutes_watched,
                    "abo_noetig": d.requires_subscription,
                    "abos": getattr(d, "subs_required", 0) or 0,
                    "abgeholt": d.is_claimed,
                }
                for d in view.drops
            ],
            "abo_noetig": "ja" if view.needs_subscription() else "nein",
            "id": view.id,
            "slug": view.game_slug,
            "ende_utc": (
                view.end_at.strftime("%Y-%m-%dT%H:%M:%SZ") if view.end_at else None
            ),
        }


class Memo:
    def __init__(self, view, future, next_start):
        self.view = view
        self.future = future
        self.next_start = next_start
        self.closed = False


class State:
    def __init__(self):
        self.reset()

    def reset(self):
        self.configured = False
        self.file = None
        self.settings = empty_settings()
        self.memo = {}
        self.views = []
        self.rank_ids = []
        self.position = {}
        self.all_ids = set()
        self.base_categories = []
        self.categories = None
        self.dirty = True
        self.last_write = 0.0
        self.last_status = 0.0
        self.day = None
        self.drop_pick = None
        self.quest_channels = set()
        self.last_current = None
        self.lock = threading.RLock()


STATE = State()


def configure(path=None, categories=None):
    STATE.reset()
    STATE.file = DropFile(path or DEFAULT_PATH)
    STATE.categories = categories
    STATE.base_categories = list(categories) if categories is not None else []
    STATE.day = day_key()
    STATE.configured = True


def active():
    return STATE.configured


def remember(campaign):
    if not STATE.configured:
        return
    try:
        now = utc_now()
        upcoming = [
            d.start_at for d in campaign.drops if d.start_at and d.start_at > now
        ]
        if campaign.start_at and campaign.start_at > now:
            upcoming.append(campaign.start_at)
        future = len([d for d in campaign.drops if d.start_at and d.start_at > now])
        view = DropView(
            campaign,
            total=len(campaign.drops),
            future=future,
            next_start=min(upcoming) if upcoming else None,
        )
        with STATE.lock:
            STATE.memo[view.id] = Memo(view, future, view.next_start)
    except Exception:
        logger.debug("Drop-Liste: Kampagne konnte nicht gemerkt werden", exc_info=True)


def _link_states(twitch):
    states = {}
    try:
        for group in twitch.unlinked_drop_report() or []:
            if group.get("campaign_id"):
                states[str(group["campaign_id"])] = (
                    True if group.get("linked") else False
                )
    except Exception:
        pass
    return states


def _blocked_games(twitch, now):
    blocked = set()
    health = getattr(twitch, "drop_watch_health", None) or {}
    for slug, state in health.items():
        until = (state or {}).get("blocked_until") or {}
        if any(deadline > now for deadline in until.values()):
            blocked.add(slug)
    return blocked


def _stream_ids(streamer):
    stream = getattr(streamer, "stream", None)
    ids = {str(i) for i in (getattr(stream, "campaigns_ids", None) or [])}
    ids |= {str(c.id) for c in (getattr(stream, "campaigns", None) or [])}
    return ids


def _quest_channel_ids(streamer):
    channel_id = str(getattr(streamer, "channel_id", "") or "")
    if not channel_id:
        return set()
    return {
        v.id
        for v in STATE.views
        if getattr(v, "quest_channel", False) and channel_id in v.channels
    }


def _live_ids(streamers):
    live = set()
    for streamer in streamers or []:
        if getattr(streamer, "is_online", False) is True:
            live |= _stream_ids(streamer)
            live |= _quest_channel_ids(streamer)
    return live


def quest_stream(streamer):
    if not STATE.configured or not STATE.quest_channels:
        return False
    if getattr(streamer, "is_online", False) is not True:
        return False
    return str(getattr(streamer, "channel_id", "") or "") in STATE.quest_channels


def _build_views(twitch, campaigns):
    links = _link_states(twitch)
    views = []
    for campaign in campaigns:
        memo = STATE.memo.get(str(campaign.id))
        view = DropView(
            campaign,
            connected=links.get(str(campaign.id)),
            total=memo.view.total_drops if memo else None,
            future=memo.future if memo else 0,
            next_start=memo.next_start if memo else None,
        )
        if memo and memo.view.total_drops < len(view.drops):
            view.total_drops = len(view.drops)
        views.append(view)
    known = {v.id for v in views}
    views.extend(DropView(extra) for extra in quests.extra_campaigns(known))
    views = quests.patch_views(views, STATE.settings.get("options") or DEFAULT_OPTIONS)
    names = []
    for view in views:
        if view.game_name not in names:
            names.append(view.game_name)
    for view in views:
        if view.game_name in ("Quest", "Unbekannt"):
            found = guess_game(view.name, names)
            if found:
                view.game_name = found
                view.game_slug = slugify(found)
    return views


def _status(view, live, blocked, now_utc):
    if getattr(view, "creator_off", False):
        return CREATOR_OFF_STATUS
    if selfcheck.is_blocked(view.id):
        return "pausiert (Selbstkontrolle: kein Fortschritt bei Twitch)"
    if view.end_at and now_utc > view.end_at:
        return "abgelaufen"
    if not view.is_earnable():
        if view.account_connected is False:
            return "Konto nicht verbunden"
        if view.next_start and view.next_start > now_utc and not view.open_drops():
            return f"heute erledigt, nächster Drop ab {local_text(view.next_start)}"
        if view.only_subscription():
            return "nur mit Abo"
        return "nichts per Zuschauen machbar"
    if view.account_connected is False:
        return "Konto nicht verbunden"
    if view.id in live and view.game_slug in blocked:
        return "pausiert, kein Fortschritt beim Zuschauen"
    return "läuft" if view.id in live else "gerade kein Live-Kanal"


def _finished(views, now_utc):
    present = {v.id for v in views}
    result = []
    for cid, memo in list(STATE.memo.items()):
        if cid in present:
            continue
        view = memo.view
        if view.end_at and now_utc > view.end_at + timedelta(days=RETENTION_DAYS):
            del STATE.memo[cid]
            continue
        closed = DropView.__new__(DropView)
        closed.__dict__.update(view.__dict__)
        closed.drops = []
        closed.future_drops = memo.future
        closed.next_start = memo.next_start
        if view.end_at and now_utc > view.end_at:
            result.append((closed, "alles abgeholt" if memo.closed else "abgelaufen"))
            continue
        memo.closed = True
        if memo.next_start and memo.next_start > now_utc:
            result.append(
                (
                    closed,
                    f"heute erledigt, nächster Drop ab {local_text(memo.next_start)}",
                )
            )
        else:
            result.append((closed, DAILY_STATUS))
    return result


def _sync_categories(settings, ranked):
    categories = STATE.categories
    if categories is None:
        return
    known = {slugify(c) for c in STATE.base_categories}
    extra = []
    games = settings["games"]
    for name, info in games.items():
        slug = info.get("slug")
        if (
            slug
            and info.get("active", True)
            and slugify(slug) not in known
            and slug not in extra
        ):
            extra.append(slug)
    for view in ranked[:TOP_GAMES_SEARCHED]:
        if (
            view.game_slug
            and slugify(view.game_slug) not in known
            and view.game_slug not in extra
        ):
            extra.append(view.game_slug)
        for slug in quests.category_slugs(view):
            if slugify(slug) not in known and slug not in extra:
                extra.append(slug)
    desired = list(STATE.base_categories) + extra
    if list(categories) != desired:
        categories[:] = desired


STATUS_LINES = 10


def _log_status(ordered, finished, settings, live, blocked, statuses):
    if not ordered and not finished:
        logger.info(
            "Drops: zurzeit keine laufende Kampagne gefunden",
            extra={"emoji": ":package:"},
        )
        return
    logger.info(
        "Drops: %d Kampagnen in Arbeitsreihenfolge",
        len(ordered),
        extra={"emoji": ":package:"},
    )
    shown = 0
    hidden = 0
    for position, view in enumerate(ordered, start=1):
        state = statuses.get(view.id, "")
        if not DropFile.is_active(view, settings):
            state = "aus (aktiv: false)"
        if shown >= STATUS_LINES or not view.watchable() or state.startswith("aus"):
            hidden += 1
            continue
        shown += 1
        nxt = None
        candidates = view.watchable()
        if candidates:
            closest = min(
                candidates, key=lambda d: d.minutes_required - d.current_minutes_watched
            )
            nxt = f"{closest.current_minutes_watched}/{closest.minutes_required} Min. ({closest.name or closest.benefit or 'Drop'})"
        logger.info(
            "Drops %d. %s | %s | %d von %d offen | naechster: %s | %s",
            position,
            view.game_name,
            view.name,
            view.open_count(),
            view.total_drops,
            nxt or "-",
            state,
        )
    if hidden:
        logger.info(
            "Drops: %d weitere Kampagnen ohne Anzeige hier, vollständige Liste in drop_campaigns.json und auf der Drops-Seite",
            hidden,
        )
    if finished:
        logger.info("Drops: %d Kampagnen erledigt oder abgelaufen", len(finished))


def on_new_day(twitch):
    logger.info("Drops: neuer Tag, alle Kampagnen werden neu geprüft")
    health = getattr(twitch, "drop_watch_health", None)
    if isinstance(health, dict):
        for state in health.values():
            if isinstance(state, dict) and isinstance(state.get("blocked_until"), dict):
                state["blocked_until"].clear()
    for memo in STATE.memo.values():
        memo.next_start = None
    STATE.dirty = True


def publish(twitch, campaigns, streamers, now=None):
    if not STATE.configured:
        return
    try:
        _publish(twitch, campaigns, streamers, time.time() if now is None else now)
    except Exception:
        logger.debug("Drop-Liste konnte nicht aktualisiert werden", exc_info=True)


def _current(views, streamers):
    if STATE.drop_pick is not None:
        login, cid = STATE.drop_pick
        view = next((v for v in views if v.id == cid), None)
        if view is not None:
            return {"kanal": login, "spiel": view.game_name, "kampagne": view.name}
    for streamer in streamers or []:
        if getattr(streamer, "is_watching", False) is not True:
            continue
        ids = [STATE.position[i] for i in matched_ids(streamer) if i in STATE.position]
        if ids:
            view = next(v for v in views if v.id == STATE.rank_ids[min(ids)])
            return {
                "kanal": streamer.username,
                "spiel": view.game_name,
                "kampagne": view.name,
            }
    return None


def _publish(twitch, campaigns, streamers, now):
    quests.refresh(twitch, now)
    selfcheck.fetch(twitch, now)
    with STATE.lock:
        now_utc = utc_now()
        key = day_key()
        if key != STATE.day:
            STATE.day = key
            on_new_day(twitch)
        if STATE.file.changed():
            STATE.settings = STATE.file.read_settings()
            STATE.dirty = True
        settings = STATE.settings
        views = _build_views(twitch, list(campaigns or []))
        finished = _finished(views, now_utc)
        ordered = DropFile.ordered(views, settings)
        ranked = DropFile.rank(views, settings)
        STATE.views = views
        STATE.rank_ids = [v.id for v in ranked]
        STATE.position = {cid: index for index, cid in enumerate(STATE.rank_ids)}
        STATE.all_ids = {v.id for v in views}
        STATE.quest_channels = {
            channel for v in ranked if v.quest_channel for channel in v.channels
        }
        quests.ensure_streamers(quests.wanted_logins(ranked))
        _sync_categories(settings, ranked)
        live = _live_ids(streamers)
        blocked = _blocked_games(twitch, now)
        statuses = {v.id: _status(v, live, blocked, now_utc) for v in views}
        selfcheck.evaluate(
            views, ranked, statuses, streamers, STATE.drop_pick, slugify, now
        )
        current = _current(views, streamers)
        if current != STATE.last_current:
            STATE.dirty = True
        if STATE.dirty or now - STATE.last_write >= WRITE_INTERVAL_SECONDS:
            STATE.last_current = current
            if STATE.file.write(views, settings, statuses, finished, current):
                STATE.settings = STATE.file._settings
                STATE.dirty = False
                STATE.last_write = now
        if now - STATE.last_status >= STATUS_INTERVAL_SECONDS:
            STATE.last_status = now
            _log_status(ordered, finished, settings, live, blocked, statuses)


def matched_ids(streamer):
    ids = {i for i in _stream_ids(streamer) if i in STATE.all_ids}
    if ids:
        return ids | _quest_channel_ids(streamer)
    stream = getattr(streamer, "stream", None)
    game = (
        stream.game_name()
        if stream is not None and callable(getattr(stream, "game_name", None))
        else None
    )
    slug = slugify(game or "")
    channel_id = str(getattr(streamer, "channel_id", ""))
    return {
        v.id
        for v in STATE.views
        if (
            slug
            and v.game_slug == slug
            and not v.quest_channel
            and (not v.channels or channel_id in v.channels)
        )
        or (slug and slug in v.quest_slugs)
    } | _quest_channel_ids(streamer)


def streamer_rank(streamer):
    positions = [
        STATE.position[i] for i in matched_ids(streamer) if i in STATE.position
    ]
    return min(positions) if positions else None


def allows_watch(streamer):
    if not STATE.configured or not STATE.views or not is_drop_discovered(streamer):
        return True
    matched = matched_ids(streamer)
    if not matched:
        return True
    return any(i in STATE.position for i in matched)


def pick_key(snapshot, fallback):
    if not STATE.configured:
        return fallback

    def key(index):
        rank = streamer_rank(snapshot[index])
        return (UNRANKED if rank is None else rank, fallback(index))

    return key


def drop_rank(streamer, rank):
    if not STATE.configured:
        return rank
    position = streamer_rank(streamer)
    return (UNRANKED if position is None else position, rank)


def reserve(
    twitch, snapshot, watching, streamers_index, streams_watched, is_drop, now=None
):
    watching = list(watching)
    if not STATE.configured or not STATE.position:
        return watching
    candidates = []
    for index in streamers_index:
        if not is_drop(index):
            continue
        rank = streamer_rank(snapshot[index])
        if rank is not None:
            candidates.append((rank, index))
    if not candidates:
        STATE.drop_pick = None
        return watching
    best_rank, best = min(candidates)
    if 0 <= best_rank < len(STATE.rank_ids):
        STATE.drop_pick = (snapshot[best].username, STATE.rank_ids[best_rank])
    if best in watching:
        kept = [
            i
            for i in watching
            if i == best
            or not is_drop(i)
            or (
                streamer_rank(snapshot[i]) is not None
                and streamer_rank(snapshot[i]) <= best_rank
            )
        ]
        return kept
    result = [
        i
        for i in watching
        if not is_drop(i)
        or (
            streamer_rank(snapshot[i]) is not None
            and streamer_rank(snapshot[i]) <= best_rank
        )
    ]
    if result and len(result) >= streams_watched:
        for position in range(len(result) - 1, -1, -1):
            if not is_drop(result[position]):
                del result[position]
                break
        else:
            result.pop()
    return [best] + result


def _file_path():
    if STATE.file is not None:
        return STATE.file.path
    return DEFAULT_PATH


def _read_file():
    try:
        with open(_file_path(), "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


EDITOR_FIELDS = (
    "id",
    "kampagne",
    "status",
    "naechster_drop",
    "abo_hinweis",
    "taeglich",
    "creator_quest",
    "aktiv",
    "offen",
    "endet",
    "kanaele",
    "konto_verbunden",
)


def editor_view():
    with STATE.lock:
        data = _read_file()
    if data is None:
        return {"available": False}
    games = []
    by_name = {}
    active_games = {
        str(g.get("spiel")): as_bool(g.get("aktiv"))
        for g in data.get("spiele") or []
        if isinstance(g, dict) and g.get("spiel")
    }
    for entry in data.get("kampagnen") or []:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        if str(entry.get("status") or "") in ("abgelaufen", "alles abgeholt"):
            continue
        name = str(entry.get("spiel") or "Unbekannt")
        if name not in by_name:
            by_name[name] = {
                "name": name,
                "active": active_games.get(name, True),
                "campaigns": [],
            }
            games.append(by_name[name])
        by_name[name]["campaigns"].append(
            {field: entry.get(field) for field in EDITOR_FIELDS}
        )
    return {
        "available": True,
        "options": read_options(data),
        "games": games,
        "jetzt": data.get("jetzt"),
        "hinweise": data.get("hinweise_selbstkontrolle") or [],
        "aktualisiert": data.get("aktualisiert"),
    }


def apply_editor(payload):
    with STATE.lock:
        data = _read_file()
        if data is None:
            raise ValueError("drop_campaigns.json gibt es noch nicht.")
        entries = [
            e
            for e in data.get("kampagnen") or []
            if isinstance(e, dict) and e.get("id")
        ]
        wanted = [str(cid) for cid in payload.get("order") or []]
        position = {cid: index for index, cid in enumerate(wanted)}
        entries.sort(key=lambda e: position.get(str(e["id"]), len(wanted)))
        active = payload.get("active") or {}
        for entry in entries:
            if str(entry["id"]) in active:
                entry["aktiv"] = active[str(entry["id"])] is True
        data["kampagnen"] = entries
        games_active = payload.get("games_active") or {}
        names = []
        for entry in entries:
            name = str(entry.get("spiel") or "Unbekannt")
            if name not in names:
                names.append(name)
        old_games = {
            str(g.get("spiel")): g
            for g in data.get("spiele") or []
            if isinstance(g, dict) and g.get("spiel")
        }
        for name in old_games:
            if name not in names:
                names.append(name)
        games = []
        for name in names:
            game = dict(old_games.get(name) or {"spiel": name, "aktiv": True})
            if name in games_active:
                game["aktiv"] = games_active[name] is True
            games.append(game)
        data["spiele"] = games
        options = read_options(data)
        incoming = payload.get("options") or {}
        for key in ("creator_quests", "auto_within_game"):
            if key in incoming:
                options[key] = incoming[key] is True
        data["einstellungen"] = write_options(options)
        path = _file_path()
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        if STATE.configured and STATE.file is not None:
            STATE.settings = STATE.file.read_settings()
            STATE.dirty = True
    logger.info("Drop-Reihenfolge auf der Einstellungsseite gespeichert.")
    return editor_view()
