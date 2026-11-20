import json
import logging
import threading
import time

import requests

logger = logging.getLogger(__name__)

GQL_URL = "https://gql.twitch.tv/gql"
PUBLIC_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
BATCH_SIZE = 15
KNOWN_SECONDS = 12 * 3600
RETRY_SECONDS = 10 * 60
WORKER_PAUSE_SECONDS = 2


class PointsState:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.enabled = {}
        self.checked_at = {}
        self.failed_at = {}
        self.pending = set()
        self.reported = set()
        self.worker = None


STATE = PointsState()


def _login(streamer):
    return str(getattr(streamer, "username", "") or "").strip().lower()


def has_points(streamer, now=None):
    login = _login(streamer)
    if not login:
        return True
    now = time.time() if now is None else now
    with STATE.lock:
        checked = STATE.checked_at.get(login)
        if checked is not None and now - checked < KNOWN_SECONDS:
            return STATE.enabled.get(login, True)
        failed = STATE.failed_at.get(login)
        if failed is None or now - failed >= RETRY_SECONDS:
            STATE.pending.add(login)
            _ensure_worker()
        return STATE.enabled.get(login, True)


def _ensure_worker():
    worker = STATE.worker
    if worker is not None and worker.is_alive():
        return
    STATE.worker = threading.Thread(
        target=_work, name="eranio-points-check", daemon=True
    )
    STATE.worker.start()


def _work():
    while True:
        time.sleep(WORKER_PAUSE_SECONDS)
        with STATE.lock:
            batch = sorted(STATE.pending)[:BATCH_SIZE]
            STATE.pending.difference_update(batch)
        if not batch:
            return
        try:
            results = fetch(batch)
        except Exception as error:
            logger.debug("Kanalpunkte-Abfrage fehlgeschlagen: %s", error)
            results = {}
        store(batch, results)


def build_query(logins):
    parts = []
    for index, login in enumerate(logins):
        parts.append(
            f"u{index}: user(login: {json.dumps(login)}) "
            "{ login channel { communityPointsSettings { isEnabled } } }"
        )
    return "query { " + " ".join(parts) + " }"


def parse(logins, payload):
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {}
    results = {}
    for index, login in enumerate(logins):
        user = data.get(f"u{index}")
        if not isinstance(user, dict):
            continue
        settings = (user.get("channel") or {}).get("communityPointsSettings")
        if isinstance(settings, dict) and isinstance(settings.get("isEnabled"), bool):
            results[login] = settings["isEnabled"]
    return results


def fetch(logins):
    response = requests.post(
        GQL_URL,
        json={"query": build_query(logins)},
        headers={"Client-Id": PUBLIC_CLIENT_ID},
        timeout=15,
    )
    response.raise_for_status()
    return parse(logins, response.json())


def store(logins, results, now=None):
    now = time.time() if now is None else now
    newly_disabled = []
    with STATE.lock:
        for login in logins:
            if login in results:
                STATE.enabled[login] = results[login]
                STATE.checked_at[login] = now
                STATE.failed_at.pop(login, None)
                if results[login] is False and login not in STATE.reported:
                    STATE.reported.add(login)
                    newly_disabled.append(login)
            else:
                STATE.failed_at[login] = now
    for login in newly_disabled:
        logger.info(
            "%s hat keine Kanalpunkte und wird nur noch für Drops geschaut",
            login,
        )
