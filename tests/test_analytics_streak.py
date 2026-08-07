import json
import os
import tempfile
import unittest

from flask import Flask

from TwitchChannelPointsMiner.classes.AnalyticsServer import (
    get_challenge_points,
    get_watch_streak_days,
    streamers,
)
from TwitchChannelPointsMiner.classes.Settings import Settings
from TwitchChannelPointsMiner.classes.entities.Streamer import Streamer
from TwitchChannelPointsMiner.TwitchChannelPointsMiner import TwitchChannelPointsMiner
from TwitchChannelPointsMiner.WatchStreakCache import WatchStreakCache


class PersistentStreakDaysTest(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_dir.cleanup)
        self._previous_analytics_path = getattr(Settings, "analytics_path", None)
        Settings.analytics_path = self._tmp_dir.name
        self.addCleanup(
            lambda: setattr(Settings, "analytics_path", self._previous_analytics_path)
        )
        self.app = Flask(__name__)

    def _file_path(self, streamer):
        return os.path.join(self._tmp_dir.name, f"{streamer.username}.json")

    def test_writes_streak_days_into_the_same_analytics_file_as_points(self):
        streamer = Streamer("teststreamer")
        streamer.channel_points = 12345
        streamer.persistent_series(event_type="Watch")
        streamer.persistent_streak_days(3)
        streamer.persistent_streak_days(4)

        with open(self._file_path(streamer), "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertIn("series", data, "points series must still be written")
        self.assertIn("streak", data, "streak series must be in the SAME file")
        self.assertEqual([entry["y"] for entry in data["streak"]], [3, 4])

    def test_persistent_streak_days_ignores_none(self):
        streamer = Streamer("teststreamer2")
        streamer.channel_points = 1
        streamer.persistent_series(event_type="Watch")
        streamer.persistent_streak_days(None)

        with open(self._file_path(streamer), "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertNotIn("streak", data)

    def test_analytics_server_reads_latest_streak_value(self):
        streamer = Streamer("teststreamer3")
        streamer.channel_points = 500
        streamer.persistent_series(event_type="Watch")
        streamer.persistent_streak_days(7)
        streamer.persistent_streak_days(8)

        with self.app.test_request_context("/streamers"):
            self.assertEqual(get_watch_streak_days(streamer.username), 8)
            self.assertEqual(get_challenge_points(streamer.username), 500)

    def test_analytics_server_returns_none_when_no_streak_recorded_yet(self):
        streamer = Streamer("teststreamer4")
        streamer.channel_points = 1
        streamer.persistent_series(event_type="Watch")

        with self.app.test_request_context("/streamers"):
            self.assertIsNone(get_watch_streak_days(streamer.username))

    def test_streamer_with_only_streak_data_does_not_crash_streamers_endpoint(self):
        # Regression test: a streamer whose analytics file only has "streak" (no
        # "series" yet, e.g. streak recorded before any points-earned event ever
        # fired) used to crash the whole /streamers response with KeyError('series')
        # for EVERY streamer, not just this one.
        streamer = Streamer("teststreamer5")
        streamer.persistent_streak_days(2)

        with open(self._file_path(streamer), "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertNotIn("series", data)
        self.assertIn("streak", data)

        with self.app.test_request_context("/streamers"):
            self.assertEqual(get_challenge_points(streamer.username), 0)
            self.assertEqual(get_watch_streak_days(streamer.username), 2)
            response = streamers()
            payload = json.loads(response.get_data(as_text=True))
        names = [entry["name"] for entry in payload]
        self.assertIn(f"{streamer.username}.json", names)


class BackfillStreakHistoryTest(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_dir.cleanup)
        self._previous_analytics_path = getattr(Settings, "analytics_path", None)
        Settings.analytics_path = self._tmp_dir.name
        self.addCleanup(
            lambda: setattr(Settings, "analytics_path", self._previous_analytics_path)
        )
        self._previous_enable_analytics = getattr(Settings, "enable_analytics", False)
        Settings.enable_analytics = True
        self.addCleanup(
            lambda: setattr(Settings, "enable_analytics", self._previous_enable_analytics)
        )

    def _file_path(self, streamer):
        return os.path.join(self._tmp_dir.name, f"{streamer.username}.json")

    def _build_miner(self, streamers, current_days):
        miner = object.__new__(TwitchChannelPointsMiner)
        miner.streamers = streamers
        miner.username = "testaccount"
        miner.watch_streak_cache = WatchStreakCache(default_account_name="testaccount")
        for streamer in streamers:
            miner.watch_streak_cache.set_streamer_status(
                streamer.username,
                watch_streak_detected=True,
                is_online=True,
                watch_streak_days=current_days,
                account_name="testaccount",
            )
        return miner

    def test_reconstructs_days_backwards_from_watch_streak_claims(self):
        streamer = Streamer("claimedstreamer")
        streamer.channel_points = 100
        streamer.persistent_series(event_type="Watch")
        # Three historical WATCH_STREAK claims, oldest first.
        streamer.persistent_annotations("WATCH_STREAK", "+250 - WATCH_STREAK")
        streamer.persistent_annotations("WATCH_STREAK", "+250 - WATCH_STREAK")
        streamer.persistent_annotations("WATCH_STREAK", "+250 - WATCH_STREAK")

        miner = self._build_miner([streamer], current_days=10)
        miner._backfill_streak_history_from_claims()

        with open(self._file_path(streamer), "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual([entry["y"] for entry in data["streak"]], [8, 9, 10])

    def test_does_not_touch_streamer_with_existing_streak_history(self):
        streamer = Streamer("alreadytracked")
        streamer.channel_points = 100
        streamer.persistent_series(event_type="Watch")
        streamer.persistent_annotations("WATCH_STREAK", "+250 - WATCH_STREAK")
        streamer.persistent_streak_days(5)  # real, go-forward tracked value

        miner = self._build_miner([streamer], current_days=99)
        miner._backfill_streak_history_from_claims()

        with open(self._file_path(streamer), "r", encoding="utf-8") as f:
            data = json.load(f)
        # Must be untouched - still just the one real value, not overwritten/appended to.
        self.assertEqual([entry["y"] for entry in data["streak"]], [5])

    def test_no_claims_means_no_backfill(self):
        streamer = Streamer("noclaims")
        streamer.channel_points = 100
        streamer.persistent_series(event_type="Watch")

        miner = self._build_miner([streamer], current_days=7)
        miner._backfill_streak_history_from_claims()

        with open(self._file_path(streamer), "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertNotIn("streak", data)


if __name__ == "__main__":
    unittest.main()
