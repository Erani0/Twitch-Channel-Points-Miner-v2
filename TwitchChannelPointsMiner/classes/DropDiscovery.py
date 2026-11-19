import logging
import time
from typing import Optional

from TwitchChannelPointsMiner.classes.Chat import ChatPresence
from TwitchChannelPointsMiner.classes.DropCampaignCollector import DropCampaignCollector
from TwitchChannelPointsMiner.classes.DropCampaignFile import DropCampaignFile, empty_settings
from TwitchChannelPointsMiner.classes.entities.Campaign import Campaign
from TwitchChannelPointsMiner.classes.entities.Streamer import Streamer, StreamerSettings

logger = logging.getLogger(__name__)

SCAN_INTERVAL_SECONDS = 15 * 60
MONITOR_INTERVAL_SECONDS = 60
STALL_SECONDS = 25 * 60
PAUSE_SECONDS = 6 * 60 * 60


class DropDiscovery:
    """Keeps one watch slot permanently on drops.

    Every SCAN_INTERVAL_SECONDS it loads the active campaigns with their real
    inventory progress and rewrites drop_campaigns.json (finished campaigns drop
    out, new ones are added, the user's order stays). The file is checked every
    minute; its order is the working order, so the slot always holds the highest
    listed campaign that currently has a live channel. A channel that goes offline
    or shows no progress for STALL_SECONDS is replaced by another live channel for
    the same campaign. Twitch.py keeps this slot off-limits for watch streaks while
    a drop channel is active (see _select_streamers_to_watch).
    """

    def __init__(
        self,
        twitch,
        miner,
        scan_interval: int = SCAN_INTERVAL_SECONDS,
        monitor_interval: int = MONITOR_INTERVAL_SECONDS,
        campaign_file: Optional[DropCampaignFile] = None,
        stall_seconds: int = STALL_SECONDS,
        collector: Optional[DropCampaignCollector] = None,
    ):
        self.twitch = twitch
        self.miner = miner
        self.scan_interval = scan_interval
        self.monitor_interval = monitor_interval
        self.stall_seconds = stall_seconds
        self.campaign_file = campaign_file
        self.collector = collector or DropCampaignCollector(twitch)
        self._finished: list[Campaign] = []
        self._eligible: dict[str, list] = {}
        self.running = True
        self._campaigns: list[Campaign] = []
        self._settings = empty_settings()
        self._queue: list[Campaign] = []
        self._queued_ids: set[str] = set()
        self._active_campaign: Optional[Campaign] = None
        self._active_streamer: Optional[Streamer] = None
        self._borrowed = False
        self._bad_channels: dict[str, set[str]] = {}
        self._progress_minutes = 0
        self._progress_at = 0.0
        self._stalls: dict[str, int] = {}
        self._paused: dict[str, float] = {}

    def stop(self) -> None:
        self.running = False

    def run(self) -> None:
        last_scan = 0.0
        while self.running and self.miner.running:
            try:
                now = time.time()
                if now - last_scan >= self.scan_interval:
                    self._refresh_queue()
                    last_scan = now
                elif self.campaign_file is not None and self.campaign_file.changed():
                    self._settings = self.campaign_file.read_settings()
                    self._apply_order()
                    self._write_file()

                if self._active_streamer is not None:
                    self._monitor_active()
                else:
                    self._start_next()
            except Exception:
                logger.debug("[drop-discovery] Cycle failed", exc_info=True)

            time.sleep(self.monitor_interval)

    def _load_campaigns(self):
        campaigns = []
        try:
            campaigns = list(self.twitch.get_active_campaigns() or [])
        except Exception:
            logger.debug("[drop-discovery] Drops dashboard not available", exc_info=True)
        known = self.campaign_file.known_slugs() if self.campaign_file is not None else []
        try:
            result = self.collector.collect(self.miner.streamers, known)
        except Exception:
            logger.debug("[drop-discovery] Campaign collection failed", exc_info=True)
            return campaigns, [], {}
        present = {c.id for c in campaigns}
        campaigns += [c for c in result.campaigns if c.id not in present]
        return campaigns, result.finished, result.channels

    def _refresh_queue(self) -> None:
        if self.campaign_file is not None:
            self._settings = self.campaign_file.read_settings()
        campaigns, finished, channels = self._load_campaigns()
        self._campaigns = list(campaigns)
        self._finished = list(finished)
        self._eligible = dict(channels)
        live_ids = {c.id for c in campaigns}
        self._bad_channels = {k: v for k, v in self._bad_channels.items() if k in live_ids}

        if self._active_campaign is not None:
            fresh = next((c for c in campaigns if c.id == self._active_campaign.id), None)
            if fresh is None:
                logger.info(
                    "[drop-discovery] Campaign '%s' is done or ended, releasing the slot",
                    self._active_campaign.name,
                )
                self._release_active()
            else:
                self._active_campaign = fresh
                self._check_progress(fresh)

        self._apply_order(look_upwards=True)
        self._write_file()

    def _paused_ids(self) -> set:
        now = time.time()
        self._paused = {cid: until for cid, until in self._paused.items() if until > now}
        return set(self._paused)

    def _apply_order(self, look_upwards: bool = True) -> None:
        paused = self._paused_ids()
        ranked = [c for c in DropCampaignFile.rank(self._campaigns, self._settings) if c.id not in paused]
        self._queue = list(ranked)
        self._queued_ids = {c.id for c in ranked}
        if self._active_campaign is None:
            return
        if self._active_campaign.id not in self._queued_ids:
            logger.info(
                "[drop-discovery] Campaign '%s' is switched off in drop_campaigns.json, releasing the slot",
                self._active_campaign.name,
            )
            self._release_active()
            return
        if not look_upwards:
            return
        for campaign in ranked:
            if campaign.id == self._active_campaign.id:
                return
            login = self._find_channel(campaign)
            if login:
                logger.info(
                    "[drop-discovery] '%s' is listed higher and has a live channel, switching from '%s'",
                    campaign.name,
                    self._active_campaign.name,
                )
                self._release_active()
                self._start_with(campaign, login)
                return

    def _write_file(self) -> None:
        if self.campaign_file is None:
            return
        self.campaign_file.write(
            self._campaigns,
            self._settings,
            self._active_campaign,
            self._active_streamer.username if self._active_streamer else None,
            finished=self._finished,
            live_ids=set(self._eligible) | ({self._active_campaign.id} if self._active_campaign else set()),
            paused_ids=self._paused_ids(),
        )

    def _check_progress(self, campaign: Campaign) -> None:
        minutes = campaign.watched_minutes()
        now = time.time()
        if minutes > self._progress_minutes or self._progress_at == 0.0:
            if minutes > self._progress_minutes:
                self._stalls.pop(campaign.id, None)
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
            self._stalls[campaign.id] = self._stalls.get(campaign.id, 0) + 1
            others = [l for l, _ in self._eligible.get(campaign.id, []) if l.lower() not in self._bad_channels.get(campaign.id, set())]
            if self._stalls[campaign.id] >= 2 or not others:
                logger.info(
                    "[drop-discovery] '%s' shows no progress while watching, pausing it for %d hours",
                    campaign.name,
                    PAUSE_SECONDS // 3600,
                )
                self._paused[campaign.id] = time.time() + PAUSE_SECONDS
                self._stalls.pop(campaign.id, None)
                self._bad_channels.pop(campaign.id, None)
            self._release_active()

    def _find_channel(self, campaign: Campaign) -> Optional[str]:
        exclude = self._bad_channels.get(campaign.id, set())
        login = self._search_channel(campaign, exclude)
        if not login and exclude:
            self._bad_channels.pop(campaign.id, None)
        return login

    def _search_channel(self, campaign: Campaign, exclude: set) -> Optional[str]:
        for login, _ in self._eligible.get(campaign.id, []):
            if login.lower() not in exclude:
                return login
        try:
            if campaign.channels:
                return self.twitch._find_live_channel_for_campaign(campaign, exclude=exclude)
            slug = (campaign.game or {}).get("slug") if isinstance(campaign.game, dict) else None
            for channel_id, login, _, _ in (self.twitch.find_drop_channels_for_game(slug, 8) or [])[:5]:
                if login.lower() in exclude:
                    continue
                offered = {str(c.get("id")) for c in self.twitch.get_channel_drop_campaigns(channel_id)}
                if campaign.id in offered:
                    return login
        except Exception:
            logger.debug("[drop-discovery] Failed to find a channel for campaign %s", campaign.id, exc_info=True)
        return None

    def _start_next(self) -> None:
        for campaign in list(self._queue):
            login = self._find_channel(campaign)
            if not login:
                logger.debug("[drop-discovery] No live channel found yet for campaign %s", campaign.name)
                continue
            if self._start_with(campaign, login):
                return

    def _start_with(self, campaign: Campaign, login: str) -> bool:
        existing = self._existing_streamer(login)
        if existing is not None:
            if existing.is_online is False:
                return False
            existing.is_auto_drop_channel = True
            streamer = existing
            borrowed = True
        else:
            streamer = self._build_streamer(login)
            try:
                failed = self.twitch.initialize_streamers_context([streamer])
            except Exception:
                logger.debug("[drop-discovery] Failed to initialize %s", login, exc_info=True)
                return False
            if streamer.username in failed or streamer.is_online is False:
                return False
            self.miner.add_dynamic_streamer(streamer)
            borrowed = False

        self._borrowed = borrowed
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
        return True

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
