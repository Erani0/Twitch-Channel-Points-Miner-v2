import logging
import time
from typing import Optional

from TwitchChannelPointsMiner.classes.Chat import ChatPresence
from TwitchChannelPointsMiner.classes.DropCampaignFile import DropCampaignFile
from TwitchChannelPointsMiner.classes.entities.Campaign import Campaign
from TwitchChannelPointsMiner.classes.entities.Streamer import Streamer, StreamerSettings

logger = logging.getLogger(__name__)

SCAN_INTERVAL_SECONDS = 5 * 60
MONITOR_INTERVAL_SECONDS = 60
STALL_SECONDS = 20 * 60


class DropDiscovery:
    """Keeps one watch slot permanently on drops.

    Every scan it loads the active campaigns with their real inventory progress,
    ranks them (the user's order from drop_campaigns.json first, then campaigns
    already started, then the one closest to its next drop, then the one ending
    first), writes the file back and makes sure the reserved slot is busy with a
    live channel that counts for the best campaign. A channel that is offline, no
    longer counts or shows no progress for STALL_SECONDS is replaced by another
    live channel for the same campaign. Twitch.py keeps this slot off-limits for
    watch streaks while a drop channel is active (see _select_streamers_to_watch).
    """

    def __init__(
        self,
        twitch,
        miner,
        scan_interval: int = SCAN_INTERVAL_SECONDS,
        monitor_interval: int = MONITOR_INTERVAL_SECONDS,
        campaign_file: Optional[DropCampaignFile] = None,
        stall_seconds: int = STALL_SECONDS,
    ):
        self.twitch = twitch
        self.miner = miner
        self.scan_interval = scan_interval
        self.monitor_interval = monitor_interval
        self.stall_seconds = stall_seconds
        self.campaign_file = campaign_file
        self.running = True
        self._queue: list[Campaign] = []
        self._queued_ids: set[str] = set()
        self._active_campaign: Optional[Campaign] = None
        self._active_streamer: Optional[Streamer] = None
        self._borrowed = False
        self._bad_channels: dict[str, set[str]] = {}
        self._progress_minutes = 0
        self._progress_at = 0.0

    def stop(self) -> None:
        self.running = False

    def run(self) -> None:
        last_scan = 0.0
        while self.running and self.miner.running:
            now = time.time()
            if now - last_scan >= self.scan_interval:
                self._refresh_queue()
                last_scan = now

            try:
                if self._active_streamer is not None:
                    self._monitor_active()
                else:
                    self._start_next()
            except Exception:
                logger.debug("[drop-discovery] Cycle failed", exc_info=True)

            time.sleep(self.monitor_interval)

    def _refresh_queue(self) -> None:
        try:
            campaigns = self.twitch.get_active_campaigns()
        except Exception:
            logger.debug("[drop-discovery] Failed to refresh active campaigns", exc_info=True)
            return

        settings = (
            self.campaign_file.read_settings()
            if self.campaign_file is not None
            else {"games": {}, "campaigns": {}}
        )
        ranked = DropCampaignFile.rank(campaigns, settings)
        self._queue = list(ranked)
        self._queued_ids = {c.id for c in ranked}
        live_ids = {c.id for c in campaigns}
        self._bad_channels = {k: v for k, v in self._bad_channels.items() if k in live_ids}

        if self._active_campaign is not None:
            fresh = next((c for c in campaigns if c.id == self._active_campaign.id), None)
            if fresh is None:
                logger.info(
                    "[drop-discovery] Campaign '%s' is done, releasing the slot",
                    self._active_campaign.name,
                )
                self._release_active()
            elif fresh.id not in self._queued_ids:
                logger.info(
                    "[drop-discovery] Campaign '%s' is switched off in drop_campaigns.json, releasing the slot",
                    fresh.name,
                )
                self._release_active()
            else:
                self._check_progress(fresh)
                if self._active_campaign is not None and ranked and ranked[0].id != fresh.id:
                    _, best_order = DropCampaignFile.effective(ranked[0], settings)
                    _, current_order = DropCampaignFile.effective(fresh, settings)
                    if best_order > 0 and (current_order == 0 or best_order < current_order):
                        logger.info(
                            "[drop-discovery] '%s' comes first in drop_campaigns.json, switching from '%s'",
                            ranked[0].name,
                            fresh.name,
                        )
                        self._release_active()
                if self._active_campaign is not None:
                    self._active_campaign = fresh

        if self.campaign_file is not None:
            self.campaign_file.write(
                ranked + [c for c in campaigns if c.id not in self._queued_ids],
                settings,
                self._active_campaign,
                self._active_streamer.username if self._active_streamer else None,
            )

    def _check_progress(self, campaign: Campaign) -> None:
        minutes = campaign.watched_minutes()
        now = time.time()
        if minutes > self._progress_minutes or self._progress_at == 0.0:
            self._progress_minutes = minutes
            self._progress_at = now
            return
        if now - self._progress_at >= self.stall_seconds:
            login = self._active_streamer.username if self._active_streamer else None
            logger.info(
                "[drop-discovery] No drop progress on %s for '%s' for %d minutes, trying another channel",
                login,
                campaign.name,
                self.stall_seconds // 60,
            )
            if login:
                self._bad_channels.setdefault(campaign.id, set()).add(login.lower())
            self._release_active()

    def _start_next(self) -> None:
        for campaign in list(self._queue):
            exclude = self._bad_channels.get(campaign.id, set())
            try:
                login = self.twitch._find_live_channel_for_campaign(campaign, exclude=exclude)
            except Exception:
                logger.debug(
                    "[drop-discovery] Failed to find a channel for campaign %s",
                    campaign.id,
                    exc_info=True,
                )
                continue
            if not login:
                if exclude:
                    self._bad_channels.pop(campaign.id, None)
                logger.debug("[drop-discovery] No live channel found yet for campaign %s", campaign.name)
                continue

            existing = self._existing_streamer(login)
            if existing is not None:
                if existing.is_online is False:
                    continue
                existing.is_auto_drop_channel = True
                streamer = existing
                self._borrowed = True
            else:
                streamer = self._build_streamer(login)
                try:
                    failed = self.twitch.initialize_streamers_context([streamer])
                except Exception:
                    logger.debug("[drop-discovery] Failed to initialize %s", login, exc_info=True)
                    continue
                if streamer.username in failed or streamer.is_online is False:
                    continue
                self.miner.add_dynamic_streamer(streamer)
                self._borrowed = False

            self._active_campaign = campaign
            self._active_streamer = streamer
            self._progress_minutes = campaign.watched_minutes()
            self._progress_at = time.time()
            logger.info(
                "Auto-watching %s for drop campaign '%s'",
                streamer.username,
                campaign.name,
                extra={"emoji": ":package:"},
            )
            return

    def _existing_streamer(self, login: str) -> Optional[Streamer]:
        wanted = login.lower()
        for streamer in list(self.miner.streamers):
            if getattr(streamer, "username", "").lower() == wanted:
                return streamer
        return None

    def _monitor_active(self) -> None:
        streamer = self._active_streamer
        try:
            self.twitch.check_streamer_online(streamer)
        except Exception:
            logger.debug("[drop-discovery] Online check failed for %s", streamer.username, exc_info=True)

        if streamer.is_online is False:
            logger.info("[drop-discovery] %s went offline, looking for another channel", streamer.username)
            self._release_active()
            self._start_next()

    def _release_active(self) -> None:
        if self._active_streamer is not None:
            if self._borrowed:
                self._active_streamer.is_auto_drop_channel = False
            else:
                self.miner.remove_dynamic_streamer(self._active_streamer)
        self._active_streamer = None
        self._active_campaign = None
        self._borrowed = False
        self._progress_minutes = 0
        self._progress_at = 0.0

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
