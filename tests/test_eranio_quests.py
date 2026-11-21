import inspect
from datetime import datetime, timedelta

from TwitchChannelPointsMiner.classes import Twitch as twitch_module
from TwitchChannelPointsMiner.eranio import drops, quests
from test_eranio_drops import FakeTwitch, campaign, publish, streamer

LACY = "8a5c50da-27c7-4e87-81f2-1b878f37baf5"
POKEMON = "3e7f0c98-893c-47a7-9044-1c61173b8f94"
GTA = "b7669f9e-c69c-4a9b-a3b2-36266c1bdfc0"
NOW = datetime(2026, 11, 21, 17, 30)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def group(gid, kind, minutes=None, subs=None, status="IN_PROGRESS", watched=0, **own):
    return {
        "id": gid,
        "progressCriteria": {
            "requirementType": kind,
            "requirements": {"minutesWatched": minutes, "subs": subs},
            "repeatableConfig": own.pop("repeat", None),
        },
        "self": {"status": status, "currentMinutesWatched": watched, **own},
        "rewards": [{"name": f"Belohnung {gid}", "thumbnailURL": "http://img/x.png"}],
    }


def inventory(*campaigns):
    return {
        "data": {
            "currentUser": {
                "inventory": {"viewerRewardDropCampaignsInProgress": list(campaigns)}
            }
        }
    }


def lacy_inventory(watched=30):
    return {
        "id": LACY,
        "name": "LACY GTA 6 MARATHON BADGE",
        "rewardGroups": [
            group("lacy-sub", "SUB", subs=1, status=None),
            group("lacy-watch", "WATCH", minutes=300, watched=watched),
        ],
    }


def lacy_details():
    return {
        "rewardGroups": [
            {
                "id": "lacy-sub",
                "name": "LACY GTA 6 MARATHON BADGE",
                "progressCriteria": {
                    "requirementType": "SUB",
                    "requirements": {"subs": 1},
                    "channels": [{"id": "494543675", "login": "lacy"}],
                },
            },
            {
                "id": "lacy-watch",
                "name": "LACY GTA 6 MARATHON!",
                "progressCriteria": {
                    "requirementType": "WATCH",
                    "requirements": {"minutesWatched": 300},
                    "channels": [{"id": "494543675", "login": "lacy"}],
                },
            },
        ]
    }


def pokemon_inventory():
    return {
        "id": POKEMON,
        "name": "Pokemon Evolutions",
        "rewardGroups": [group("pikachu", "WATCH", minutes=20, watched=2)],
    }


def pokemon_details():
    names = ["Pokémon UNITE", "Special Events", "Just Chatting", "DJs", "Music"]
    return {
        "rewardGroups": [
            {
                "id": "pikachu",
                "name": "Pikachu",
                "progressCriteria": {
                    "requirementType": "WATCH",
                    "requirements": {"minutesWatched": 20},
                    "channels": [],
                    "categories": [{"id": n, "displayName": n} for n in names],
                },
            }
        ]
    }


def built(*items, details=None):
    return quests.build_quests(inventory(*items), details or {}, NOW)


class TestBuild:
    def test_creator_quest_keeps_its_channel_progress_and_sub_hint(self):
        quest = built(lacy_inventory(), details={LACY: lacy_details()})[LACY]
        assert quest.channel_quest is True
        assert quest.channels == {"494543675": "lacy"}
        assert quest.remaining() == 270
        assert quest.sub_label() == "Sub nötig"

    def test_sub_groups_only_known_from_details_still_count(self):
        item = lacy_inventory()
        item["rewardGroups"] = item["rewardGroups"][1:]
        quest = built(item, details={LACY: lacy_details()})[LACY]
        assert quest.sub_label() == "Sub nötig"
        assert quest.remaining() == 270

    def test_gift_campaign_says_how_many_subs(self):
        item = lacy_inventory()
        item["rewardGroups"][0] = group("lacy-sub", "SUB", subs=5, status=None)
        quest = built(item)[LACY]
        assert quest.sub_label() == "5 Subs nötig, auch verschenkt"

    def test_category_quest_lists_its_categories_without_channels(self):
        quest = built(pokemon_inventory(), details={POKEMON: pokemon_details()})[
            POKEMON
        ]
        assert quest.channel_quest is False
        assert "djs" in quest.category_slugs and "just-chatting" in quest.category_slugs

    def test_daily_repeat_done_for_today_is_not_watched(self):
        item = {
            "id": GTA,
            "name": "GTAVI Launch Celebration",
            "rewardGroups": [
                group(
                    "dvd",
                    "WATCH",
                    minutes=60,
                    watched=60,
                    grantCount=4,
                    repeat={"repeatableTimes": 6},
                    currentWindow={"expiresAt": iso(NOW + timedelta(hours=18))},
                )
            ],
        }
        assert built(item)[GTA].remaining() is None

    def test_expired_window_starts_again_at_zero(self):
        item = pokemon_inventory()
        item["rewardGroups"][0]["self"]["currentWindow"] = {
            "expiresAt": iso(NOW - timedelta(hours=1))
        }
        assert built(item)[POKEMON].remaining() == 20

    def test_claimed_groups_are_done(self):
        item = pokemon_inventory()
        item["rewardGroups"][0]["self"]["status"] = "CLAIMED"
        assert built(item)[POKEMON].remaining() is None


def install(*items, details=None):
    quests.STATE.configured = True
    quests.STATE.quests = built(*items, details=details)
    quests.STATE.last_refresh = float("inf")


class TestSelection:
    def test_live_creator_channel_becomes_the_drop_stream(self, tmp_path):
        drops.configure(path=str(tmp_path / "d.json"), categories=["base"])
        install(lacy_inventory(), details={LACY: lacy_details()})
        gta = campaign(LACY, game="Grand Theft Auto VI")
        lacy = streamer("lacy", game="Just Chatting", channel_id="494543675")
        other = streamer("someone", game="Just Chatting", channel_id="1")
        layer = type("L", (), {"twitch": FakeTwitch()})()
        publish(layer, [gta], [lacy, other])
        assert drops.quest_stream(lacy) is True
        assert drops.quest_stream(other) is False
        assert LACY in drops.matched_ids(lacy)
        assert drops.streamer_rank(lacy) == 0

    def test_offline_creator_channel_is_not_a_drop_stream(self, tmp_path):
        drops.configure(path=str(tmp_path / "d.json"), categories=["base"])
        install(lacy_inventory(), details={LACY: lacy_details()})
        lacy = streamer("lacy", game="Just Chatting", channel_id="494543675")
        lacy.is_online = False
        layer = type("L", (), {"twitch": FakeTwitch()})()
        publish(layer, [campaign(LACY, game="Grand Theft Auto VI")], [lacy])
        assert drops.quest_stream(lacy) is False

    def test_finished_creator_quest_frees_the_channel(self, tmp_path):
        drops.configure(path=str(tmp_path / "d.json"), categories=["base"])
        install(lacy_inventory(watched=300), details={LACY: lacy_details()})
        lacy = streamer("lacy", game="Just Chatting", channel_id="494543675")
        layer = type("L", (), {"twitch": FakeTwitch()})()
        publish(layer, [campaign(LACY, game="Grand Theft Auto VI")], [lacy])
        assert drops.quest_stream(lacy) is False

    def test_category_quest_adds_dj_and_chatting_categories(self, tmp_path):
        shared = ["base"]
        drops.configure(path=str(tmp_path / "d.json"), categories=shared)
        install(pokemon_inventory(), details={POKEMON: pokemon_details()})
        layer = type("L", (), {"twitch": FakeTwitch()})()
        publish(layer, [campaign(POKEMON, game="Special Events")], [])
        assert "just-chatting" in shared and "djs" in shared
        dj = streamer("tschessy", game="DJs")
        assert POKEMON in drops.matched_ids(dj)

    def test_followed_dj_stream_collects_the_category_quest(self, tmp_path):
        drops.configure(path=str(tmp_path / "d.json"), categories=["base"])
        install(pokemon_inventory(), details={POKEMON: pokemon_details()})
        layer = type("L", (), {"twitch": FakeTwitch()})()
        dj = streamer("tschessy", game="DJs")
        gamer = streamer("gamer", game="Rust")
        publish(layer, [campaign(POKEMON, game="Special Events")], [dj, gamer])
        assert drops.quest_stream(dj) is True
        assert drops.quest_stream(gamer) is False
        assert drops.streamer_rank(dj) == 0

    def test_file_shows_channel_and_sub_hint(self, tmp_path):
        import json

        path = tmp_path / "d.json"
        drops.configure(path=str(path), categories=["base"])
        install(lacy_inventory(), details={LACY: lacy_details()})
        layer = type("L", (), {"twitch": FakeTwitch()})()
        publish(layer, [campaign(LACY, game="Grand Theft Auto VI")], [])
        entry = next(
            e
            for e in json.loads(path.read_text(encoding="utf-8"))["kampagnen"]
            if e["id"] == LACY
        )
        assert entry["kanaele"] == "nur lacy"
        assert entry["abo_hinweis"] == "Sub nötig"
        assert entry["naechster_drop"].startswith("30 von 300 Minuten")


class TestMissingCampaign:
    def test_creator_quest_without_base_campaign_gets_its_own_entry(self, tmp_path):
        import json

        path = tmp_path / "d.json"
        drops.configure(path=str(path), categories=["base"])
        details = lacy_details()
        details["game"] = {
            "displayName": "Grand Theft Auto VI",
            "slug": "grand-theft-auto-vi",
        }
        details["endAt"] = iso(NOW + timedelta(days=9))
        install(lacy_inventory(), details={LACY: details})
        lacy = streamer("lacy", game="Just Chatting", channel_id="494543675")
        layer = type("L", (), {"twitch": FakeTwitch()})()
        publish(layer, [], [lacy])
        assert drops.quest_stream(lacy) is True
        entry = next(
            e
            for e in json.loads(path.read_text(encoding="utf-8"))["kampagnen"]
            if e["id"] == LACY
        )
        assert entry["spiel"] == "Grand Theft Auto VI"
        assert entry["status"] == "läuft"


class TestChannels:
    def test_missing_quest_channels_are_added_once(self):
        added = []

        class Miner:
            streamers = [type("S", (), {"username": "known"})()]

            def add_streamers(self, logins):
                added.append(list(logins))

        quests.configure(Miner())
        quests.ensure_streamers(["known", "lacy"])
        for thread in __import__("threading").enumerate():
            if thread.name == "eranio-quest-channels":
                thread.join(5)
        assert added == [["lacy"]]
        quests.ensure_streamers(["known", "lacy"])
        assert added == [["lacy"]]

    def test_category_slots_prefer_chatting_and_djs(self):
        view = type(
            "V", (), {"quest_slugs": ["pokemon-unite", "djs", "just-chatting", "music"]}
        )()
        assert quests.category_slugs(view) == ["just-chatting", "djs", "music"]


def test_the_watch_loop_counts_quest_channels_as_drop_streams():
    text = inspect.getsource(twitch_module.Twitch.send_minute_watched_events)
    assert "eranio_drops.quest_stream(streamers_snapshot[index])" in text
