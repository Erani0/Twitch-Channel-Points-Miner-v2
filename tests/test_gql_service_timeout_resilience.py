import unittest
from unittest.mock import patch

from TwitchChannelPointsMiner.classes.Twitch import (
    REWARD_LIST_SERVICE_TIMEOUT_RETRY_ATTEMPTS,
    SUSTAINED_SERVICE_TIMEOUT_ESCALATION_SECONDS,
    SUSTAINED_SERVICE_TIMEOUT_GAP_SECONDS,
    Twitch,
)
from TwitchChannelPointsMiner.classes.entities.Streamer import Streamer


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


if __name__ == "__main__":
    unittest.main()
