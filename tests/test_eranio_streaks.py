import json
import logging
from types import SimpleNamespace

import pytest

from TwitchChannelPointsMiner.classes.CopyOnWriteList import CopyOnWriteList
from TwitchChannelPointsMiner.classes.Settings import Priority
from TwitchChannelPointsMiner.classes.Twitch import Twitch
from TwitchChannelPointsMiner.eranio import streak
from TwitchChannelPointsMiner.eranio.streak import Milestone, MissedStream
from TwitchChannelPointsMiner.eranio.streak_cache import migrate_old_cache
from TwitchChannelPointsMiner.WatchStreakCache import WatchStreakCache

T0 = 1_800_000_000.0
PRIORITY = [Priority.STREAK, Priority.ORDER]


class FakeClient:
    def __init__(self):
        self.milestones = {}
        self.created = {}
        self.reward_calls = []
        self.on_call = None

    def reward_list(self, channel_id):
        self.reward_calls.append(channel_id)
        if self.on_call is not None:
            self.on_call()
        return self.milestones.get(
            channel_id,
            Milestone(state="NONE", value=0, achievement_at=None, expires_at=None),
        )

    def stream_created_at(self, channel_id):
        return self.created.get(channel_id)


def make(login, bid="100", minutes=0, watch_streak=True, missing=True, online=True):
    stream = SimpleNamespace(
        broadcast_id=bid, minute_watched=minutes, watch_streak_missing=missing
    )
    return SimpleNamespace(
        username=login,
        channel_id=f"id-{login}",
        is_online=online,
        stream=stream,
        settings=SimpleNamespace(watch_streak=watch_streak),
    )


@pytest.fixture
def client():
    fake = FakeClient()
    streak.configure()
    streak.STATE.client = fake
    return fake


def run(streamers, now, watching=None, streams_watched=2, is_drop=None, priority=None):
    snapshot = list(streamers)
    index = list(range(len(snapshot)))
    result = streak.apply(
        SimpleNamespace(),
        snapshot,
        index[:streams_watched] if watching is None else watching,
        index,
        PRIORITY if priority is None else priority,
        streams_watched,
        is_drop or (lambda i: False),
        now,
    )
    return result


def done_milestone(at, value=1, expires=None):
    return Milestone(state="ACTIVE", value=value, achievement_at=at, expires_at=expires)


def test_none_channel_is_pending_and_watched(client):
    channel = make("neu")
    assert run([channel], T0) == [0]
    assert client.reward_calls == ["id-neu"]
    assert streak.is_pending(channel, T0 + 20) is True


def test_first_streak_without_event_is_confirmed_by_recheck(client):
    channel = make("neu", minutes=0)
    client.created["id-neu"] = T0
    assert run([channel], T0) == [0]
    channel.stream.minute_watched = 5
    client.milestones["id-neu"] = done_milestone(T0 + 270, value=1)
    assert run([channel], T0 + 300, watching=[]) == []
    assert channel.stream.watch_streak_missing is False
    assert streak.is_pending(channel, T0 + 320) is False


def test_recheck_is_rate_limited_and_waits_for_five_minutes(client):
    channel = make("neu")
    run([channel], T0)
    channel.stream.minute_watched = 2
    run([channel], T0 + 200)
    assert len(client.reward_calls) == 1
    channel.stream.minute_watched = 5
    run([channel], T0 + 301)
    run([channel], T0 + 320)
    assert len(client.reward_calls) == 2
    channel.stream.minute_watched = 8
    run([channel], T0 + 500)
    assert len(client.reward_calls) == 3


def test_done_channel_frees_slot_immediately(client):
    first, second = make("a"), make("b")
    assert run([first, second], T0, streams_watched=1) == [0]
    first.stream.watch_streak_missing = False
    assert run([first, second], T0 + 20, streams_watched=1) == [1]


def test_stuck_slot_case_streak_already_done_is_not_watched(client):
    shlorox = make("shlorox", missing=True)
    other = make("pyka")
    client.created["id-shlorox"] = T0 - 3600
    client.milestones["id-shlorox"] = done_milestone(T0 - 600, value=106)
    assert run([shlorox, other], T0, streams_watched=1) == [1]
    for step in range(1, 30):
        assert 0 not in run([shlorox, other], T0 + step * 600, streams_watched=1)
    assert Twitch._has_pending_watch_streak(shlorox) is False


def test_fan_out_respects_max_parallel(client):
    streamers = [make(f"c{i}") for i in range(5)]
    streak.configure(max_parallel=3)
    streak.STATE.client = client
    assert len(run(streamers, T0, streams_watched=2)) == 3
    streak.configure(max_parallel=None)
    streak.STATE.client = client
    assert len(run(streamers, T0, streams_watched=2)) == 2


def test_streak_length_ordering(client):
    streamers = [make("kurz"), make("lang"), make("mittel")]
    lengths = {"kurz": 3, "lang": 106, "mittel": 40}
    for streamer in streamers:
        client.milestones[streamer.channel_id] = Milestone(
            state="ACTIVE",
            value=lengths[streamer.username],
            achievement_at=T0 - 86400,
            expires_at=None,
        )
    streak.configure(requested_priority=[Priority.STREAK_LENGTH_DESCENDING])
    streak.STATE.client = client
    assert run(streamers, T0, watching=[], streams_watched=3) == [1, 2, 0]
    streak.configure(requested_priority=[Priority.STREAK_LENGTH_ASCENDING])
    streak.STATE.client = client
    assert run(streamers, T0 + 1, watching=[], streams_watched=3) == [0, 2, 1]


def test_expiring_streak_comes_first(client):
    soon, late = make("soon"), make("late")
    client.milestones["id-soon"] = Milestone("ACTIVE", 5, T0 - 86400, T0 + 3600)
    client.milestones["id-late"] = Milestone("ACTIVE", 50, T0 - 86400, T0 + 30 * 3600)
    streak.configure(requested_priority=[Priority.STREAK_LENGTH_DESCENDING])
    streak.STATE.client = client
    assert run([late, soon], T0, watching=[], streams_watched=1) == [1]


def test_logical_stream_is_reused_within_gap(client):
    channel = make("x", bid="100")
    client.created["id-x"] = T0
    run([channel], T0)
    channel.stream.watch_streak_missing = False
    run([channel], T0 + 20)
    channel.stream.broadcast_id = "200"
    channel.stream.watch_streak_missing = True
    channel.stream.minute_watched = 0
    assert run([channel], T0 + 20 + 600, watching=[]) == []
    assert len(client.reward_calls) == 1
    assert streak.STATE.tracks["x"].broadcast_ids == {"100", "200"}


def test_new_logical_stream_after_gap(client):
    channel = make("x", bid="100")
    run([channel], T0)
    channel.stream.watch_streak_missing = False
    run([channel], T0 + 20)
    channel.stream.broadcast_id = "200"
    channel.stream.watch_streak_missing = True
    channel.stream.minute_watched = 0
    assert run([channel], T0 + 20 + 3600) == [0]


def test_fallback_cap_gives_up_once_and_frees_slot(client, caplog):
    stuck, other = make("stuck"), make("other")
    client.created["id-stuck"] = T0
    run([stuck, other], T0, streams_watched=1)
    caplog.set_level(logging.INFO)
    for minute in range(5, 31, 5):
        stuck.stream.minute_watched = minute
        result = run([stuck, other], T0 + minute * 60, streams_watched=1)
    assert result == [1]
    gave_up = [r for r in caplog.records if "aufgegeben" in r.getMessage()]
    assert len(gave_up) == 1
    run([stuck, other], T0 + 3000, streams_watched=1)
    assert len([r for r in caplog.records if "aufgegeben" in r.getMessage()]) == 1


def test_cap_not_reached_before_thirty_minutes(client):
    stuck = make("stuck")
    for minute in (0, 10, 20, 29):
        stuck.stream.minute_watched = minute
        assert run([stuck], T0 + minute * 60) == [0]


def test_synthetic_broadcast_id_is_merged_after_restart(tmp_path, client):
    cache = WatchStreakCache.load(tmp_path / "cache.json", "acc")
    cache.ensure("x", "x:2026-11-20T10:00:00+00:00", started_at=T0 - 600)
    cache.mark_claimed("x", "x:2026-11-20T10:00:00+00:00", claimed_at=T0 - 300)
    streak.configure(cache=cache)
    streak.STATE.client = client
    channel = make("x", bid="555")
    cache.ensure("x", "555", started_at=T0)
    assert streak.is_pending(channel, T0) is False
    keys = [s.broadcast_id for s in cache._sessions.values()]
    assert keys == ["555"]
    assert cache.get("x", "555").claimed is True
    assert client.reward_calls == []


def test_suspended_missed_stream_logged_once_and_rescued_first(client, caplog):
    normal, rescue = make("normal"), make("rescue")
    client.milestones["id-rescue"] = Milestone(
        state="SUSPENDED",
        value=40,
        achievement_at=T0 - 5 * 86400,
        expires_at=T0 + 86400,
        missed=[
            MissedStream(T0 - 7200, T0 - 3600, "SUSPENDED", T0 + 86400),
            MissedStream(T0 - 90000, T0 - 86400, "RECOVERED", T0 + 86400),
        ],
    )
    caplog.set_level(logging.WARNING)
    assert run([normal, rescue], T0, watching=[], streams_watched=1) == [1]
    run([normal, rescue], T0 + 400, watching=[], streams_watched=1)
    run([normal, rescue], T0 + 800, watching=[], streams_watched=1)
    warnings = [
        r.getMessage() for r in caplog.records if "ausgesetzt" in r.getMessage()
    ]
    assert len(warnings) == 1
    assert "Streak bei rescue (40) ausgesetzt, verpasster Stream" in warnings[0]
    assert "retten bis" in warnings[0]


def test_missed_log_survives_restart(tmp_path, client, caplog):
    path = tmp_path / "missed.json"
    milestone = Milestone(
        "SUSPENDED",
        7,
        T0 - 86400 * 3,
        T0 + 86400,
        [MissedStream(T0 - 7200, T0 - 3600, "SUSPENDED", T0 + 86400)],
    )
    streak.configure(missed_path=str(path))
    streak.STATE.client = client
    client.milestones["id-r"] = milestone
    caplog.set_level(logging.WARNING)
    run([make("r")], T0)
    streak.configure(missed_path=str(path))
    streak.STATE.client = client
    run([make("r")], T0 + 5000)
    assert len([r for r in caplog.records if "ausgesetzt" in r.getMessage()]) == 1
    assert json.loads(path.read_text(encoding="utf-8"))


def test_snapshot_iteration_survives_list_mutation(client):
    live = CopyOnWriteList([make("a"), make("b"), make("c")])

    def mutate():
        live[:] = [make("a")]

    client.on_call = mutate
    snapshot = list(live)
    result = streak.apply(
        SimpleNamespace(), snapshot, [0, 1], [0, 1, 2], PRIORITY, 2, lambda i: False, T0
    )
    assert result == [0, 1]
    assert len(live) == 1


def test_old_cache_file_is_migrated(tmp_path):
    old = tmp_path / "old.json"
    old.write_text(
        json.dumps(
            {
                "version": 4,
                "sessions": [
                    {
                        "account_name": "Acc",
                        "streamer_login": "x",
                        "broadcast_id": "111",
                        "started_at": T0,
                        "attempts": 2,
                        "claimed": True,
                        "last_attempt_at": T0 + 300,
                        "ended_at": T0 + 9000,
                    },
                    {
                        "account_name": "acc",
                        "streamer_login": "x",
                        "broadcast_id": "x:2026-11-20T10:00:00+00:00",
                        "started_at": T0 + 100,
                        "claimed": False,
                        "ended_at": None,
                    },
                    {
                        "account_name": "other",
                        "streamer_login": "y",
                        "broadcast_id": "9",
                        "started_at": T0,
                    },
                ],
                "streamer_statuses": [
                    {
                        "account_name": "acc",
                        "streamer_login": "x",
                        "watch_streak_days": 12,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    cache = WatchStreakCache.load(tmp_path / ".state" / "new.json", "acc")
    count, lengths = migrate_old_cache(cache, str(old))
    assert count == 1
    assert lengths == {"x": 12}
    session = cache.get("x", "111")
    assert session.claimed is True and session.claimed_at == T0 + 300
    assert (tmp_path / ".state" / "new.json").exists()
    again, _ = migrate_old_cache(cache, str(old))
    assert again == 0
    reloaded = WatchStreakCache.load(tmp_path / ".state" / "new.json", "acc")
    assert reloaded.get("x", "111").claimed is True


def test_loan_lends_drop_slot_briefly_and_returns_it(client):
    streak.STATE.lend_drop_slot = True
    drop, a, b = make("drop", watch_streak=False), make("a"), make("b")
    streamers = [drop, a, b]
    is_drop = lambda i: i == 0
    first = run(streamers, T0, watching=[0, 1], streams_watched=2, is_drop=is_drop)
    assert first == [1, 2]
    info = streak.loan_info()
    assert info.active and info.login == "b" and info.max_seconds == 900
    later = run(
        streamers, T0 + 800, watching=[0, 1], streams_watched=2, is_drop=is_drop
    )
    assert 0 not in later
    after = run(
        streamers, T0 + 901, watching=[0, 1], streams_watched=2, is_drop=is_drop
    )
    assert 0 in after
    assert streak.loan_info().active is False


def test_loan_ends_immediately_when_streak_confirmed(client):
    streak.STATE.lend_drop_slot = True
    drop, a, b = make("drop", watch_streak=False), make("a"), make("b")
    streamers = [drop, a, b]
    is_drop = lambda i: i == 0
    run(streamers, T0, watching=[0, 1], streams_watched=2, is_drop=is_drop)
    assert streak.loan_info().active
    b.stream.watch_streak_missing = False
    result = run(
        streamers, T0 + 20, watching=[0, 1], streams_watched=2, is_drop=is_drop
    )
    assert 0 in result
    assert streak.loan_info().active is False


def test_only_one_loan_at_a_time_with_cooldown(client):
    streak.STATE.lend_drop_slot = True
    drop = make("drop", watch_streak=False)
    pending = [make(f"p{i}") for i in range(4)]
    streamers = [drop] + pending
    is_drop = lambda i: i == 0
    run(streamers, T0, watching=[0, 1], streams_watched=2, is_drop=is_drop)
    assert streak.loan_info().login == "p1"
    result = run(
        streamers, T0 + 100, watching=[0, 1], streams_watched=2, is_drop=is_drop
    )
    assert len(result) == 2 and 0 not in result
    run(streamers, T0 + 901, watching=[0, 1], streams_watched=2, is_drop=is_drop)
    assert streak.loan_info().active is False
    second = run(
        streamers, T0 + 1000, watching=[0, 1], streams_watched=2, is_drop=is_drop
    )
    assert 0 in second
    assert streak.loan_info().active is False
    run(streamers, T0 + 1600, watching=[0, 1], streams_watched=2, is_drop=is_drop)
    assert streak.loan_info().login == "p2"


def test_loan_never_blocks_drop_slot_for_unconfirmable_streak(client):
    streak.STATE.lend_drop_slot = True
    drop = make("drop", watch_streak=False)
    streamers = [drop, make("a"), make("b")]
    is_drop = lambda i: i == 0
    blocked_for = 0
    for step in range(0, 200):
        now = T0 + step * 60
        for channel in streamers[1:]:
            channel.stream.minute_watched = step
        result = run(
            streamers, now, watching=[0, 1], streams_watched=2, is_drop=is_drop
        )
        if 0 not in result:
            blocked_for += 1
    assert blocked_for <= 15 + 15


def test_unconfigured_state_keeps_base_behaviour():
    streak.STATE.reset()
    streamer = make("x")
    streamer.offline_at = -60
    streamer.stream.minute_watched = 0
    assert Twitch._has_pending_watch_streak(streamer, now=0) is False
    assert streak.apply(
        SimpleNamespace(), [streamer], [0], [0], PRIORITY, 2, lambda i: False
    ) == [0]


def test_minute_watcher_uses_streak_selection_with_fan_out(monkeypatch):
    from test_streams_watched import _run_one_watch_iteration, _watch_streamer

    fake = FakeClient()
    streak.configure(max_parallel=3)
    streak.STATE.client = fake
    streamers = [_watch_streamer(f"s{i}", watch_streak=True) for i in range(4)]
    for streamer in streamers:
        streamer.channel_id = f"id-{streamer.username}"
        streamer.stream.broadcast_id = "1"
    posted = _run_one_watch_iteration(
        monkeypatch,
        streamers,
        streams_watched=2,
        priority=[Priority.STREAK, Priority.ORDER],
    )
    assert len(posted) == 3
    streamers[0].stream.watch_streak_missing = False
    posted = _run_one_watch_iteration(
        monkeypatch,
        streamers,
        streams_watched=2,
        priority=[Priority.STREAK, Priority.ORDER],
    )
    assert "https://spade.test/s0" not in posted[:3]


def test_drop_stream_with_open_streak_keeps_its_drop_slot(client):
    streak.configure(max_parallel=2)
    streak.STATE.client = client
    streamers = [make("a"), make("b"), make("c"), make("lacy")]
    result = run(
        streamers,
        T0,
        watching=[3, 0, 1],
        streams_watched=3,
        is_drop=lambda i: i == 3,
    )
    assert 3 in result
    assert result.count(3) == 1
    assert len(result) == 3
