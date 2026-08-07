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


class ResetCorruptedStreakBackfillTest(unittest.TestCase):
    def setUp(self):
        self._tmp_analytics_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_analytics_dir.cleanup)
        self._previous_analytics_path = getattr(Settings, "analytics_path", None)
        Settings.analytics_path = self._tmp_analytics_dir.name
        self.addCleanup(
            lambda: setattr(Settings, "analytics_path", self._previous_analytics_path)
        )
        self._previous_enable_analytics = getattr(Settings, "enable_analytics", False)
        Settings.enable_analytics = True
        self.addCleanup(
            lambda: setattr(Settings, "enable_analytics", self._previous_enable_analytics)
        )

        self._tmp_cwd_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_cwd_dir.cleanup)
        self._previous_cwd = os.getcwd()
        os.chdir(self._tmp_cwd_dir.name)
        self.addCleanup(lambda: os.chdir(self._previous_cwd))

    def _file_path(self, streamer):
        return os.path.join(self._tmp_analytics_dir.name, f"{streamer.username}.json")

    def _build_miner(self, streamers):
        miner = object.__new__(TwitchChannelPointsMiner)
        miner.streamers = streamers
        miner.username = "testaccount"
        return miner

    def test_removes_streak_key_and_leaves_everything_else_intact(self):
        streamer = Streamer("corrupted")
        streamer.channel_points = 100
        streamer.persistent_series(event_type="Watch")
        streamer.persistent_streak_days(250)  # the bad, inflated backfilled value

        miner = self._build_miner([streamer])
        miner._reset_corrupted_streak_backfill()

        with open(self._file_path(streamer), "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertNotIn("streak", data)
        self.assertIn("series", data, "unrelated data must survive the cleanup")

    def test_only_runs_once_per_install(self):
        streamer = Streamer("runsonce")
        streamer.persistent_streak_days(1)

        miner = self._build_miner([streamer])
        miner._reset_corrupted_streak_backfill()

        # Simulate real, go-forward tracking writing a fresh value after the cleanup.
        streamer.persistent_streak_days(2)

        # A second cleanup pass (e.g. next restart) must be a no-op now.
        miner._reset_corrupted_streak_backfill()

        with open(self._file_path(streamer), "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual([entry["y"] for entry in data["streak"]], [2])

    def test_streamer_without_a_file_yet_does_not_crash(self):
        streamer = Streamer("neverwritten")
        miner = self._build_miner([streamer])
        miner._reset_corrupted_streak_backfill()  # must not raise


if __name__ == "__main__":
    unittest.main()
