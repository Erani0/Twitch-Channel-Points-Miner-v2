import json
import logging
import os
import time
from datetime import timedelta
from types import SimpleNamespace

import pytest

from TwitchChannelPointsMiner.classes.entities.Campaign import Campaign
from TwitchChannelPointsMiner.classes.entities.Drop import utc_now
from TwitchChannelPointsMiner.classes.Settings import Priority
from TwitchChannelPointsMiner.eranio import drops, streak
from TwitchChannelPointsMiner.eranio.drops import DropFile, DropView, empty_settings
from test_eranio_compat import owner_options, workdir  # noqa: F401
import TwitchChannelPointsMiner as package

FMT = "%Y-%m-%dT%H:%M:%SZ"
T0 = 1_800_000_000.0


def raw_campaign(
    cid,
    game="Test Game",
    minutes=60,
    end_in=3600,
    channels=None,
    subscription=False,
    extra_drops=(),
):
    now = utc_now()
    drop = {
        "id": f"{cid}-d1",
        "name": "Test Drop",
        "startAt": (now - timedelta(days=1)).strftime(FMT),
        "endAt": (now + timedelta(seconds=end_in)).strftime(FMT),
        "requiredMinutesWatched": minutes,
        "requiredSubs": 1 if subscription else 0,
        "benefitEdges": [
            {
                "benefit": {
                    "id": "b",
                    "name": "Prize",
                    "imageAssetURL": "http://img/p.png",
                }
            }
        ],
    }
    drops_list = [drop]
    for name, start_in in extra_drops:
        other = dict(drop)
        other["id"] = f"{cid}-{name}"
        other["name"] = name
        other["startAt"] = (now + timedelta(hours=start_in)).strftime(FMT)
        drops_list.append(other)
    return {
        "id": cid,
        "name": f"Kampagne {cid}",
        "status": "ACTIVE",
        "game": {
            "id": game,
            "displayName": game,
            "slug": drops.slugify(game),
            "boxArtURL": "http://img/box.png",
        },
        "startAt": (now - timedelta(days=2)).strftime(FMT),
        "endAt": (now + timedelta(seconds=end_in)).strftime(FMT),
        "allow": {"channels": [{"id": c} for c in channels] if channels else None},
        "timeBasedDrops": drops_list,
    }


def campaign(cid, watched=0, **kwargs):
    value = Campaign(raw_campaign(cid, **kwargs))
    value.drops[0].current_minutes_watched = watched
    return value


def view(cid, watched=0, **kwargs):
    return DropView(campaign(cid, watched=watched, **kwargs))


def ids(views):
    return [v.id for v in views]


def streamer(login, campaigns=(), game="Test Game", discovered=False, channel_id=None):
    stream = SimpleNamespace(
        campaigns=list(campaigns),
        campaigns_ids=[c.id for c in campaigns],
        game_name=lambda: game,
    )
    return SimpleNamespace(
        username=login,
        channel_id=channel_id or f"id-{login}",
        is_online=True,
        is_watching=False,
        stream=stream,
        from_category=discovered,
        from_wildcard_category=False,
        from_badge_campaign=False,
        settings=SimpleNamespace(watch_streak=False),
    )


class FakeTwitch:
    def __init__(self):
        self.report = []
        self.drop_watch_health = {}

    def unlinked_drop_report(self):
        return self.report


@pytest.fixture
def path(tmp_path):
    return str(tmp_path / "drop_campaigns.json")


@pytest.fixture
def layer(path):
    shared = ["base-game"]
    drops.configure(path=path, categories=shared)
    return SimpleNamespace(path=path, categories=shared, twitch=FakeTwitch())


def read(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def save(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
    os.utime(path, (time.time() + 5, time.time() + 5))


def publish(layer, campaigns, streamers=(), now=T0):
    for item in campaigns:
        drops.remember(item)
    drops.publish(layer.twitch, campaigns, list(streamers), now)


class TestOrder:
    def test_without_file_started_and_closest_drops_come_first(self):
        views = [
            view("long", minutes=120),
            view("fresh", minutes=10),
            view("started", minutes=60, watched=20),
        ]
        assert ids(DropFile.rank(views, empty_settings())) == [
            "started",
            "fresh",
            "long",
        ]

    def test_file_position_is_the_working_order(self):
        views = [view("a"), view("b"), view("c")]
        settings = {"games": {}, "campaigns": {}, "order": ["c", "b", "a"]}
        assert ids(DropFile.rank(views, settings)) == ["c", "b", "a"]

    def test_new_campaign_lands_below_its_game_or_at_the_end(self):
        views = [
            view("gta1", game="Grand Theft Auto VI"),
            view("pogo1", game="Pokemon GO"),
            view("pogo2", game="Pokemon GO"),
            view("other", game="Anderes"),
        ]
        settings = {"games": {}, "campaigns": {}, "order": ["pogo1", "gta1"]}
        assert ids(DropFile.ordered(views, settings)) == [
            "pogo1",
            "pogo2",
            "gta1",
            "other",
        ]

    def test_switched_off_subscription_only_and_unlinked_are_skipped(self):
        off, sub, ok, game_off, unlinked = (
            view("off"),
            view("sub", subscription=True),
            view("ok"),
            view("g", game="Langweilig"),
            view("u"),
        )
        unlinked.account_connected = False
        settings = {
            "games": {"Langweilig": {"active": False}},
            "campaigns": {"off": {"active": False}},
            "order": ["off", "sub", "ok", "g", "u"],
        }
        assert ids(DropFile.rank([off, sub, ok, game_off, unlinked], settings)) == [
            "ok"
        ]

    def test_zero_minute_drops_and_missing_precondition_do_not_count(self):
        zero = view("zero", minutes=0)
        blocked = view("blocked")
        blocked.drops[0].has_preconditions_met = False
        assert not zero.is_earnable() and not blocked.is_earnable()


class TestFile:
    def test_user_order_survives_and_new_ones_are_added(self, path):
        file = DropFile(path)
        a, b, c = (
            view("a", game="Grand Theft Auto VI", watched=25),
            view("b", game="Pokemon GO"),
            view("c", game="Anderes"),
        )
        file.write([a, b, c], file.read_settings(), {"a": "läuft"})
        data = read(path)
        assert data["kampagnen"][0]["naechster_drop"] == "25 von 60 Minuten (Test Drop)"
        assert data["kampagnen"][0]["status"] == "läuft"
        assert data["kampagnen"][0]["slug"] == "grand-theft-auto-vi"
        data["kampagnen"] = [
            data["kampagnen"][2],
            data["kampagnen"][1],
            data["kampagnen"][0],
        ]
        data["kampagnen"][1]["aktiv"] = False
        save(path, data)
        assert file.changed()
        settings = file.read_settings()
        assert not file.changed()
        file.write([a, b, c, view("b2", game="Pokemon GO")], settings)
        data = read(path)
        assert [k["id"] for k in data["kampagnen"]] == ["c", "b", "b2", "a"]
        assert data["kampagnen"][1]["aktiv"] is False

    def test_entries_carry_the_v3_details(self, path):
        file = DropFile(path)
        file.write([view("a")], file.read_settings())
        entry = read(path)["kampagnen"][0]
        assert entry["art"] == "Drop-Kampagne"
        assert entry["spiel_bild"] == "http://img/box.png"
        assert entry["drops"][0]["bild"] == "http://img/p.png"
        assert entry["drops"][0]["minuten_noetig"] == 60
        assert entry["abo_noetig"] == "nein"
        assert entry["konto_verbunden"] == "unbekannt"

    def test_removal_two_weeks_after_the_end(self, path):
        file = DropFile(path)
        file.write([view("quiet"), view("done")], file.read_settings())
        entries = read(path)["kampagnen"]
        for entry in entries:
            entry["ende_utc"] = (
                utc_now() - timedelta(days=3 if entry["id"] == "quiet" else 15)
            ).strftime(FMT)
        save(path, {"kampagnen": entries})
        file.write([view("running")], file.read_settings())
        data = {k["id"]: k for k in read(path)["kampagnen"]}
        assert data["quiet"]["status"] == "abgelaufen"
        assert "done" not in data

    def test_game_with_slug_is_kept_and_known(self, path):
        file = DropFile(path)
        save(
            path,
            {
                "spiele": [
                    {
                        "spiel": "Grand Theft Auto VI",
                        "slug": "grand-theft-auto-vi",
                        "aktiv": True,
                    }
                ],
                "kampagnen": [],
            },
        )
        settings = file.read_settings()
        assert file.known_slugs() == ["grand-theft-auto-vi"]
        file.write([], settings)
        assert read(path)["spiele"] == [
            {
                "spiel": "Grand Theft Auto VI",
                "aktiv": True,
                "slug": "grand-theft-auto-vi",
            }
        ]

    def test_small_slip_is_fixed_and_rewritten_clean(self, path):
        file = DropFile(path)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('{"kampagnen": [{"id": "b", "aktiv": false,}, {"id": "a"},]')
        settings = file.read_settings()
        assert file.broken
        assert settings["order"] == ["b", "a"]
        assert settings["campaigns"]["b"]["active"] is False
        assert os.path.exists(path.replace(".json", ".fehlerhaft.json"))
        assert file.write([view("a"), view("b")], settings)
        assert [k["id"] for k in read(path)["kampagnen"]] == ["b", "a"]
        assert not file.broken
        assert not os.path.exists(path + ".tmp")

    def test_badly_broken_file_keeps_order_and_active_values(self, path):
        file = DropFile(path)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(
                '{"spiele": [{"spiel": "Pokemon GO", "aktiv": false}], "kampagnen": [ {"spiel": "x" "aktiv": false, "id": "c"} {"aktiv": true "id": "a"} kaputt ::: '
            )
        settings = file.read_settings()
        assert settings["order"] == ["c", "a"]
        assert settings["campaigns"]["c"]["active"] is False
        assert settings["games"]["Pokemon GO"]["active"] is False

    def test_unreadable_file_falls_back_to_the_last_valid_state(self, path):
        file = DropFile(path)
        save(path, {"kampagnen": [{"id": "x"}, {"id": "y"}]})
        assert file.read_settings()["order"] == ["x", "y"]
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("völlig kaputt")
        settings = file.read_settings()
        assert settings["order"] == ["x", "y"]
        assert (
            open(path.replace(".json", ".fehlerhaft.json"), encoding="utf-8").read()
            == "völlig kaputt"
        )

    def test_editor_bom_and_friendly_values(self, path):
        file = DropFile(path)
        with open(path, "w", encoding="utf-8-sig") as handle:
            json.dump(
                {
                    "spiele": [{"spiel": "A", "aktiv": "nein"}],
                    "kampagnen": [
                        {"id": "z", "aktiv": "ja"},
                        {"id": "z", "aktiv": False},
                    ],
                },
                handle,
            )
        settings = file.read_settings()
        assert not file.broken
        assert settings["order"] == ["z"]
        assert settings["campaigns"]["z"]["active"] is True
        assert settings["games"]["A"]["active"] is False

    def test_old_file_of_the_previous_version_is_kept(self, layer):
        old = {
            "hinweis": ["alt"],
            "aktualisiert": "01.01.2026 10:00",
            "jetzt": None,
            "spiele": [{"spiel": "Alt Spiel", "aktiv": False, "slug": "alt-spiel"}],
            "kampagnen": [
                {
                    "spiel": "Test Game",
                    "kampagne": "Kampagne b",
                    "aktiv": False,
                    "status": "läuft",
                    "id": "b",
                    "slug": "test-game",
                    "ende_utc": None,
                },
                {
                    "spiel": "Test Game",
                    "kampagne": "Kampagne a",
                    "aktiv": True,
                    "status": "läuft",
                    "id": "a",
                    "slug": "test-game",
                    "ende_utc": None,
                },
            ],
        }
        save(layer.path, old)
        publish(layer, [campaign("a"), campaign("b"), campaign("c")])
        data = read(layer.path)
        assert [k["id"] for k in data["kampagnen"]] == ["b", "a", "c"]
        assert data["kampagnen"][0]["aktiv"] is False
        assert {"spiel": "Alt Spiel", "aktiv": False, "slug": "alt-spiel"} in data[
            "spiele"
        ]


class TestLayer:
    def test_status_texts(self, layer):
        layer.twitch.report = [{"campaign_id": "unl", "linked": False}]
        live = streamer("live", [campaign("run")])
        publish(
            layer,
            [
                campaign("run"),
                campaign("quiet"),
                campaign("sub", subscription=True),
                campaign("unl"),
            ],
            [live],
        )
        data = {k["id"]: k for k in read(layer.path)["kampagnen"]}
        assert data["run"]["status"] == "läuft"
        assert data["quiet"]["status"] == "gerade kein Live-Kanal"
        assert data["sub"]["status"] == "nur mit Abo"
        assert data["sub"]["abo_noetig"] == "ja"
        assert data["unl"]["status"] == "Konto nicht verbunden"
        assert data["unl"]["konto_verbunden"] == "nein"

    def test_paused_when_v3_blocks_the_game(self, layer):
        layer.twitch.drop_watch_health = {
            "test-game": {"blocked_until": {"live": time.time() + 600}}
        }
        live = streamer("live", [campaign("run")])
        publish(layer, [campaign("run")], [live], now=time.time())
        assert read(layer.path)["kampagnen"][0]["status"].startswith("pausiert")

    def test_finished_campaign_is_marked_and_kept(self, layer):
        drops.remember(Campaign(raw_campaign("done")))
        publish(layer, [campaign("other")])
        data = {k["id"]: k for k in read(layer.path)["kampagnen"]}
        assert data["done"]["status"] == drops.DAILY_STATUS
        assert data["done"]["offen"] == "0 von 1 Drops"

    def test_all_claimed_with_future_end_stays_daily_and_listed(self, layer):
        drops.remember(Campaign(raw_campaign("done")))
        for step in range(3):
            publish(layer, [campaign("other")], now=T0 + step * 900)
            data = {k["id"]: k for k in read(layer.path)["kampagnen"]}
            assert data["done"]["status"] == "heute erledigt, wird täglich neu geprüft"
            assert (
                not drops.STATE.file._settings["campaigns"]["done"]["entry"]["status"]
                == "alles abgeholt"
            )

    def test_same_drop_id_resets_next_day_and_is_mined_again(self, layer):
        item = campaign("daily", game="Spiel D")
        drops.remember(Campaign(raw_campaign("daily", game="Spiel D")))
        watcher = streamer("w", [], game="Spiel D", discovered=True)
        publish(layer, [], [watcher])
        assert read(layer.path)["kampagnen"][0]["status"] == drops.DAILY_STATUS
        drops.STATE.day = ("alt", "alt")
        publish(layer, [item], [watcher], now=T0 + 100)
        watcher.stream.campaigns = [item]
        watcher.stream.campaigns_ids = [item.id]
        publish(layer, [item], [watcher], now=T0 + 1100)
        entry = read(layer.path)["kampagnen"][0]
        assert entry["status"] == "läuft"
        assert drops.allows_watch(watcher)
        assert drops.streamer_rank(watcher) == 0

    def test_all_claimed_and_ended_is_finished_and_removed_after_two_weeks(self, layer):
        ended = Campaign(raw_campaign("old"))
        drops.remember(ended)
        publish(layer, [])
        assert read(layer.path)["kampagnen"][0]["status"] == drops.DAILY_STATUS
        drops.STATE.memo["old"].view.end_at = utc_now() - timedelta(days=1)
        publish(layer, [], now=T0 + 900)
        assert read(layer.path)["kampagnen"][0]["status"] == "alles abgeholt"
        drops.STATE.memo["old"].view.end_at = utc_now() - timedelta(days=15)
        data = read(layer.path)
        data["kampagnen"][0]["ende_utc"] = (utc_now() - timedelta(days=15)).strftime(
            FMT
        )
        save(layer.path, data)
        publish(layer, [], now=T0 + 1800)
        assert [k["id"] for k in read(layer.path)["kampagnen"]] == []

    def test_daily_chest_stays_open_until_next_day(self, layer):
        drops.remember(Campaign(raw_campaign("chest", extra_drops=(("Bronze", 10),))))
        publish(layer, [])
        entry = {k["id"]: k for k in read(layer.path)["kampagnen"]}["chest"]
        assert entry["status"].startswith("heute erledigt, nächster Drop ab")
        assert entry["offen"] == "1 von 2 Drops"
        assert entry["naechster_start"]

    def test_day_change_rechecks_daily_campaign(self, layer):
        drops.remember(Campaign(raw_campaign("chest", extra_drops=(("Bronze", 10),))))
        publish(layer, [])
        layer.twitch.drop_watch_health = {
            "x": {"blocked_until": {"a": time.time() + 999}}
        }
        drops.STATE.day = ("alt", "alt")
        publish(layer, [], now=T0 + 100)
        assert layer.twitch.drop_watch_health["x"]["blocked_until"] == {}
        entry = {k["id"]: k for k in read(layer.path)["kampagnen"]}["chest"]
        assert entry["status"] == drops.DAILY_STATUS

    def test_quest_type_is_reported(self, layer):
        quest = campaign("q")
        quest.reward_categories = [
            {"id": "1", "displayName": "Quest Game", "name": "q"}
        ]
        publish(layer, [quest])
        assert read(layer.path)["kampagnen"][0]["art"] == "Quest"

    def test_status_overview_is_logged(self, layer, caplog):
        with caplog.at_level(logging.INFO):
            publish(layer, [campaign("a"), campaign("b", subscription=True)])
        text = "\n".join(r.getMessage() for r in caplog.records)
        assert "Drops: 2 Kampagnen in Arbeitsreihenfolge" in text
        assert (
            "Drops 1. Test Game | Kampagne a | 1 von 1 offen | naechster: 0/60 Min. (Test Drop) | gerade kein Live-Kanal"
            in text
        )

    def test_list_order_decides_the_drop_pick(self, layer):
        a, b = campaign("a", game="Spiel A"), campaign("b", game="Spiel B")
        sa = streamer("sa", [a], game="Spiel A", discovered=True)
        sb = streamer("sb", [b], game="Spiel B", discovered=True)
        publish(layer, [a, b], [sa, sb])
        key = drops.pick_key([sa, sb], lambda i: 0)
        assert key(0) < key(1)
        data = read(layer.path)
        data["kampagnen"] = list(reversed(data["kampagnen"]))
        save(layer.path, data)
        publish(layer, [a, b], [sa, sb], now=T0 + 60)
        key = drops.pick_key([sa, sb], lambda i: 0)
        assert key(1) < key(0)

    def test_inactive_campaign_and_game_are_not_watched(self, layer):
        a, b = campaign("a", game="Spiel A"), campaign("b", game="Spiel B")
        sa = streamer("sa", [a], game="Spiel A", discovered=True)
        sb = streamer("sb", [b], game="Spiel B", discovered=True)
        publish(layer, [a, b], [sa, sb])
        assert drops.allows_watch(sa) and drops.allows_watch(sb)
        data = read(layer.path)
        data["kampagnen"][0]["aktiv"] = False
        data["spiele"][1]["aktiv"] = False
        save(layer.path, data)
        publish(layer, [a, b], [sa, sb], now=T0 + 60)
        assert not drops.allows_watch(sa)
        assert not drops.allows_watch(sb)

    def test_explicit_streamers_are_never_blocked(self, layer):
        a = campaign("a")
        explicit = streamer("e", [a], discovered=False)
        save(layer.path, {"kampagnen": [{"id": "a", "aktiv": False}]})
        publish(layer, [a], [explicit])
        assert drops.allows_watch(explicit)

    def test_unearnable_campaign_does_not_block_the_next(self, layer):
        sub, ok = campaign("sub", subscription=True), campaign("ok")
        s_sub = streamer("s1", [sub], discovered=True)
        s_ok = streamer("s2", [ok], discovered=True)
        save(layer.path, {"kampagnen": [{"id": "sub"}, {"id": "ok"}]})
        publish(layer, [sub, ok], [s_sub, s_ok])
        assert drops.STATE.rank_ids == ["ok"]
        assert not drops.allows_watch(s_sub)
        assert drops.allows_watch(s_ok)

    def test_restricted_campaign_only_ranks_its_channels(self, layer):
        restricted = campaign("r", channels=["id-allowed"])
        allowed = streamer("allowed", [], channel_id="id-allowed")
        other = streamer("other", [], channel_id="id-other")
        publish(layer, [restricted])
        assert drops.streamer_rank(allowed) == 0
        assert drops.streamer_rank(other) is None

    def test_game_slug_search_hook(self, layer):
        save(
            layer.path,
            {
                "spiele": [
                    {
                        "spiel": "Grand Theft Auto VI",
                        "slug": "grand-theft-auto-vi",
                        "aktiv": True,
                    },
                    {"spiel": "Aus", "slug": "aus", "aktiv": False},
                ],
                "kampagnen": [],
            },
        )
        publish(layer, [campaign("a", game="Spiel A")])
        assert layer.categories[0] == "base-game"
        assert "grand-theft-auto-vi" in layer.categories
        assert "spiel-a" in layer.categories
        assert "aus" not in layer.categories

    def test_without_auto_discovery_everything_is_plain(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        drops.STATE.reset()
        a = campaign("a")
        discovered = streamer("x", [a], discovered=True)
        assert drops.allows_watch(discovered)
        assert drops.pick_key([discovered], lambda i: 5)(0) == 5
        assert drops.drop_rank(discovered, 3) == 3
        assert drops.reserve(None, [discovered], [], [0], 2, lambda i: True) == []
        drops.publish(FakeTwitch(), [a], [])
        assert not os.path.exists(drops.DEFAULT_PATH)


def streak_streamer(login):
    item = streamer(login)
    item.settings = SimpleNamespace(watch_streak=True)
    item.stream.broadcast_id = "1"
    item.stream.minute_watched = 0
    item.stream.watch_streak_missing = True
    return item


class TestSlot:
    def prepare(self, layer, names=("top", "low")):
        views = []
        streamers = []
        for name in names:
            item = campaign(name, game=f"Spiel {name}")
            views.append(item)
            streamers.append(
                streamer(name, [item], game=f"Spiel {name}", discovered=True)
            )
        save(layer.path, {"kampagnen": [{"id": n} for n in names]})
        publish(layer, views, streamers)
        return streamers

    def test_top_campaign_gets_the_fixed_slot_even_when_slots_are_full(self, layer):
        streamers = self.prepare(layer) + [streamer("p1"), streamer("p2")]
        result = drops.reserve(
            layer.twitch, streamers, [2, 3], [0, 1, 2, 3], 2, lambda i: i < 2
        )
        assert result[0] == 0 and len(result) == 2

    def test_lower_drop_stream_gives_way_to_the_listed_top(self, layer):
        streamers = self.prepare(layer)
        assert drops.reserve(
            layer.twitch, streamers, [1], [0, 1], 2, lambda i: True
        ) == [0]

    def test_slot_kept_when_top_already_watched(self, layer):
        streamers = self.prepare(layer)
        assert drops.reserve(
            layer.twitch, streamers, [0, 1], [0, 1], 2, lambda i: True
        ) == [0]

    def test_slot_is_lent_at_most_fifteen_minutes_then_returned(self, layer):
        streak.configure()
        streak.STATE.client = SimpleNamespace(
            reward_list=lambda cid: streak.Milestone(
                state="NONE", value=0, achievement_at=None, expires_at=None
            ),
            stream_created_at=lambda cid: None,
        )
        streamers = self.prepare(layer, names=("top",))
        snapshot = streamers + [streak_streamer("a"), streak_streamer("b")]
        index = list(range(len(snapshot)))
        priority = [Priority.STREAK, Priority.DROPS]

        def step(now):
            watching = drops.reserve(
                layer.twitch, snapshot, [0, 1], index, 2, lambda i: i == 0, now
            )
            return streak.apply(
                SimpleNamespace(),
                snapshot,
                watching,
                index,
                priority,
                2,
                lambda i: i == 0,
                now,
            )

        assert 0 not in step(T0)
        assert streak.loan_info().active
        assert 0 not in step(T0 + 800)
        assert 0 in step(T0 + 901)
        assert streak.loan_info().active is False
        assert 0 in step(T0 + 1000)


class TestCompat:
    def run_mine(self, workdir, monkeypatch, **options):
        _, created = workdir
        miner = package.TwitchChannelPointsMiner(**{**owner_options(), **options})
        created.append(miner)
        seen = {}
        monkeypatch.setattr(miner, "run", lambda **kwargs: seen.update(kwargs))
        return miner, seen

    def test_auto_discovery_shares_the_category_list_and_enables_discovery(
        self, workdir, monkeypatch
    ):
        miner, seen = self.run_mine(workdir, monkeypatch)
        miner.mine(["a"])
        assert seen["categories"] is drops.STATE.categories
        assert seen["wildcard_categories"] is True
        assert seen["drop_pick_stickiness_minutes"] == 0
        assert seen["category_refresh_interval_hours"] == 0.25
        assert drops.active()

    def test_explicit_options_are_respected(self, workdir, monkeypatch):
        miner, seen = self.run_mine(workdir, monkeypatch)
        miner.mine(
            ["a"],
            categories=["x"],
            wildcard_categories=False,
            drop_pick_stickiness_minutes=7,
            category_refresh_interval_hours=0.1,
        )
        assert seen["categories"] == ["x"]
        assert seen["wildcard_categories"] is False
        assert seen["drop_pick_stickiness_minutes"] == 7
        assert seen["category_refresh_interval_hours"] == 0.1

    def test_without_auto_discovery_the_base_options_stay_untouched(
        self, workdir, monkeypatch
    ):
        miner, seen = self.run_mine(workdir, monkeypatch, auto_discover_drops=False)
        miner.mine(["a"])
        assert seen["wildcard_categories"] is False
        assert seen["categories"] == []
        assert seen["drop_pick_stickiness_minutes"] == 15
        assert seen["category_refresh_interval_hours"] == 6
        assert not drops.active()
