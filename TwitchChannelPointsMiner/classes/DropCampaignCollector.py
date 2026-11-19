import logging
from datetime import datetime, timezone

from TwitchChannelPointsMiner.classes.entities.Campaign import Campaign

logger = logging.getLogger(__name__)

MAX_STREAMER_LOOKUPS = 30
MAX_GAME_LOOKUPS = 40
CHANNELS_PER_GAME = 8


def _game(game) -> dict:
    game = game if isinstance(game, dict) else {}
    name = game.get("displayName") or game.get("name") or ""
    return {"id": game.get("id"), "name": game.get("name") or name, "displayName": name, "slug": game.get("slug")}


def _first_start(starts) -> str:
    return min(starts) if starts else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _benefit_ids(raw_drop) -> set:
    ids = set()
    for edge in raw_drop.get("benefitEdges") or []:
        benefit = edge.get("benefit") if isinstance(edge, dict) else None
        if isinstance(benefit, dict) and benefit.get("id"):
            ids.add(str(benefit["id"]).split("_CUSTOM_ID_")[0])
    return ids


class CollectResult:
    def __init__(self, campaigns, finished, channels):
        self.campaigns = campaigns
        self.finished = finished
        self.channels = channels


class DropCampaignCollector:
    """Builds the list of running drop campaigns without the drops dashboard, which
    returns nothing for the TV login. Sources: live channels the miner already
    watches that carry the drops tag, live drop channels of games seen before, and
    the inventory (campaigns in progress). Claimed drops are recognised from the
    inventory's reward list."""

    def __init__(self, twitch):
        self.twitch = twitch

    def collect(self, streamers, known_slugs) -> CollectResult:
        sources = []
        seen_channels = set()
        counts = {"streamer": 0, "game": 0}
        limits = {"streamer": MAX_STREAMER_LOOKUPS, "game": MAX_GAME_LOOKUPS}

        def add_source(channel_id, login, viewers, game, kind):
            if not channel_id or not login or channel_id in seen_channels:
                return
            if counts[kind] >= limits[kind]:
                return
            counts[kind] += 1
            seen_channels.add(channel_id)
            sources.append((channel_id, login, viewers, _game(game)))

        live = []
        for streamer in list(streamers or []):
            stream = getattr(streamer, "stream", None)
            if getattr(streamer, "is_online", False) and stream is not None and getattr(streamer, "channel_id", None):
                live.append((0 if getattr(stream, "drops_tags", False) else 1, -(getattr(stream, "viewers_count", 0) or 0), streamer))
        live.sort(key=lambda x: (x[0], x[1]))
        for _, _, streamer in live:
            stream = streamer.stream
            add_source(str(streamer.channel_id), streamer.username, getattr(stream, "viewers_count", 0) or 0, getattr(stream, "game", {}) or {}, "streamer")

        inventory = {"in_progress": [], "claimed": set()}
        for _ in range(2):
            try:
                inventory = self.twitch.get_drop_inventory()
            except Exception:
                logger.debug("[drop-discovery] Inventory lookup failed", exc_info=True)
            if inventory["in_progress"] or inventory["claimed"]:
                break

        slugs = []
        for slug in list(known_slugs or []) + [_game(c.get("game")).get("slug") for c in inventory["in_progress"]]:
            if slug and slug not in slugs:
                slugs.append(slug)
        for slug in slugs:
            try:
                for channel_id, login, viewers, game in self.twitch.find_drop_channels_for_game(slug, CHANNELS_PER_GAME):
                    add_source(channel_id, login, viewers, game, "game")
            except Exception:
                logger.debug("[drop-discovery] Directory lookup failed for %s", slug, exc_info=True)

        raw = {}
        games = {}
        channels = {}
        for channel_id, login, viewers, game in sources:
            try:
                found = self.twitch.get_channel_drop_campaigns(channel_id)
            except Exception:
                logger.debug("[drop-discovery] Drop lookup failed for %s", login, exc_info=True)
                continue
            for campaign in found:
                cid = str(campaign["id"])
                raw.setdefault(cid, campaign)
                if game.get("displayName"):
                    games.setdefault(cid, game)
                channels.setdefault(cid, [])
                if login not in [x[0] for x in channels[cid]]:
                    channels[cid].append((login, viewers))

        for campaign in inventory["in_progress"]:
            cid = str(campaign["id"])
            raw[cid] = campaign
            games[cid] = _game(campaign.get("game"))

        campaigns = []
        finished = []
        for cid, data in raw.items():
            built = self._build(data, games.get(cid) or _game(data.get("game")), inventory["claimed"])
            if built is None:
                continue
            campaigns.append(built)

        try:
            campaigns = self.twitch.sync_campaign_progress(campaigns)
        except Exception:
            logger.debug("[drop-discovery] Progress sync failed", exc_info=True)

        active = []
        for campaign in campaigns:
            upcoming = [d.start_at for d in campaign.drops if not d.is_claimed and d.start_at > datetime.utcnow()]
            campaign.next_start = min(upcoming) if upcoming else None
            campaign.clear_drops()
            (active if campaign.drops or campaign.next_start else finished).append(campaign)
        for cid in channels:
            channels[cid].sort(key=lambda x: x[1], reverse=True)
        return CollectResult(active, finished, channels)

    @staticmethod
    def _build(data, game, claimed):
        drops = [d for d in data.get("timeBasedDrops") or [] if isinstance(d, dict)]
        if not drops or not data.get("endAt"):
            return None
        starts = [d.get("startAt") for d in drops if d.get("startAt")]
        payload = {
            "id": str(data["id"]),
            "name": data.get("name") or "Unbekannte Kampagne",
            "status": data.get("status") or "ACTIVE",
            "game": game,
            "allow": data.get("allow") if isinstance(data.get("allow"), dict) else {"channels": None},
            "startAt": data.get("startAt") or _first_start(starts),
            "endAt": data["endAt"],
            "timeBasedDrops": [
                {
                    "id": d.get("id"),
                    "name": d.get("name") or "",
                    "benefitEdges": d.get("benefitEdges") or [],
                    "requiredMinutesWatched": d.get("requiredMinutesWatched") or 0,
                    "startAt": d.get("startAt") or data.get("startAt") or _first_start(starts),
                    "endAt": d.get("endAt") or data["endAt"],
                }
                for d in drops
                if d.get("id")
            ],
            "self": data.get("self") if isinstance(data.get("self"), dict) else {},
        }
        try:
            campaign = Campaign(payload)
        except Exception:
            logger.debug("[drop-discovery] Could not read campaign %s", data.get("id"), exc_info=True)
            return None
        if not campaign.dt_match:
            return None
        by_id = {str(d.get("id")): d for d in drops}
        for drop in campaign.drops:
            ids = _benefit_ids(by_id.get(str(drop.id), {}))
            if ids and ids <= claimed:
                drop.is_claimed = True
        return campaign
