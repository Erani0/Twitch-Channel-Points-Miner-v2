import logging
import time
from typing import Optional

from TwitchChannelPointsMiner.classes.Chat import ChatPresence
from TwitchChannelPointsMiner.classes.entities.Campaign import Campaign
from TwitchChannelPointsMiner.classes.entities.Streamer import Streamer, StreamerSettings

logger = logging.getLogger(__name__)

SCAN_INTERVAL_SECONDS = 5 * 60
MONITOR_INTERVAL_SECONDS = 60


class DropDiscovery:
    """Finds live channels for currently active drop campaigns that aren't in the
    user's configured streamer list, and watches them one at a time in the shared
    "universal" watch slot until every campaign it finds has been fully claimed.

    Never touches the reserved slot used by the user's own streamers/watch-streaks
    (Twitch.py's selection logic keeps that slot off-limits, see
    _select_streamers_to_watch); this class only manages which channel currently
    occupies the shared slot from the drops side.
    """

    def __init__(
        self,
        twitch,
        miner,
        scan_interval: int = SCAN_INTERVAL_SECONDS,
        monitor_interval: int = MONITOR_INTERVAL_SECONDS,
    ):
        self.twitch = twitch
        self.miner = miner
        self.scan_interval = scan_interval
        self.monitor_interval = monitor_interval
        self.running = True
        self._queue: list[Campaign] = []
        self._queued_ids: set[str] = set()
        self._active_campaign: Optional[Campaign] = None
        self._active_streamer: Optional[Streamer] = None

    def stop(self) -> None:
        self.running = False

    def run(self) -> None:
        last_scan = 0.0
        while self.running and self.miner.running:
            now = time.time()
            if now - last_scan >= self.scan_interval:
                self._refresh_queue()
                last_scan = now

            if self._active_streamer is not None:
                self._monitor_active()
            else:
                self._start_next()

            time.sleep(self.monitor_interval)

    def _refresh_queue(self) -> None:
        try:
            campaigns = self.twitch.get_active_campaigns()
        except Exception:
            logger.debug(
                "[drop-discovery] Failed to refresh active campaigns", exc_info=True
            )
            return

        active_id = self._active_campaign.id if self._active_campaign else None
        for campaign in campaigns:
            if campaign.id == active_id or campaign.id in self._queued_ids:
                continue
            self._queue.append(campaign)
            self._queued_ids.add(campaign.id)
        self._queue.sort(key=lambda c: c.end_at)

    def _start_next(self) -> None:
        while self._queue:
            campaign = self._queue.pop(0)
            self._queued_ids.discard(campaign.id)

            try:
                login = self.twitch._find_live_channel_for_campaign(campaign)
            except Exception:
                logger.debug(
                    "[drop-discovery] Failed to find a channel for campaign %s",
                    campaign.id,
                    exc_info=True,
                )
                continue
            if not login:
                logger.debug(
                    "[drop-discovery] No live channel found yet for campaign %s",
                    campaign.name,
                )
                continue

            streamer = self._build_streamer(login)
            try:
                failed = self.twitch.initialize_streamers_context([streamer])
            except Exception:
                logger.debug(
                    "[drop-discovery] Failed to initialize %s", login, exc_info=True
                )
                continue
            if streamer.username in failed or streamer.is_online is False:
                continue

            self.miner.add_dynamic_streamer(streamer)
            self._active_campaign = campaign
            self._active_streamer = streamer
            logger.info(
                "Auto-watching %s for drop campaign '%s'",
                streamer.username,
                campaign.name,
                extra={"emoji": ":package:"},
            )
            return
        # Queue exhausted for now; _refresh_queue will repopulate it on the next scan.

    def _monitor_active(self) -> None:
        streamer = self._active_streamer
        campaign = self._active_campaign

        try:
            self.twitch.check_streamer_online(streamer)
        except Exception:
            logger.debug(
                "[drop-discovery] Online check failed for %s",
                streamer.username,
                exc_info=True,
            )

        if streamer.is_online is False:
            logger.info(
                "[drop-discovery] %s went offline, releasing the slot",
                streamer.username,
            )
            self._release_active()
            return

        if self._campaign_complete(campaign):
            logger.info(
                "[drop-discovery] Campaign '%s' fully claimed, releasing the slot",
                campaign.name,
            )
            self._release_active()

    def _campaign_complete(self, campaign: Campaign) -> bool:
        try:
            campaigns = self.twitch.get_active_campaigns()
        except Exception:
            # Can't confirm completion this cycle; keep watching rather than
            # dropping progress on a transient API error.
            return False
        return not any(c.id == campaign.id for c in campaigns)

    def _release_active(self) -> None:
        if self._active_streamer is not None:
            self.miner.remove_dynamic_streamer(self._active_streamer)
        self._active_streamer = None
        self._active_campaign = None

    def _build_streamer(self, login: str) -> Streamer:
        settings = StreamerSettings(
            make_predictions=False,
            follow_raid=False,
            claim_drops=True,
            claim_moments=False,
            watch_streak=False,
            community_goals=False,
            chat=ChatPresence.NEVER,
        )
        settings.default()
        streamer = Streamer(login, settings=settings)
        streamer.is_auto_drop_channel = True
        return streamer
