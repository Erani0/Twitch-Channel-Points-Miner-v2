import os
import sys
import logging
from colorama import Fore
from TwitchChannelPointsMiner import TwitchChannelPointsMiner
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

try:
    from TwitchChannelPointsMiner.run_config_migration import (
        discover_new_constructor_kwargs,
        ensure_constructor_kwargs,
    )

    ensure_constructor_kwargs(
        os.path.abspath(__file__),
        "TwitchChannelPointsMiner",
        discover_new_constructor_kwargs(TwitchChannelPointsMiner),
    )
except Exception as e:
    print(f"Hinweis: Einstellungs-Migration fehlgeschlagen: {e}")

TWITCH_USER = os.environ.get("TWITCH_USER", "")
TWITCH_PASS = os.environ.get("TWITCH_PASS", "")

SERVER_PORT = int(os.environ.get("SERVER_PORT", 5000))
for i, arg in enumerate(sys.argv):
    if arg == "--port" and i + 1 < len(sys.argv):
        SERVER_PORT = int(sys.argv[i + 1])
    elif arg.startswith("--port="):
        SERVER_PORT = int(arg.split("=")[1])

try:
    twitch_miner = TwitchChannelPointsMiner(
        username=TWITCH_USER,
        password=TWITCH_PASS,
        claim_drops_startup=True,
        priority=[Priority.STREAK, Priority.DROPS, Priority.ORDER],
        enable_analytics=True,
        disable_ssl_cert_verification=False,
        disable_at_in_nickname=True,
        watch_only_drops=False,
        stop_watch_when_drops_completed=False,
        watch_streak_max_parallel=2,
        use_hermes=True,
        logger_settings=LoggerSettings(
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
        ),
        streamer_settings=StreamerSettings(
            make_predictions=False,
            follow_raid=True,
            claim_drops=True,
            claim_moments=True,
            watch_streak=True,
            chat=ChatPresence.ONLINE,
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
        ),
    )

    twitch_miner.analytics(host="0.0.0.0", port=SERVER_PORT, refresh=5, days_ago=360)

    twitch_miner.mine(
        [
            Streamer(
                "Zicke8",
                settings=StreamerSettings(
                    make_predictions=False,
                    follow_raid=True,
                    claim_drops=True,
                    watch_streak=True,
                    bet=BetSettings(
                        strategy=Strategy.SMART,
                        percentage=5,
                        stealth_mode=True,
                        percentage_gap=20,
                        max_points=234,
                        filter_condition=FilterCondition(
                            by=OutcomeKeys.TOTAL_USERS, where=Condition.LTE, value=800
                        ),
                    ),
                ),
            ),
            Streamer(
                "shlorox",
                settings=StreamerSettings(
                    make_predictions=False,
                    follow_raid=True,
                    claim_drops=True,
                    watch_streak=True,
                    bet=BetSettings(
                        strategy=Strategy.SMART,
                        percentage=5,
                        stealth_mode=True,
                        percentage_gap=20,
                        max_points=234,
                        filter_condition=FilterCondition(
                            by=OutcomeKeys.TOTAL_USERS, where=Condition.LTE, value=800
                        ),
                    ),
                ),
            ),
            Streamer(
                "Vanessa_Lopez_Official",
                settings=StreamerSettings(
                    make_predictions=False,
                    follow_raid=False,
                    watch_streak=True,
                    bet=BetSettings(
                        strategy=Strategy.SMART,
                        percentage=5,
                        stealth_mode=False,
                        percentage_gap=30,
                        max_points=50000,
                        filter_condition=FilterCondition(
                            by=OutcomeKeys.ODDS, where=Condition.LT, value=300
                        ),
                    ),
                ),
            ),
            Streamer(
                "PYKA",
                settings=StreamerSettings(
                    make_predictions=False,
                    follow_raid=False,
                    claim_drops=True,
                    watch_streak=True,
                    bet=BetSettings(
                        strategy=Strategy.SMART,
                        percentage=5,
                        stealth_mode=True,
                        percentage_gap=20,
                        max_points=234,
                        filter_condition=FilterCondition(
                            by=OutcomeKeys.TOTAL_USERS, where=Condition.LTE, value=800
                        ),
                    ),
                ),
            ),
            Streamer(
                "Z1ppo",
                settings=StreamerSettings(
                    make_predictions=False,
                    follow_raid=True,
                    claim_drops=False,
                    bet=BetSettings(
                        strategy=Strategy.PERCENTAGE,
                        percentage=5,
                        stealth_mode=False,
                        percentage_gap=20,
                        max_points=1234,
                        filter_condition=FilterCondition(
                            by=OutcomeKeys.TOTAL_POINTS, where=Condition.GTE, value=250
                        ),
                    ),
                ),
            ),
            Streamer(
                "Sintica",
                settings=StreamerSettings(
                    make_predictions=False,
                    follow_raid=True,
                    claim_drops=False,
                    bet=BetSettings(
                        strategy=Strategy.PERCENTAGE,
                        percentage=5,
                        stealth_mode=False,
                        percentage_gap=20,
                        max_points=1234,
                        filter_condition=FilterCondition(
                            by=OutcomeKeys.TOTAL_POINTS, where=Condition.GTE, value=250
                        ),
                    ),
                ),
            ),
            Streamer(
                "Colaway",
                settings=StreamerSettings(
                    make_predictions=False,
                    follow_raid=True,
                    claim_drops=False,
                    bet=BetSettings(
                        strategy=Strategy.PERCENTAGE,
                        percentage=5,
                        stealth_mode=False,
                        percentage_gap=20,
                        max_points=1234,
                        filter_condition=FilterCondition(
                            by=OutcomeKeys.TOTAL_POINTS, where=Condition.GTE, value=250
                        ),
                    ),
                ),
            ),
            Streamer(
                "ColawayTV",
                settings=StreamerSettings(
                    make_predictions=False,
                    follow_raid=True,
                    claim_drops=False,
                    bet=BetSettings(
                        strategy=Strategy.PERCENTAGE,
                        percentage=5,
                        stealth_mode=False,
                        percentage_gap=20,
                        max_points=1234,
                        filter_condition=FilterCondition(
                            by=OutcomeKeys.TOTAL_POINTS, where=Condition.GTE, value=250
                        ),
                    ),
                ),
            ),
            Streamer(
                "Shady_Devil_x",
                settings=StreamerSettings(
                    make_predictions=False,
                    follow_raid=True,
                    claim_drops=False,
                    bet=BetSettings(
                        strategy=Strategy.PERCENTAGE,
                        percentage=5,
                        stealth_mode=False,
                        percentage_gap=20,
                        max_points=1234,
                        filter_condition=FilterCondition(
                            by=OutcomeKeys.TOTAL_POINTS, where=Condition.GTE, value=250
                        ),
                    ),
                ),
            ),
            Streamer(
                "Halbsteiv",
                settings=StreamerSettings(
                    make_predictions=False,
                    follow_raid=True,
                    claim_drops=False,
                    bet=BetSettings(
                        strategy=Strategy.PERCENTAGE,
                        percentage=5,
                        stealth_mode=False,
                        percentage_gap=20,
                        max_points=1234,
                        filter_condition=FilterCondition(
                            by=OutcomeKeys.TOTAL_POINTS, where=Condition.GTE, value=250
                        ),
                    ),
                ),
            ),
            Streamer(
                "DirkNeuenfels",
                settings=StreamerSettings(
                    make_predictions=False,
                    follow_raid=True,
                    claim_drops=False,
                    bet=BetSettings(
                        strategy=Strategy.PERCENTAGE,
                        percentage=5,
                        stealth_mode=False,
                        percentage_gap=20,
                        max_points=1234,
                        filter_condition=FilterCondition(
                            by=OutcomeKeys.TOTAL_POINTS, where=Condition.GTE, value=250
                        ),
                    ),
                ),
            ),
            Streamer(
                "sickEmoAngel",
                settings=StreamerSettings(
                    make_predictions=False, follow_raid=True, watch_streak=True
                ),
            ),
            Streamer(
                "Sherpa",
                settings=StreamerSettings(
                    make_predictions=False,
                    follow_raid=True,
                    claim_drops=True,
                    watch_streak=True,
                    bet=BetSettings(
                        strategy=Strategy.HIGH_ODDS,
                        percentage=7,
                        stealth_mode=True,
                        percentage_gap=20,
                        max_points=90,
                        filter_condition=FilterCondition(
                            by=OutcomeKeys.PERCENTAGE_USERS,
                            where=Condition.GTE,
                            value=300,
                        ),
                    ),
                ),
            ),
            Streamer("eranio"),
        ],
        followers=True,
        followers_order=FollowersOrder.ASC,
    )
except KeyboardInterrupt:
    print("Miner durch Benutzer gestoppt (KeyboardInterrupt). Beende...")
    sys.exit(0)
except Exception as e:
    print("=========================================================================")
    print(f"KRITISCHER FEHLER aufgetreten: {e}")
    print("Miner wird in 15 Sekunden komplett neu gestartet...")
    print("=========================================================================")
    import time

    time.sleep(15)
    os.execv(sys.executable, [sys.executable] + sys.argv)
