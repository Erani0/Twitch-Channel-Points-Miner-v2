import unittest
from types import SimpleNamespace

from TwitchChannelPointsMiner.classes.HlsWatcher import HlsWatcher, SEEN_LIMIT, playlist_entries
from TwitchChannelPointsMiner.classes.Twitch import Twitch

MASTER = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nhttps://cdn.example/high.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=2\nhttps://cdn.example/low.m3u8\n"


def media(*names):
    lines = ["#EXTM3U", "#EXT-X-TWITCH-PREFETCH:https://cdn.example/future.ts"]
    for name in names:
        lines += ["#EXTINF:2.000,live", name]
    return "\n".join(lines) + "\n"


class FakeTwitch:
    def __init__(self):
        self.playlists = [media("https://cdn.example/a.ts", "https://cdn.example/b.ts")]
        self.calls = []
        self.status = {}
        self.tokens = 0

    def fetch_token(self, streamer):
        self.tokens += 1
        return ("sig", "tok")

    def request(self, method, url, **kwargs):
        self.calls.append((method, url))
        if url in self.status:
            return SimpleNamespace(status_code=self.status[url], text="")
        if "usher.ttvnw.net" in url:
            return SimpleNamespace(status_code=200, text=MASTER)
        if url.endswith("low.m3u8"):
            text = self.playlists[0] if len(self.playlists) == 1 else self.playlists.pop(0)
            return SimpleNamespace(status_code=200, text=text)
        return SimpleNamespace(status_code=200, text="")

    def heads(self):
        return [url for method, url in self.calls if method == "HEAD"]


def streamer(name="kanal", broadcast="1", online=True):
    return SimpleNamespace(username=name, is_online=online, stream=SimpleNamespace(broadcast_id=broadcast))


def watcher(fake):
    return HlsWatcher(fake.fetch_token, fake.request, "UA", lambda: True)


class HlsWatcherTest(unittest.TestCase):
    def test_heads_every_new_segment_of_the_lowest_variant(self):
        fake = FakeTwitch()
        w = watcher(fake)
        w.set_target(streamer())
        self.assertEqual(w.tick(), 2)
        self.assertEqual(fake.heads(), ["https://cdn.example/a.ts", "https://cdn.example/b.ts"])
        self.assertIn(("GET", "https://cdn.example/low.m3u8"), fake.calls)
        self.assertNotIn("https://cdn.example/future.ts", fake.heads())

    def test_segments_are_requested_only_once(self):
        fake = FakeTwitch()
        fake.playlists = [
            media("https://cdn.example/a.ts", "https://cdn.example/b.ts"),
            media("https://cdn.example/b.ts", "https://cdn.example/c.ts"),
        ]
        w = watcher(fake)
        w.set_target(streamer())
        w.tick()
        self.assertEqual(w.tick(), 1)
        self.assertEqual(fake.heads().count("https://cdn.example/b.ts"), 1)
        self.assertEqual(fake.tokens, 1)
        self.assertEqual(w.segments_sent, 3)

    def test_relative_segment_urls_are_resolved(self):
        self.assertEqual(
            playlist_entries(media("seg/1.ts"), "https://cdn.example/v1/low.m3u8"),
            ["https://cdn.example/v1/seg/1.ts"],
        )

    def test_no_target_or_offline_sends_nothing(self):
        fake = FakeTwitch()
        w = watcher(fake)
        self.assertEqual(w.tick(), 0)
        w.set_target(streamer(online=False))
        self.assertEqual(w.tick(), 0)
        self.assertEqual(fake.calls, [])

    def test_expired_playlist_fetches_a_new_token(self):
        fake = FakeTwitch()
        w = watcher(fake)
        w.set_target(streamer())
        w.tick()
        fake.status["https://cdn.example/low.m3u8"] = 403
        self.assertEqual(w.tick(), 0)
        del fake.status["https://cdn.example/low.m3u8"]
        w.tick()
        self.assertEqual(fake.tokens, 2)

    def test_failed_head_is_retried_next_time(self):
        fake = FakeTwitch()
        fake.status["https://cdn.example/a.ts"] = 404
        w = watcher(fake)
        w.set_target(streamer())
        self.assertEqual(w.tick(), 1)
        del fake.status["https://cdn.example/a.ts"]
        self.assertEqual(w.tick(), 1)

    def test_new_channel_or_broadcast_starts_fresh(self):
        fake = FakeTwitch()
        w = watcher(fake)
        w.set_target(streamer("eins"))
        w.tick()
        w.set_target(streamer("zwei"))
        self.assertEqual(w.tick(), 2)
        self.assertEqual(w.target_login, "zwei")
        w.set_target(streamer("zwei", broadcast="2"))
        self.assertEqual(w.tick(), 2)
        self.assertEqual(fake.tokens, 3)

    def test_missing_token_or_failing_requests_do_not_raise(self):
        fake = FakeTwitch()
        w = HlsWatcher(lambda s: None, fake.request, "UA", lambda: True)
        w.set_target(streamer())
        self.assertEqual(w.tick(), 0)

        def boom(*args, **kwargs):
            raise ConnectionError("weg")

        w = HlsWatcher(fake.fetch_token, boom, "UA", lambda: True)
        w.set_target(streamer())
        self.assertEqual(w.tick(), 0)

    def test_seen_list_stays_bounded(self):
        fake = FakeTwitch()
        fake.playlists = [media(*[f"https://cdn.example/{i}.ts" for i in range(SEEN_LIMIT + 50)])]
        w = watcher(fake)
        w.set_target(streamer())
        w.tick()
        self.assertEqual(len(w._seen), SEEN_LIMIT)

    def test_run_stops_when_miner_stops(self):
        fake = FakeTwitch()
        state = {"n": 0}

        def running():
            state["n"] += 1
            return state["n"] <= 2

        w = HlsWatcher(fake.fetch_token, fake.request, "UA", running, sleep=lambda s: None)
        w.set_target(streamer())
        w.run()
        self.assertEqual(state["n"], 3)


class HlsTargetTest(unittest.TestCase):
    def make(self, name, auto=False, drops=False):
        return SimpleNamespace(username=name, is_auto_drop_channel=auto, drops_condition=lambda: drops)

    def test_auto_drop_channel_wins(self):
        streamers = [self.make("a", drops=True), self.make("b", auto=True)]
        self.assertEqual(Twitch._hls_target(streamers, [0, 1]).username, "b")

    def test_falls_back_to_a_watched_channel_with_drops(self):
        streamers = [self.make("a"), self.make("b", drops=True)]
        self.assertEqual(Twitch._hls_target(streamers, [0, 1]).username, "b")

    def test_none_without_drops(self):
        streamers = [self.make("a"), self.make("b")]
        self.assertIsNone(Twitch._hls_target(streamers, [0, 1]))
        self.assertIsNone(Twitch._hls_target(streamers, []))


if __name__ == "__main__":
    unittest.main()
