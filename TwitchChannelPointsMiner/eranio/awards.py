import logging
import threading

from TwitchChannelPointsMiner.classes.entities.Drop import parse_datetime

logger = logging.getLogger(__name__)

REPORTED = set()
REPORTED_LOCK = threading.Lock()


def _benefit_ids(drop_dict):
    ids = []
    for edge in drop_dict.get("benefitEdges") or []:
        benefit = edge.get("benefit") if isinstance(edge, dict) else None
        if isinstance(benefit, dict) and benefit.get("id"):
            ids.append(str(benefit["id"]))
    return ids


def shared_benefit_ids(campaign_dicts):
    seen = {}
    for campaign in campaign_dicts or []:
        if not isinstance(campaign, dict):
            continue
        for drop in campaign.get("timeBasedDrops") or []:
            if not isinstance(drop, dict):
                continue
            for benefit_id in set(_benefit_ids(drop)):
                seen[benefit_id] = seen.get(benefit_id, 0) + 1
    return {benefit_id for benefit_id, count in seen.items() if count > 1}


def _award_times(inventory):
    times = {}
    for award in inventory.get("gameEventDrops") or []:
        if not isinstance(award, dict) or not award.get("id"):
            continue
        try:
            awarded_at = parse_datetime(str(award.get("lastAwardedAt") or ""))
        except ValueError:
            continue
        times.setdefault(str(award["id"]), []).append(awarded_at)
    return times


def mark_awarded(campaign, inventory, shared_ids):
    if not isinstance(inventory, dict):
        return []
    in_progress = inventory.get("dropCampaignsInProgress")
    if not isinstance(in_progress, list):
        return []
    if any(
        isinstance(entry, dict) and str(entry.get("id")) == str(campaign.id)
        for entry in in_progress
    ):
        return []
    times = _award_times(inventory)
    if not times:
        return []
    marked = []
    for drop in campaign.drops:
        if drop.is_claimed is True:
            continue
        ids = _benefit_ids({"benefitEdges": drop.benefit_edges})
        if not ids or any(benefit_id in shared_ids for benefit_id in ids):
            continue
        if all(
            any(drop.start_at <= at <= drop.end_at for at in times.get(benefit_id, []))
            for benefit_id in ids
        ):
            drop.is_claimed = True
            drop.current_minutes_watched = drop.minutes_required
            marked.append(drop)
    _report(campaign, marked)
    return marked


def _report(campaign, marked):
    for drop in marked:
        key = f"{campaign.id}|{drop.id}"
        with REPORTED_LOCK:
            if key in REPORTED:
                continue
            REPORTED.add(key)
        game = (
            campaign.game.get("displayName") if isinstance(campaign.game, dict) else ""
        )
        logger.info(
            "%s | %s | %s wurde von Twitch schon gutgeschrieben und wird nicht mehr geschaut",
            game or "Drops",
            campaign.name,
            drop.name,
        )
