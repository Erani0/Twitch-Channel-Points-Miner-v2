import logging
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

CHECK_SECONDS = 30 * 60
STALL_SECONDS = 60 * 60
BLOCK_SECONDS = 2 * 3600
NO_CHANNEL_SECONDS = 2 * 3600
REPEAT_SECONDS = 6 * 3600
KEEP_SECONDS = 24 * 3600
FILE_LIMIT = 10


class State:
    def __init__(self):
        self.reset()

    def reset(self):
        self.lock = threading.Lock()
        self.warnings = []
        self.last_fetch = 0
        self.inventory = None
        self.pick = None
        self.pick_minutes = None
        self.pick_since = None
        self.blocked = {}
        self.waiting_since = {}
        self.reported = {}
        self.seen_awards = None


STATE = State()


def _local(ts):
    try:
        from zoneinfo import ZoneInfo

        zone = ZoneInfo("Europe/Berlin")
    except Exception:
        zone = None
    moment = datetime.fromtimestamp(ts, tz=timezone.utc)
    return (moment.astimezone(zone) if zone else moment.astimezone()).strftime(
        "%d.%m. %H:%M"
    )


def warn(text, now, key=None):
    key = key or text
    with STATE.lock:
        last = STATE.reported.get(key)
        if last is not None and now - last < REPEAT_SECONDS:
            return False
        STATE.reported[key] = now
        STATE.warnings.append((now, text))
        STATE.warnings = [w for w in STATE.warnings if now - w[0] < KEEP_SECONDS]
    logger.warning("Selbstkontrolle: %s", text)
    return True


def warnings_for_file(now=None):
    now = time.time() if now is None else now
    with STATE.lock:
        recent = [w for w in STATE.warnings if now - w[0] < KEEP_SECONDS]
    return [f"{_local(ts)} {text}" for ts, text in recent[-FILE_LIMIT:]][::-1]


def is_blocked(campaign_id, now=None):
    now = time.time() if now is None else now
    until = STATE.blocked.get(str(campaign_id))
    return until is not None and until > now


def fetch(twitch, now):
    if now - STATE.last_fetch < CHECK_SECONDS:
        return
    STATE.last_fetch = now
    getter = getattr(twitch, "get_drops_inventory", None)
    if getter is None:
        return
    try:
        inventory = getter()
    except Exception:
        logger.debug("Selbstkontrolle: Inventar nicht lesbar", exc_info=True)
        return
    if isinstance(inventory, dict) and inventory:
        STATE.inventory = inventory


def _watched_total(view):
    return sum(
        d.minutes_required if d.is_claimed else d.current_minutes_watched
        for d in view.drops
    )


def _check_stall(views, statuses, pick, now):
    if pick is None:
        STATE.pick = None
        return
    login, campaign_id = pick
    view = next((v for v in views if v.id == campaign_id), None)
    if view is None or statuses.get(campaign_id) != "läuft":
        STATE.pick = None
        return
    total = _watched_total(view)
    if STATE.pick != campaign_id or STATE.pick_minutes != total:
        STATE.pick = campaign_id
        STATE.pick_minutes = total
        STATE.pick_since = now
        return
    if now - STATE.pick_since < STALL_SECONDS:
        return
    STATE.blocked[campaign_id] = now + BLOCK_SECONDS
    STATE.pick = None
    warn(
        f"{view.game_name} | {view.name}: seit {int((now - STATE.pick_since) // 60)} Min. "
        f"auf {login} keine Minuten bei Twitch, wird 2 Std. übersprungen",
        now,
        key=f"stall:{campaign_id}",
    )


def _online_slugs(streamers, slugify):
    slugs = set()
    for streamer in streamers or []:
        if getattr(streamer, "is_online", False) is not True:
            continue
        stream = getattr(streamer, "stream", None)
        game = getattr(stream, "game_name", None)
        name = game() if callable(game) else None
        if name:
            slugs.add(slugify(name))
    return slugs


def _check_no_channel(ranked, statuses, streamers, slugify, now):
    online = _online_slugs(streamers, slugify)
    for view in ranked[:5]:
        if statuses.get(view.id) != "gerade kein Live-Kanal":
            STATE.waiting_since.pop(view.id, None)
            continue
        since = STATE.waiting_since.setdefault(view.id, now)
        if now - since < NO_CHANNEL_SECONDS:
            continue
        slugs = {view.game_slug} | set(getattr(view, "quest_slugs", []) or [])
        if view.quest_channel or not (slugs & online):
            continue
        warn(
            f"{view.game_name} | {view.name}: seit {int((now - since) // 3600)} Std. ohne "
            "Drop-Kanal, obwohl in der Kategorie Kanäle live sind",
            now,
            key=f"nochannel:{view.id}",
        )


def _check_awards(views, now):
    inventory = STATE.inventory
    if not isinstance(inventory, dict):
        return
    awards = {}
    for item in inventory.get("gameEventDrops") or []:
        if isinstance(item, dict) and item.get("id"):
            awards[str(item["id"])] = str(item.get("name") or "")
    if STATE.seen_awards is None:
        STATE.seen_awards = set(awards)
        return
    known = set()
    for view in views:
        for drop in view.drops:
            for value in (drop.name, drop.benefit):
                if value:
                    known.update(part.strip().lower() for part in str(value).split(","))
    for award_id, name in awards.items():
        if award_id in STATE.seen_awards:
            continue
        STATE.seen_awards.add(award_id)
        if name.lower() in known:
            logger.info("Selbstkontrolle: Twitch hat %s gutgeschrieben", name)
            continue
        warn(
            f"Twitch hat '{name}' gutgeschrieben, das der Miner nicht in seiner Liste hatte",
            now,
            key=f"award:{award_id}",
        )


def evaluate(views, ranked, statuses, streamers, pick, slugify, now=None):
    now = time.time() if now is None else now
    try:
        _check_stall(views, statuses, pick, now)
        _check_no_channel(ranked, statuses, streamers, slugify, now)
        _check_awards(views, now)
    except Exception:
        logger.debug("Selbstkontrolle fehlgeschlagen", exc_info=True)
    STATE.blocked = {k: v for k, v in STATE.blocked.items() if v > now}
