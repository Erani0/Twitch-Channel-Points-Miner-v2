import logging
import os
from pathlib import Path

from TwitchChannelPointsMiner.classes.Settings import FollowersOrder, Priority, Settings
from TwitchChannelPointsMiner.eranio import drops, export, streak, streak_history
from TwitchChannelPointsMiner.eranio.streak_cache import migrate_old_cache
from TwitchChannelPointsMiner.eranio.git_config import dedupe_git_safe_directories
from TwitchChannelPointsMiner.TwitchChannelPointsMiner import (
    TwitchChannelPointsMiner as BaseMiner,
)

logger = logging.getLogger(__name__)

MIN_OFFLINE_FOR_NEW_STREAK = 1800
DROP_REFRESH_HOURS = 0.25

STREAK_LENGTH_PRIORITIES = (
    Priority.STREAK_LENGTH_ASCENDING,
    Priority.STREAK_LENGTH_DESCENDING,
)


def normalize_priority(priority):
    if priority is None:
        return None
    entries = list(priority) if isinstance(priority, (list, tuple)) else [priority]
    normalized = []
    for entry in entries:
        mapped = Priority.STREAK if entry in STREAK_LENGTH_PRIORITIES else entry
        if mapped == Priority.STREAK and Priority.STREAK in normalized:
            continue
        normalized.append(mapped)
    return normalized


def normalize_watch_streak_max_parallel(value):
    if value is None:
        return None
    return max(1, int(value))


def normalize_watch_streak_min_offline_seconds(value):
    if value is None:
        return MIN_OFFLINE_FOR_NEW_STREAK
    return max(0, int(value))


class TwitchChannelPointsMiner(BaseMiner):
    def __init__(
        self,
        username: str,
        password: str = None,
        claim_drops_startup: bool = False,
        enable_analytics: bool = False,
        disable_ssl_cert_verification: bool = False,
        disable_at_in_nickname: bool = False,
        watch_only_drops: bool = False,
        stop_watch_when_drops_completed: bool = False,
        auto_discover_drops: bool = False,
        priority=None,
        logger_settings=None,
        streamer_settings=None,
        watch_streak_max_parallel: int | None = None,
        watch_streak_min_offline_seconds: int = MIN_OFFLINE_FOR_NEW_STREAK,
        use_hermes: bool = True,
        **v3_options,
    ):
        try:
            dedupe_git_safe_directories()
        except Exception:
            pass

        self.watch_only_drops = bool(watch_only_drops)
        self.stop_watch_when_drops_completed = bool(stop_watch_when_drops_completed)
        self.auto_discover_drops = bool(auto_discover_drops)
        self.watch_streak_max_parallel = normalize_watch_streak_max_parallel(
            watch_streak_max_parallel
        )
        self.watch_streak_min_offline_seconds = (
            normalize_watch_streak_min_offline_seconds(watch_streak_min_offline_seconds)
        )
        self.use_hermes = bool(use_hermes)
        self.requested_priority = (
            list(priority) if isinstance(priority, (list, tuple)) else priority
        )

        options = dict(v3_options)
        options.setdefault("update_check", False)
        if logger_settings is not None:
            options["logger_settings"] = logger_settings
        if streamer_settings is not None:
            options["streamer_settings"] = streamer_settings
        normalized_priority = normalize_priority(priority)
        if normalized_priority is not None:
            options["priority"] = normalized_priority
        super().__init__(
            username,
            claim_drops_startup=claim_drops_startup,
            enable_analytics=enable_analytics,
            disable_ssl_cert_verification=disable_ssl_cert_verification,
            disable_at_in_nickname=disable_at_in_nickname,
            **options,
        )

        if use_hermes:
            logger.info("The classic event connection (PubSub) is used.")
        state_dir = os.path.join(Path().absolute(), "logs")
        _, known_length = migrate_old_cache(
            self.watch_streak_cache,
            os.path.join(
                state_dir, f"watch_streak_cache.{self.username.lower()}.json"
            ),
            self.watch_streak_min_offline_seconds,
        )
        export.configure(self.username)
        streak.configure(
            max_parallel=self.watch_streak_max_parallel,
            min_gap_seconds=self.watch_streak_min_offline_seconds,
            requested_priority=self._as_list(priority),
            cache=self.watch_streak_cache,
            missed_path=os.path.join(
                state_dir, ".state", f"eranio_streak_missed.{self.username.lower()}.json"
            ),
            known_length=known_length,
        )

    @staticmethod
    def _as_list(priority):
        if priority is None:
            return []
        return list(priority) if isinstance(priority, (list, tuple)) else [priority]

    def analytics(
        self,
        host: str = "127.0.0.1",
        port: int = 5000,
        refresh: int = 5,
        days_ago: int = 7,
        password: str = None,
        log_poll_interval: int = 5,
    ):
        if not Settings.enable_analytics:
            return super().analytics(
                host=host,
                port=port,
                refresh=refresh,
                days_ago=days_ago,
                password=None,
                log_poll_interval=log_poll_interval,
            )
        from TwitchChannelPointsMiner.classes.AnalyticsServer import AnalyticsServer

        http_server = AnalyticsServer(
            host="127.0.0.1",
            port=port,
            refresh=refresh,
            days_ago=min(days_ago, 365 * 15),
            username=self.username,
            password=None,
            log_poll_interval=log_poll_interval,
            logs_file=self.logs_file,
        )
        http_server.host = host
        http_server.daemon = True
        http_server.name = "Analytics Thread"
        http_server.start()

    def mine(
        self,
        streamers: list = None,
        blacklist: list = None,
        followers: bool = False,
        followers_order: FollowersOrder = FollowersOrder.ASC,
        *args,
        watch_only_drops: bool = None,
        stop_watch_when_drops_completed: bool = None,
        **kwargs,
    ):
        if self.auto_discover_drops:
            if args:
                shared = list(args[0] or [])
                args = (shared,) + tuple(args[1:])
            else:
                shared = list(kwargs.get("categories") or [])
                kwargs["categories"] = shared
            drops.configure(categories=shared)
            kwargs.setdefault("wildcard_categories", True)
            kwargs.setdefault("drop_pick_stickiness_minutes", 0)
            kwargs["category_refresh_interval_hours"] = min(
                float(kwargs.get("category_refresh_interval_hours", 6)),
                DROP_REFRESH_HOURS,
            )
        else:
            drops.STATE.reset()
        if watch_only_drops is not None:
            self.watch_only_drops = bool(watch_only_drops)
        if stop_watch_when_drops_completed is not None:
            self.stop_watch_when_drops_completed = bool(
                stop_watch_when_drops_completed
            )
        streak_history.start(self)
        export.STATE.follow_order = followers_order
        export.start(self)
        try:
            return super().mine(
                list(streamers) if streamers is not None else [],
                list(blacklist) if blacklist is not None else [],
                followers,
                followers_order,
                *args,
                **kwargs,
            )
        finally:
            export.finish(self)
