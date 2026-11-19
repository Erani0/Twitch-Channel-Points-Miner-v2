import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from TwitchChannelPointsMiner.classes.DropCampaignFile import DropCampaignFile
from TwitchChannelPointsMiner.classes.DropDiscovery import DropDiscovery
from TwitchChannelPointsMiner.classes.Settings import Priority
from TwitchChannelPointsMiner.classes.Twitch import Twitch
from TwitchChannelPointsMiner.classes.entities.Campaign import Campaign
from TwitchChannelPointsMiner.WatchStreakCache import WatchStreakCache
from tests.test_drop_discovery import FakeMiner, make_campaign_dict, make_streamer


def campaign(cid, game="Test Game", minutes=60, watched=0, end_in=3600, connected=True, channels=None, subscription=False):
    data = make_campaign_dict(cid, channels=channels, end_in_seconds=end_in)
    data["game"] = {"id": game, "displayName": game, "slug": game.lower().replace(" ", "-")}
    data["timeBasedDrops"][0]["requiredMinutesWatched"] = minutes
    if subscription:
        data["timeBasedDrops"][0]["isSubscriptionOnly"] = True
    data["self"] = {"isAccountConnected": connected}
    c = Campaign(data)
    c.drops[0].current_minutes_watched = watched
    return c


class RankingTest(unittest.TestCase):
    empty = {"games": {}, "campaigns": {}}

    def test_started_campaign_beats_untouched_one(self):
        fresh = campaign("fresh", minutes=10)
        started = campaign("started", minutes=60, watched=20)
        ranked = DropCampaignFile.rank([fresh, started], self.empty)
        self.assertEqual([c.id for c in ranked], ["started", "fresh"])

    def test_closest_drop_first_then_earliest_end(self):
        long = campaign("long", minutes=120)
        short = campaign("short", minutes=15)
        soon = campaign("soon", minutes=15, end_in=600)
        ranked = DropCampaignFile.rank([long, short, soon], self.empty)
        self.assertEqual([c.id for c in ranked], ["soon", "short", "long"])

    def test_game_order_and_campaign_order_win_over_automatic(self):
        gta = campaign("gta", game="Grand Theft Auto VI", minutes=60)
        pogo = campaign("pogo", game="Pokémon GO", minutes=20, watched=10)
        other = campaign("other", minutes=5, watched=4)
        settings = {
            "games": {"Grand Theft Auto VI": {"order": 1, "active": True}, "Pokémon GO": {"order": 2, "active": True}},
            "campaigns": {},
        }
        ranked = DropCampaignFile.rank([other, pogo, gta], settings)
        self.assertEqual([c.id for c in ranked], ["gta", "pogo", "other"])

        settings["campaigns"]["pogo"] = {"order": 0, "active": False}
        ranked = DropCampaignFile.rank([other, pogo, gta], settings)
        self.assertEqual([c.id for c in ranked], ["gta", "other"])

    def test_switched_off_game_and_subscription_only_are_skipped(self):
        off = campaign("off", game="Langweilig")
        sub = campaign("sub", subscription=True)
        ok = campaign("ok")
        settings = {"games": {"Langweilig": {"order": 0, "active": False}}, "campaigns": {}}
        self.assertEqual([c.id for c in DropCampaignFile.rank([off, sub, ok], settings)], ["ok"])

    def test_unlinked_account_goes_last(self):
        unlinked = campaign("unlinked", minutes=5, connected=False)
        linked = campaign("linked", minutes=50)
        self.assertEqual([c.id for c in DropCampaignFile.rank([unlinked, linked], self.empty)], ["linked", "unlinked"])


class FileTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "drop_campaigns.json")
        self.file = DropCampaignFile(self.path)

    def read(self):
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def test_file_lists_campaigns_and_keeps_user_edits(self):
        gta = campaign("gta", game="Grand Theft Auto VI", minutes=60, watched=25)
        settings = self.file.read_settings()
        self.file.write([gta], settings)
        data = self.read()
        self.assertEqual(data["spiele"][0]["spiel"], "Grand Theft Auto VI")
        self.assertEqual(data["kampagnen"][0]["naechster_drop"], "25 von 60 Minuten (Test Drop)")
        self.assertEqual(data["kampagnen"][0]["konto_verbunden"], "ja")

        data["spiele"][0]["reihenfolge"] = 1
        data["kampagnen"][0]["aktiv"] = False
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        settings = self.file.read_settings()
        self.file.write([gta, campaign("neu", game="Pokémon GO")], settings)
        data = self.read()
        self.assertEqual(data["spiele"][0]["reihenfolge"], 1)
        self.assertFalse(data["kampagnen"][0]["aktiv"])
        self.assertEqual(data["kampagnen"][1]["spiel"], "Pokémon GO")
        self.assertIn("Pokémon GO", open(self.path, encoding="utf-8").read())

    def test_ended_campaigns_disappear_but_game_settings_stay(self):
        settings = {"games": {"Grand Theft Auto VI": {"order": 1, "active": True}}, "campaigns": {}}
        self.file.write([], settings)
        data = self.read()
        self.assertEqual(data["kampagnen"], [])
        self.assertEqual(data["spiele"][0]["reihenfolge"], 1)

    def test_broken_file_is_never_overwritten_and_last_settings_stay(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"spiele": [{"spiel": "Grand Theft Auto VI", "reihenfolge": 1}]}, f)
        good = self.file.read_settings()
        self.assertEqual(good["games"]["Grand Theft Auto VI"]["order"], 1)

        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"spiele": [ kaputt')
        settings = self.file.read_settings()
        self.assertTrue(self.file.broken)
        self.assertEqual(settings["games"]["Grand Theft Auto VI"]["order"], 1)
        self.assertFalse(self.file.write([campaign("x")], settings))
        self.assertEqual(open(self.path, encoding="utf-8").read(), '{"spiele": [ kaputt')

    def test_friendly_values_are_understood(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"spiele": [{"spiel": "A", "reihenfolge": "2", "aktiv": "nein"}], "kampagnen": [{"id": "c", "reihenfolge": "x"}]}, f)
        settings = self.file.read_settings()
        self.assertEqual(settings["games"]["A"], {"order": 2, "active": False})
        self.assertEqual(settings["campaigns"]["c"], {"order": 0, "active": True})


def fake_initialize(streamers, max_workers=10):
    for s in streamers:
        s.is_online = True
    return set()


class DiscoveryBehaviourTest(unittest.TestCase):
    def setUp(self):
        self.twitch = Twitch("test", "ua")
        self.miner = FakeMiner()
        self.dir = tempfile.mkdtemp()
        self.file = DropCampaignFile(os.path.join(self.dir, "drop_campaigns.json"))
        self.discovery = DropDiscovery(self.twitch, self.miner, scan_interval=9999, monitor_interval=0, campaign_file=self.file, stall_seconds=1200)

    def test_stalled_channel_is_replaced_by_another_one_for_the_same_campaign(self):
        gta = campaign("gta", game="Grand Theft Auto VI", watched=10)
        with patch.object(Twitch, "get_active_campaigns", return_value=[gta]), patch.object(
            Twitch, "initialize_streamers_context", side_effect=fake_initialize
        ), patch.object(Twitch, "_find_live_channel_for_campaign", side_effect=lambda c, exclude=None: "kanal_b" if "kanal_a" in (exclude or ()) else "kanal_a") as finder:
            self.discovery._refresh_queue()
            self.discovery._start_next()
            self.assertEqual(self.discovery._active_streamer.username, "kanal_a")

            self.discovery._progress_at = time.time() - 1300
            self.discovery._refresh_queue()
            self.assertIsNone(self.discovery._active_streamer)
            self.discovery._start_next()
            self.assertEqual(self.discovery._active_streamer.username, "kanal_b")
            self.assertIn("kanal_a", finder.call_args.kwargs["exclude"])

    def test_progress_keeps_the_channel(self):
        gta = campaign("gta", watched=10)
        with patch.object(Twitch, "get_active_campaigns", return_value=[gta]), patch.object(
            Twitch, "initialize_streamers_context", side_effect=fake_initialize
        ), patch.object(Twitch, "_find_live_channel_for_campaign", return_value="kanal_a"):
            self.discovery._refresh_queue()
            self.discovery._start_next()
            self.discovery._progress_at = time.time() - 1300
            more = campaign("gta", watched=15)
            with patch.object(Twitch, "get_active_campaigns", return_value=[more]):
                self.discovery._refresh_queue()
            self.assertEqual(self.discovery._active_streamer.username, "kanal_a")

    def test_explicit_order_switches_the_running_campaign(self):
        other = campaign("other", game="Anderes", watched=5)
        gta = campaign("gta", game="Grand Theft Auto VI")
        with patch.object(Twitch, "get_active_campaigns", return_value=[other, gta]), patch.object(
            Twitch, "initialize_streamers_context", side_effect=fake_initialize
        ), patch.object(Twitch, "_find_live_channel_for_campaign", side_effect=lambda c, exclude=None: f"kanal_{c.id}"):
            self.discovery._refresh_queue()
            self.discovery._start_next()
            self.assertEqual(self.discovery._active_campaign.id, "other")

            with open(self.file.path, encoding="utf-8") as f:
                data = json.load(f)
            for entry in data["spiele"]:
                if entry["spiel"] == "Grand Theft Auto VI":
                    entry["reihenfolge"] = 1
            with open(self.file.path, "w", encoding="utf-8") as f:
                json.dump(data, f)

            self.discovery._refresh_queue()
            self.assertIsNone(self.discovery._active_campaign)
            self.discovery._start_next()
            self.assertEqual(self.discovery._active_campaign.id, "gta")

    def test_streamer_from_own_list_is_borrowed_not_duplicated(self):
        own = make_streamer("eranio_freund")
        self.miner.streamers.append(own)
        gta = campaign("gta")
        with patch.object(Twitch, "get_active_campaigns", return_value=[gta]), patch.object(
            Twitch, "_find_live_channel_for_campaign", return_value="Eranio_Freund"
        ):
            self.discovery._refresh_queue()
            self.discovery._start_next()
            self.assertIs(self.discovery._active_streamer, own)
            self.assertTrue(own.is_auto_drop_channel)
            self.assertEqual(self.miner.added, [])

            with patch.object(Twitch, "get_active_campaigns", return_value=[]):
                self.discovery._refresh_queue()
            self.assertFalse(own.is_auto_drop_channel)
            self.assertIn(own, self.miner.streamers)

    def test_drop_slot_survives_pending_watch_streaks(self):
        self.twitch.watch_streak_cache = WatchStreakCache(default_account_name="test")
        self.twitch.max_watch_amount = 2
        streaks = [make_streamer(f"streak_{i}") for i in range(4)]
        for s in streaks:
            s.settings.watch_streak = True
        drop = make_streamer("drop_channel")
        drop.is_auto_drop_channel = True
        streamers = streaks + [drop]
        selection = self.twitch._select_streamers_to_watch(streamers, list(range(len(streamers))), [Priority.STREAK, Priority.DROPS, Priority.ORDER])
        names = [streamers[i].username for i in selection]
        self.assertIn("drop_channel", names)
        self.assertLessEqual(len(names), 2)


if __name__ == "__main__":
    unittest.main()
