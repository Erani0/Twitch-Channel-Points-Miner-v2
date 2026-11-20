import logging

from TwitchChannelPointsMiner.eranio import quiet


def make(func, message, level=logging.INFO):
    return logging.LogRecord(
        quiet.LOGGER_NAME, level, "x", 1, message, None, None, func
    )


def test_noisy_info_lines_are_dropped():
    f = quiet.DemoteNoisyInfo()
    assert f.filter(make("__active_incomplete_drop_deadline", "Enough time")) is False
    assert f.filter(make("send_minute_watched_events", "Campaign: x")) is False


def test_other_lines_stay_unchanged():
    f = quiet.DemoteNoisyInfo()
    assert f.filter(make("send_minute_watched_events", "Claim drop")) is True
    assert f.filter(make("__log_category", "kaputt", logging.WARNING)) is True


def test_install_adds_the_filter_once():
    quiet.install()
    quiet.install()
    target = logging.getLogger(quiet.LOGGER_NAME)
    assert sum(isinstance(x, quiet.DemoteNoisyInfo) for x in target.filters) == 1
