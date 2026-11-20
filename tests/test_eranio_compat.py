import importlib
import inspect
import logging
import os
import pickle
import runpy
import signal
import socket
import sys
import threading
from pathlib import Path

import pytest
from colorama import Fore

import TwitchChannelPointsMiner as package
from TwitchChannelPointsMiner.classes.Chat import ChatPresence
from TwitchChannelPointsMiner.classes.entities.Bet import (
    BetSettings,
    Condition,
    DelayMode,
    FilterCondition,
    OutcomeKeys,
    Strategy,
)
from TwitchChannelPointsMiner.classes.entities.Streamer import (
    Streamer,
    StreamerSettings,
)
from TwitchChannelPointsMiner.classes.Settings import (
    Events,
    FollowersOrder,
    Priority,
    Settings,
)
from TwitchChannelPointsMiner.classes.Twitch import Twitch
from TwitchChannelPointsMiner.eranio import compat
from TwitchChannelPointsMiner.eranio.git_config import dedupe_git_safe_directories
from TwitchChannelPointsMiner.logger import ColorPalette, LoggerSettings

miner_module = importlib.import_module(
    "TwitchChannelPointsMiner.TwitchChannelPointsMiner"
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(socket, "gethostbyname", lambda host: "127.0.0.1")
    monkeypatch.setattr(miner_module, "check_versions", lambda: ("3.22.0", "3.22.0"))
    root_logger = logging.getLogger()
    handlers = set(root_logger.handlers)
    level = root_logger.level
    signals = (signal.SIGINT, signal.SIGSEGV, signal.SIGTERM)
    previous = {sign: signal.getsignal(sign) for sign in signals}
    created = []
    names = set(Settings.__slots__) | {
        "analytics_path",
        "config_path",
        "latest_release_version",
        "update_instructions",
    }
    missing = object()
    saved = {name: Settings.__dict__.get(name, missing) for name in names}
    yield tmp_path, created
    for name, value in saved.items():
        if value is missing:
            if name in Settings.__dict__ and name not in Settings.__slots__:
                delattr(Settings, name)
            elif name in Settings.__slots__ and not hasattr(Settings.__dict__.get(name), "__get__"):
                pass
        else:
            setattr(Settings, name, value)
    for miner in created:
        try:
            miner.queue_listener.stop()
            for handler in miner.queue_listener.handlers:
                handler.close()
        except Exception:
            pass
    for handler in set(root_logger.handlers) - handlers:
        root_logger.removeHandler(handler)
        handler.close()
    root_logger.setLevel(level)
    for sign, handler in previous.items():
        signal.signal(sign, handler)


def owner_options():
    return dict(
        auto_discover_drops=True,
        watch_streak_min_offline_seconds=1800,
        username="someone",
        password="",
        claim_drops_startup=True,
        priority=[Priority.STREAK, Priority.DROPS, Priority.ORDER],
        enable_analytics=True,
        disable_ssl_cert_verification=False,
        disable_at_in_nickname=True,
        watch_only_drops=False,
        stop_watch_when_drops_completed=False,
        watch_streak_max_parallel=4,
        use_hermes=True,
        logger_settings=LoggerSettings(
            save=False,
            console_level=logging.INFO,
            console_username=False,
            auto_clear=True,
            time_zone="Europe/Berlin",
            file_level=logging.INFO,
            emoji=True,
            less=False,
            colored=True,
            color_palette=ColorPalette(
                STREAMER_online="GREEN",
                streamer_offline="red",
                BET_wiN=Fore.MAGENTA,
                SUBSCRIPTION="CYAN",
            ),
        ),
        streamer_settings=StreamerSettings(
            make_predictions=False,
            follow_raid=True,
            claim_drops=True,
            claim_moments=True,
            watch_streak=True,
            chat=ChatPresence.ONLINE,
            bet=BetSettings(
                strategy=Strategy.SMART,
                percentage=5,
                percentage_gap=20,
                max_points=50000,
                stealth_mode=True,
                delay_mode=DelayMode.FROM_END,
                delay=6,
                minimum_points=20000,
                filter_condition=FilterCondition(
                    by=OutcomeKeys.TOTAL_USERS, where=Condition.LTE, value=800
                ),
            ),
        ),
    )


def test_package_exports_the_compatible_class():
    assert package.TwitchChannelPointsMiner is compat.TwitchChannelPointsMiner
    assert issubclass(
        compat.TwitchChannelPointsMiner, miner_module.TwitchChannelPointsMiner
    )


def test_priority_and_event_names_of_the_old_version_exist():
    for name in (
        "ORDER",
        "STREAK",
        "FAVORITE",
        "DROPS",
        "SUBSCRIBED",
        "POINTS_ASCENDING",
        "POINTS_DESCENDING",
        "STREAK_LENGTH_ASCENDING",
        "STREAK_LENGTH_DESCENDING",
    ):
        assert hasattr(Priority, name)
    assert Priority.STREAK_LENGTH_ASCENDING is not Priority.STREAK
    assert hasattr(Events, "SUBSCRIPTION")
    assert hasattr(FollowersOrder, "ASC") and hasattr(FollowersOrder, "DESC")


def test_old_run_py_imports_resolve():
    from TwitchChannelPointsMiner.classes.Discord import Discord
    from TwitchChannelPointsMiner.classes.Telegram import Telegram

    assert Discord and Telegram


def test_priority_normalization_maps_streak_length_to_streak():
    assert compat.normalize_priority(None) is None
    assert compat.normalize_priority(
        [Priority.STREAK_LENGTH_DESCENDING, Priority.DROPS, Priority.ORDER]
    ) == [Priority.STREAK, Priority.DROPS, Priority.ORDER]
    assert compat.normalize_priority(
        [Priority.STREAK, Priority.STREAK_LENGTH_ASCENDING]
    ) == [Priority.STREAK]
    assert compat.normalize_priority(Priority.STREAK_LENGTH_ASCENDING) == [
        Priority.STREAK
    ]


def test_miner_builds_with_the_owners_full_option_set(workdir, caplog):
    tmp_path, created = workdir
    with caplog.at_level(logging.INFO):
        miner = package.TwitchChannelPointsMiner(**owner_options())
    created.append(miner)

    assert miner.username == "someone"
    assert miner.auto_discover_drops is True
    assert miner.watch_only_drops is False
    assert miner.stop_watch_when_drops_completed is False
    assert miner.watch_streak_max_parallel == 4
    assert miner.watch_streak_min_offline_seconds == 1800
    assert miner.use_hermes is True
    assert miner.claim_drops_startup is True
    assert miner.priority == [Priority.STREAK, Priority.DROPS, Priority.ORDER]
    assert miner.update_check_enabled is False
    assert (tmp_path / "analytics" / "someone").is_dir()
    messages = [record.getMessage() for record in caplog.records]
    assert "The classic event connection (PubSub) is used." in messages


def test_streak_length_priorities_are_accepted_and_logged(workdir, caplog):
    _, created = workdir
    options = owner_options()
    options["priority"] = [Priority.STREAK_LENGTH_DESCENDING, Priority.ORDER]
    with caplog.at_level(logging.INFO):
        miner = package.TwitchChannelPointsMiner(**options)
    created.append(miner)
    assert miner.priority == [Priority.STREAK, Priority.ORDER]
    assert miner.requested_priority == [
        Priority.STREAK_LENGTH_DESCENDING,
        Priority.ORDER,
    ]
    assert any("STREAK_LENGTH" in record.getMessage() for record in caplog.records)


def test_minimal_construction_and_v3_options(workdir):
    _, created = workdir
    miner = package.TwitchChannelPointsMiner(
        "someone",
        logger_settings=LoggerSettings(save=False),
        streams_watched=1,
    )
    created.append(miner)
    assert miner.streams_watched == 1
    assert miner.watch_streak_max_parallel is None
    assert miner.watch_streak_min_offline_seconds == 1800
    assert miner.priority == [Priority.STREAK, Priority.DROPS, Priority.ORDER]


def test_old_constructor_parameter_names_and_order_are_kept():
    parameters = list(inspect.signature(compat.TwitchChannelPointsMiner.__init__).parameters)
    old = [
        "username",
        "password",
        "claim_drops_startup",
        "enable_analytics",
        "disable_ssl_cert_verification",
        "disable_at_in_nickname",
        "watch_only_drops",
        "stop_watch_when_drops_completed",
        "auto_discover_drops",
        "priority",
        "logger_settings",
        "streamer_settings",
        "watch_streak_max_parallel",
        "watch_streak_min_offline_seconds",
        "use_hermes",
    ]
    assert [name for name in parameters if name in old] == old


def test_analytics_accepts_the_old_keywords(workdir, monkeypatch):
    _, created = workdir
    from TwitchChannelPointsMiner.classes import AnalyticsServer as server_module

    started = []
    monkeypatch.setattr(
        server_module.AnalyticsServer, "start", lambda self: started.append(self)
    )
    miner = package.TwitchChannelPointsMiner(**owner_options())
    created.append(miner)
    miner.analytics(host="0.0.0.0", port=5000, refresh=5, days_ago=360)
    assert len(started) == 1
    assert started[0].host == "0.0.0.0"
    miner.analytics(host="127.0.0.1", port=5001)
    miner.analytics(host="0.0.0.0", port=5002, password="secret")
    assert [server.port for server in started] == [5000, 5001, 5002]
    assert started[2].password == "secret"


def test_mine_accepts_the_old_keywords(workdir, monkeypatch):
    _, created = workdir
    miner = package.TwitchChannelPointsMiner(**owner_options())
    created.append(miner)
    seen = {}
    monkeypatch.setattr(miner, "run", lambda **kwargs: seen.update(kwargs))
    streamers = [Streamer("x", settings=StreamerSettings(make_predictions=False))]
    miner.mine(
        streamers,
        followers=True,
        followers_order=FollowersOrder.ASC,
        watch_only_drops=True,
        stop_watch_when_drops_completed=True,
        blacklist=["bad"],
    )
    assert seen["streamers"] == streamers
    assert seen["blacklist"] == ["bad"]
    assert seen["followers"] is True
    assert seen["followers_order"] is FollowersOrder.ASC
    assert "watch_only_drops" not in seen
    assert miner.watch_only_drops is True
    assert miner.stop_watch_when_drops_completed is True
    miner.mine(None, None)
    assert seen["streamers"] == []
    assert seen["blacklist"] == []
    miner.mine(["a", "b"])
    assert seen["streamers"] == ["a", "b"]


def old_pickle_cookies():
    return [
        {"name": "auth-token", "value": "tokentoken"},
        {"name": "persistent", "value": "12345%3Aabc"},
        {"name": "unique_id", "value": None},
    ]


def test_existing_pickle_cookie_file_is_read_without_new_login(workdir, monkeypatch):
    tmp_path, created = workdir
    miner = package.TwitchChannelPointsMiner(**owner_options())
    created.append(miner)
    cookies_file = Path(miner.twitch.cookies_file)
    assert cookies_file == tmp_path / "cookies" / "someone.pkl"
    with open(cookies_file, "wb") as handle:
        pickle.dump(old_pickle_cookies(), handle)

    flows = []
    from TwitchChannelPointsMiner.classes.TwitchLogin import TwitchLogin

    monkeypatch.setattr(
        TwitchLogin, "login_flow", lambda self: flows.append(1) or True
    )
    monkeypatch.setattr(Twitch, "update_client_version", lambda self: None)
    miner.twitch.login()

    assert flows == []
    assert miner.twitch.twitch_login.get_auth_token() == "tokentoken"
    assert miner.twitch.twitch_login.get_user_id() == 12345
    assert cookies_file.read_text(encoding="utf-8").startswith("[")


def test_pickle_cookie_with_foreign_objects_is_refused(workdir):
    from TwitchChannelPointsMiner.classes.Exceptions import WrongCookiesException

    _, created = workdir
    miner = package.TwitchChannelPointsMiner(**owner_options())
    created.append(miner)
    cookies_file = Path(miner.twitch.cookies_file)
    with open(cookies_file, "wb") as handle:
        pickle.dump([{"name": "a", "value": threading.Lock}], handle)
    with pytest.raises(WrongCookiesException):
        miner.twitch.twitch_login.load_cookies(str(cookies_file))


def test_git_safe_directory_entries_are_deduplicated(tmp_path):
    config = tmp_path / ".gitconfig"
    config.write_text(
        "[user]\n\tname = a\n[safe]\n\tdirectory = /home/container\n"
        "\tdirectory = /home/container\n\tdirectory = /other\n"
        "\tdirectory = /home/container\n",
        encoding="utf-8",
    )
    assert dedupe_git_safe_directories(str(config)) is True
    text = config.read_text(encoding="utf-8")
    assert text.count("/home/container") == 1
    assert "/other" in text and "name = a" in text
    assert dedupe_git_safe_directories(str(config)) is False
    assert dedupe_git_safe_directories(str(tmp_path / "missing")) is False


def test_dedupe_runs_from_the_constructor(workdir, monkeypatch):
    _, created = workdir
    calls = []
    monkeypatch.setattr(compat, "dedupe_git_safe_directories", lambda: calls.append(1))
    miner = package.TwitchChannelPointsMiner(
        "someone", logger_settings=LoggerSettings(save=False)
    )
    created.append(miner)
    assert calls == [1]


def test_run_config_migration_module_keeps_working_for_old_run_py(tmp_path):
    from TwitchChannelPointsMiner.run_config_migration import (
        discover_new_constructor_kwargs,
        ensure_constructor_kwargs,
    )

    discovered = discover_new_constructor_kwargs(package.TwitchChannelPointsMiner)
    assert discovered["use_hermes"] == "True"
    run_file = tmp_path / "run.py"
    run_file.write_text(
        "miner = TwitchChannelPointsMiner(\n    username='a',\n    use_hermes=True,\n)\n",
        encoding="utf-8",
    )
    changed = ensure_constructor_kwargs(
        str(run_file), "TwitchChannelPointsMiner", discovered
    )
    assert changed is True
    patched = run_file.read_text(encoding="utf-8")
    compile(patched, "run.py", "exec")
    assert "auto_discover_drops=False" in patched
    assert (
        ensure_constructor_kwargs(str(run_file), "TwitchChannelPointsMiner", discovered)
        is False
    )


class StoppedAtLogin(Exception):
    pass


class Exited(BaseException):
    pass


def test_egg_template_run_py_starts_up_to_the_login(workdir, monkeypatch):
    tmp_path, created = workdir
    script = tmp_path / "run.py"
    script.write_text(
        (FIXTURES / "eranio_egg_run.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.setenv("TWITCH_USER", "someone")
    monkeypatch.setenv("TWITCH_PASS", "")
    monkeypatch.setattr(sys, "argv", [str(script), "--port", "5999"])
    from TwitchChannelPointsMiner.classes import AnalyticsServer as server_module

    monkeypatch.setattr(server_module.AnalyticsServer, "start", lambda self: None)
    logins = []

    def fake_login(self):
        logins.append(self.cookies_file)
        raise StoppedAtLogin()

    def fake_exit():
        raise Exited()

    def no_restart(*args):
        raise AssertionError("restart")

    monkeypatch.setattr(Twitch, "login", fake_login)
    monkeypatch.setattr(miner_module, "_exit_after_crash", fake_exit)
    monkeypatch.setattr(os, "execv", no_restart)

    with pytest.raises(Exited):
        runpy.run_path(str(script), run_name="__main__")

    assert logins == [str(tmp_path / "cookies" / "someone.pkl")]
    compile(script.read_text(encoding="utf-8"), "run.py", "exec")
