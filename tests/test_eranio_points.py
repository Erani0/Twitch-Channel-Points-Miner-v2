import json
from types import SimpleNamespace

from TwitchChannelPointsMiner.classes import Twitch as twitch_module
from TwitchChannelPointsMiner.eranio import points


def streamer(name):
    return SimpleNamespace(username=name)


def test_unknown_channels_are_allowed_and_queued():
    assert points.has_points(streamer("Alpha"), now=100) is True
    assert points.STATE.pending == {"alpha"}


def test_channels_without_points_are_skipped_after_the_check():
    points.store(["alpha", "beta"], {"alpha": False, "beta": True}, now=100)
    assert points.has_points(streamer("alpha"), now=200) is False
    assert points.has_points(streamer("beta"), now=200) is True
    assert points.STATE.pending == set()


def test_a_known_result_is_checked_again_after_one_day():
    points.store(["alpha"], {"alpha": False}, now=0)
    later = points.KNOWN_SECONDS + 1
    assert points.has_points(streamer("alpha"), now=later) is False
    assert points.STATE.pending == {"alpha"}


def test_a_failed_check_waits_before_retrying():
    points.store(["alpha"], {}, now=100)
    assert points.has_points(streamer("alpha"), now=150) is True
    assert points.STATE.pending == set()
    assert points.has_points(streamer("alpha"), now=100 + points.RETRY_SECONDS)
    assert points.STATE.pending == {"alpha"}


def test_query_and_parse_use_one_alias_per_channel():
    query = points.build_query(["a", 'b"x'])
    assert 'u0: user(login: "a")' in query
    assert 'u1: user(login: "b\\"x")' in query
    payload = {
        "data": {
            "u0": {"channel": {"communityPointsSettings": {"isEnabled": False}}},
            "u1": None,
        }
    }
    assert points.parse(["a", "b"], payload) == {"a": False}
    assert points.parse(["a"], {"errors": []}) == {}


def test_fetch_sends_a_single_request(monkeypatch):
    sent = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "data": {
                    "u0": {"channel": {"communityPointsSettings": {"isEnabled": True}}}
                }
            }

    def post(url, json=None, headers=None, timeout=None):
        sent.append((url, json, headers))
        return Response()

    monkeypatch.setattr(points.requests, "post", post)
    assert points.fetch(["alpha"]) == {"alpha": True}
    assert len(sent) == 1 and sent[0][0] == points.GQL_URL


def test_disabled_channel_is_reported_once(caplog):
    caplog.set_level("DEBUG")
    points.store(["alpha"], {"alpha": False}, now=0)
    points.store(["alpha"], {"alpha": False}, now=1)
    assert caplog.text.count("alpha hat keine Kanalpunkte") == 1


def test_watch_selection_uses_the_points_check():
    import inspect

    text = inspect.getsource(twitch_module.Twitch.send_minute_watched_events)
    assert "eranio_points.has_points(streamers_snapshot[i])" in text
    json.dumps(points.STATE.enabled)


def test_batches_stay_within_the_twitch_alias_limit():
    assert points.BATCH_SIZE <= 15


def test_the_result_is_kept_for_a_day_and_survives_a_restart(tmp_path, monkeypatch):
    path = tmp_path / "check.json"
    monkeypatch.setattr(points, "cache_path", lambda: str(path))
    assert points.KNOWN_SECONDS == 24 * 3600
    points.store(["alpha", "beta"], {"alpha": False, "beta": True}, now=1000)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["kanaele"]["alpha"] == {"punkte": False, "geprueft": 1000}
    points.STATE.reset()
    assert points.has_points(streamer("alpha"), now=1000 + 23 * 3600) is False
    assert points.has_points(streamer("beta"), now=1000 + 23 * 3600) is True
    assert points.STATE.pending == set()
    points.STATE.reset()
    assert points.has_points(streamer("alpha"), now=1000 + 25 * 3600) is True
    assert points.STATE.pending == {"alpha"}


def test_a_broken_cache_file_is_ignored(tmp_path, monkeypatch):
    path = tmp_path / "check.json"
    path.write_text("kein json", encoding="utf-8")
    monkeypatch.setattr(points, "cache_path", lambda: str(path))
    assert points.has_points(streamer("alpha"), now=10) is True
    assert points.STATE.pending == {"alpha"}
