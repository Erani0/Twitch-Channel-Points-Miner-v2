import logging
import threading
import time

from TwitchChannelPointsMiner.classes.Settings import Settings
from TwitchChannelPointsMiner.eranio import streak

logger = logging.getLogger(__name__)

RECORD_INTERVAL_SECONDS = 6 * 3600
SYNC_INTERVAL_SECONDS = 15 * 60
FIRST_SYNC_DELAY_SECONDS = 60


class HistoryState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.recorded = {}
        self.lock = threading.Lock()
        self.thread = None
        self.stop = threading.Event()


STATE = HistoryState()


def current_days(login):
    track = streak.STATE.tracks.get(login)
    if track is not None and track.value is not None:
        return max(0, int(track.value))
    known = streak.STATE.known_length.get(login)
    if known is not None:
        return max(0, int(known))
    return None


def record(streamer, days, now=None):
    if days is None or getattr(Settings, "enable_analytics", False) is not True:
        return False
    if not getattr(Settings, "analytics_path", None):
        return False
    now = time.time() if now is None else now
    login = streamer.username
    with STATE.lock:
        last = STATE.recorded.get(login)
        if (
            last is not None
            and last[0] == days
            and now - last[1] < RECORD_INTERVAL_SECONDS
        ):
            return False
        STATE.recorded[login] = (days, now)
    try:
        streamer.persistent_streak_days(days)
    except Exception:
        logger.debug("Streak-Verlauf von %s nicht gespeichert", login, exc_info=True)
        return False
    return True


def sync(streamers, now=None):
    written = 0
    for streamer in list(streamers or []):
        if record(streamer, current_days(streamer.username), now):
            written += 1
    return written


def start(miner):
    if STATE.thread is not None and STATE.thread.is_alive():
        return
    STATE.stop.clear()

    def loop():
        if STATE.stop.wait(FIRST_SYNC_DELAY_SECONDS):
            return
        while True:
            try:
                sync(miner.streamers)
            except Exception:
                logger.debug("Streak-Verlauf: Abgleich fehlgeschlagen", exc_info=True)
            if STATE.stop.wait(SYNC_INTERVAL_SECONDS):
                return

    STATE.thread = threading.Thread(target=loop, name="Streak history", daemon=True)
    STATE.thread.start()
