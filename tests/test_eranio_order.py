import json
from datetime import timedelta
from types import SimpleNamespace

from TwitchChannelPointsMiner.classes.entities.Drop import utc_now
from TwitchChannelPointsMiner.eranio import drops, quests, selfcheck
from TwitchChannelPointsMiner.eranio.drops import DropFile, empty_settings
from test_eranio_drops import FakeTwitch, campaign, publish, streamer, view
from test_eranio_quests import LACY, install, lacy_details, lacy_inventory
from test_eranio_settings import HEADERS, login, make_server

FMT = "%Y-%m-%dT%H:%M:%SZ"


def ids(views):
    return [v.id for v in views]


def short_lived(cid, game, minutes=60, watched=0):
    item = view(cid, game=game, minutes=minutes, watched=watched)
    item.start_at = utc_now() - timedelta(hours=2)
    item.end_at = utc_now() + timedelta(hours=10)
    return item


def long_lived(cid, game, minutes=60, watched=0):
    item = view(cid, game=game, minutes=minutes, watched=watched)
    item.start_at = utc_now() - timedelta(days=5)
    item.end_at = utc_now() + timedelta(days=5)
    return item


class TestAutomaticOrder:
    def test_game_order_then_daily_then_shortest_watchtime(self):
        views = [
            long_lived("gta-long", "Grand Theft Auto VI", minutes=1440),
            long_lived("gta-short", "Grand Theft Auto VI", minutes=180),
            short_lived("gta-daily", "Grand Theft Auto VI", minutes=600),
            long_lived("poke", "Special Events", minutes=20),
        ]
        settings = empty_settings()
        settings["order"] = ["poke", "gta-long", "gta-short", "gta-daily"]
        assert ids(DropFile.rank(views, settings)) == [
            "poke",
            "gta-daily",
            "gta-short",
            "gta-long",
        ]

    def test_without_automatic_the_manual_order_counts(self):
        views = [
            long_lived("a", "Spiel", minutes=600),
            long_lived("b", "Spiel", minutes=20),
        ]
        settings = empty_settings()
        settings["order"] = ["a", "b"]
        settings["options"]["auto_within_game"] = False
        assert ids(DropFile.rank(views, settings)) == ["a", "b"]

    def test_repeating_quest_counts_as_daily(self):
        repeat = long_lived("repeat", "Spiel", minutes=600)
        repeat.repeating = True
        quick = long_lived("quick", "Spiel", minutes=10)
        settings = empty_settings()
        settings["order"] = ["quick", "repeat"]
        assert ids(DropFile.rank([quick, repeat], settings)) == ["repeat", "quick"]


class TestGameGuess:
    def test_gta_quests_join_grand_theft_auto(self):
        names = ["Grand Theft Auto VI", "Black Desert"]
        assert drops.guess_game("GTA VI Release Zarbex Sub", names) == names[0]
        assert drops.guess_game("LACY GTA 6 MARATHON BADGE", names) == names[0]
        assert drops.guess_game("Database Supporter GTA 6", names) == names[0]

    def test_unrelated_names_stay_unassigned(self):
        names = ["Grand Theft Auto VI", "Black Desert"]
        assert drops.guess_game("OG", names) is None
        assert drops.guess_game("Dogninja", names) is None


class TestCreatorSwitch:
    def test_switched_off_creator_quests_are_listed_but_not_watched(self, tmp_path):
        path = tmp_path / "d.json"
        drops.configure(path=str(path), categories=["base"])
        install(lacy_inventory(), details={LACY: lacy_details()})
        path.write_text(
            json.dumps({"einstellungen": {"creator_quests": False}, "kampagnen": []}),
            encoding="utf-8",
        )
        lacy = streamer("lacy", game="Just Chatting", channel_id="494543675")
        layer = SimpleNamespace(twitch=FakeTwitch())
        publish(layer, [campaign(LACY, game="Grand Theft Auto VI")], [lacy])
        assert drops.quest_stream(lacy) is False
        assert LACY not in drops.STATE.position
        entry = next(
            e
            for e in json.loads(path.read_text(encoding="utf-8"))["kampagnen"]
            if e["id"] == LACY
        )
        assert entry["status"] == drops.CREATOR_OFF_STATUS
        assert quests.wanted_logins([]) == []


class TestEditor:
    def test_editor_reorders_switches_and_keeps_options(self, tmp_path):
        path = tmp_path / "d.json"
        drops.configure(path=str(path), categories=["base"])
        a = campaign("a", game="Spiel A")
        b = campaign("b", game="Spiel B")
        layer = SimpleNamespace(twitch=FakeTwitch())
        publish(layer, [a, b], [])
        shown = drops.editor_view()
        assert [g["name"] for g in shown["games"]] == ["Spiel A", "Spiel B"]
        result = drops.apply_editor(
            {
                "order": ["b", "a"],
                "active": {"a": False},
                "games_active": {"Spiel B": True},
                "options": {"creator_quests": False, "auto_within_game": True},
            }
        )
        assert [g["name"] for g in result["games"]] == ["Spiel B", "Spiel A"]
        assert result["options"]["creator_quests"] is False
        assert drops.STATE.settings["order"] == ["b", "a"]
        assert drops.STATE.settings["campaigns"]["a"]["active"] is False
        publish(layer, [a, b], [], now=10**10)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert [k["id"] for k in data["kampagnen"]] == ["b", "a"]
        assert data["einstellungen"]["creator_quests"] is False

    def test_settings_route_needs_login(self, tmp_path, monkeypatch):
        server = make_server(tmp_path, monkeypatch)
        client = server.app.test_client()
        assert client.get("/settings/api/drops", headers=HEADERS).status_code == 401
        login(client)
        answer = client.get("/settings/api/drops", headers=HEADERS)
        assert answer.status_code == 200
        assert answer.get_json()["available"] is False


class TestSelfCheck:
    def test_pick_without_progress_for_an_hour_is_paused(self):
        item = long_lived("bd", "Black Desert", minutes=120, watched=80)
        statuses = {"bd": "läuft"}
        selfcheck.evaluate(
            [item], [item], statuses, [], ("jnny", "bd"), drops.slugify, now=0
        )
        selfcheck.evaluate(
            [item], [item], statuses, [], ("jnny", "bd"), drops.slugify, now=1800
        )
        assert not selfcheck.is_blocked("bd", now=1800)
        selfcheck.evaluate(
            [item], [item], statuses, [], ("jnny", "bd"), drops.slugify, now=3700
        )
        assert selfcheck.is_blocked("bd", now=3700)
        assert "keine Minuten" in selfcheck.warnings_for_file(now=3700)[0]

    def test_progress_resets_the_stall_clock(self):
        item = long_lived("bd", "Black Desert", minutes=120, watched=80)
        statuses = {"bd": "läuft"}
        selfcheck.evaluate(
            [item], [item], statuses, [], ("jnny", "bd"), drops.slugify, now=0
        )
        item.drops[0].current_minutes_watched = 100
        selfcheck.evaluate(
            [item], [item], statuses, [], ("jnny", "bd"), drops.slugify, now=3700
        )
        assert not selfcheck.is_blocked("bd", now=3700)

    def test_unknown_award_is_reported_once(self):
        item = long_lived("bd", "Black Desert")
        selfcheck.STATE.inventory = {"gameEventDrops": [{"id": "old", "name": "Alt"}]}
        selfcheck.evaluate([item], [item], {}, [], None, drops.slugify, now=0)
        selfcheck.STATE.inventory = {
            "gameEventDrops": [
                {"id": "old", "name": "Alt"},
                {"id": "new", "name": "Goldener Leguan"},
            ]
        }
        selfcheck.evaluate([item], [item], {}, [], None, drops.slugify, now=60)
        selfcheck.evaluate([item], [item], {}, [], None, drops.slugify, now=120)
        warnings = selfcheck.warnings_for_file(now=120)
        assert len(warnings) == 1 and "Goldener Leguan" in warnings[0]

    def test_waiting_campaign_with_live_category_channels_is_reported(self):
        item = long_lived("poke", "Special Events")
        item.quest_slugs = ["djs"]
        dj = streamer("tschessy", game="DJs")
        statuses = {"poke": "gerade kein Live-Kanal"}
        selfcheck.evaluate([item], [item], statuses, [dj], None, drops.slugify, now=0)
        selfcheck.evaluate(
            [item], [item], statuses, [dj], None, drops.slugify, now=7300
        )
        assert "ohne Drop-Kanal" in selfcheck.warnings_for_file(now=7300)[0]
