import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from TwitchChannelPointsMiner import TwitchChannelPointsMiner as MinerClass
from TwitchChannelPointsMiner.classes.DropCampaignCollector import CollectResult, DropCampaignCollector
from TwitchChannelPointsMiner.classes.DropCampaignFile import DropCampaignFile, empty_settings
from TwitchChannelPointsMiner.classes.DropDiscovery import DropDiscovery
from TwitchChannelPointsMiner.classes.Settings import Priority
from TwitchChannelPointsMiner.classes.Twitch import Twitch
from TwitchChannelPointsMiner.classes.entities.Campaign import Campaign
from TwitchChannelPointsMiner.run_config_migration import discover_new_constructor_kwargs, ensure_constructor_kwargs
from TwitchChannelPointsMiner.utils import dedupe_git_safe_directories
from TwitchChannelPointsMiner.WatchStreakCache import WatchStreakCache
from tests.test_drop_discovery import FakeMiner, make_campaign_dict, make_streamer

FMT = "%Y-%m-%dT%H:%M:%SZ"


def campaign(cid, game="Test Game", minutes=60, watched=0, end_in=3600, connected=True, channels=None, subscription=False):
    data = make_campaign_dict(cid, channels=channels, end_in_seconds=end_in)
    data["game"] = {"id": game, "displayName": game, "slug": game.lower().replace(" ", "-").replace("é", "e")}
    data["timeBasedDrops"][0]["requiredMinutesWatched"] = minutes
    if subscription:
        data["timeBasedDrops"][0]["isSubscriptionOnly"] = True
    data["self"] = {"isAccountConnected": connected}
    c = Campaign(data)
    c.drops[0].current_minutes_watched = watched
    return c


def ids(campaigns):
    return [c.id for c in campaigns]


class FakeCollector:
    def __init__(self):
        self.campaigns = []
        self.finished = []
        self.channels = {}
        self.slugs = None

    def collect(self, streamers, known_slugs):
        self.slugs = list(known_slugs)
        return CollectResult(list(self.campaigns), list(self.finished), dict(self.channels))


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

    def broken_copy(self):
        return self.path.replace(".json", ".fehlerhaft.json")

    def test_user_order_survives_and_new_ones_are_added(self):
        a, b, c = campaign("a", game="Grand Theft Auto VI", watched=25), campaign("b", game="Pokémon GO"), campaign("c", game="Anderes")
        self.file.write([a, b, c], self.file.read_settings())
        data = self.read()
        self.assertEqual(data["kampagnen"][0]["naechster_drop"], "25 von 60 Minuten (Test Drop)")
        self.assertEqual(data["kampagnen"][0]["status"], "läuft")
        self.assertEqual(data["kampagnen"][0]["slug"], "grand-theft-auto-vi")

        data["kampagnen"] = [data["kampagnen"][2], data["kampagnen"][1], data["kampagnen"][0]]
        data["kampagnen"][1]["aktiv"] = False
        self.save(data)
        self.assertTrue(self.file.changed())
        settings = self.file.read_settings()
        self.assertFalse(self.file.changed())

        self.file.write([a, b, c, campaign("b2", game="Pokémon GO")], settings)
        data = self.read()
        self.assertEqual([k["id"] for k in data["kampagnen"]], ["c", "b", "b2", "a"])
        self.assertFalse(data["kampagnen"][1]["aktiv"])

    def test_statuses_and_removal_two_weeks_after_the_end(self):
        running, done, quiet = campaign("running"), campaign("done"), campaign("quiet")
        self.file.write([running, quiet], self.file.read_settings(), finished=[done], live_ids={"running"})
        data = {k["id"]: k for k in self.read()["kampagnen"]}
        self.assertEqual(data["running"]["status"], "läuft")
        self.assertEqual(data["quiet"]["status"], "gerade kein Live-Kanal")
        self.assertEqual(data["done"]["status"], "alles abgeholt")

        settings = self.file.read_settings()
        entries = self.read()["kampagnen"]
        old_end = (datetime.utcnow() - timedelta(days=3)).strftime(FMT)
        gone_end = (datetime.utcnow() - timedelta(days=15)).strftime(FMT)
        for entry in entries:
            if entry["id"] == "quiet":
                entry["ende_utc"] = old_end
            if entry["id"] == "done":
                entry["ende_utc"] = gone_end
        self.save({"kampagnen": entries})
        settings = self.file.read_settings()
        self.file.write([running], settings, live_ids={"running"})
        data = {k["id"]: k for k in self.read()["kampagnen"]}
        self.assertEqual(data["quiet"]["status"], "abgelaufen")
        self.assertNotIn("done", data)
        self.assertEqual(data["running"]["status"], "läuft")

    def test_known_games_are_remembered_for_the_next_search(self):
        self.file.write([campaign("p", game="Pokémon GO")], self.file.read_settings())
        self.assertEqual(self.file.known_slugs(), ["pokemon-go"])

    def test_small_slip_is_fixed_and_rewritten_clean(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"kampagnen": [{"id": "b", "aktiv": false,}, {"id": "a"},]')
        settings = self.file.read_settings()
        self.assertTrue(self.file.broken)
        self.assertEqual(settings["order"], ["b", "a"])
        self.assertFalse(settings["campaigns"]["b"]["active"])
        self.assertTrue(os.path.exists(self.broken_copy()))
        self.assertTrue(self.file.write([campaign("a"), campaign("b")], settings))
        self.assertEqual([k["id"] for k in self.read()["kampagnen"]], ["b", "a"])
        self.assertFalse(self.file.broken)

    def test_badly_broken_file_keeps_order_and_active_values(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"spiele": [{"spiel": "Pokémon GO", "aktiv": false}], "kampagnen": [ {"spiel": "x" "aktiv": false, "id": "c"} {"aktiv": true "id": "a"} kaputt ::: ')
        settings = self.file.read_settings()
        self.assertEqual(settings["order"], ["c", "a"])
        self.assertFalse(settings["campaigns"]["c"]["active"])
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

    def test_editor_bom_and_friendly_values(self):
        with open(self.path, "w", encoding="utf-8-sig") as f:
            json.dump({"spiele": [{"spiel": "A", "aktiv": "nein"}], "kampagnen": [{"id": "z", "aktiv": "ja"}, {"id": "z", "aktiv": False}]}, f)
        settings = self.file.read_settings()
        self.assertFalse(self.file.broken)
        self.assertEqual(settings["order"], ["z"])
        self.assertTrue(settings["campaigns"]["z"]["active"])
        self.assertFalse(settings["games"]["A"]["active"])


def raw_channel_campaign(cid, end_in_days=30, drops=(("Haunter", 20, "b1"), ("Gengar", 20, "b2"))):
    start = (datetime.utcnow() - timedelta(days=1)).strftime(FMT)
    end = (datetime.utcnow() + timedelta(days=end_in_days)).strftime(FMT)
    return {
        "id": cid,
        "name": f"Kampagne {cid}",
        "game": {"id": "509663", "name": "Special Events"},
        "endAt": end,
        "timeBasedDrops": [
            {"id": f"{cid}-{name}", "name": name, "startAt": start, "endAt": end, "requiredMinutesWatched": minutes, "benefitEdges": [{"benefit": {"id": benefit, "name": name}}]}
            for name, minutes, benefit in drops
        ],
    }


class FakeTwitch:
    def __init__(self):
        self.channel_campaigns = {}
        self.directory = {}
        self.inventory = {"in_progress": [], "claimed": set()}

    def get_drop_inventory(self):
        return self.inventory

    def find_drop_channels_for_game(self, slug, limit=8):
        return self.directory.get(slug, [])

    def get_channel_drop_campaigns(self, channel_id):
        return self.channel_campaigns.get(channel_id, [])

    def sync_campaign_progress(self, campaigns):
        return campaigns


class CollectorTest(unittest.TestCase):
    def test_finds_campaigns_from_live_drop_channels_and_known_games(self):
        twitch = FakeTwitch()
        pogo = {"id": "490655", "displayName": "Pokémon GO", "name": "Pokémon GO", "slug": "pokemon-go"}
        twitch.directory["pokemon-go"] = [("c1", "j0beats", 300, pogo), ("c2", "hoshiri13", 100, pogo)]
        twitch.channel_campaigns = {"c1": [raw_channel_campaign("evo")], "c2": [raw_channel_campaign("evo")], "c3": [raw_channel_campaign("gta", drops=(("Jacke", 60, "g1"),))]}
        own = make_streamer("gta_freund")
        own.channel_id = "c3"
        own.stream.drops_tags = True
        own.stream.game = {"id": "1", "displayName": "Grand Theft Auto VI", "slug": "grand-theft-auto-vi"}

        result = DropCampaignCollector(twitch).collect([own], ["pokemon-go"])
        by_id = {c.id: c for c in result.campaigns}
        self.assertEqual(set(by_id), {"evo", "gta"})
        self.assertEqual(by_id["evo"].game["displayName"], "Pokémon GO")
        self.assertEqual(by_id["gta"].game["displayName"], "Grand Theft Auto VI")
        self.assertEqual([x[0] for x in result.channels["evo"]], ["j0beats", "hoshiri13"])
        self.assertEqual(by_id["evo"].remaining_minutes(), 20)

    def test_claimed_rewards_are_recognised_and_fully_claimed_campaigns_marked_finished(self):
        twitch = FakeTwitch()
        game = {"displayName": "Pokémon GO", "slug": "pokemon-go"}
        twitch.directory["pokemon-go"] = [("c1", "j0beats", 10, game)]
        twitch.channel_campaigns = {"c1": [raw_channel_campaign("evo"), raw_channel_campaign("alt", drops=(("Pikachu", 20, "p1"),))]}
        twitch.inventory = {"in_progress": [], "claimed": {"b1", "p1"}}
        result = DropCampaignCollector(twitch).collect([], ["pokemon-go"])
        self.assertEqual([d.name for d in result.campaigns[0].drops], ["Gengar"])
        self.assertEqual([c.id for c in result.finished], ["alt"])

    def test_inventory_campaigns_bring_their_own_game(self):
        twitch = FakeTwitch()
        raw = raw_channel_campaign("anno", drops=(("Skarabäus", 120, "s1"),))
        raw["game"] = {"id": "163", "name": "Anno 117: Pax Romana", "slug": "anno-117-pax-romana"}
        twitch.inventory = {"in_progress": [raw], "claimed": set()}
        result = DropCampaignCollector(twitch).collect([], [])
        self.assertEqual(result.campaigns[0].game["slug"], "anno-117-pax-romana")


def fake_initialize(streamers, max_workers=10):
    for s in streamers:
        s.is_online = True
    return set()


class DiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.twitch = Twitch("test", "ua")
        self.miner = FakeMiner()
        self.file = DropCampaignFile(os.path.join(tempfile.mkdtemp(), "drop_campaigns.json"))
        self.collector = FakeCollector()
        self.discovery = DropDiscovery(self.twitch, self.miner, scan_interval=9999, monitor_interval=0, campaign_file=self.file, stall_seconds=1500, collector=self.collector)
        patcher = patch.object(Twitch, "get_active_campaigns", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        init = patch.object(Twitch, "initialize_streamers_context", side_effect=fake_initialize)
        init.start()
        self.addCleanup(init.stop)

    def move_to_top(self, cid):
        with open(self.file.path, encoding="utf-8") as f:
            data = json.load(f)
        entry = next(k for k in data["kampagnen"] if k["id"] == cid)
        data["kampagnen"].remove(entry)
        data["kampagnen"].insert(0, entry)
        with open(self.file.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.utime(self.file.path, (time.time() + 5, time.time() + 5))

    def test_editing_the_list_switches_within_a_minute(self):
        self.collector.campaigns = [campaign("other", game="Anderes", watched=5), campaign("gta", game="Grand Theft Auto VI")]
        self.collector.channels = {"other": [("kanal_other", 10)], "gta": [("kanal_gta", 10)]}
        self.discovery._refresh_queue()
        self.discovery._start_next()
        self.assertEqual(self.discovery._active_campaign.id, "other")

        self.move_to_top("gta")
        self.assertTrue(self.file.changed())
        self.discovery._settings = self.file.read_settings()
        self.discovery._apply_order()
        self.assertEqual(self.discovery._active_campaign.id, "gta")
        self.assertEqual(self.discovery._active_streamer.username, "kanal_gta")

    def test_higher_entry_without_live_channel_keeps_the_current_one(self):
        self.collector.campaigns = [campaign("other", game="Anderes", watched=5), campaign("gta", game="Grand Theft Auto VI")]
        self.collector.channels = {"other": [("kanal_other", 10)]}
        with patch.object(Twitch, "find_drop_channels_for_game", return_value=[]):
            self.discovery._refresh_queue()
            self.discovery._start_next()
            self.move_to_top("gta")
            self.discovery._settings = self.file.read_settings()
            self.discovery._apply_order()
        self.assertEqual(self.discovery._active_campaign.id, "other")
        self.assertEqual(self.miner.removed, [])

    def test_directory_channel_is_only_used_when_it_really_has_the_campaign(self):
        gta = campaign("gta", game="Grand Theft Auto VI")
        self.collector.campaigns = [gta]
        game = {"displayName": "Grand Theft Auto VI"}
        with patch.object(Twitch, "find_drop_channels_for_game", return_value=[("1", "falsch", 9, game), ("2", "richtig", 5, game)]), patch.object(
            Twitch, "get_channel_drop_campaigns", side_effect=lambda cid: [{"id": "anders"}] if cid == "1" else [{"id": "gta"}]
        ):
            self.discovery._refresh_queue()
            self.discovery._start_next()
        self.assertEqual(self.discovery._active_streamer.username, "richtig")

    def test_finished_campaign_moves_on_and_is_marked_in_the_list(self):
        a, b = campaign("a"), campaign("b")
        self.collector.campaigns = [a, b]
        self.collector.channels = {"a": [("kanal_a", 1)], "b": [("kanal_b", 1)]}
        self.discovery._refresh_queue()
        self.discovery._start_next()
        self.assertEqual(self.discovery._active_campaign.id, "a")
        self.collector.campaigns = [b]
        self.collector.finished = [a]
        self.discovery._refresh_queue()
        self.discovery._start_next()
        self.assertEqual(self.discovery._active_campaign.id, "b")
        with open(self.file.path, encoding="utf-8") as f:
            data = {k["id"]: k["status"] for k in json.load(f)["kampagnen"]}
        self.assertEqual(data, {"a": "alles abgeholt", "b": "läuft"})

    def test_stalled_channel_is_replaced_by_another_one(self):
        self.collector.campaigns = [campaign("gta", watched=10)]
        self.collector.channels = {"gta": [("kanal_a", 50), ("kanal_b", 10)]}
        self.discovery._refresh_queue()
        self.discovery._start_next()
        self.assertEqual(self.discovery._active_streamer.username, "kanal_a")
        self.discovery._progress_at = time.time() - 1600
        self.discovery._refresh_queue()
        self.assertIsNone(self.discovery._active_streamer)
        self.discovery._start_next()
        self.assertEqual(self.discovery._active_streamer.username, "kanal_b")

    def test_campaign_without_progress_and_no_other_channel_is_paused(self):
        self.collector.campaigns = [campaign("sub", game="Grand Theft Auto VI", watched=0), campaign("pogo", game="Pokémon GO")]
        self.collector.channels = {"sub": [("zarbex", 50)], "pogo": [("j0beats", 10)]}
        self.discovery._refresh_queue()
        self.discovery._start_next()
        self.assertEqual(self.discovery._active_campaign.id, "sub")
        self.discovery._progress_at = time.time() - 1600
        self.discovery._refresh_queue()
        self.assertIn("sub", self.discovery._paused)
        self.discovery._start_next()
        self.assertEqual(self.discovery._active_campaign.id, "pogo")
        with open(self.file.path, encoding="utf-8") as f:
            status = {k["id"]: k["status"] for k in json.load(f)["kampagnen"]}
        self.assertTrue(status["sub"].startswith("pausiert"))

    def test_zero_minute_drops_do_not_count_as_next_drop(self):
        c = campaign("rockstar", minutes=0)
        self.assertIsNone(c.remaining_minutes())
        self.assertFalse(c.is_earnable())

    def test_progress_keeps_the_channel(self):
        self.collector.campaigns = [campaign("gta", watched=10)]
        self.collector.channels = {"gta": [("kanal_a", 1)]}
        self.discovery._refresh_queue()
        self.discovery._start_next()
        self.discovery._progress_at = time.time() - 1600
        self.collector.campaigns = [campaign("gta", watched=15)]
        self.discovery._refresh_queue()
        self.assertEqual(self.discovery._active_streamer.username, "kanal_a")

    def test_known_games_from_the_file_are_handed_to_the_collector(self):
        self.collector.campaigns = [campaign("p", game="Pokémon GO")]
        self.discovery._refresh_queue()
        self.collector.campaigns = []
        self.discovery._refresh_queue()
        self.assertEqual(self.collector.slugs, ["pokemon-go"])

    def test_streamer_from_own_list_is_borrowed_not_duplicated(self):
        own = make_streamer("eranio_freund")
        self.miner.streamers.append(own)
        self.collector.campaigns = [campaign("gta")]
        self.collector.channels = {"gta": [("Eranio_Freund", 1)]}
        self.discovery._refresh_queue()
        self.discovery._start_next()
        self.assertIs(self.discovery._active_streamer, own)
        self.assertTrue(own.is_auto_drop_channel)
        self.assertEqual(self.miner.added, [])
        self.collector.campaigns = []
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
