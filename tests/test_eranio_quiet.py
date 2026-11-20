import logging

from TwitchChannelPointsMiner.eranio import quiet


def make(func, message, level=logging.INFO):
    return logging.LogRecord(
        quiet.LOGGER_NAME, level, "x", 1, message, None, None, func
    )


def test_noisy_info_lines_become_debug():
    f = quiet.DemoteNoisyInfo()
    record = make("__active_incomplete_drop_deadline", "Enough time")
    assert f.filter(record) is True
    assert record.levelno == logging.DEBUG
    record = make("send_minute_watched_events", "Campaign: x")
    f.filter(record)
    assert record.levelno == logging.DEBUG


def test_other_lines_stay_unchanged():
    f = quiet.DemoteNoisyInfo()
    record = make("send_minute_watched_events", "Claim drop")
    f.filter(record)
    assert record.levelno == logging.INFO
    record = make("__log_category", "kaputt", logging.WARNING)
    f.filter(record)
    assert record.levelno == logging.WARNING


def test_install_adds_the_filter_once():
    quiet.install()
    quiet.install()
    target = logging.getLogger(quiet.LOGGER_NAME)
    assert sum(isinstance(x, quiet.DemoteNoisyInfo) for x in target.filters) == 1
