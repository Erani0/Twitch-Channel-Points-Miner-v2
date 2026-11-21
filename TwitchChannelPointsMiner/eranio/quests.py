import copy
import logging
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace

logger = logging.getLogger(__name__)

REFRESH_SECONDS = 10 * 60
DETAILS_SECONDS = 6 * 3600
CLAIM_RETRY_SECONDS = 60 * 60
MAX_CHANNELS = 15
CATEGORY_SLOTS = 3
PREFERRED_SLUGS = ("just-chatting", "djs", "music", "special-events")
DONE_STATUSES = frozenset(["CLAIMED", "FULFILLED", "EXPIRED"])
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

INVENTORY_REQUEST = {
    "operationName": "ViewerRewardDropInventory",
    "variables": {},
    "extensions": {
        "persistedQuery": {
            "version": 1,
            "sha256Hash": "27e5625f916e910002e293a16fca17a9082848bd48d49c0f8aa34cdfd76ea5e5",
        }
    },
}

DETAILS_QUERY = (
    "query EranioQuestDetails($id: ID!) {"
    "dropsCampaign(id: $id) {"
    "id name status endAt game { id displayName slug boxArtURL } "
    "rewardGroups {"
    "id name "
    "progressCriteria {"
    "requirementType requirements { minutesWatched subs } "
    "channels { id login } categories { id displayName }"
    "} "
    "rewards { id name thumbnailURL }"
    "}"
    "}"
    "}"
)


def _slugify(value):
    from TwitchChannelPointsMiner.eranio.drops import slugify

    return slugify(value)


def _parse(value):
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _count(value):
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def sub_label(subs):
    if subs <= 0:
        return None
    if subs == 1:
        return "Sub nötig"
    return f"{subs} Subs nötig, auch verschenkt"


class QuestDrop:
    def __init__(
        self,
        group_id,
        name,
        benefit,
        image,
        minutes,
        watched,
        claimed,
        subs,
        waiting,
    ):
        self.id = group_id
        self.name = name
        self.benefit = benefit
        self.image = image
        self.minutes_required = minutes
        self.current_minutes_watched = min(watched, minutes) if minutes else 0
        self.is_claimed = claimed
        self.requires_subscription = subs > 0
        self.subs_required = subs
        self.has_preconditions_met = False if waiting else True
        self.start_at = None


class Quest:
    def __init__(self, campaign_id, name):
        self.id = campaign_id
        self.name = name
        self.drops = []
        self.channels = {}
        self.category_slugs = []
        self.claimable = []
        self.game = None
        self.end_at = None

    @property
    def channel_quest(self):
        return bool(self.channels)

    def sub_label(self):
        open_subs = [
            d.subs_required
            for d in self.drops
            if d.requires_subscription and not d.is_claimed
        ]
        return sub_label(max(open_subs)) if open_subs else None

    def remaining(self):
        values = [
            d.minutes_required - d.current_minutes_watched
            for d in self.drops
            if not d.is_claimed
            and not d.requires_subscription
            and d.minutes_required > 0
            and d.has_preconditions_met is not False
        ]
        return min(values) if values else None


class State:
    def __init__(self):
        self.reset()

    def reset(self):
        self.lock = threading.Lock()
        self.configured = False
        self.miner = None
        self.quests = {}
        self.details = {}
        self.last_refresh = 0
        self.claim_tries = {}
        self.added = set()
        self.adding = False


STATE = State()


def configure(miner=None):
    STATE.reset()
    STATE.configured = True
    STATE.miner = miner


def build_quests(inventory, details, now):
    quests = {}
    campaigns = (
        (((inventory or {}).get("data") or {}).get("currentUser") or {}).get(
            "inventory"
        )
        or {}
    ).get("viewerRewardDropCampaignsInProgress") or []
    for campaign in campaigns:
        if not isinstance(campaign, dict) or not campaign.get("id"):
            continue
        campaign_id = str(campaign["id"])
        info = details.get(campaign_id) or {}
        info_groups = {
            str(g.get("id")): g
            for g in info.get("rewardGroups") or []
            if isinstance(g, dict)
        }
        quest = Quest(campaign_id, campaign.get("name") or campaign_id)
        if isinstance(info.get("game"), dict):
            quest.game = dict(info["game"])
        quest.end_at = _parse(info.get("endAt") or campaign.get("endAt"))
        groups = [g for g in campaign.get("rewardGroups") or [] if isinstance(g, dict)]
        seen = {str(g.get("id")) for g in groups}
        groups += [g for gid, g in info_groups.items() if gid not in seen]
        for group in groups:
            if not isinstance(group, dict) or not group.get("id"):
                continue
            group_id = str(group["id"])
            detail = info_groups.get(group_id) or {}
            criteria = (
                detail.get("progressCriteria") or group.get("progressCriteria") or {}
            )
            requirements = criteria.get("requirements") or {}
            kind = criteria.get("requirementType")
            minutes = _count(requirements.get("minutesWatched"))
            subs = _count(requirements.get("subs"))
            if kind == "WATCH" and minutes <= 0:
                continue
            if kind not in ("WATCH", "SUB"):
                continue
            own = group.get("self") or {}
            status = own.get("status")
            repeat = (group.get("progressCriteria") or {}).get("repeatableConfig")
            times = max(_count((repeat or {}).get("repeatableTimes")), 1)
            grants = _count(own.get("grantCount"))
            claimed = status in DONE_STATUSES or grants >= times
            window = own.get("currentWindow") or {}
            expires = _parse(window.get("expiresAt"))
            window_open = expires is None or expires > now
            watched = _count(own.get("currentMinutesWatched")) if window_open else 0
            next_at = _parse(own.get("nextEligibleAt"))
            waiting = (next_at is not None and next_at > now) or (
                kind == "WATCH" and minutes and watched >= minutes and not claimed
            )
            if status == "CLAIMABLE":
                quest.claimable.append(group_id)
                waiting = True
            rewards = [r for r in group.get("rewards") or [] if isinstance(r, dict)]
            reward = rewards[0] if rewards else {}
            quest.drops.append(
                QuestDrop(
                    group_id,
                    detail.get("name") or group.get("name") or reward.get("name"),
                    reward.get("name"),
                    reward.get("thumbnailURL"),
                    minutes if kind == "WATCH" else 0,
                    watched,
                    claimed,
                    subs if kind == "SUB" else 0,
                    waiting,
                )
            )
            if kind == "WATCH":
                for channel in criteria.get("channels") or []:
                    if isinstance(channel, dict) and channel.get("id"):
                        quest.channels[str(channel["id"])] = str(
                            channel.get("login") or ""
                        ).lower()
                for category in criteria.get("categories") or []:
                    if isinstance(category, dict):
                        slug = _slugify(
                            category.get("displayName") or category.get("name")
                        )
                        if slug and slug not in quest.category_slugs:
                            quest.category_slugs.append(slug)
        if quest.drops:
            quests[campaign_id] = quest
    return quests


def refresh(twitch, now=None):
    if not STATE.configured:
        return
    current = time.time() if now is None else now
    if current - STATE.last_refresh < REFRESH_SECONDS:
        return
    STATE.last_refresh = current
    gql = getattr(twitch, "gql", None)
    if gql is None:
        return
    try:
        inventory = gql.post_gql_request_raw(
            INVENTORY_REQUEST["operationName"], copy.deepcopy(INVENTORY_REQUEST)
        )
    except Exception:
        logger.warning("Quests: Inventar bei Twitch nicht lesbar", exc_info=True)
        return
    campaigns = (
        (((inventory or {}).get("data") or {}).get("currentUser") or {}).get(
            "inventory"
        )
        or {}
    ).get("viewerRewardDropCampaignsInProgress") or []
    for campaign in campaigns:
        campaign_id = str((campaign or {}).get("id") or "")
        if not campaign_id:
            continue
        known = STATE.details.get(campaign_id)
        if known and current - known[0] < DETAILS_SECONDS:
            continue
        try:
            answer = gql.post_gql_request_raw(
                "EranioQuestDetails",
                {
                    "operationName": "EranioQuestDetails",
                    "query": DETAILS_QUERY,
                    "variables": {"id": campaign_id},
                },
            )
            info = ((answer or {}).get("data") or {}).get("dropsCampaign") or {}
            STATE.details[campaign_id] = (current, info)
        except Exception:
            logger.warning(
                "Quests: Details zu %s nicht lesbar", campaign_id, exc_info=True
            )
    details = {key: value[1] for key, value in STATE.details.items()}
    quests = build_quests(inventory, details, datetime.utcnow())
    with STATE.lock:
        changed = set(quests) != set(STATE.quests)
        STATE.quests = quests
    if changed:
        bound = [q for q in quests.values() if q.channel_quest]
        logger.info(
            "Quests geladen: %s, davon %s an Kanäle gebunden (%s)",
            len(quests),
            len(bound),
            ", ".join(sorted({l for q in bound for l in q.channels.values() if l})),
        )
    _claim(twitch, quests, current)


def _claim(twitch, quests, now):
    gql = getattr(twitch, "gql", None)
    login = getattr(twitch, "twitch_login", None)
    if gql is None or login is None:
        return
    try:
        user_id = login.get_user_id()
    except Exception:
        return
    for quest in quests.values():
        for group_id in quest.claimable:
            key = f"{quest.id}#{group_id}"
            if now - STATE.claim_tries.get(key, 0) < CLAIM_RETRY_SECONDS:
                continue
            STATE.claim_tries[key] = now
            try:
                gql.claim_drop_rewards(f"{user_id}#{quest.id}#{group_id}")
                logger.info("Quest %s: Belohnung abgeholt", quest.name)
            except Exception:
                logger.debug("Quests: Abholen fehlgeschlagen", exc_info=True)


def patch_views(views):
    with STATE.lock:
        quests = dict(STATE.quests)
    for view in views:
        quest = quests.get(view.id)
        view.quest_channel = False
        view.quest_slugs = []
        view.sub_hint = None
        view.channel_logins = []
        if quest is None:
            continue
        view.quest = True
        view.sub_hint = quest.sub_label()
        if quest.channel_quest:
            view.quest_channel = True
            view.drops = list(quest.drops)
            view.total_drops = len(view.drops)
            view.future_drops = 0
            view.channels = list(quest.channels)
            view.channel_logins = [l for l in quest.channels.values() if l]
        else:
            view.quest_slugs = list(quest.category_slugs)
    return views


def category_slugs(view):
    slugs = list(getattr(view, "quest_slugs", None) or [])
    preferred = [s for s in PREFERRED_SLUGS if s in slugs]
    rest = [s for s in slugs if s not in preferred]
    return (preferred + rest)[:CATEGORY_SLOTS]


def wanted_logins(ranked_views):
    logins = []
    for view in ranked_views:
        if not getattr(view, "quest_channel", False) or not view.is_earnable():
            continue
        for login in getattr(view, "channel_logins", []) or []:
            if login and login not in logins:
                logins.append(login)
    return logins[:MAX_CHANNELS]


def ensure_streamers(logins):
    miner = STATE.miner
    if miner is None or STATE.adding:
        return
    tracked = {getattr(s, "username", "") for s in getattr(miner, "streamers", [])}
    missing = [l for l in logins if l not in tracked and l not in STATE.added]
    if not missing:
        return
    STATE.adding = True

    def run():
        try:
            miner.add_streamers(missing)
            STATE.added.update(missing)
            logger.info("Quest-Kanäle aufgenommen: %s", ", ".join(missing))
        except Exception:
            logger.warning("Quests: Kanäle nicht aufgenommen", exc_info=True)
        finally:
            STATE.adding = False

    threading.Thread(target=run, name="eranio-quest-channels", daemon=True).start()


def extra_campaigns(known_ids):
    with STATE.lock:
        quests = list(STATE.quests.values())
    extra = []
    for quest in quests:
        if quest.id in known_ids or not quest.channel_quest:
            continue
        extra.append(
            SimpleNamespace(
                id=quest.id,
                name=quest.name,
                game=quest.game or {"displayName": "Quest"},
                reward_categories=[],
                end_at=quest.end_at,
                start_at=None,
                drops=[],
                channels=[],
            )
        )
    return extra
