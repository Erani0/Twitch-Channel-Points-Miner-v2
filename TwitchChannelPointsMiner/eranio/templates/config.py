# -*- coding: utf-8 -*-
CONFIG_VERSION = 12
# Einstellungen des Miners. Sie lassen sich hier oder auf der Einstellungsseite ändern.

import os
import sys
import subprocess
import logging
from colorama import Fore
from TwitchChannelPointsMiner.logger import LoggerSettings, ColorPalette
from TwitchChannelPointsMiner.classes.Chat import ChatPresence
from TwitchChannelPointsMiner.classes.Discord import Discord
from TwitchChannelPointsMiner.classes.Telegram import Telegram
from TwitchChannelPointsMiner.classes.Settings import Priority, Events, FollowersOrder
from TwitchChannelPointsMiner.classes.entities.Bet import (
    Strategy,
    BetSettings,
    Condition,
    OutcomeKeys,
    FilterCondition,
    DelayMode,
)
from TwitchChannelPointsMiner.classes.entities.Streamer import (
    Streamer,
    StreamerSettings,
)
from TwitchChannelPointsMiner.classes.Settings import StreamerSource
from TwitchChannelPointsMiner.classes.Email import Email

MINER_CONFIG = {
    "username": os.environ.get("TWITCH_USER", "__USERNAME__"),
    "claim_drops_startup": True,
    "enable_analytics": True,
    "disable_ssl_cert_verification": False,
    "disable_at_in_nickname": True,
    "logger_settings": LoggerSettings(
        save=True,
        console_level=logging.INFO,
        console_username=False,
        auto_clear=True,
        time_zone="Europe/Berlin",
        file_level=logging.INFO,
        emoji=True,
        less=False,
        colored=True,
        color_palette=ColorPalette(
            STREAMER_online="GREEN", streamer_offline="red", BET_wiN=Fore.MAGENTA
        ),
        # telegram=Telegram(chat_id=123456789, token="TOKEN", events=[]),
        # discord=Discord(webhook_api="https://discord.com/api/webhooks/...", events=[]),
        # webhook=Webhook(endpoint="https://example.com/webhook", method="POST", events=[]),
        # matrix=Matrix(username="USER", password="PASSWORD", homeserver="matrix.org", room_id="ROOM", events=[]),
        # pushover=Pushover(userkey="USER_KEY", token="TOKEN", priority=0, sound="pushover", events=[]),
        # gotify=Gotify(endpoint="https://example.com/message?token=TOKEN", priority=0, events=[]),
        # email=Email(host="smtp.example.com", port=587, sender="miner@example.com", recipients=["you@example.com"], events=[]),
        # ntfy=Ntfy(topic="YOUR_NTFY_TOPIC", events=[]),
        # apprise=Apprise(urls=["discord://WEBHOOK_ID/WEBHOOK_TOKEN"], events=[]),
        console_format="text",
        date_format="dd/mm/yy",
        file_format="text",
        log_retention_days=7,
        daily_report=False,
        daily_report_time="00:00",
        username=None,
    ),
    "streamer_settings": StreamerSettings(
        make_predictions=False,
        follow_raid=True,
        claim_drops=True,
        claim_moments=True,
        watch_streak=True,
        chat=ChatPresence.NEVER,
        bet=BetSettings(
            strategy=Strategy.SMART,
            percentage=5,
            percentage_gap=20,
            max_points=50000,
            stealth_mode=True,
            delay_mode=DelayMode.FROM_END,
            delay=6,
            minimum_points=20000,
            filter_condition=FilterCondition(
                by=OutcomeKeys.TOTAL_USERS, where=Condition.LTE, value=800
            ),
        ),
        favorite=False,
        points_limit=None,
        community_goals=False,
        gift_sub_thanks=False,
        gift_sub_message=None,
    ),
    "streamer_source_priority": [
        StreamerSource.STREAMERS,
        StreamerSource.FOLLOWERS,
        StreamerSource.CATEGORIES,
        StreamerSource.BADGES,
        StreamerSource.WILDCARD_CATEGORIES,
    ],
    "update_check": True,
    "update_check_interval_hours": 24,
    "streams_watched": 2,
    "android_login": True,
    "priority": [Priority.STREAK, Priority.DROPS, Priority.ORDER, Priority.FAVORITE],
}

STREAMERS = [
    Streamer("eranio"),
]

MINE_CONFIG = {
    "followers": True,
    "followers_order": FollowersOrder.ASC,
    "categories": [],
    "blacklist": [],
    "category_drops_enabled": True,
    "category_limit": 30,
    "category_sort": "VIEWERS_DESC",
    "category_campaign_order": "ORDER",
    "category_chat": ChatPresence.NEVER,
    "category_log_level": logging.INFO,
    "drop_item_art": False,
    "print_open_drop_campaigns_on_load": False,
    "scrape_drop_progress_on_load": False,
    "log_drop_checks": False,
    "track_category_streamer_points": False,
    "category_refresh_interval_hours": 2,
    "drop_progress_stall_minutes": 10,
    "drop_pick_stickiness_minutes": 15,
    "watch_status_interval_minutes": 15,
    "category_drops_override_streamers": False,
    "drop_badge_catalog": True,
    "drop_badge_refresh_interval_hours": 1,
    "auto_mine_badge_drops": False,
    "badge_drop_streamer_limit": 1,
    "wildcard_categories": True,
    "wildcard_category_limit": 10,
    "wildcard_category_streamer_limit": 1,
    "wildcard_category_pin_active": True,
}

ANALYTICS_CONFIG = {
    "host": "0.0.0.0",
    "port": int(os.environ.get("SERVER_PORT", __PORT__)),
    "refresh": 5,
    "days_ago": 360,
    "password": None,
    "log_poll_interval": 5,
}

ERANIO_CONFIG = {
    "auto_discover_drops": True,
    "watch_streak_min_offline_seconds": 1800,
    "priority": [Priority.STREAK, Priority.DROPS, Priority.ORDER],
    "watch_only_drops": False,
    "stop_watch_when_drops_completed": False,
    "watch_streak_max_parallel": 2,
    "use_hermes": True,
}
