from types import SimpleNamespace

import pytest

from TwitchChannelPointsMiner.classes.Settings import Settings
from TwitchChannelPointsMiner.logger import LoggingFormat


@pytest.fixture(autouse=True)
def configured_logger():
    """Entities expect the application to have initialized Settings.logger."""
    previous = getattr(Settings, "logger", None)
    Settings.logger = SimpleNamespace(less=False, console_format=LoggingFormat.TEXT)
    yield
    Settings.logger = previous


@pytest.fixture(autouse=True)
def reset_eranio_streak_state():
    from TwitchChannelPointsMiner.eranio import streak

    from TwitchChannelPointsMiner.eranio import drops, quests, selfcheck

    streak.STATE.reset()
    drops.STATE.reset()
    quests.STATE.reset()
    selfcheck.STATE.reset()
    yield
    streak.STATE.reset()
    drops.STATE.reset()
    quests.STATE.reset()
    selfcheck.STATE.reset()


@pytest.fixture(autouse=True)
def offline_eranio_points(monkeypatch):
    from TwitchChannelPointsMiner.eranio import points

    points.STATE.reset()
    monkeypatch.setattr(points, "_ensure_worker", lambda: None)
    monkeypatch.setattr(points, "cache_path", lambda: None)
    yield
    points.STATE.reset()


@pytest.fixture(autouse=True)
def _reset_eranio_quiet_filter():
    yield
    import logging as _logging

    from TwitchChannelPointsMiner.eranio import quiet as _quiet

    _target = _logging.getLogger(_quiet.LOGGER_NAME)
    for _f in list(_target.filters):
        if isinstance(_f, _quiet.DemoteNoisyInfo):
            _target.removeFilter(_f)
