import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from TwitchChannelPointsMiner import TwitchChannelPointsMiner as MinerClass
from TwitchChannelPointsMiner.classes.DropCampaignFile import DropCampaignFile, empty_settings
from TwitchChannelPointsMiner.classes.DropDiscovery import DropDiscovery
from TwitchChannelPointsMiner.classes.Settings import Priority
from TwitchChannelPointsMiner.classes.Twitch import Twitch
from TwitchChannelPointsMiner.classes.entities.Campaign import Campaign
from TwitchChannelPointsMiner.run_config_migration import discover_new_constructor_kwargs, ensure_constructor_kwargs
from TwitchChannelPointsMiner.utils import dedupe_git_safe_directories
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


def ids(campaigns):
    return [c.id for c in campaigns]


class OrderTest(unittest.TestCase):
    def test_without_file_started_and_closest_drops_come_first(self):
        fresh = campaign("fresh", minutes=10)
        started = campaign("started", minutes=60, watched=20)
        long = campaign("long", minutes=120)
        unlinked = campaign("unlinked", minutes=5, connected=False)
        self.assertEqual(ids(DropCampaignFile.rank([long, fresh, unlinked, started], empty_settings())), ["started", "fresh", "long", "unlinked"])

    def test_file_position_is_the_working_order(self):
        a, b, c = campaign("a", minutes=5, watched=4), campaign("b"), campaign("c")
        settings = {"games": {}, "campaigns": {}, "order": ["c", "b", "a"]}
        self.assertEqual(ids(DropCampaignFile.rank([a, b, c], settings)), ["c", "b", "a"])

    def test_new_campaign_lands_below_its_game_or_at_the_end(self):
        gta1 = campaign("gta1", game="Grand Theft Auto VI")
        pogo1 = campaign("pogo1", game="Pokémon GO")
        pogo2 = campaign("pogo2", game="Pokémon GO")
        other = campaign("other", game="Anderes")
        settings = {"games": {}, "campaigns": {}, "order": ["pogo1", "gta1"]}
        self.assertEqual(ids(DropCampaignFile.ordered([gta1, pogo1, pogo2, other], settings)), ["pogo1", "pogo2", "gta1", "other"])

    def test_switched_off_entries_and_subscription_only_are_skipped(self):
        off, sub, ok, game_off = campaign("off"), campaign("sub", subscription=True), campaign("ok"), campaign("g", game="Langweilig")
        settings = {"games": {"Langweilig": {"active": False}}, "campaigns": {"off": {"active": False}}, "order": ["off", "sub", "ok", "g"]}
        self.assertEqual(ids(DropCampaignFile.rank([off, sub, ok, game_off], settings)), ["ok"])


class FileTest(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "drop_campaigns.json")
        self.file = DropCampaignFile(self.path)

    def read(self):
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def save(self, data):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.utime(self.path, (time.time() + 5, time.time() + 5))

    def test_user_order_survives_removes_only_finished_and_adds_new(self):
        a, b, c = campaign("a", game="Grand Theft Auto VI", watched=25), campaign("b", game="Pokémon GO"), campaign("c", game="Anderes")
        self.file.write([a, b, c], self.file.read_settings())
        data = self.read()
        self.assertEqual(data["kampagnen"][0]["naechster_drop"], "25 von 60 Minuten (Test Drop)")
        self.assertEqual(data["kampagnen"][0]["konto_verbunden"], "ja")

        data["kampagnen"] = [data["kampagnen"][2], data["kampagnen"][1], data["kampagnen"][0]]
        data["kampagnen"][1]["aktiv"] = False
        self.save(data)
        self.assertTrue(self.file.changed())
        settings = self.file.read_settings()
        self.assertFalse(self.file.changed())

        new_pogo = campaign("b2", game="Pokémon GO")
        self.file.write([a, b, new_pogo], settings)
        data = self.read()
        self.assertEqual([k["id"] for k in data["kampagnen"]], ["b", "b2", "a"])
        self.assertFalse(data["kampagnen"][0]["aktiv"])
        self.assertIn("Pokémon GO", open(self.path, encoding="utf-8").read())
        self.assertFalse(self.file.changed())

    def broken_copy(self):
        return self.path.replace(".json", ".fehlerhaft.json")

    def test_small_slip_is_fixed_and_rewritten_clean(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"kampagnen": [{"id": "b", "aktiv": false,}, {"id": "a"},]')
        settings = self.file.read_settings()
        self.assertTrue(self.file.broken)
        self.assertEqual(settings["order"], ["b", "a"])
        self.assertFalse(settings["campaigns"]["b"]["active"])
        self.assertTrue(os.path.exists(self.broken_copy()))
        self.assertTrue(self.file.write([campaign("a"), campaign("b")], settings))
        data = self.read()
        self.assertEqual([k["id"] for k in data["kampagnen"]], ["b", "a"])
        self.assertFalse(self.file.broken)

    def test_badly_broken_file_keeps_order_and_active_values(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"spiele": [{"spiel": "Pokémon GO", "aktiv": false}], "kampagnen": [ {"spiel": "x" "aktiv": false, "id": "c"} {"aktiv": true "id": "a"} kaputt ::: ')
        settings = self.file.read_settings()
        self.assertEqual(settings["order"], ["c", "a"])
        self.assertFalse(settings["campaigns"]["c"]["active"])
        self.assertTrue(settings["campaigns"]["a"]["active"])
        self.assertFalse(settings["games"]["Pokémon GO"]["active"])
        self.file.write([campaign("a"), campaign("c")], settings)
        self.assertEqual([k["id"] for k in self.read()["kampagnen"]], ["c", "a"])

    def test_unreadable_file_falls_back_to_the_last_valid_state(self):
        self.save({"kampagnen": [{"id": "x"}, {"id": "y"}]})
        self.assertEqual(self.file.read_settings()["order"], ["x", "y"])
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("völlig kaputt")
        settings = self.file.read_settings()
        self.assertEqual(settings["order"], ["x", "y"])
        self.assertEqual(open(self.broken_copy(), encoding="utf-8").read(), "völlig kaputt")
        self.assertTrue(self.file.write([campaign("x"), campaign("y")], settings))
        self.assertEqual([k["id"] for k in self.read()["kampagnen"]], ["x", "y"])

    def test_editor_bom_is_accepted(self):
        with open(self.path, "w", encoding="utf-8-sig") as f:
            json.dump({"kampagnen": [{"id": "z"}]}, f)
        self.assertEqual(self.file.read_settings()["order"], ["z"])
        self.assertFalse(self.file.broken)

    def test_friendly_values_and_duplicates(self):
        self.save({"spiele": [{"spiel": "A", "aktiv": "nein"}], "kampagnen": [{"id": "c", "aktiv": "ja"}, {"id": "c", "aktiv": False}]})
        settings = self.file.read_settings()
        self.assertEqual(settings["games"]["A"], {"active": False})
        self.assertEqual(settings["campaigns"]["c"], {"active": True})
        self.assertEqual(settings["order"], ["c"])


def fake_initialize(streamers, max_workers=10):
    for s in streamers:
        s.is_online = True
    return set()


class DiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.twitch = Twitch("test", "ua")
        self.miner = FakeMiner()
        self.file = DropCampaignFile(os.path.join(tempfile.mkdtemp(), "drop_campaigns.json"))
        self.discovery = DropDiscovery(self.twitch, self.miner, scan_interval=9999, monitor_interval=0, campaign_file=self.file, stall_seconds=1500)

    def move_to_top(self, cid):
        with open(self.file.path, encoding="utf-8") as f:
            data = json.load(f)
        entry = next(k for k in data["kampagnen"] if k["id"] == cid)
        data["kampagnen"].remove(entry)
        data["kampagnen"].insert(0, entry)
        with open(self.file.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.utime(self.file.path, (time.time() + 5, time.time() + 5))

    def test_editing_the_list_switches_within_a_minute_without_twitch_scan(self):
        other = campaign("other", game="Anderes", watched=5)
        gta = campaign("gta", game="Grand Theft Auto VI")
        with patch.object(Twitch, "get_active_campaigns", return_value=[other, gta]) as scan, patch.object(
            Twitch, "initialize_streamers_context", side_effect=fake_initialize
        ), patch.object(Twitch, "_find_live_channel_for_campaign", side_effect=lambda c, exclude=None: f"kanal_{c.id}"):
            self.discovery._refresh_queue()
            self.discovery._start_next()
            self.assertEqual(self.discovery._active_campaign.id, "other")

            self.move_to_top("gta")
            self.assertTrue(self.file.changed())
            self.discovery._settings = self.file.read_settings()
            self.discovery._apply_order()
            self.assertEqual(self.discovery._active_campaign.id, "gta")
            self.assertEqual(scan.call_count, 1)

    def test_higher_entry_without_live_channel_keeps_the_current_one(self):
        other = campaign("other", game="Anderes", watched=5)
        gta = campaign("gta", game="Grand Theft Auto VI")
        with patch.object(Twitch, "get_active_campaigns", return_value=[other, gta]), patch.object(
            Twitch, "initialize_streamers_context", side_effect=fake_initialize
        ), patch.object(Twitch, "_find_live_channel_for_campaign", side_effect=lambda c, exclude=None: None if c.id == "gta" else "kanal_other"):
            self.discovery._refresh_queue()
            self.discovery._start_next()
            self.move_to_top("gta")
            self.discovery._settings = self.file.read_settings()
            self.discovery._apply_order()
            self.assertEqual(self.discovery._active_campaign.id, "other")
            self.assertEqual(self.miner.removed, [])

    def test_finished_campaign_moves_on_and_leaves_the_list(self):
        a, b = campaign("a"), campaign("b")
        with patch.object(Twitch, "initialize_streamers_context", side_effect=fake_initialize), patch.object(
            Twitch, "_find_live_channel_for_campaign", side_effect=lambda c, exclude=None: f"kanal_{c.id}"
        ):
            with patch.object(Twitch, "get_active_campaigns", return_value=[a, b]):
                self.discovery._refresh_queue()
                self.discovery._start_next()
            self.assertEqual(self.discovery._active_campaign.id, "a")
            with patch.object(Twitch, "get_active_campaigns", return_value=[b]):
                self.discovery._refresh_queue()
            self.discovery._start_next()
            self.assertEqual(self.discovery._active_campaign.id, "b")
            with open(self.file.path, encoding="utf-8") as f:
                self.assertEqual([k["id"] for k in json.load(f)["kampagnen"]], ["b"])

    def test_stalled_channel_is_replaced_by_another_one(self):
        gta = campaign("gta", watched=10)
        with patch.object(Twitch, "get_active_campaigns", return_value=[gta]), patch.object(
            Twitch, "initialize_streamers_context", side_effect=fake_initialize
        ), patch.object(Twitch, "_find_live_channel_for_campaign", side_effect=lambda c, exclude=None: "kanal_b" if "kanal_a" in (exclude or ()) else "kanal_a"):
            self.discovery._refresh_queue()
            self.discovery._start_next()
            self.discovery._progress_at = time.time() - 1600
            self.discovery._refresh_queue()
            self.assertEqual(self.discovery._active_streamer.username if self.discovery._active_streamer else None, None)
            self.discovery._start_next()
            self.assertEqual(self.discovery._active_streamer.username, "kanal_b")

    def test_progress_keeps_the_channel(self):
        with patch.object(Twitch, "initialize_streamers_context", side_effect=fake_initialize), patch.object(
            Twitch, "_find_live_channel_for_campaign", return_value="kanal_a"
        ):
            with patch.object(Twitch, "get_active_campaigns", return_value=[campaign("gta", watched=10)]):
                self.discovery._refresh_queue()
                self.discovery._start_next()
            self.discovery._progress_at = time.time() - 1600
            with patch.object(Twitch, "get_active_campaigns", return_value=[campaign("gta", watched=15)]):
                self.discovery._refresh_queue()
            self.assertEqual(self.discovery._active_streamer.username, "kanal_a")

    def test_streamer_from_own_list_is_borrowed_not_duplicated(self):
        own = make_streamer("eranio_freund")
        self.miner.streamers.append(own)
        with patch.object(Twitch, "_find_live_channel_for_campaign", return_value="Eranio_Freund"):
            with patch.object(Twitch, "get_active_campaigns", return_value=[campaign("gta")]):
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


class UpdateSafetyTest(unittest.TestCase):
    def test_old_run_py_keeps_its_values_and_gets_missing_settings_off(self):
        fd, path = tempfile.mkstemp(suffix=".py")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("twitch_miner = TwitchChannelPointsMiner(\n    username=TWITCH_USER,\n    claim_drops_startup=True,\n)\n")
        ensure_constructor_kwargs(path, "TwitchChannelPointsMiner", discover_new_constructor_kwargs(MinerClass))
        source = open(path, encoding="utf-8").read()
        os.remove(path)
        self.assertIn("auto_discover_drops=False,", source)
        self.assertIn("claim_drops_startup=True,", source)
        compile(source, "run.py", "exec")

    def test_gitconfig_repeats_are_removed_once(self):
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("[user]\n\tname = x\n[safe]\n" + "\tdirectory = /home/container\n" * 80 + "\tdirectory = /other\n")
        self.assertTrue(dedupe_git_safe_directories(path))
        content = open(path, encoding="utf-8").read()
        self.assertEqual(content.count("directory = /home/container"), 1)
        self.assertIn("directory = /other", content)
        self.assertIn("name = x", content)
        self.assertFalse(dedupe_git_safe_directories(path))
        os.remove(path)


if __name__ == "__main__":
    unittest.main()
