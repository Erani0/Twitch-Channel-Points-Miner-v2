import json
import re
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from TwitchChannelPointsMiner import __version__
from TwitchChannelPointsMiner.classes import AnalyticsServer as analytics_module
from TwitchChannelPointsMiner.classes.AnalyticsServer import AnalyticsServer
from TwitchChannelPointsMiner.classes.entities.Streamer import Streamer
from TwitchChannelPointsMiner.classes.Settings import Settings
from TwitchChannelPointsMiner.eranio import dashboard, streak, streak_history
from TwitchChannelPointsMiner.eranio.dashboard import safe_image

ASSETS = Path(dashboard.ASSETS_DIR)
FORBIDDEN = ["zarmstrong", "v3", "3.22.0", "795629a", "Charts-Miner-v3"]
CDN = "https://static-cdn.jtvnw.net/ttv-boxart/123-285x380.jpg"
DROP_CDN = "https://static-cdn.jtvnw.net/twitch-quests-assets/REWARD/abc.png"


def streamer(name="alpha"):
    instance = Streamer.__new__(Streamer)
    instance.username = name
    instance.mutex = threading.Lock()
    instance.channel_points = 10
    return instance


@pytest.fixture
def env(tmp_path, monkeypatch):
    analytics = tmp_path / "analytics"
    analytics.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Settings, "analytics_path", str(analytics), raising=False)
    monkeypatch.setattr(Settings, "enable_analytics", True, raising=False)
    (analytics / "alpha.json").write_text(
        json.dumps(
            {
                "series": [{"x": 1_700_000_000_000, "y": 100, "z": "Watch"}],
                "annotations": [],
                "streak": [
                    {"x": 1_700_000_000_000, "y": 4},
                    {"x": 1_700_100_000_000, "y": 5},
                ],
            }
        ),
        encoding="utf-8",
    )
    (analytics / "beta.json").write_text(
        json.dumps({"series": [{"x": 1_700_000_000_000, "y": 5, "z": "Watch"}]}),
        encoding="utf-8",
    )
    (analytics / "secret.txt").write_text("secret", encoding="utf-8")
    (tmp_path / "drop_campaigns.json").write_text(
        json.dumps(
            {
                "aktualisiert": "20.11.2026 10:00",
                "jetzt": {"kanal": "alpha", "spiel": "Game", "kampagne": "Camp"},
                "kampagnen": [
                    {
                        "id": "c1",
                        "spiel": "Game",
                        "spiel_bild": CDN,
                        "kampagne": "Camp",
                        "aktiv": True,
                        "status": "läuft",
                        "endet": "30.11.2026 10:00",
                        "ende_utc": "2999-01-01T00:00:00Z",
                        "offen": "1 von 2 Drops",
                        "naechster_drop": "5 von 60 Minuten (Hat)",
                        "art": "Quest",
                        "abo_noetig": "ja",
                        "konto_verbunden": "nein",
                        "drops": [
                            {
                                "name": "Hat",
                                "belohnung": "<b>Hat</b>",
                                "bild": DROP_CDN,
                                "minuten_noetig": 60,
                                "minuten_aktuell": 5,
                                "abo_noetig": True,
                                "abgeholt": False,
                            },
                            {
                                "name": "Pet",
                                "belohnung": "Pet",
                                "bild": "http://evil.example/x.png",
                                "minuten_noetig": 30,
                                "minuten_aktuell": 30,
                                "abo_noetig": False,
                                "abgeholt": True,
                            },
                        ],
                    },
                    {
                        "id": "c2",
                        "spiel": "Other",
                        "spiel_bild": "https://evil.example/box.png",
                        "kampagne": "Daily",
                        "aktiv": False,
                        "status": "heute erledigt, wird täglich neu geprüft",
                        "art": "Drop-Kampagne",
                        "abo_noetig": "nein",
                        "konto_verbunden": "ja",
                        "naechster_start": "21.11.2026 00:00",
                        "drops": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (analytics / "drops_by_category.json").write_text(
        json.dumps(
            {
                "drops": [
                    {
                        "x": 2,
                        "category": "Game",
                        "campaign": "Camp",
                        "item_name": "Hat",
                        "benefit": "Hat",
                        "status": "captured",
                        "item_art_url": DROP_CDN,
                    },
                    {
                        "x": 1,
                        "category": "Game",
                        "campaign": "Old",
                        "item_name": "Gone",
                        "status": "failed",
                        "item_art_url": "https://evil.example/a.png",
                    },
                    {"x": 3, "category": "Game", "status": "in_progress"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (analytics / "now_watching.json").write_text(
        json.dumps(
            [
                {
                    "username": "alpha",
                    "reason": "drops",
                    "game": "Game",
                    "channel_points": 5,
                },
                {
                    "username": "beta",
                    "reason": "points",
                    "game": None,
                    "channel_points": 7,
                },
            ]
        ),
        encoding="utf-8",
    )
    dashboard.UPDATE.reset()
    streak_history.STATE.reset()
    analytics_module.response_cache.clear()
    server = AnalyticsServer(password=None)
    return SimpleNamespace(
        client=server.app.test_client(), analytics=analytics, server=server
    )


def static_url(env, name):
    return env.server.app.static_url_path + "/" + name


def test_pages_and_assets_are_served(env):
    page = env.client.get("/")
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    for marker in (
        'id="drops-panel"',
        'id="watching-box"',
        'id="delete-dialog"',
        'id="log-pause"',
    ):
        assert marker in body
    for name in ("dashboard.js", "dashboard.css", "dark-theme.css", "banner.png"):
        response = env.client.get(static_url(env, name))
        response.close()
        assert response.status_code == 200, name
        assert static_url(env, name) in body or name == "banner.png"


def test_the_base_pages_are_not_served(env):
    for name in (
        "charts.html",
        "script.js",
        "style.css",
        "windows_shell.html",
        "tail_buffer.js",
    ):
        response = env.client.get(static_url(env, name))
        response.close()
        assert response.status_code == 404, name


def test_drops_endpoint_shape_and_image_filter(env):
    data = env.client.get("/drops").get_json()
    assert set(data) == {"kampagnen", "jetzt", "aktualisiert", "verlauf"}
    first, second = data["kampagnen"]
    assert first["spiel_bild"] == CDN
    assert first["art"] == "Quest"
    assert first["abo_noetig"] is True
    assert first["konto_verbunden"] == "nein"
    assert first["drops"][0]["bild"] == DROP_CDN
    assert first["drops"][1]["bild"] is None
    assert first["drops"][1]["abgeholt"] is True
    assert second["spiel_bild"] == (
        "https://static-cdn.jtvnw.net/ttv-boxart/Other-144x192.jpg"
    )
    assert second["aktiv"] is False
    assert second["tages_drop"] is True
    assert data["jetzt"]["kanal"] == "alpha"
    history = data["verlauf"]
    assert [row["item_name"] for row in history["abgeholt"]] == ["Hat"]
    assert [row["item_name"] for row in history["abgelaufen"]] == ["Gone"]
    assert history["abgelaufen"][0]["item_art_url"] is None


def test_drops_endpoint_hides_ended_campaigns(env, tmp_path):
    path = tmp_path / "drop_campaigns.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    base = data["kampagnen"][0]
    data["kampagnen"] += [
        {**base, "id": "old", "kampagne": "Old", "status": "abgelaufen", "ende_utc": None},
        {**base, "id": "past", "kampagne": "Past", "status": "läuft", "ende_utc": "2020-01-01T00:00:00Z"},
        {**base, "id": "done", "kampagne": "Done", "status": "alles abgeholt", "ende_utc": "2999-01-01T00:00:00Z"},
        {**base, "id": "odd", "status": "läuft", "ende_utc": "kaputt"},
    ]
    path.write_text(json.dumps(data), encoding="utf-8")
    result = env.client.get("/drops").get_json()
    assert [c["id"] for c in result["kampagnen"]] == ["c1", "c2", "odd"]
    ended = result["verlauf"]["kampagnen"]
    assert [row["kampagne"] for row in ended] == ["Done", "Past", "Old"]
    assert ended[0]["abgeschlossen"] is True and ended[1]["abgeschlossen"] is False
    assert ended[0]["drops_gesamt"] == 2 and ended[0]["drops_abgeholt"] == 1
    assert ended[0]["spiel_bild"] == CDN


def test_game_and_history_images_are_filled_in():
    assert dashboard.game_image("Call of Duty: Warzone") == (
        "https://static-cdn.jtvnw.net/ttv-boxart/Call%20of%20Duty%3A%20Warzone-144x192.jpg"
    )
    assert dashboard.game_image("Unbekannt") is None
    assert dashboard.game_image("Game", CDN) == CDN
    index = dashboard.drop_image_index(
        [{"spiel": "Game", "kampagne": "Camp", "drops": [{"name": "Hat", "belohnung": "Big Hat", "bild": DROP_CDN}]}]
    )
    assert dashboard.history_image({"campaign": "camp", "item_name": "hat"}, index) == DROP_CDN
    assert dashboard.history_image({"category": "Game", "benefit": "Big Hat"}, index) == DROP_CDN
    assert dashboard.history_image({"campaign": "Other", "item_name": "Hat"}, index) is None


def test_history_is_kept_in_its_own_file(env, tmp_path):
    first = env.client.get("/drops").get_json()["verlauf"]
    assert [r["item_name"] for r in first["abgeholt"]] == ["Hat"]
    stored = json.loads(
        (env.analytics / dashboard.HISTORY_FILE).read_text(encoding="utf-8")
    )
    assert {e["art"] for e in stored["eintraege"]} == {"abgeholt", "abgelaufen"}
    (env.analytics / "drops_by_category.json").unlink()
    (tmp_path / "drop_campaigns.json").unlink()
    later = env.client.get("/drops").get_json()["verlauf"]
    assert [r["item_name"] for r in later["abgeholt"]] == ["Hat"]
    assert [r["item_name"] for r in later["abgelaufen"]] == ["Gone"]


def test_history_does_not_duplicate_and_fills_missing_images(env):
    env.client.get("/drops")
    env.client.get("/drops")
    path = env.analytics / dashboard.HISTORY_FILE
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert len(stored["eintraege"]) == 2
    gone = next(e for e in stored["eintraege"] if e["art"] == "abgelaufen")
    assert gone["daten"]["item_art_url"] is None
    result = dashboard.remember_history(
        {"abgelaufen": [dict(gone["daten"], item_art_url=DROP_CDN)]}
    )
    assert result["abgelaufen"][0]["item_art_url"] == DROP_CDN


def test_drops_endpoint_without_files_is_empty(env, tmp_path):
    (env.analytics / dashboard.HISTORY_FILE).unlink(missing_ok=True)
    (tmp_path / "drop_campaigns.json").unlink()
    (env.analytics / "drops_by_category.json").unlink()
    data = env.client.get("/drops").get_json()
    assert data["kampagnen"] == []
    assert data["verlauf"] == {"abgeholt": [], "abgelaufen": [], "kampagnen": []}


def test_watching_reasons(env):
    streak.STATE.tracks["alpha"] = streak.Track(login="alpha", logical_start=0.0)
    streak.STATE.tracks["beta"] = streak.Track(
        login="beta", logical_start=0.0, done=True
    )
    streak.STATE.known_length["beta"] = 12
    data = env.client.get("/watching").get_json()
    by_name = {row["username"]: row for row in data["channels"]}
    assert by_name["alpha"]["reasons"] == ["Drop", "Streak"]
    assert by_name["beta"]["reasons"] == ["Points"]
    assert by_name["beta"]["streak_days"] == 12
    assert set(data["streak_loan"]) == {"active", "login", "expires_at"}


def test_nothing_reveals_the_base(env, monkeypatch):
    monkeypatch.setattr(dashboard, "fetch_latest_version", lambda: "99.0.0")
    texts = [env.client.get("/").get_data(as_text=True)]
    for path in ("/drops", "/watching", "/update_info", "/streamers", "/json/alpha"):
        texts.append(env.client.get(path).get_data(as_text=True))
    for path in ASSETS.iterdir():
        if path.suffix in (".html", ".js", ".css"):
            texts.append(path.read_text(encoding="utf-8"))
    for text in texts:
        for word in FORBIDDEN:
            assert word not in text, word
    assert not (ASSETS / "V3_BASE").exists()


def test_the_base_marker_file_is_in_the_package_only():
    marker = Path(dashboard.__file__).parent / "V3_BASE"
    assert re.fullmatch(r"\d+\.\d+\.\d+ [0-9a-f]{7,40}", marker.read_text().strip())


def test_the_startup_version_is_the_own_version():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)
    assert __version__ != "3.22.0"


def test_no_authentication_is_required_or_offered(env):
    for path in (
        "/",
        "/streamers",
        "/json_all",
        "/drops",
        "/watching",
        "/log",
        "/drops_by_category",
    ):
        response = env.client.get(path)
        assert response.status_code != 401, path
        assert "WWW-Authenticate" not in response.headers
    assert env.server.password is None
    assert env.client.get("/config").status_code == 404
    assert env.client.post("/config/notifications/discord/test").status_code == 404


def test_json_path_traversal_is_blocked(env):
    for path in (
        "/json/..%2fsecret",
        "/json/../secret",
        "/json/secret.txt",
        "/json/..%5c..%5csecret",
    ):
        assert env.client.get(path).status_code == 404, path
    assert env.client.get("/json/alpha").status_code == 200


def test_delete_removes_one_streamer(env):
    assert env.client.delete("/streamers/alpha").status_code == 204
    assert not (env.analytics / "alpha.json").exists()
    assert (env.analytics / "beta.json").exists()
    assert env.client.delete("/streamers/alpha").status_code == 404
    assert env.client.delete("/streamers/secret.txt").status_code == 404
    assert (env.analytics / "secret.txt").exists()
    names = [row["name"] for row in env.client.get("/streamers").get_json()]
    assert names == ["beta.json"]


def test_cross_site_delete_is_rejected(env):
    response = env.client.delete(
        "/streamers/beta", headers={"Origin": "http://evil.example"}
    )
    assert response.status_code == 403
    assert (env.analytics / "beta.json").exists()


def test_update_info_uses_only_the_own_repository(env, monkeypatch):
    assert "Erani0/Twitch-Channel-Points-Miner-v2" in dashboard.UPDATE_SOURCE
    monkeypatch.setattr(dashboard, "fetch_latest_version", lambda: "99.0.0")
    assert env.client.get("/update_info").get_json() == {
        "available": True,
        "latest": "99.0.0",
    }
    dashboard.UPDATE.reset()
    monkeypatch.setattr(dashboard, "fetch_latest_version", lambda: __version__)
    assert env.client.get("/update_info").get_json() == {
        "available": False,
        "latest": None,
    }
    dashboard.UPDATE.reset()

    def broken():
        raise OSError("offline")

    monkeypatch.setattr(dashboard, "fetch_latest_version", broken)
    assert env.client.get("/update_info").get_json() == {
        "available": False,
        "latest": None,
    }


def test_the_version_is_read_from_the_own_init_file(monkeypatch):
    class Response:
        text = '# -*- coding: utf-8 -*-\n__version__ = "4.1.2"  # marker\n'

        def raise_for_status(self):
            return None

    monkeypatch.setattr(dashboard.requests, "get", lambda url, timeout: Response())
    assert dashboard.fetch_latest_version() == "4.1.2"


def test_safe_image_accepts_only_https_twitch_hosts():
    assert safe_image(CDN) == CDN
    assert safe_image("https://x.twitchcdn.net/a.png")
    assert safe_image("http://static-cdn.jtvnw.net/a.png") is None
    assert safe_image("https://jtvnw.net.evil.example/a.png") is None
    assert safe_image("https://evil.example/jtvnw.net/a.png") is None
    assert safe_image("javascript:alert(1)") is None
    assert safe_image(None) is None


def test_streamer_list_contains_the_watch_streak_days(env):
    rows = {row["name"]: row for row in env.client.get("/streamers").get_json()}
    assert rows["alpha.json"]["watch_streak_days"] == 5
    assert rows["beta.json"]["watch_streak_days"] is None
    assert rows["alpha.json"]["points"] == 100


def test_the_streak_series_is_served(env):
    data = env.client.get("/json/alpha").get_json()
    assert [entry["y"] for entry in data["streak"]] == [4, 5]
    assert data["series"][0]["y"] == 100
    assert (
        "streak"
        in {e["name"]: e for e in env.client.get("/json_all").get_json()}["alpha"][
            "data"
        ]
    )


def test_old_streak_history_survives_new_entries(env):
    alpha = streamer("alpha")
    assert streak_history.record(alpha, 6, now=1000.0) is True
    data = json.loads((env.analytics / "alpha.json").read_text(encoding="utf-8"))
    assert [entry["y"] for entry in data["streak"]] == [4, 5, 6]
    assert data["series"][0]["y"] == 100
    assert all(set(entry) == {"x", "y"} for entry in data["streak"])
    rows = {row["name"]: row for row in env.client.get("/streamers").get_json()}
    assert rows["alpha.json"]["watch_streak_days"] == 6


def test_unchanged_days_are_not_written_again_within_the_interval(env):
    alpha = streamer("alpha")
    assert streak_history.record(alpha, 6, now=1000.0) is True
    assert streak_history.record(alpha, 6, now=1100.0) is False
    assert streak_history.record(alpha, 7, now=1200.0) is True
    assert (
        streak_history.record(
            alpha, 7, now=1200.0 + streak_history.RECORD_INTERVAL_SECONDS
        )
        is True
    )
    data = json.loads((env.analytics / "alpha.json").read_text(encoding="utf-8"))
    assert [entry["y"] for entry in data["streak"]] == [4, 5, 6, 7, 7]


def test_streak_history_is_new_file_when_none_exists(env):
    gamma = streamer("gamma")
    assert streak_history.record(gamma, 3, now=5.0) is True
    data = json.loads((env.analytics / "gamma.json").read_text(encoding="utf-8"))
    assert [entry["y"] for entry in data["streak"]] == [3]


def test_sync_uses_the_reward_list_value_then_the_migrated_old_cache(env):
    alpha, beta, gamma = streamer("alpha"), streamer("beta"), streamer("gamma")
    streak.STATE.tracks["alpha"] = streak.Track(
        login="alpha", logical_start=0.0, value=9
    )
    streak.STATE.known_length.update({"alpha": 1, "beta": 21})
    assert streak_history.sync([alpha, beta, gamma], now=10.0) == 2
    stored = {
        name: json.loads((env.analytics / f"{name}.json").read_text(encoding="utf-8"))
        for name in ("alpha", "beta")
    }
    assert stored["alpha"]["streak"][-1]["y"] == 9
    assert stored["beta"]["streak"][-1]["y"] == 21
    assert not (env.analytics / "gamma.json").exists()


def test_nothing_is_written_without_analytics(env, monkeypatch):
    monkeypatch.setattr(Settings, "enable_analytics", False, raising=False)
    assert streak_history.record(streamer("alpha"), 8, now=1.0) is False
    data = json.loads((env.analytics / "alpha.json").read_text(encoding="utf-8"))
    assert [entry["y"] for entry in data["streak"]] == [4, 5]


def test_the_reward_list_check_records_the_days(env):
    alpha = streamer("alpha")
    alpha.channel_id = "1"
    alpha.stream = SimpleNamespace(watch_streak_missing=True)
    client = SimpleNamespace(
        reward_list=lambda channel_id: streak.Milestone(
            state="ACTIVE", value=8, achievement_at=None, expires_at=None, missed=[]
        ),
        stream_created_at=lambda channel_id: None,
    )
    streak.STATE.client = client
    track = streak.Track(login="alpha", logical_start=0.0)
    streak.run_check(alpha, track, 100.0)
    data = json.loads((env.analytics / "alpha.json").read_text(encoding="utf-8"))
    assert data["streak"][-1]["y"] == 8


def test_the_front_end_keeps_the_streak_display():
    script = (ASSETS / "dashboard.js").read_text(encoding="utf-8")
    for needle in (
        "watch_streak_days",
        "Streak ascending",
        "#ff9d45",
        "Watch streak (days)",
        'response["streak"]',
    ):
        assert needle in script or needle in (ASSETS / "index.html").read_text(
            encoding="utf-8"
        )
    page = (ASSETS / "index.html").read_text(encoding="utf-8")
    assert "Streak ascending" in page and "Streak descending" in page


def test_drop_pick_is_shown_as_drop_reason(env, tmp_path, monkeypatch):
    from TwitchChannelPointsMiner.eranio import dashboard, drops

    monkeypatch.setattr(drops.STATE, "drop_pick", ("alpha", "x"), raising=False)
    monkeypatch.setattr(
        dashboard,
        "read_json_file",
        lambda path: (
            [{"username": "alpha", "reason": "points"}]
            if str(path).endswith("now_watching.json")
            else {}
        ),
    )
    channels = dashboard.now_watching_overview()["channels"]
    assert channels[0]["reasons"][0] == "Drop"
