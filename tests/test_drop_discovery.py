import os
import tempfile
import time
import unittest
from unittest.mock import patch

from TwitchChannelPointsMiner.classes.DropDiscovery import DropDiscovery
from TwitchChannelPointsMiner.classes.Settings import Priority
from TwitchChannelPointsMiner.classes.Twitch import Twitch
from TwitchChannelPointsMiner.classes.entities.Campaign import Campaign
from TwitchChannelPointsMiner.classes.entities.Streamer import Streamer, StreamerSettings
from TwitchChannelPointsMiner.run_config_migration import (
    discover_new_constructor_kwargs,
    ensure_constructor_kwargs,
)
from TwitchChannelPointsMiner.WatchStreakCache import WatchStreakCache


def make_streamer(username: str, online: bool = True) -> Streamer:
    settings = StreamerSettings(
        watch_streak=False,
        claim_drops=False,
        claim_moments=False,
        make_predictions=False,
        follow_raid=False,
        community_goals=False,
    )
    streamer = Streamer(username, settings=settings)
    streamer.is_online = online
    streamer.online_at = time.time()
    return streamer


def make_campaign_dict(campaign_id: str, channels=None, end_in_seconds: float = 3600):
    from datetime import datetime, timedelta

    fmt = "%Y-%m-%dT%H:%M:%SZ"
    started = (datetime.utcnow() - timedelta(hours=1)).strftime(fmt)
    ends = (datetime.utcnow() + timedelta(seconds=end_in_seconds)).strftime(fmt)
    return {
        "id": campaign_id,
        "game": {"id": "1", "displayName": "Test Game", "slug": "test-game"},
        "name": f"Campaign {campaign_id}",
        "status": "ACTIVE",
        "allow": {
            "channels": (
                None
                if channels is None
                else [{"id": cid, "login": login} for cid, login in channels]
            )
        },
        "startAt": started,
        "endAt": ends,
        "timeBasedDrops": [
            {
                "id": "drop1",
                "name": "Test Drop",
                "requiredMinutesWatched": 30,
                "benefitEdges": [],
                "startAt": started,
                "endAt": ends,
            }
        ],
    }


class SlotReservationTest(unittest.TestCase):
    def test_auto_drop_channel_always_reserves_one_slot(self):
        twitch = Twitch("test", "ua")
        twitch.watch_streak_cache = WatchStreakCache(default_account_name="test")
        twitch.max_watch_amount = 2

        regular_a = make_streamer("regular_a")
        regular_b = make_streamer("regular_b")
        auto_channel = make_streamer("auto_drop_channel")
        auto_channel.is_auto_drop_channel = True

        streamers = [regular_a, regular_b, auto_channel]
        streamers_index = list(range(len(streamers)))

        selection = twitch._select_streamers_to_watch(
            streamers, streamers_index, [Priority.ORDER]
        )

        selected_usernames = {streamers[i].username for i in selection}
        self.assertIn("auto_drop_channel", selected_usernames)
        self.assertEqual(len(selection), 2, "max_watch_amount=2 must not be exceeded")

    def test_auto_drop_channel_never_competes_for_its_own_slot(self):
        twitch = Twitch("test", "ua")
        twitch.watch_streak_cache = WatchStreakCache(default_account_name="test")
        twitch.max_watch_amount = 2

        auto_channel = make_streamer("auto_drop_channel")
        auto_channel.is_auto_drop_channel = True
        streamers = [auto_channel]
        streamers_index = [0]

        selection = twitch._select_streamers_to_watch(
            streamers, streamers_index, [Priority.ORDER]
        )
        self.assertEqual(selection, [0])

    def test_without_auto_drop_channel_behaves_as_before(self):
        twitch = Twitch("test", "ua")
        twitch.watch_streak_cache = WatchStreakCache(default_account_name="test")
        twitch.max_watch_amount = 2

        streamers = [make_streamer("a"), make_streamer("b"), make_streamer("c")]
        streamers_index = list(range(len(streamers)))

        selection = twitch._select_streamers_to_watch(
            streamers, streamers_index, [Priority.ORDER]
        )
        self.assertEqual(len(selection), 2)


class FakeMiner:
    def __init__(self):
        self.running = True
        self.streamers = []
        self.added = []
        self.removed = []

    def add_dynamic_streamer(self, streamer):
        self.streamers.append(streamer)
        self.added.append(streamer.username)

    def remove_dynamic_streamer(self, streamer):
        if streamer in self.streamers:
            self.streamers.remove(streamer)
        self.removed.append(streamer.username)


class DropDiscoveryRotationTest(unittest.TestCase):
    def test_rotates_to_next_campaign_once_current_completes(self):
        twitch = Twitch("test", "ua")
        miner = FakeMiner()
        discovery = DropDiscovery(twitch, miner, scan_interval=9999, monitor_interval=0)

        campaign_a = Campaign(make_campaign_dict("A", channels=[("id1", "login1")]))
        campaign_b = Campaign(make_campaign_dict("B", channels=[("id2", "login2")]))

        def fake_initialize(streamers, max_workers=10):
            for streamer in streamers:
                streamer.is_online = True
            return set()

        with patch.object(
            Twitch, "_find_live_channel_for_campaign", side_effect=["login1", "login2"]
        ), patch.object(
            Twitch, "initialize_streamers_context", side_effect=fake_initialize
        ), patch.object(
            Twitch, "check_streamer_online", return_value=None
        ):
            discovery._queue = [campaign_a, campaign_b]
            discovery._queued_ids = {"A", "B"}

            discovery._start_next()
            self.assertEqual(miner.added, ["login1"])
            self.assertEqual(discovery._active_campaign.id, "A")

            # Campaign A is now complete (no longer reported as active) -> should
            # release the slot and immediately move on to campaign B.
            with patch.object(Twitch, "get_active_campaigns", return_value=[campaign_b]):
                discovery._monitor_active()
            self.assertEqual(miner.removed, ["login1"])
            self.assertIsNone(discovery._active_streamer)

            discovery._start_next()
            self.assertEqual(miner.added, ["login1", "login2"])
            self.assertEqual(discovery._active_campaign.id, "B")

    def test_queue_empty_after_all_campaigns_done_leaves_slot_free(self):
        twitch = Twitch("test", "ua")
        miner = FakeMiner()
        discovery = DropDiscovery(twitch, miner, scan_interval=9999, monitor_interval=0)

        discovery._queue = []
        discovery._queued_ids = set()
        discovery._start_next()

        self.assertIsNone(discovery._active_streamer)
        self.assertEqual(miner.added, [])


class RunConfigMigrationTest(unittest.TestCase):
    def _write_temp_file(self, content: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".py")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def test_adds_missing_kwarg_without_touching_existing_ones(self):
        path = self._write_temp_file(
            "twitch_miner = TwitchChannelPointsMiner(\n"
            "    username=TWITCH_USER,\n"
            "    password=TWITCH_PASS,\n"
            ")\n"
        )
        changed = ensure_constructor_kwargs(
            path, "TwitchChannelPointsMiner", {"auto_discover_drops": "False"}
        )
        self.assertTrue(changed)
        with open(path, "r", encoding="utf-8") as f:
            patched = f.read()
        self.assertIn("auto_discover_drops=False,", patched)
        self.assertIn("username=TWITCH_USER,", patched)
        self.assertIn("password=TWITCH_PASS,", patched)
        compile(patched, path, "exec")

    def test_does_not_duplicate_existing_kwarg(self):
        path = self._write_temp_file(
            "twitch_miner = TwitchChannelPointsMiner(\n"
            "    username=TWITCH_USER,\n"
            "    auto_discover_drops=True,\n"
            ")\n"
        )
        changed = ensure_constructor_kwargs(
            path, "TwitchChannelPointsMiner", {"auto_discover_drops": "False"}
        )
        self.assertFalse(changed)
        with open(path, "r", encoding="utf-8") as f:
            patched = f.read()
        self.assertEqual(patched.count("auto_discover_drops"), 1)
        self.assertIn("auto_discover_drops=True,", patched)

    def test_leaves_invalid_python_untouched(self):
        broken_source = "def broken(:\n    pass\n"
        path = self._write_temp_file(broken_source)
        changed = ensure_constructor_kwargs(
            path, "TwitchChannelPointsMiner", {"auto_discover_drops": "False"}
        )
        self.assertFalse(changed)
        with open(path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), broken_source)

    def test_single_line_call_is_left_untouched(self):
        path = self._write_temp_file(
            'twitch_miner = TwitchChannelPointsMiner(username=TWITCH_USER)\n'
        )
        changed = ensure_constructor_kwargs(
            path, "TwitchChannelPointsMiner", {"auto_discover_drops": "False"}
        )
        self.assertFalse(changed)


class FindLiveChannelForCampaignTest(unittest.TestCase):
    def test_whitelist_campaign_picks_highest_viewer_count(self):
        twitch = Twitch("test", "ua")
        campaign = Campaign(
            make_campaign_dict(
                "W1", channels=[("id1", "small_channel"), ("id2", "big_channel")]
            )
        )

        def fake_post(json_data):
            # Batched WithIsStreamLiveQuery request: a list of query dicts.
            results = []
            for item in json_data:
                channel_id = item["variables"]["id"]
                if channel_id == "id1":
                    results.append(
                        {"data": {"user": {"stream": {"id": "s1", "viewersCount": 5}}}}
                    )
                else:
                    results.append(
                        {"data": {"user": {"stream": {"id": "s2", "viewersCount": 500}}}}
                    )
            return results

        with patch.object(Twitch, "post_gql_request", side_effect=fake_post):
            login = twitch._find_live_channel_for_campaign(campaign)
        self.assertEqual(login, "big_channel")

    def test_whitelist_campaign_skips_offline_channels(self):
        twitch = Twitch("test", "ua")
        campaign = Campaign(
            make_campaign_dict("W2", channels=[("id1", "offline_channel")])
        )

        def fake_post(json_data):
            return [{"data": {"user": {"stream": None}}}]

        with patch.object(Twitch, "post_gql_request", side_effect=fake_post):
            login = twitch._find_live_channel_for_campaign(campaign)
        self.assertIsNone(login)

    def test_open_campaign_uses_directory_search(self):
        twitch = Twitch("test", "ua")
        campaign = Campaign(make_campaign_dict("O1", channels=None))

        def fake_post(json_data):
            self.assertEqual(json_data["operationName"], "DirectoryPage_Game")
            self.assertEqual(json_data["variables"]["slug"], "test-game")
            return {
                "data": {
                    "game": {
                        "streams": {
                            "edges": [
                                {
                                    "node": {
                                        "viewersCount": 10,
                                        "broadcaster": {"login": "low"},
                                    }
                                },
                                {
                                    "node": {
                                        "viewersCount": 999,
                                        "broadcaster": {"login": "high"},
                                    }
                                },
                            ]
                        }
                    }
                }
            }

        with patch.object(Twitch, "post_gql_request", side_effect=fake_post):
            login = twitch._find_live_channel_for_campaign(campaign)
        self.assertEqual(login, "high")


class DiscoverNewConstructorKwargsTest(unittest.TestCase):
    def test_only_returns_optional_simple_literal_defaults(self):
        class Example:
            def __init__(
                self,
                username: str,
                password: str = None,
                auto_discover_drops: bool = False,
                watch_streak_min_offline_seconds: int = 1800,
                logger_settings: object = object(),
            ):
                pass

        discovered = discover_new_constructor_kwargs(Example)

        self.assertNotIn("username", discovered, "required params must be skipped")
        self.assertNotIn(
            "logger_settings", discovered, "non-literal defaults must be skipped"
        )
        self.assertEqual(discovered["password"], "None")
        self.assertEqual(discovered["auto_discover_drops"], "False")
        self.assertEqual(discovered["watch_streak_min_offline_seconds"], "1800")

    def test_discovers_auto_discover_drops_from_the_real_miner_class(self):
        from TwitchChannelPointsMiner.TwitchChannelPointsMiner import (
            TwitchChannelPointsMiner,
        )

        discovered = discover_new_constructor_kwargs(TwitchChannelPointsMiner)
        self.assertEqual(discovered.get("auto_discover_drops"), "False")

    def test_feeding_discovery_output_into_ensure_constructor_kwargs(self):
        fd, path = tempfile.mkstemp(suffix=".py")
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(
                "twitch_miner = TwitchChannelPointsMiner(\n"
                "    username=TWITCH_USER,\n"
                ")\n"
            )

        class Example:
            def __init__(self, username: str, brand_new_toggle: bool = True):
                pass

        changed = ensure_constructor_kwargs(
            path, "TwitchChannelPointsMiner", discover_new_constructor_kwargs(Example)
        )
        self.assertTrue(changed)
        with open(path, "r", encoding="utf-8") as f:
            patched = f.read()
        self.assertIn("brand_new_toggle=True,", patched)
        compile(patched, path, "exec")


class StreakLengthPriorityTest(unittest.TestCase):
    def _twitch_with_streak_days(self, days_by_username: dict[str, int]) -> Twitch:
        twitch = Twitch("test", "ua")
        cache = WatchStreakCache(default_account_name="test")
        for username, days in days_by_username.items():
            cache.set_streamer_status(
                username,
                watch_streak_detected=True,
                is_online=True,
                watch_streak_days=days,
                account_name="test",
            )
        twitch.watch_streak_cache = cache
        twitch.max_watch_amount = 3
        return twitch

    def test_descending_prioritizes_higher_streak_first(self):
        twitch = self._twitch_with_streak_days({"low": 2, "high": 50, "mid": 10})
        streamers = [make_streamer("low"), make_streamer("high"), make_streamer("mid")]
        selection = twitch._select_streamers_to_watch(
            streamers, list(range(3)), [Priority.STREAK_LENGTH_DESCENDING]
        )
        self.assertEqual(
            [streamers[i].username for i in selection], ["high", "mid", "low"]
        )

    def test_ascending_prioritizes_lower_streak_first(self):
        twitch = self._twitch_with_streak_days({"low": 2, "high": 50, "mid": 10})
        streamers = [make_streamer("low"), make_streamer("high"), make_streamer("mid")]
        selection = twitch._select_streamers_to_watch(
            streamers, list(range(3)), [Priority.STREAK_LENGTH_ASCENDING]
        )
        self.assertEqual(
            [streamers[i].username for i in selection], ["low", "mid", "high"]
        )

    def test_unknown_streak_sorts_last_in_either_direction(self):
        twitch = self._twitch_with_streak_days({"known": 5})
        streamers = [make_streamer("unknown"), make_streamer("known")]
        selection = twitch._select_streamers_to_watch(
            streamers, list(range(2)), [Priority.STREAK_LENGTH_DESCENDING]
        )
        self.assertEqual(
            [streamers[i].username for i in selection], ["known", "unknown"]
        )


if __name__ == "__main__":
    unittest.main()
