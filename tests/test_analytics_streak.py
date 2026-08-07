import json
import os
import tempfile
import unittest

from flask import Flask

from TwitchChannelPointsMiner.classes.AnalyticsServer import (
    get_challenge_points,
    get_watch_streak_days,
)
from TwitchChannelPointsMiner.classes.Settings import Settings
from TwitchChannelPointsMiner.classes.entities.Streamer import Streamer


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


if __name__ == "__main__":
    unittest.main()
