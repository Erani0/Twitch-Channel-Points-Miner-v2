import json
from types import SimpleNamespace

from TwitchChannelPointsMiner.eranio import drops
from TwitchChannelPointsMiner.eranio.drops import DropFile, empty_settings
from test_eranio_drops import FakeTwitch, campaign, publish
from test_eranio_order import ids, long_lived


class LinkGql:
    def __init__(self, links):
        self.links = links
        self.calls = 0

    def post_gql_request_raw(self, name, body):
        self.calls += 1
        return {
            "data": {
                "currentUser": {
                    "dropCampaigns": [
                        {"id": cid, "self": {"isAccountConnected": linked}}
                        for cid, linked in self.links.items()
                    ]
                }
            }
        }


def options(**values):
    result = dict(drops.DEFAULT_OPTIONS)
    result.update(values)
    return result


class TestOptions:
    def test_defaults_change_nothing(self):
        read = drops.read_options({})
        assert read["linked_only"] is False
        assert read["followed_only"] is False
        assert read["always_games"] == []

    def test_round_trip(self):
        written = drops.write_options(
            options(linked_only=True, followed_only=True, always_games=["GTA"])
        )
        assert written["nur_verbundene_konten"] is True
        assert drops.read_options({"einstellungen": written})["always_games"] == ["GTA"]


class TestLinkedOnly:
    def test_unlinked_campaigns_are_skipped_but_always_games_stay(self):
        linked = long_lived("linked", "Overwatch")
        linked.account_connected = True
        other = long_lived("other", "Genshin Impact")
        other.account_connected = False
        poke = long_lived("poke", "Special Events")
        poke.name = "Pokemon Evolutions"
        settings = empty_settings()
        settings["options"] = options(
            linked_only=True, always_games=["Pokemon Evolutions"]
        )
        drops.STATE.links = {"linked": True, "other": False}
        assert set(ids(DropFile.rank([linked, other, poke], settings))) == {
            "linked",
            "poke",
        }

    def test_filter_stays_off_while_twitch_gave_no_answer(self):
        other = long_lived("other", "Genshin Impact")
        settings = empty_settings()
        settings["options"] = options(linked_only=True)
        drops.STATE.links = None
        assert ids(DropFile.rank([other], settings)) == ["other"]

    def test_links_are_fetched_and_marked(self, tmp_path):
        path = tmp_path / "d.json"
        path.write_text(
            json.dumps({"einstellungen": {"nur_verbundene_konten": True}}),
            encoding="utf-8",
        )
        drops.configure(path=str(path), categories=["base"])
        twitch = FakeTwitch()
        twitch.gql = LinkGql({"a": True, "b": False})
        layer = SimpleNamespace(twitch=twitch)
        publish(
            layer, [campaign("a", game="Spiel A"), campaign("b", game="Spiel B")], []
        )
        assert drops.STATE.rank_ids == ["a"]
        entries = json.loads(path.read_text(encoding="utf-8"))["kampagnen"]
        status = {e["id"]: e["status"] for e in entries}
        assert status["b"] == drops.UNLINKED_OFF_STATUS


class TestFollowedOnly:
    def test_only_always_games_are_searched(self, tmp_path):
        path = tmp_path / "d.json"
        path.write_text(
            json.dumps(
                {
                    "einstellungen": {
                        "nur_gefolgte_kanaele": True,
                        "immer_sammeln": ["Grand Theft Auto VI"],
                    }
                }
            ),
            encoding="utf-8",
        )
        shared = []
        drops.configure(path=str(path), categories=shared)
        layer = SimpleNamespace(twitch=FakeTwitch())
        publish(
            layer,
            [
                campaign("gta", game="Grand Theft Auto VI"),
                campaign("ow", game="Overwatch"),
            ],
            [],
        )
        assert "grand-theft-auto-vi" in shared
        assert "overwatch" not in shared
        assert set(drops.STATE.rank_ids) == {"gta", "ow"}
