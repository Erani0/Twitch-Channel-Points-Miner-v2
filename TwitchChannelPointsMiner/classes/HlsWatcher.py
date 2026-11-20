import logging
import threading
import time
from collections import OrderedDict
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

POLL_SECONDS = 10
SEEN_LIMIT = 300
TIMEOUT = 10
HEADERS = {"Origin": "https://www.twitch.tv", "Referer": "https://www.twitch.tv/"}


def playlist_entries(text: str, base_url: str) -> list:
    entries = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        entries.append(urljoin(base_url, line))
    return entries


class HlsWatcher:
    def __init__(self, fetch_token, request, user_agent, is_running, poll_seconds=POLL_SECONDS, sleep=time.sleep):
        self.fetch_token = fetch_token
        self.request = request
        self.user_agent = user_agent
        self.is_running = is_running
        self.poll_seconds = poll_seconds
        self.sleep = sleep
        self._lock = threading.Lock()
        self._target = None
        self._key = None
        self._media_url = None
        self._seen = OrderedDict()
        self.segments_sent = 0

    def set_target(self, streamer) -> None:
        with self._lock:
            self._target = streamer

    @property
    def target_login(self):
        return self._key[0] if self._key else None

    def run(self) -> None:
        while self.is_running():
            try:
                self.tick()
            except Exception:
                logger.debug("[hls] Segment polling failed", exc_info=True)
            self.sleep(self.poll_seconds)

    def tick(self) -> int:
        with self._lock:
            streamer = self._target
        if streamer is None or getattr(streamer, "is_online", False) is not True:
            self._reset(None)
            return 0
        key = (streamer.username, streamer.stream.broadcast_id)
        if key != self._key:
            self._reset(key)
            logger.info(
                "[hls] Videostuecke fuer %s werden abgefragt, damit Drop-Minuten zaehlen",
                streamer.username,
                extra={"emoji": ":package:"},
            )
        if self._media_url is None:
            self._media_url = self._resolve_media_url(streamer)
            if self._media_url is None:
                return 0
        playlist = self._get(self._media_url)
        if playlist is None:
            self._media_url = None
            return 0
        sent = 0
        for url in playlist_entries(playlist, self._media_url):
            if url in self._seen:
                continue
            if self._head(url):
                self._remember(url)
                sent += 1
        self.segments_sent += sent
        return sent

    def _reset(self, key) -> None:
        self._key = key
        self._media_url = None
        self._seen.clear()

    def _remember(self, url) -> None:
        self._seen[url] = True
        while len(self._seen) > SEEN_LIMIT:
            self._seen.popitem(last=False)

    def _resolve_media_url(self, streamer):
        token = self.fetch_token(streamer)
        if not token:
            return None
        signature, value = token
        master_url = (
            f"https://usher.ttvnw.net/api/channel/hls/{streamer.username}.m3u8"
            f"?sig={signature}&token={value}"
        )
        master = self._get(master_url)
        if master is None:
            return None
        variants = playlist_entries(master, master_url)
        return variants[-1] if variants else None

    def _headers(self) -> dict:
        return {"User-Agent": self.user_agent, **HEADERS}

    def _get(self, url):
        try:
            response = self.request("GET", url, headers=self._headers(), timeout=TIMEOUT)
        except Exception:
            logger.debug("[hls] GET failed", exc_info=True)
            return None
        if response.status_code != 200:
            return None
        return response.text

    def _head(self, url) -> bool:
        try:
            response = self.request("HEAD", url, headers=self._headers(), timeout=TIMEOUT)
        except Exception:
            logger.debug("[hls] HEAD failed", exc_info=True)
            return False
        return response.status_code == 200
