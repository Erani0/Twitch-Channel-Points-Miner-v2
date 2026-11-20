import json
import logging
import os

from TwitchChannelPointsMiner.WatchStreakCache import WatchStreakSession
from TwitchChannelPointsMiner.eranio.streak import is_synthetic_broadcast_id

logger = logging.getLogger(__name__)


def load_old_cache(path, account_name):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError):
        return [], {}
    if not isinstance(payload, dict):
        return [], {}
    account = account_name.lower().strip()
    sessions = []
    for item in payload.get("sessions") or []:
        if not isinstance(item, dict):
            continue
        try:
            if str(item.get("account_name", "")).lower().strip() != account:
                continue
            login = str(item.get("streamer_login", "")).lower().strip()
            broadcast_id = str(item.get("broadcast_id", ""))
            if not login or not broadcast_id:
                continue
            claimed = bool(item.get("claimed", False))
            started_at = float(item["started_at"])
            last_attempt = item.get("last_attempt_at")
            ended = item.get("ended_at")
            sessions.append(
                WatchStreakSession(
                    account_name=account,
                    streamer_login=login,
                    broadcast_id=broadcast_id,
                    started_at=started_at,
                    claimed=claimed,
                    claimed_at=(
                        float(last_attempt)
                        if claimed and last_attempt not in (None, "")
                        else (started_at if claimed else None)
                    ),
                    ended_at=float(ended) if ended not in (None, "") else None,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    lengths = {}
    for item in payload.get("streamer_statuses") or []:
        if not isinstance(item, dict):
            continue
        days = item.get("watch_streak_days")
        login = str(item.get("streamer_login", "")).lower().strip()
        try:
            if login and days not in (None, ""):
                lengths[login] = max(0, int(days))
        except (TypeError, ValueError):
            continue
    return sessions, lengths


def migrate_old_cache(cache, old_path, min_gap_seconds=1800):
    lengths = {}
    if cache is None or not old_path or not os.path.isfile(old_path):
        return 0, lengths
    sessions, lengths = load_old_cache(old_path, cache.account_name)
    if not sessions:
        return 0, lengths
    if os.path.isfile(cache.path) or cache._sessions:
        return 0, lengths
    real = [s for s in sessions if not is_synthetic_broadcast_id(s.broadcast_id)]
    synthetic = [s for s in sessions if is_synthetic_broadcast_id(s.broadcast_id)]
    kept = list(real)
    for item in synthetic:
        target = next(
            (
                r
                for r in real
                if r.streamer_login == item.streamer_login
                and abs(r.started_at - item.started_at) <= min_gap_seconds * 4
            ),
            None,
        )
        if target is None:
            kept.append(item)
            continue
        if item.claimed:
            target.claimed = True
            target.claimed_at = target.claimed_at or item.claimed_at
        target.started_at = min(target.started_at, item.started_at)
    with cache._lock:
        for session in kept:
            cache._sessions[session.key] = session
        cache._save_locked()
    logger.info(
        "Streak-Verlauf aus der alten Datei übernommen (%d Sitzungen)", len(kept)
    )
    return len(kept), lengths
