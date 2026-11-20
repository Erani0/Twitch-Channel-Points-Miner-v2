import copy
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from TwitchChannelPointsMiner.classes.Settings import Priority

logger = logging.getLogger(__name__)

REWARD_LIST_OPERATION = {
    "operationName": "RewardList",
    "extensions": {
        "persistedQuery": {
            "version": 1,
            "sha256Hash": "0b1471876d7647993731b9e3c6a13bf304c67fb31d07f06a945d42286ee377c4",
        }
    },
}
STREAM_LIVE_OPERATION = {
    "operationName": "WithIsStreamLiveQuery",
    "extensions": {
        "persistedQuery": {
            "version": 1,
            "sha256Hash": "04e46329a6786ff3a81c01c50bfa5d725902507a0deb83b0edbf7abe7a3716ea",
        }
    },
}

FIRST_CHECK_WATCHED_MINUTES = 5
CHECK_INTERVAL_SECONDS = 180
GIVE_UP_WATCHED_MINUTES = 30
LOAN_MAX_SECONDS = 15 * 60
LOAN_COOLDOWN_SECONDS = 10 * 60
URGENT_EXPIRY_SECONDS = 12 * 3600
WARNING_THROTTLE_SECONDS = 15 * 60


def parse_timestamp(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def is_synthetic_broadcast_id(broadcast_id):
    return broadcast_id is not None and ":" in str(broadcast_id)


def format_local(timestamp):
    return datetime.fromtimestamp(timestamp).strftime("%d.%m. %H:%M")


@dataclass
class MissedStream:
    started_at: float | None
    ended_at: float | None
    state: str
    expires_at: float | None


@dataclass
class Milestone:
    state: str
    value: int | None
    achievement_at: float | None
    expires_at: float | None
    missed: list = field(default_factory=list)


@dataclass
class LoanState:
    login: str
    started_at: float

    @property
    def expires_at(self):
        return self.started_at + LOAN_MAX_SECONDS


@dataclass
class LoanInfo:
    active: bool
    login: str | None
    started_at: float | None
    expires_at: float | None
    max_seconds: int
    cooldown_until: float


def parse_reward_list(data):
    channel = (data or {}).get("channel") or {}
    own = channel.get("self") or {}
    outer = own.get("watchStreakMilestone") or {}
    inner = outer.get("watchStreakMilestone") or {}
    try:
        value = int(inner.get("value")) if inner.get("value") is not None else None
    except (TypeError, ValueError):
        value = None
    missed = []
    for item in outer.get("missedStreams") or []:
        if not isinstance(item, dict):
            continue
        missed.append(
            MissedStream(
                started_at=parse_timestamp(item.get("startedAt")),
                ended_at=parse_timestamp(item.get("endedAt")),
                state=str(item.get("state") or ""),
                expires_at=parse_timestamp(item.get("expiresAt")),
            )
        )
    return Milestone(
        state=str(outer.get("state") or "NONE"),
        value=value,
        achievement_at=parse_timestamp(inner.get("achievementTimestamp")),
        expires_at=parse_timestamp(outer.get("expiresAt")),
        missed=missed,
    )


class GqlClient:
    def __init__(self, gql):
        self.gql = gql

    def _post(self, template, variables):
        payload = copy.deepcopy(template)
        payload["variables"] = variables
        parser = self.gql.parser
        return self.gql.post_gql_request_single(
            template["operationName"],
            payload,
            lambda response: parser.parse_base_response(response, True)[2],
        )

    def reward_list(self, channel_id):
        data = self._post(
            REWARD_LIST_OPERATION,
            {"channelID": channel_id, "shouldIncludeAllSuspendedStreaks": True},
        )
        return parse_reward_list(data)

    def stream_created_at(self, channel_id):
        data = self._post(STREAM_LIVE_OPERATION, {"id": channel_id})
        stream = ((data or {}).get("user") or {}).get("stream") or {}
        return parse_timestamp(stream.get("createdAt"))


@dataclass
class Track:
    login: str
    logical_start: float
    current_broadcast_id: str | None = None
    broadcast_ids: set = field(default_factory=set)
    last_seen: float = 0.0
    done: bool = False
    done_at: float | None = None
    gave_up: bool = False
    rescue: bool = False
    baseline_value: int | None = None
    value: int | None = None
    expires_at: float | None = None
    checks: int = 0
    last_check_at: float = 0.0
    carried_minutes: float = 0.0
    last_stream_minutes: float = 0.0
    created_checked_for: str | None = None
    last_warning_at: float = 0.0

    def watched_minutes(self):
        return self.carried_minutes + self.last_stream_minutes


class StreakState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.configured = False
        self.max_parallel = None
        self.min_gap_seconds = 1800
        self.length_order = None
        self.cache = None
        self.client = None
        self.twitch = None
        self.tracks = {}
        self.known_length = {}
        self.missed_logged = set()
        self.missed_path = None
        self.loan = None
        self.loan_cooldown_until = 0.0
        self.loan_exhausted = set()
        self.lock = threading.RLock()


STATE = StreakState()


def configure(
    max_parallel=None,
    min_gap_seconds=1800,
    requested_priority=None,
    cache=None,
    missed_path=None,
    known_length=None,
):
    STATE.reset()
    STATE.max_parallel = max_parallel
    STATE.min_gap_seconds = max(0, int(min_gap_seconds))
    for entry in list(requested_priority or []):
        if entry == Priority.STREAK_LENGTH_DESCENDING:
            STATE.length_order = "desc"
            break
        if entry == Priority.STREAK_LENGTH_ASCENDING:
            STATE.length_order = "asc"
            break
    STATE.cache = cache
    STATE.known_length = dict(known_length or {})
    STATE.missed_path = missed_path
    load_missed()
    STATE.configured = True


def load_missed():
    if not STATE.missed_path:
        return
    try:
        with open(STATE.missed_path, "r", encoding="utf-8") as handle:
            STATE.missed_logged = set(json.load(handle))
    except (OSError, ValueError, TypeError):
        STATE.missed_logged = set()


def save_missed():
    if not STATE.missed_path:
        return
    try:
        os.makedirs(os.path.dirname(STATE.missed_path), exist_ok=True)
        with open(STATE.missed_path, "w", encoding="utf-8") as handle:
            json.dump(sorted(STATE.missed_logged), handle)
    except OSError:
        pass


def bind(twitch):
    if STATE.client is None and getattr(twitch, "gql", None) is not None:
        STATE.client = GqlClient(twitch.gql)
    STATE.twitch = twitch


def cache_sessions(login):
    cache = STATE.cache
    if cache is None:
        return []
    with cache._lock:
        return sorted(
            (s for s in cache._sessions.values() if s.streamer_login == login),
            key=lambda s: s.started_at,
        )


def merge_synthetic_sessions(login, real_broadcast_id):
    cache = STATE.cache
    if cache is None or is_synthetic_broadcast_id(real_broadcast_id):
        return 0
    merged = 0
    with cache._lock:
        real = cache._sessions.get(cache._key(login, real_broadcast_id))
        synthetic = [
            s
            for s in cache._sessions.values()
            if s.streamer_login == login and is_synthetic_broadcast_id(s.broadcast_id)
        ]
        if real is None or not synthetic:
            return 0
        for item in synthetic:
            if abs(item.started_at - real.started_at) > STATE.min_gap_seconds * 4:
                continue
            if item.claimed:
                real.claimed = True
                if real.claimed_at is None:
                    real.claimed_at = item.claimed_at or item.started_at
            real.started_at = min(real.started_at, item.started_at)
            del cache._sessions[item.key]
            merged += 1
        if merged:
            cache._save_locked()
    return merged


def chain_from_cache(login, now):
    sessions = cache_sessions(login)
    if not sessions:
        return None, False, None
    latest = sessions[-1]
    reference = latest.ended_at if latest.ended_at is not None else now
    if now - reference >= STATE.min_gap_seconds:
        return None, False, None
    start = latest.started_at
    claimed = latest.claimed
    for previous in reversed(sessions[:-1]):
        gap = 0 if previous.ended_at is None else start - previous.ended_at
        if gap >= STATE.min_gap_seconds:
            break
        start = min(start, previous.started_at)
        claimed = claimed or previous.claimed
    return start, claimed, reference


def new_track(streamer, now):
    start, claimed, seen = chain_from_cache(streamer.username, now)
    track = Track(
        login=streamer.username, logical_start=start if start is not None else now
    )
    track.last_seen = seen if seen is not None else now
    if claimed:
        track.done = True
        track.done_at = now
    return track


def update(streamer, now=None):
    now = time.time() if now is None else now
    login = streamer.username
    stream = streamer.stream
    broadcast_id = getattr(stream, "broadcast_id", None)
    track = STATE.tracks.get(login)
    if track is None:
        track = new_track(streamer, now)
        STATE.tracks[login] = track
    elif (
        broadcast_id is not None
        and track.current_broadcast_id is not None
        and str(broadcast_id) != track.current_broadcast_id
        and not is_synthetic_broadcast_id(track.current_broadcast_id)
        and now - track.last_seen >= STATE.min_gap_seconds
    ):
        track = Track(login=login, logical_start=now)
        STATE.tracks[login] = track
    if broadcast_id is not None:
        if (
            track.current_broadcast_id is not None
            and is_synthetic_broadcast_id(track.current_broadcast_id)
            and not is_synthetic_broadcast_id(broadcast_id)
        ):
            track.broadcast_ids.discard(track.current_broadcast_id)
        merge_synthetic_sessions(login, broadcast_id)
        track.current_broadcast_id = str(broadcast_id)
        track.broadcast_ids.add(str(broadcast_id))
    minutes = float(getattr(stream, "minute_watched", 0) or 0)
    if minutes < track.last_stream_minutes:
        track.carried_minutes += track.last_stream_minutes
    track.last_stream_minutes = minutes
    track.last_seen = now
    if not track.done and getattr(stream, "watch_streak_missing", True) is False:
        mark_done(streamer, track, now, "Ereignis")
    return track


def mark_done(streamer, track, now, source, value=None):
    if track.done:
        return
    track.done = True
    track.done_at = now
    track.rescue = False
    try:
        streamer.stream.watch_streak_missing = False
    except AttributeError:
        pass
    cache = STATE.cache
    if cache is not None and track.current_broadcast_id:
        cache.mark_claimed(track.login, track.current_broadcast_id)
    shown = value if value is not None else track.value
    logger.info(
        "Streak bei %s bestätigt (%s%s)",
        track.login,
        f"Wert {shown}, " if shown is not None else "",
        source,
        extra={"emoji": ":fire:"},
    )


def warn_throttled(track, now, message, *args):
    if now - track.last_warning_at >= WARNING_THROTTLE_SECONDS:
        track.last_warning_at = now
        logger.warning(message, *args)


def check_due(track, now):
    if track.done or track.gave_up:
        return False
    if track.checks == 0:
        return True
    if now - track.last_check_at < CHECK_INTERVAL_SECONDS:
        return False
    return track.watched_minutes() >= FIRST_CHECK_WATCHED_MINUTES


def run_check(streamer, track, now):
    client = STATE.client
    channel_id = getattr(streamer, "channel_id", None)
    if client is None or channel_id in (None, ""):
        return
    track.last_check_at = now
    track.checks += 1
    broadcast_id = track.current_broadcast_id
    if broadcast_id and track.created_checked_for != broadcast_id:
        track.created_checked_for = broadcast_id
        try:
            created = client.stream_created_at(channel_id)
        except Exception as error:
            logger.debug("Streamstart von %s nicht abrufbar: %s", track.login, error)
            created = None
        if created is not None and created < track.logical_start:
            track.logical_start = created
    try:
        milestone = client.reward_list(channel_id)
    except Exception as error:
        warn_throttled(
            track, now, "Streak-Abfrage bei %s fehlgeschlagen: %s", track.login, error
        )
        return
    track.value = milestone.value
    track.expires_at = milestone.expires_at
    if track.baseline_value is None:
        track.baseline_value = milestone.value or 0
    report_missed(track, milestone, now)
    advanced = (
        milestone.achievement_at is not None
        and milestone.achievement_at >= track.logical_start
    ) or (milestone.value is not None and milestone.value > track.baseline_value)
    if advanced:
        mark_done(streamer, track, now, "Twitch-Abfrage", milestone.value)


def report_missed(track, milestone, now):
    rescue = False
    for missed in milestone.missed:
        if missed.state != "SUSPENDED":
            continue
        if missed.expires_at is not None and missed.expires_at <= now:
            continue
        rescue = True
        key = f"{track.login}|{missed.started_at}|{missed.ended_at}"
        if key in STATE.missed_logged:
            continue
        STATE.missed_logged.add(key)
        save_missed()
        logger.warning(
            "Streak bei %s (%s) ausgesetzt, verpasster Stream %s-%s, retten bis %s: "
            "Clip, VOD oder Stream ansehen",
            track.login,
            milestone.value if milestone.value is not None else 0,
            format_local(missed.started_at) if missed.started_at else "?",
            format_local(missed.ended_at) if missed.ended_at else "?",
            format_local(missed.expires_at) if missed.expires_at else "?",
        )
    track.rescue = rescue and not track.done


def refresh(streamer, now):
    track = update(streamer, now)
    if track.done or track.gave_up:
        return track
    if check_due(track, now):
        run_check(streamer, track, now)
    if (
        not track.done
        and not track.gave_up
        and track.watched_minutes() >= GIVE_UP_WATCHED_MINUTES
    ):
        track.gave_up = True
        logger.info(
            "Streak bei %s nach %d Minuten ohne Bestätigung aufgegeben, "
            "Platz wird freigegeben",
            track.login,
            GIVE_UP_WATCHED_MINUTES,
        )
    return track


def streak_enabled(streamer):
    settings = getattr(streamer, "settings", None)
    return getattr(settings, "watch_streak", False) is True


def is_pending(streamer, now=None):
    if not STATE.configured:
        return None
    if not streak_enabled(streamer) or getattr(streamer, "is_online", True) is False:
        return False
    with STATE.lock:
        track = update(streamer, time.time() if now is None else now)
        return not track.done and not track.gave_up


def ordering_key(snapshot, index, base_rank, now):
    login = snapshot[index].username
    track = STATE.tracks.get(login)
    expires = track.expires_at if track is not None else None
    urgent = expires is not None and expires - now <= URGENT_EXPIRY_SECONDS
    value = None
    if track is not None and track.value is not None:
        value = track.value
    elif login in STATE.known_length:
        value = STATE.known_length[login]
    if STATE.length_order == "desc":
        length_key = (value in (None, 0), -(value or 0))
    elif STATE.length_order == "asc":
        length_key = (value in (None, 0), value or 0)
    else:
        length_key = (False, 0)
    rescue = track is not None and track.rescue
    return (0 if rescue else 1, 0 if urgent else 1, length_key, base_rank)


def pending_order(snapshot, candidate_indexes, now):
    pending = []
    for rank, index in enumerate(candidate_indexes):
        streamer = snapshot[index]
        if not streak_enabled(streamer) or getattr(streamer, "is_online", True) is False:
            continue
        track = refresh(streamer, now)
        if not track.done and not track.gave_up:
            pending.append((index, rank))
    pending.sort(key=lambda item: ordering_key(snapshot, item[0], item[1], now))
    return [index for index, _ in pending]


def loan_info():
    loan = STATE.loan
    return LoanInfo(
        active=loan is not None,
        login=loan.login if loan else None,
        started_at=loan.started_at if loan else None,
        expires_at=loan.expires_at if loan else None,
        max_seconds=LOAN_MAX_SECONDS,
        cooldown_until=STATE.loan_cooldown_until,
    )


def loan_key(login):
    track = STATE.tracks.get(login)
    start = track.logical_start if track is not None else 0
    return f"{login}|{start}"


def end_loan(now):
    STATE.loan = None
    STATE.loan_cooldown_until = now + LOAN_COOLDOWN_SECONDS


def update_loan(snapshot, pending, unserved, drop_available, now):
    pending_logins = {snapshot[i].username for i in pending}
    loan = STATE.loan
    if loan is not None:
        if loan.login not in pending_logins:
            end_loan(now)
        elif now >= loan.expires_at:
            STATE.loan_exhausted.add(loan_key(loan.login))
            logger.info(
                "Leihgabe des Drop-Platzes an %s nach %d Minuten beendet",
                loan.login,
                LOAN_MAX_SECONDS // 60,
            )
            end_loan(now)
    if (
        STATE.loan is None
        and unserved
        and drop_available
        and now >= STATE.loan_cooldown_until
    ):
        for index in unserved:
            login = snapshot[index].username
            if loan_key(login) in STATE.loan_exhausted:
                continue
            STATE.loan = LoanState(login=login, started_at=now)
            break
    return STATE.loan


def wants_drop_slot(snapshot, unserved, now=None):
    now = time.time() if now is None else now
    if STATE.loan is not None:
        return True
    if now < STATE.loan_cooldown_until:
        return False
    return any(loan_key(snapshot[i].username) not in STATE.loan_exhausted for i in unserved)


def apply(
    twitch,
    snapshot,
    watching,
    streamers_index,
    priority,
    streams_watched,
    is_drop_stream,
    now=None,
):
    watching = list(watching)
    if not STATE.configured or Priority.STREAK not in (priority or []):
        return watching
    now = time.time() if now is None else now
    bind(twitch)
    with STATE.lock:
        candidates = list(streamers_index)
        for index, streamer in enumerate(snapshot):
            if (
                index not in candidates
                and getattr(streamer, "is_online", False) is True
                and streak_enabled(streamer)
            ):
                update(streamer, now)
        pending = pending_order(snapshot, candidates, now)
        pending_set = set(pending)
        drop_holders = [
            index
            for index in watching
            if index not in pending_set and is_drop_stream(index)
        ]
        if STATE.max_parallel is None:
            streak_slots = max(0, streams_watched - len(drop_holders))
        else:
            streak_slots = STATE.max_parallel
        served = pending[:streak_slots]
        unserved = pending[streak_slots:]
        loan = update_loan(snapshot, pending, unserved, bool(drop_holders), now)
        lent = []
        if loan is not None and drop_holders:
            loan_index = next(
                (i for i in unserved if snapshot[i].username == loan.login), None
            )
            if loan_index is not None:
                served.append(loan_index)
                lent = drop_holders[:1]
                drop_holders = drop_holders[1:]
        served_set = set(served)
        kept_drops = [i for i in drop_holders if i not in served_set]
        others = [
            i
            for i in watching
            if i not in served_set
            and i not in kept_drops
            and i not in lent
            and i not in pending_set
        ]
        limit = streams_watched
        if STATE.max_parallel is not None:
            limit = max(streams_watched, len(served) + len(kept_drops))
        room = max(0, limit - len(served) - len(kept_drops))
        return served + kept_drops + others[:room]
