import time
import unittest
from unittest.mock import patch

from TwitchChannelPointsMiner.classes.Twitch import (
    ActiveWatchStreakAttempt,
    REWARD_LIST_SERVICE_TIMEOUT_RETRY_ATTEMPTS,
    SUSTAINED_SERVICE_TIMEOUT_ESCALATION_SECONDS,
    SUSTAINED_SERVICE_TIMEOUT_GAP_SECONDS,
    Twitch,
)
from TwitchChannelPointsMiner.classes.entities.Streamer import Streamer
from TwitchChannelPointsMiner.WatchStreakCache import (
    MAX_STREAK_ATTEMPTS_PER_BROADCAST,
    WatchStreakCache,
)


def service_timeout_response():
    return {"errors": [{"message": "service timeout"}]}


def ok_response():
    return {"data": {"channel": {"self": {"watchStreakMilestone": None}}}}


class RewardListRetryTest(unittest.TestCase):
    def _make_streamer(self):
        streamer = Streamer("teststreamer")
        streamer.channel_id = "12345"
        return streamer

    def test_retries_after_service_timeout_and_succeeds(self):
        twitch = Twitch("test", "ua")
        streamer = self._make_streamer()
        responses = [service_timeout_response(), service_timeout_response(), ok_response()]

        with patch.object(Twitch, "post_gql_request", side_effect=responses) as mocked, \
                patch("TwitchChannelPointsMiner.classes.Twitch.time.sleep") as mocked_sleep:
            result = twitch._get_reward_list_response(streamer)

        self.assertEqual(mocked.call_count, 3)
        self.assertEqual(mocked_sleep.call_count, 2)
        self.assertEqual(result, ok_response())

    def test_does_not_retry_forever(self):
        twitch = Twitch("test", "ua")
        streamer = self._make_streamer()

        with patch.object(
            Twitch, "post_gql_request", side_effect=lambda *_: service_timeout_response()
        ) as mocked, patch("TwitchChannelPointsMiner.classes.Twitch.time.sleep"):
            result = twitch._get_reward_list_response(streamer)

        self.assertEqual(mocked.call_count, REWARD_LIST_SERVICE_TIMEOUT_RETRY_ATTEMPTS)
        self.assertEqual(result, service_timeout_response())

    def test_no_retry_needed_on_first_success(self):
        twitch = Twitch("test", "ua")
        streamer = self._make_streamer()

        with patch.object(Twitch, "post_gql_request", return_value=ok_response()) as mocked, \
                patch("TwitchChannelPointsMiner.classes.Twitch.time.sleep") as mocked_sleep:
            result = twitch._get_reward_list_response(streamer)

        self.assertEqual(mocked.call_count, 1)
        mocked_sleep.assert_not_called()
        self.assertEqual(result, ok_response())


class SustainedServiceTimeoutEscalationTest(unittest.TestCase):
    def test_escalates_to_warning_after_sustained_duration(self):
        # Simulate periodic calls (e.g. one per streamer cycle) well within the gap
        # window, so this reads as one continuous incident rather than separate ones.
        twitch = Twitch("test", "ua")
        start = 1_000_000.0
        step = 60  # seconds between calls, well under SUSTAINED_SERVICE_TIMEOUT_GAP_SECONDS

        elapsed = 0
        with patch("TwitchChannelPointsMiner.classes.Twitch.logger") as mocked_logger:
            while elapsed < SUSTAINED_SERVICE_TIMEOUT_ESCALATION_SECONDS:
                with patch(
                    "TwitchChannelPointsMiner.classes.Twitch.time.time",
                    return_value=start + elapsed,
                ):
                    twitch._log_gql_errors("RewardList", service_timeout_response())
                elapsed += step
            mocked_logger.warning.assert_not_called()

            with patch(
                "TwitchChannelPointsMiner.classes.Twitch.time.time",
                return_value=start + elapsed,
            ):
                twitch._log_gql_errors("RewardList", service_timeout_response())
            mocked_logger.warning.assert_called_once()

    def test_only_escalates_once_per_incident(self):
        twitch = Twitch("test", "ua")
        start = 2_000_000.0
        step = 60
        past_threshold_at = start + SUSTAINED_SERVICE_TIMEOUT_ESCALATION_SECONDS + step

        with patch("TwitchChannelPointsMiner.classes.Twitch.logger") as mocked_logger:
            elapsed = 0
            while start + elapsed <= past_threshold_at:
                with patch(
                    "TwitchChannelPointsMiner.classes.Twitch.time.time",
                    return_value=start + elapsed,
                ):
                    twitch._log_gql_errors("RewardList", service_timeout_response())
                elapsed += step
            mocked_logger.warning.assert_called_once()

            with patch(
                "TwitchChannelPointsMiner.classes.Twitch.time.time",
                return_value=start + elapsed,
            ):
                twitch._log_gql_errors("RewardList", service_timeout_response())
            mocked_logger.warning.assert_called_once()  # still just the one call, no repeat

    def test_gap_starts_a_fresh_incident(self):
        twitch = Twitch("test", "ua")
        start = 3_000_000.0

        with patch("TwitchChannelPointsMiner.classes.Twitch.time.time", return_value=start):
            twitch._log_gql_errors("RewardList", service_timeout_response())

        after_gap = start + SUSTAINED_SERVICE_TIMEOUT_GAP_SECONDS + 1
        with patch("TwitchChannelPointsMiner.classes.Twitch.time.time", return_value=after_gap):
            twitch._log_gql_errors("RewardList", service_timeout_response())

        incident = twitch._suppressed_service_timeout_incidents["RewardList"]
        self.assertEqual(incident["since"], after_gap, "a big gap should reset the clock")

    def test_successful_response_clears_the_incident(self):
        twitch = Twitch("test", "ua")
        start = 4_000_000.0

        with patch("TwitchChannelPointsMiner.classes.Twitch.time.time", return_value=start):
            twitch._log_gql_errors("RewardList", service_timeout_response())
        self.assertIn("RewardList", twitch._suppressed_service_timeout_incidents)

        twitch._log_gql_errors("RewardList", ok_response())
        self.assertNotIn("RewardList", twitch._suppressed_service_timeout_incidents)


class StreakAttemptOutageExtensionTest(unittest.TestCase):
    def _make_streamer(self, username: str, broadcast_id: str, online_at: float) -> Streamer:
        streamer = Streamer(username)
        streamer.is_online = True
        streamer.online_at = online_at
        streamer.stream.broadcast_id = broadcast_id
        streamer.stream.watch_streak_missing = True
        return streamer

    def _pending_attempt_setup(self):
        twitch = Twitch("outage-test", "ua")
        twitch.watch_streak_cache = WatchStreakCache(default_account_name="outage-test")
        now = time.time()
        streamer = self._make_streamer("streamer", "broadcast-1", online_at=now - 120)

        session = twitch.watch_streak_cache.ensure_session(
            streamer.username,
            streamer.stream.broadcast_id,
            started_at=now - 120,
            account_name=twitch.account_username,
        )
        attempt = ActiveWatchStreakAttempt(
            session_key=session.key(),
            streamer=streamer.username,
            broadcast_id=streamer.stream.broadcast_id,
            # Already past the attempt timeout, so cleanup must decide: consume or extend.
            started_at=now - twitch.streak_attempt_timeout_seconds - 1,
            watch_counter_at_start=0,
        )
        twitch._active_streak_attempts[attempt.session_key] = attempt
        return twitch, streamer, session, now

    def test_attempt_is_extended_not_consumed_during_active_outage(self):
        twitch, streamer, session, now = self._pending_attempt_setup()
        twitch._suppressed_service_timeout_incidents["RewardList"] = {
            "since": now - 600,
            "last": now - 5,  # still ongoing
            "escalated": True,
        }

        twitch._cleanup_streak_attempts([streamer], now)

        updated = twitch.watch_streak_cache.get_session(
            streamer.username, streamer.stream.broadcast_id, account_name=twitch.account_username
        )
        self.assertEqual(updated.attempts, 0, "outage must not burn an attempt")
        self.assertIsNone(updated.ended_at, "session must stay open while streamer is online")
        self.assertIn(session.key(), twitch._active_streak_attempts)
        self.assertEqual(
            twitch._active_streak_attempts[session.key()].started_at,
            now,
            "the attempt clock should reset so it doesn't immediately re-timeout",
        )

    def test_attempt_is_consumed_normally_without_an_outage(self):
        twitch, streamer, session, now = self._pending_attempt_setup()
        # No entry in _suppressed_service_timeout_incidents - normal conditions.

        twitch._cleanup_streak_attempts([streamer], now)

        updated = twitch.watch_streak_cache.get_session(
            streamer.username, streamer.stream.broadcast_id, account_name=twitch.account_username
        )
        self.assertEqual(updated.attempts, 1)
        self.assertIsNone(updated.ended_at, "one attempt alone must not exhaust a 5-attempt budget")

    def test_stale_outage_record_does_not_extend(self):
        twitch, streamer, session, now = self._pending_attempt_setup()
        twitch._suppressed_service_timeout_incidents["RewardList"] = {
            "since": now - 900,
            "last": now - (SUSTAINED_SERVICE_TIMEOUT_GAP_SECONDS + 10),  # long over, incident is stale
            "escalated": True,
        }

        twitch._cleanup_streak_attempts([streamer], now)

        updated = twitch.watch_streak_cache.get_session(
            streamer.username, streamer.stream.broadcast_id, account_name=twitch.account_username
        )
        self.assertEqual(updated.attempts, 1, "a stale/ended incident must not keep extending attempts")

    def test_max_attempts_per_broadcast_is_five(self):
        self.assertEqual(MAX_STREAK_ATTEMPTS_PER_BROADCAST, 5)

    def test_session_only_exhausts_after_five_attempts_without_outage(self):
        twitch, streamer, session, now = self._pending_attempt_setup()

        # mark_attempt() releases the slot back for the selection logic to pick up
        # again later (it doesn't re-add to _active_streak_attempts itself), so each
        # round here re-creates a fresh attempt the way _select_streak_streamers would.
        for i in range(MAX_STREAK_ATTEMPTS_PER_BROADCAST):
            elapsed_now = now + i * (twitch.streak_attempt_timeout_seconds + 1)
            twitch._active_streak_attempts[session.key()] = ActiveWatchStreakAttempt(
                session_key=session.key(),
                streamer=streamer.username,
                broadcast_id=streamer.stream.broadcast_id,
                started_at=elapsed_now - twitch.streak_attempt_timeout_seconds - 1,
                watch_counter_at_start=0,
            )
            twitch._cleanup_streak_attempts([streamer], elapsed_now)

        updated = twitch.watch_streak_cache.get_session(
            streamer.username, streamer.stream.broadcast_id, account_name=twitch.account_username
        )
        self.assertEqual(updated.attempts, MAX_STREAK_ATTEMPTS_PER_BROADCAST)
        self.assertIsNotNone(updated.ended_at, "must exhaust once the 5-attempt budget is used up")


if __name__ == "__main__":
    unittest.main()
