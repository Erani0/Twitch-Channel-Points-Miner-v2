import json
import os
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

from TwitchChannelPointsMiner.classes.entities.Streamer import Streamer
from TwitchChannelPointsMiner.classes.Settings import Settings
from TwitchChannelPointsMiner.eranio import export, streak, streak_history
from TwitchChannelPointsMiner.utils import _millify
from TwitchChannelPointsMiner.WatchStreakCache import WatchStreakCache


@pytest.fixture(autouse=True)
def clean_state():
    export.STATE.reset()
    streak_history.STATE.reset()
    yield
    export.STATE.stop.set()
    export.STATE.reset()
    streak_history.STATE.reset()


@pytest.fixture
def miner(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "enable_analytics", False, raising=False)
    export.configure("tester", directory=str(tmp_path))
    export.STATE.path = str(tmp_path / "streamers.xlsx")
    return SimpleNamespace(
        streamers=[],
        username="tester",
        running=False,
        watch_streak_cache=WatchStreakCache(tmp_path / "cache.json", "tester"),
        twitch=None,
    )


def make_streamer(name, points=0, sub=False, banned=False, created=None, history=None):
    streamer = Streamer(name)
    streamer.channel_points = points
    streamer.activeMultipliers = [{"factor": 0.2}] if sub else None
    if created is not None:
        streak.STATE.tracks[name] = streak.Track(
            login=name, logical_start=created.timestamp()
        )
    streamer.history = history or {}
    export.STATE.ban_status[name] = banned
    export.STATE.ban_lookup_attempted.add(name)
    return streamer


def test_rows_are_sorted_and_formatted(miner):
    easyemi = make_streamer(
        "easyemi",
        184880,
        sub=True,
        banned=True,
        created=datetime(2026, 3, 4, tzinfo=timezone.utc),
        history={
            "WATCH": {"counter": 2, "amount": 20},
            "WATCH_STREAK": {"counter": 1, "amount": 450},
        },
    )
    rubia = make_streamer(
        "rubia",
        26870,
        sub=True,
        created=datetime(2026, 3, 5, tzinfo=timezone.utc),
        history={"CLAIM": {"counter": 1, "amount": 999}},
    )
    itsceydi = make_streamer(
        "itsceydi", 82570, created=datetime(2026, 3, 6, tzinfo=timezone.utc)
    )
    miner.streamers = [rubia, easyemi, itsceydi]
    export.STATE.follow_dates = {"easyemi": "2025-07-21T12:34:56Z", "rubia": None}
    streak.STATE.known_length["easyemi"] = 12
    export.STATE.baseline = {"easyemi": 0, "itsceydi": 0, "rubia": 0}
    export.STATE.anchor = {"easyemi": 0, "itsceydi": 0, "rubia": 0}

    rows = export.build_rows(miner)

    assert [row["Streamer"] for row in rows] == ["easyemi", "itsceydi", "rubia"]
    assert [row["Points"] for row in rows] == [
        _millify(184880),
        _millify(82570),
        _millify(26870),
    ]
    assert [row["Followdate"] for row in rows] == ["21.07.2025", "...", "..."]
    assert [row["Last Stream"] for row in rows] == [
        "04.03.2026",
        "06.03.2026",
        "05.03.2026",
    ]
    assert [row["Sub"] for row in rows] == ["yes", "no", "yes"]
    assert [row["Banned"] for row in rows] == ["yes", "no", "no"]
    assert [row["Watchstreaks"] for row in rows] == [12, 0, 0]
    assert [row["Points gained"] for row in rows] == [470, 0, 999]
    assert list(rows[0]) == export.COLUMNS


def test_follow_date_accepts_datetime_values():
    assert (
        export.format_followdate(datetime(2025, 7, 21, tzinfo=timezone.utc))
        == "21.07.2025"
    )
    assert export.format_followdate(None) == "..."
    assert export.format_followdate("broken") == "..."


def test_points_gained_starts_from_zero_without_baseline(miner):
    miner.streamers = [
        make_streamer(
            "demo",
            1000,
            history={
                "WATCH": {"counter": 1, "amount": 12},
                "CLAIM": {"counter": 1, "amount": 50},
            },
        )
    ]
    assert export.build_rows(miner)[0]["Points gained"] == 0


def test_points_gained_persists_across_same_day_restart(miner, tmp_path):
    directory = str(tmp_path)
    export.configure("tester", directory=directory)
    export.STATE.path = str(tmp_path / "streamers.xlsx")
    streamer = make_streamer("demo", history={"WATCH": {"counter": 1, "amount": 120}})
    miner.streamers = [streamer]

    assert export.build_rows(miner)[0]["Points gained"] == 0
    export.save_baseline_if_dirty()

    streamer.history = {
        "WATCH": {"counter": 1, "amount": 120},
        "CLAIM": {"counter": 1, "amount": 50},
    }
    assert export.build_rows(miner)[0]["Points gained"] == 50
    export.save_baseline_if_dirty()

    export.configure("tester", directory=directory)
    export.STATE.path = str(tmp_path / "streamers.xlsx")
    restarted = make_streamer("demo")
    miner.streamers = [restarted]
    assert export.build_rows(miner)[0]["Points gained"] == 50


def test_points_gained_ignores_legacy_baseline_payload(miner, tmp_path):
    with open(export.STATE.baseline_path, "w", encoding="utf-8") as handle:
        json.dump(
            {"day_key": datetime.now().strftime("%Y-%m-%d"), "baseline": {"demo": 999}},
            handle,
        )
    export.load_baseline()
    assert export.STATE.baseline == {}
    assert export.STATE.snapshot == {}
    miner.streamers = [make_streamer("demo")]
    assert export.build_rows(miner)[0]["Points gained"] == 0


def test_points_gained_resets_on_day_change(miner):
    miner.streamers = [
        make_streamer("demo", history={"WATCH": {"counter": 1, "amount": 120}})
    ]
    export.STATE.day_key = "2000-01-01"
    export.STATE.baseline = {"demo": 0}
    assert export.build_rows(miner)[0]["Points gained"] == 0


def test_watch_streak_days_come_from_the_reward_list_when_unknown(miner):
    calls = []

    class Client:
        def reward_list(self, channel_id):
            calls.append(channel_id)
            return SimpleNamespace(value=26)

    streak.STATE.client = Client()
    streamer = make_streamer("demo")
    streamer.channel_id = "123456"
    miner.streamers = [streamer]

    assert export.build_rows(miner)[0]["Watchstreaks"] == 26
    assert export.build_rows(miner)[0]["Watchstreaks"] == 26
    assert calls == ["123456"]
    assert streak.STATE.known_length["demo"] == 26


def test_watch_streak_days_prefer_the_tracked_value(miner):
    streak.STATE.tracks["demo"] = streak.Track(login="demo", logical_start=0.0, value=9)
    streak.STATE.known_length["demo"] = 3
    miner.streamers = [make_streamer("demo")]
    assert export.build_rows(miner)[0]["Watchstreaks"] == 9


def test_export_persists_the_days_into_the_analytics_file(miner, tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "enable_analytics", True, raising=False)
    monkeypatch.setattr(Settings, "analytics_path", str(tmp_path), raising=False)
    streak.STATE.known_length["demo"] = 7
    streamer = make_streamer("demo")
    miner.streamers = [streamer]
    export.build_rows(miner)
    data = json.loads((tmp_path / "demo.json").read_text(encoding="utf-8"))
    assert [entry["y"] for entry in data["streak"]] == [7]


def test_banned_column_uses_the_base_ban_status_once(miner):
    from TwitchChannelPointsMiner.classes.entities.ChannelBanStatus import (
        ChannelBanStatus,
    )

    calls = []

    class Gql:
        def channel_ban_statuses(self, channel_ids):
            calls.append(list(channel_ids))
            return {"123456": ChannelBanStatus(True, permanent=True)}

    miner.twitch = SimpleNamespace(gql=Gql(), channel_bans={})
    streak.STATE.known_length["demo"] = 1
    streamer = Streamer("demo")
    streamer.channel_id = "123456"
    miner.streamers = [streamer]

    assert export.build_rows(miner)[0]["Banned"] == "yes"
    assert export.build_rows(miner)[0]["Banned"] == "yes"
    assert calls == [["123456"]]


def test_banned_column_prefers_the_base_cache(miner):
    from TwitchChannelPointsMiner.classes.entities.ChannelBanStatus import (
        ChannelBanStatus,
    )

    class Gql:
        def channel_ban_statuses(self, channel_ids):
            raise AssertionError("cache must be used")

    miner.twitch = SimpleNamespace(
        gql=Gql(), channel_bans={"123456": (ChannelBanStatus(False), 0)}
    )
    streamer = Streamer("demo")
    streamer.channel_id = "123456"
    streak.STATE.known_length["demo"] = 1
    miner.streamers = [streamer]
    assert export.build_rows(miner)[0]["Banned"] == "no"


def test_follow_dates_are_read_from_the_follow_pages(miner):
    node = SimpleNamespace(
        login="Demo",
        self=SimpleNamespace(
            follower=SimpleNamespace(
                followed_at=datetime(2025, 7, 21, tzinfo=timezone.utc)
            )
        ),
    )
    page = SimpleNamespace(
        follows=SimpleNamespace(
            edges=[SimpleNamespace(node=node)],
            page_info=SimpleNamespace(has_next_page=False, end_cursor=None),
        )
    )
    gql = SimpleNamespace(
        parser=SimpleNamespace(parse_channel_follows_response=None),
        post_gql_request_single=lambda name, payload, parser: page,
    )
    miner.twitch = SimpleNamespace(gql=gql)
    export.load_follow_dates(miner)
    assert export.format_followdate(export.STATE.follow_dates["demo"]) == "21.07.2025"


def test_follow_date_failure_is_not_fatal(miner):
    miner.twitch = None
    export.load_follow_dates(miner)
    assert export.STATE.follow_dates == {}


def test_format_timestamp_date_uses_the_utc_date():
    timestamp = datetime(2026, 3, 4, 0, 30, tzinfo=timezone.utc).timestamp()
    assert export.format_timestamp_date(timestamp) == "04.03.2026"
    assert export.format_timestamp_date(None) == "..."


def test_last_stream_date_uses_the_latest_cached_session(miner):
    streamer = Streamer("demo")
    started = datetime(2026, 3, 5, 10, 0, tzinfo=timezone.utc).timestamp()
    miner.watch_streak_cache.ensure("demo", "broadcast-demo", started)
    assert export.last_stream_date(miner, streamer) == "05.03.2026"


ROW = {
    "Streamer": "very_long_streamer_name",
    "Points": "184.88k",
    "Followdate": "21.07.2025",
    "Last Stream": "04.03.2026",
    "Sub": "yes",
    "Banned": "yes",
    "Watchstreaks": 26,
    "Points gained": 460,
}


def test_workbook_formatting(miner):
    export.write_xlsx(miner, [ROW])
    sheet = load_workbook(export.STATE.path).active
    for header in ["A1", "B1", "C1", "D1", "E1", "F1", "G1", "H1"]:
        assert sheet[header].font.bold
        assert sheet[header].alignment.horizontal == "center"
        assert sheet[header].fill.fill_type == "solid"
        assert (sheet[header].fill.fgColor.rgb or "").endswith("1F4E78")
    assert [cell.value for cell in sheet[1]] == export.COLUMNS
    assert sheet.title == "Sheet"
    assert sheet.freeze_panes == "A2"
    assert sheet.row_dimensions[1].height == 22
    assert len(sheet.tables) == 1
    table = next(iter(sheet.tables.values()))
    assert table.ref == "A1:H2"
    assert table.tableStyleInfo.name == "TableStyleMedium2"
    assert sheet["B2"].alignment.horizontal == "right"
    assert sheet["H2"].alignment.horizontal == "right"
    assert sheet["C2"].number_format == "DD.MM.YYYY"
    assert sheet["C2"].value.strftime("%d.%m.%Y") == "21.07.2025"
    assert sheet["D2"].value.strftime("%d.%m.%Y") == "04.03.2026"
    assert (sheet["G2"].fill.fgColor.rgb or "").endswith("E8F5E9")
    assert (sheet["H2"].fill.fgColor.rgb or "").endswith("F1F8E9")
    assert any(
        str(entry.sqref).startswith("H2") for entry in sheet.conditional_formatting
    )
    widths = [sheet.column_dimensions[letter].width for letter in "ABCDEFGH"]
    assert widths == [20, 10, 13, 13, 8, 10, 14, 15]


def test_workbook_rolls_to_a_new_date_file(miner, tmp_path, monkeypatch):
    old = tmp_path / "report_2026-03-05_tester.xlsx"
    new = tmp_path / "report_2026-03-06_tester.xlsx"
    export.STATE.path = str(old)
    monkeypatch.setattr(export, "dated_path", lambda directory, username: str(new))
    export.write_xlsx(miner, [ROW])
    assert export.STATE.path == str(new)
    assert not old.exists()
    assert new.exists()


def test_file_name_pattern(tmp_path):
    export.configure("Some User", directory=str(tmp_path))
    name = os.path.basename(export.STATE.path)
    today = datetime.now().strftime("%Y-%m-%d")
    assert name == f"report_{today}_some_user.xlsx"


def test_databar_is_skipped_when_nothing_was_gained(miner):
    export.write_xlsx(miner, [dict(ROW, **{"Points gained": 0, "Watchstreaks": 0})])
    sheet = load_workbook(export.STATE.path).active
    assert len(sheet.conditional_formatting) == 0


def test_the_loop_exports_on_start_and_on_the_interval(miner, monkeypatch):
    calls = []

    def fake_export(target):
        calls.append(1)
        if len(calls) == 2:
            target.running = False

    monkeypatch.setattr(export, "export_snapshot", fake_export)
    monkeypatch.setattr(export, "START_POLL_SECONDS", 0.01)
    export.STATE.interval = 0.01
    miner.running = True
    miner.streamers = [Streamer("demo")]
    export.start(miner)
    export.STATE.thread.join(timeout=5)
    assert len(calls) == 2


def test_finish_writes_a_last_export(miner):
    miner.streamers = [make_streamer("demo", 5)]
    export.finish(miner)
    assert os.path.isfile(export.STATE.path)
    sheet = load_workbook(export.STATE.path).active
    assert sheet["A2"].value == "demo"


def test_export_failure_does_not_raise(miner, monkeypatch):
    miner.streamers = [make_streamer("demo")]
    monkeypatch.setattr(
        export, "write_xlsx", lambda *args: (_ for _ in ()).throw(OSError("full"))
    )
    export.export_snapshot(miner)
