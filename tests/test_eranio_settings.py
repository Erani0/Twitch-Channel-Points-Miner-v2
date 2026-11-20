import ast
import hashlib
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import TwitchChannelPointsMiner as package
from TwitchChannelPointsMiner import runner
from TwitchChannelPointsMiner.classes import AnalyticsServer as server_module
from TwitchChannelPointsMiner.classes.AnalyticsServer import AnalyticsServer
from TwitchChannelPointsMiner.classes.Settings import Priority, Settings
from TwitchChannelPointsMiner.config_editor import (
    migrate_web_config,
    read_managed_web_config,
    update_managed_web_config,
)
from TwitchChannelPointsMiner.config_migration import (
    CONFIG_VERSION,
    migrate_config,
)
from TwitchChannelPointsMiner.eranio import (
    android,
    config_file,
    launcher,
    settings_model,
    settings_page,
)

from test_eranio_compat import owner_options, workdir  # noqa: F401

FIXTURE = Path(__file__).parent / "fixtures" / "eranio_egg_run.py"
HEADERS = {
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Origin": "http://localhost",
    "Referer": "http://localhost/",
    "User-Agent": "Mozilla/5.0",
}
TOKEN = "a" * 30
URL = f"https://www.twitch.tv/#access_token={TOKEN}&scope=&token_type=bearer"


@pytest.fixture(autouse=True)
def clean_state():
    config_file.STATE.reset()
    android.STATE.reset()
    yield
    config_file.STATE.reset()
    android.STATE.reset()


@pytest.fixture
def egg(tmp_path):
    run_py = tmp_path / "run.py"
    run_py.write_bytes(FIXTURE.read_bytes())
    config_dir = tmp_path / "config"
    config_file.STATE.config_dir = config_dir
    config_file.convert(run_py, config_dir / "config.py")
    return SimpleNamespace(
        run_py=run_py, dir=config_dir, config=config_dir / "config.py", root=tmp_path
    )


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def block_source(path):
    text = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.Assign) and node.targets[0].id == "ERANIO_CONFIG":
            return ast.get_source_segment(text, node)
    return None


def make_server(tmp_path, monkeypatch, password="geheim"):
    monkeypatch.chdir(tmp_path)
    analytics = tmp_path / "analytics"
    analytics.mkdir(exist_ok=True)
    monkeypatch.setattr(Settings, "analytics_path", str(analytics), raising=False)
    monkeypatch.setattr(Settings, "enable_analytics", True, raising=False)
    server = AnalyticsServer(password=None)
    if password:
        settings_page.install(
            server.app, server, password, lambda: {"username": "someone"}
        )
    server_module.response_cache.clear()
    return server


def login(client, password="geheim"):
    return client.post(
        "/settings/api/login", json={"password": password}, headers=HEADERS
    )


def save(client, payload):
    return client.post("/settings/api/save", json=payload, headers=HEADERS)


def test_without_a_password_the_settings_page_does_not_exist(tmp_path, monkeypatch):
    server = make_server(tmp_path, monkeypatch, password=None)
    client = server.app.test_client()
    for method, path in [
        ("get", "/settings"),
        ("get", "/settings/api/state"),
        ("get", "/settings/api/session"),
        ("post", "/settings/api/login"),
        ("post", "/settings/api/save"),
        ("post", "/settings/api/android"),
    ]:
        assert getattr(client, method)(path, headers=HEADERS).status_code == 404, path
    page = client.get("/", headers=HEADERS).get_data(as_text=True)
    assert "/settings" not in page
    assert client.get("/streamers", headers=HEADERS).status_code == 200


def test_the_dashboard_stays_open_and_links_to_the_settings(tmp_path, monkeypatch):
    server = make_server(tmp_path, monkeypatch)
    client = server.app.test_client()
    page = client.get("/", headers=HEADERS)
    assert page.status_code == 200
    assert 'href="/settings"' in page.get_data(as_text=True)
    assert client.get("/streamers", headers=HEADERS).status_code == 200
    assert client.get("/settings", headers=HEADERS).status_code == 200


def test_wrong_password_is_refused_and_five_failures_lock_the_client(
    tmp_path, monkeypatch
):
    server = make_server(tmp_path, monkeypatch)
    client = server.app.test_client()
    for _ in range(5):
        assert login(client, "falsch").status_code == 401
    locked = login(client, "geheim")
    assert locked.status_code == 429
    assert "geheim" not in locked.get_data(as_text=True)
    assert client.get("/settings/api/state", headers=HEADERS).status_code == 401


def test_correct_password_opens_a_session_and_logout_closes_it(
    tmp_path, monkeypatch, egg
):
    server = make_server(tmp_path, monkeypatch)
    client = server.app.test_client()
    assert client.get("/settings/api/state", headers=HEADERS).status_code == 401
    response = login(client)
    assert response.status_code == 200
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert "geheim" not in cookie
    state = client.get("/settings/api/state", headers=HEADERS)
    assert state.status_code == 200
    assert "geheim" not in state.get_data(as_text=True)
    assert client.post("/settings/api/logout", headers=HEADERS).status_code == 200
    assert client.get("/settings/api/state", headers=HEADERS).status_code == 401


def test_sessions_expire_after_twelve_idle_hours_and_lockout_after_ten_minutes():
    auth = settings_page.Auth("pw")
    token, _ = auth.check("1.2.3.4", "pw", now=1000)
    assert auth.valid(token, now=1000 + 11 * 3600)
    assert auth.valid(token, now=1000 + 11 * 3600 + 12 * 3600 - 1)
    assert not auth.valid(token, now=1000 + 11 * 3600 + 2 * 12 * 3600 + 5)
    for _ in range(5):
        auth.check("5.6.7.8", "x", now=2000)
    assert auth.check("5.6.7.8", "pw", now=2000 + 300)[0] is None
    assert auth.check("5.6.7.8", "pw", now=2000 + 601)[0] is not None
    assert auth.check("9.9.9.9", "pw", now=2000)[0] is not None


def test_state_shows_the_values_of_config_py(tmp_path, monkeypatch, egg):
    server = make_server(tmp_path, monkeypatch)
    client = server.app.test_client()
    login(client)
    state = client.get("/settings/api/state", headers=HEADERS).get_json()
    assert state["source"] == "config.py"
    assert state["editable"] is True
    names = [item["username"] for item in state["settings"]["streamers"]]
    assert "Zicke8" in names and "eranio" in names
    assert state["settings"]["extras"]["eranio"]["watch_streak_max_parallel"] == 2
    assert state["settings"]["extras"]["eranio"]["priority"][0] == "STREAK"
    assert "base_only" in state


def test_settings_are_read_only_without_config_py(tmp_path, monkeypatch):
    config_file.STATE.config_dir = tmp_path / "config"
    server = make_server(tmp_path, monkeypatch)
    client = server.app.test_client()
    login(client)
    state = client.get("/settings/api/state", headers=HEADERS).get_json()
    assert state["editable"] is False and state["readonly_reason"]
    assert (
        save(client, {"action": "add", "kind": "streamers", "value": "x"}).status_code
        == 409
    )


def test_unreadable_config_py_is_shown_read_only(tmp_path, monkeypatch):
    folder = tmp_path / "config"
    folder.mkdir()
    (folder / "config.py").write_text(
        "MINER_CONFIG = {'username': 'x'}\n", encoding="utf-8"
    )
    config_file.STATE.config_dir = folder
    server = make_server(tmp_path, monkeypatch)
    client = server.app.test_client()
    login(client)
    state = client.get("/settings/api/state", headers=HEADERS).get_json()
    assert state["editable"] is False and state["readonly_reason"]


def test_conversion_keeps_run_py_and_moves_our_options_into_the_block(egg):
    assert digest(egg.run_py) == digest(FIXTURE)
    text = egg.config.read_text(encoding="utf-8")
    tree = ast.parse(text)
    assigned = {
        node.targets[0].id for node in tree.body if isinstance(node, ast.Assign)
    }
    assert {
        "MINER_CONFIG",
        "STREAMERS",
        "MINE_CONFIG",
        "ANALYTICS_CONFIG",
        "ERANIO_CONFIG",
    } <= assigned
    assert [n.targets[0].id for n in tree.body if isinstance(n, ast.Assign)][
        -1
    ] == "ERANIO_CONFIG"
    namespace = {}
    exec(compile(text, "config.py", "exec"), namespace)
    miner = namespace["MINER_CONFIG"]
    for name in config_file.ERANIO_KEYS:
        assert name not in miner
    assert miner["claim_drops_startup"] is True
    block = namespace["ERANIO_CONFIG"]
    assert block["watch_streak_max_parallel"] == 2
    assert block["use_hermes"] is True
    assert block["priority"][:3] == [Priority.STREAK, Priority.DROPS, Priority.ORDER]
    assert len(namespace["STREAMERS"]) == 14
    assert "config_password" not in text
    assert (egg.dir / ".converted-from-run-py").exists()
    assert oct(egg.config.stat().st_mode & 0o777) in (
        oct(0o600),
        oct(0o666),
        oct(0o644),
    )


def test_block_reader_maps_priorities_and_ignores_unknown_keys(tmp_path):
    path = tmp_path / "config.py"
    path.write_text(
        "from TwitchChannelPointsMiner.classes.Settings import Priority\n"
        "ERANIO_CONFIG = {'auto_discover_drops': True, 'priority': [Priority.STREAK_LENGTH_ASCENDING, Priority.DROPS], 'unbekannt': 1}\n",
        encoding="utf-8",
    )
    options = config_file.read_eranio_block(path)
    assert options == {
        "auto_discover_drops": True,
        "priority": [Priority.STREAK_LENGTH_ASCENDING, Priority.DROPS],
    }
    assert config_file.read_eranio_block(tmp_path / "fehlt.py") == {}


def test_miner_reads_our_block_from_the_runtime_config_directory(workdir, egg):
    _, created = workdir
    text = egg.config.read_text(encoding="utf-8")
    text = text.replace(
        "'watch_streak_max_parallel': 2", "'watch_streak_max_parallel': 7"
    )
    egg.config.write_text(text, encoding="utf-8")
    Settings.config_path = str(egg.dir)
    options = owner_options()
    options["watch_streak_max_parallel"] = 1
    options["priority"] = [Priority.ORDER]
    miner = package.TwitchChannelPointsMiner(**options)
    created.append(miner)
    assert miner.watch_streak_max_parallel == 7
    assert miner.requested_priority[:3] == [
        Priority.STREAK,
        Priority.DROPS,
        Priority.ORDER,
    ]


def test_miner_without_runtime_config_uses_its_arguments(workdir):
    _, created = workdir
    config_file.STATE.config_dir = None
    if hasattr(Settings, "config_path"):
        Settings.config_path = None
    options = owner_options()
    options["watch_streak_max_parallel"] = 3
    miner = package.TwitchChannelPointsMiner(**options)
    created.append(miner)
    assert miner.watch_streak_max_parallel == 3


def test_dashboard_values_from_the_launcher_always_win(monkeypatch):
    monkeypatch.setenv(config_file.ENV_PORT, "6111")
    monkeypatch.setenv(config_file.ENV_HOST, "0.0.0.0")
    monkeypatch.setenv(config_file.ENV_PASSWORD, "aus-run-py")
    assert config_file.dashboard_overrides("127.0.0.1", 5000, "aus-config") == (
        "0.0.0.0",
        6111,
        "aus-run-py",
    )
    monkeypatch.setenv(config_file.ENV_PORT, "kaputt")
    assert config_file.dashboard_overrides("h", 5000, None)[1] == 5000
    for name in (config_file.ENV_PORT, config_file.ENV_HOST, config_file.ENV_PASSWORD):
        monkeypatch.delenv(name)
    assert config_file.dashboard_overrides("h", 5, "p") == ("h", 5, "p")


def test_compat_analytics_takes_port_host_and_password_from_the_environment(
    workdir, monkeypatch
):
    _, created = workdir
    started = []
    monkeypatch.setattr(
        server_module.AnalyticsServer, "start", lambda self: started.append(self)
    )
    monkeypatch.setenv(config_file.ENV_PORT, "6222")
    monkeypatch.setenv(config_file.ENV_HOST, "0.0.0.0")
    monkeypatch.setenv(config_file.ENV_PASSWORD, "pw-aus-run-py")
    miner = package.TwitchChannelPointsMiner(**owner_options())
    created.append(miner)
    miner.analytics(host="127.0.0.1", port=5000, config_password="anderes")
    server = started[0]
    assert server.host == "0.0.0.0" and server.port == 6222
    client = server.app.test_client()
    assert login(client, "anderes").status_code == 401
    assert login(client, "pw-aus-run-py").status_code == 200
    assert server.password is None


def record_runner(monkeypatch):
    calls = []
    monkeypatch.setattr(
        runner,
        "run_config",
        lambda config, path, ready=None: calls.append((config, path)),
    )
    return calls


def test_launcher_uses_an_existing_config_through_the_base_runner(egg, monkeypatch):
    calls = record_runner(monkeypatch)
    monkeypatch.delenv(config_file.ENV_PORT, raising=False)
    result = launcher.run(
        port=6333, config_password="pw", config_dir=egg.dir, legacy_run_py=egg.run_py
    )
    assert result == 0
    config, path = calls[0]
    assert path == egg.config
    assert config.STREAMERS and "username" in config.MINER_CONFIG
    assert os.environ[config_file.ENV_PORT] == "6333"
    assert os.environ[config_file.ENV_PASSWORD] == "pw"
    assert digest(egg.run_py) == digest(FIXTURE)
    for name in (config_file.ENV_PORT, config_file.ENV_PASSWORD, config_file.ENV_HOST):
        os.environ.pop(name, None)


def test_launcher_converts_the_egg_run_py_when_there_is_no_config(
    tmp_path, monkeypatch
):
    run_py = tmp_path / "run.py.old"
    run_py.write_bytes(FIXTURE.read_bytes())
    calls = record_runner(monkeypatch)
    target = tmp_path / "config"
    config_file.STATE.config_dir = target
    assert launcher.run(port=5001, config_dir=target, legacy_run_py=run_py) == 0
    assert (target / "config.py").is_file()
    assert block_source(target / "config.py")
    assert len(calls[0][0].STREAMERS) == 14
    assert digest(run_py) == digest(FIXTURE)
    for name in (config_file.ENV_PORT, config_file.ENV_PASSWORD, config_file.ENV_HOST):
        os.environ.pop(name, None)


def test_launcher_falls_back_to_the_old_run_py_when_conversion_fails(
    tmp_path, monkeypatch, capsys
):
    run_py = tmp_path / "run.py.old"
    run_py.write_text("print('alt')\n", encoding="utf-8")
    executed = []
    monkeypatch.setattr(os, "execve", lambda *args: executed.append(args))
    record_runner(monkeypatch)
    launcher.run(port=5001, config_dir=tmp_path / "config", legacy_run_py=run_py)
    assert executed and executed[0][1][-1] == str(run_py)
    assert executed[0][2][launcher.LEGACY_ENV] == "1"
    error = capsys.readouterr().err
    assert "Docker" not in error and "container" not in error.lower()
    assert not (tmp_path / "config" / "config.py").exists()
    for name in (config_file.ENV_PORT, config_file.ENV_PASSWORD, config_file.ENV_HOST):
        os.environ.pop(name, None)


def test_launcher_reports_a_missing_configuration(tmp_path, capsys):
    assert launcher.run(config_dir=tmp_path / "config", legacy_run_py=None) == 1
    assert "FEHLER" in capsys.readouterr().err


def test_editor_changes_keep_comments_and_the_run_py_untouched(egg):
    before = egg.config.read_text(encoding="utf-8")
    comment_lines = [
        line for line in before.splitlines() if line.strip().startswith("#")
    ]
    settings_model.update(
        egg.config, {"action": "add", "kind": "streamers", "value": "neuer"}
    )
    settings_model.update(
        egg.config, {"action": "remove", "kind": "streamers", "value": "Halbsteiv"}
    )
    state = settings_model.update(
        egg.config,
        {
            "action": "update_eranio",
            "values": {
                "auto_discover_drops": True,
                "priority": ["STREAK_LENGTH_DESCENDING", "DROPS"],
            },
        },
    )
    settings_model.update(
        egg.config, {"action": "update_miner", "values": {"claim_drops_startup": False}}
    )
    settings_model.update(
        egg.config, {"action": "update_defaults", "values": {"chat": "ALWAYS"}}
    )
    settings_model.update(
        egg.config, {"action": "update_bet", "values": {"percentage": 9}}
    )
    settings_model.update(
        egg.config,
        {
            "action": "update_streamer_extra",
            "username": "eranio",
            "values": {"watch_streak": True},
        },
    )
    after = egg.config.read_text(encoding="utf-8")
    ast.parse(after)
    for line in comment_lines:
        assert line in after
    names = [item["username"] for item in state["streamers"]]
    assert "neuer" in names and "Halbsteiv" not in names
    assert state["extras"]["eranio"]["auto_discover_drops"] is True
    assert state["extras"]["eranio"]["priority"] == [
        "STREAK_LENGTH_DESCENDING",
        "DROPS",
    ]
    namespace = {}
    exec(compile(after, "config.py", "exec"), namespace)
    assert namespace["ERANIO_CONFIG"]["priority"] == [
        Priority.STREAK_LENGTH_DESCENDING,
        Priority.DROPS,
    ]
    assert namespace["MINER_CONFIG"]["claim_drops_startup"] is False
    assert (egg.dir / "config.py.eranio.bak").is_file()
    assert digest(egg.run_py) == digest(FIXTURE)


def test_editor_rejects_invalid_values(egg):
    with pytest.raises(Exception):
        settings_model.update(
            egg.config,
            {"action": "update_eranio", "values": {"priority": ["GIBT_ES_NICHT"]}},
        )
    with pytest.raises(Exception):
        settings_model.update(
            egg.config,
            {"action": "update_eranio", "values": {"watch_streak_max_parallel": 0}},
        )
    with pytest.raises(Exception):
        settings_model.update(
            egg.config, {"action": "update_eranio", "values": {"os": 1}}
        )


def test_the_block_is_created_when_it_is_missing(egg):
    text = egg.config.read_text(encoding="utf-8")
    start = text.index("ERANIO_CONFIG")
    egg.config.write_text(text[:start].rstrip() + "\n", encoding="utf-8")
    settings_model.update(
        egg.config, {"action": "update_eranio", "values": {"auto_discover_drops": True}}
    )
    assert config_file.read_eranio_block(egg.config) == {"auto_discover_drops": True}


def test_save_through_the_page_and_notification_state(tmp_path, monkeypatch, egg):
    server = make_server(tmp_path, monkeypatch)
    client = server.app.test_client()
    assert (
        save(client, {"action": "add", "kind": "streamers", "value": "x"}).status_code
        == 401
    )
    login(client)
    response = save(
        client, {"action": "add", "kind": "streamers", "value": "pagestreamer"}
    )
    assert response.status_code == 200
    assert any(
        s["username"] == "pagestreamer"
        for s in response.get_json()["settings"]["streamers"]
    )
    bad = save(client, {"action": "update_eranio", "values": {"priority": []}})
    assert bad.status_code == 400
    note = save(
        client,
        {
            "action": "update_notification",
            "provider": "ntfy",
            "values": {
                "enabled": True,
                "topic": "geheimes-thema",
                "events": ["STREAMER_ONLINE"],
            },
        },
    )
    assert note.status_code == 200
    body = note.get_data(as_text=True)
    assert "geheimes-thema" not in body
    assert (
        client.post(
            "/settings/api/notifications/unbekannt/test", headers=HEADERS
        ).status_code
        == 404
    )


GUARD_OLD = """\
CONFIG_VERSION = {version}
from TwitchChannelPointsMiner.classes.Settings import Priority, StreamerSource
from TwitchChannelPointsMiner.classes.entities.Streamer import Streamer
MINER_CONFIG = {{
    "username": "alice",
    "streamer_source_priority": [StreamerSource.STREAMERS],
}}
STREAMERS = [Streamer("one"), "two"]
MINE_CONFIG = {{"followers": True, "categories": []}}
ANALYTICS_CONFIG = None

# Eigene Optionen, nur vom eigenen Teil gelesen.
ERANIO_CONFIG = {{
    "auto_discover_drops": True,
    "watch_streak_max_parallel": 4,
    "priority": [Priority.STREAK_LENGTH_ASCENDING, Priority.DROPS],
}}
"""


@pytest.mark.parametrize("version", [None, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11])
def test_guard_base_migration_keeps_the_block(tmp_path, version):
    source = GUARD_OLD.format(version=version if version else 0)
    if version is None:
        source = source.replace("CONFIG_VERSION = 0\n", "")
    path = tmp_path / "config.py"
    path.write_text(source, encoding="utf-8")
    original = block_source(path)
    assert migrate_config(path) is True
    migrated = path.read_text(encoding="utf-8")
    assert f"CONFIG_VERSION = {CONFIG_VERSION}" in migrated
    assert block_source(path) == original
    assert "Eigene Optionen, nur vom eigenen Teil gelesen." in migrated
    assert config_file.read_eranio_block(path)["watch_streak_max_parallel"] == 4
    assert migrate_config(path) is False
    assert block_source(path) == original


def test_guard_runner_load_config_keeps_the_block(egg):
    original = block_source(egg.config)
    module = runner._load_config(egg.config)
    assert block_source(egg.config) == original
    assert module.ERANIO_CONFIG["watch_streak_max_parallel"] == 2
    for name in config_file.ERANIO_KEYS:
        if name != "priority":
            assert name not in module.MINER_CONFIG
    assert config_file.read_eranio_block(egg.config)["priority"][:3] == [
        Priority.STREAK,
        Priority.DROPS,
        Priority.ORDER,
    ]


def test_guard_web_config_migration_keeps_the_block(egg):
    original = block_source(egg.config)
    overrides = {
        "streamers": [{"username": "uebernommen", "settings": {"claim_drops": False}}],
        "categories": ["Just Chatting"],
        "category": {"limit": 12},
        "logging": {"console_level": "WARNING"},
        "notifications": {
            "ntfy": {
                "enabled": True,
                "fields": {"events": ["STREAMER_ONLINE"]},
                "secrets": {"topic": "t"},
            }
        },
    }
    (egg.dir / "web-config.json").write_text(json.dumps(overrides), encoding="utf-8")
    assert migrate_web_config(egg.config) is True
    assert block_source(egg.config) == original
    state = read_managed_web_config(egg.config)
    assert any(s["username"] == "uebernommen" for s in state["streamers"])
    ast.parse(egg.config.read_text(encoding="utf-8"))


def test_guard_base_editor_paths_keep_the_block(egg):
    original = block_source(egg.config)
    actions = [
        {"action": "add", "kind": "streamers", "value": "guard_one"},
        {
            "action": "update_streamer",
            "username": "guard_one",
            "settings": {"claim_drops": False, "chat": "NEVER"},
        },
        {"action": "reorder_streamers", "usernames": None},
        {"action": "remove", "kind": "streamers", "value": "guard_one"},
        {"action": "add", "kind": "categories", "value": "Chess"},
        {"action": "update_category", "values": {"limit": 5, "sort": "RANDOM"}},
        {"action": "update_sources", "values": {"badges": True}},
        {
            "action": "update_logging",
            "values": {"console_level": "ERROR", "daily_report": True},
        },
        {"action": "update_updates", "values": {"enabled": False}},
        {"action": "update_login", "values": {"android": True}},
        {
            "action": "update_notification",
            "provider": "telegram",
            "values": {
                "enabled": True,
                "chat_id": 5,
                "token": "abc",
                "events": ["STREAMER_ONLINE"],
            },
        },
        {
            "action": "update_notification",
            "provider": "telegram",
            "values": {"enabled": False},
        },
        {
            "action": "update_notification",
            "provider": "discord",
            "values": {
                "enabled": True,
                "webhook_api": "https://discord.com/api/webhooks/1/x",
                "events": [],
            },
        },
    ]
    for payload in actions:
        if payload.get("usernames", 0) is None:
            payload["usernames"] = [
                s["username"]
                for s in reversed(read_managed_web_config(egg.config)["streamers"])
            ]
        update_managed_web_config(egg.config, payload)
        assert block_source(egg.config) == original, payload["action"]
    ast.parse(egg.config.read_text(encoding="utf-8"))
    runner._load_config(egg.config)
    assert block_source(egg.config) == original


def test_guard_our_editor_does_not_disturb_the_base_blocks(egg):
    namespace_before = {}
    exec(compile(egg.config.read_text(encoding="utf-8"), "c", "exec"), namespace_before)
    settings_model.update(
        egg.config,
        {
            "action": "update_eranio",
            "values": {"watch_streak_min_offline_seconds": 600},
        },
    )
    namespace_after = {}
    exec(compile(egg.config.read_text(encoding="utf-8"), "c", "exec"), namespace_after)
    for name in ("STREAMERS", "MINE_CONFIG", "ANALYTICS_CONFIG"):
        assert (
            repr(namespace_before[name]) == repr(namespace_after[name])
            or name == "STREAMERS"
        )
    assert len(namespace_before["STREAMERS"]) == len(namespace_after["STREAMERS"])
    assert namespace_after["ERANIO_CONFIG"]["watch_streak_min_offline_seconds"] == 600


class FakeMiner:
    def __init__(self):
        self.running = True
        self.ws_pool = object()
        self.added = []
        self.removed = []
        self.refreshed = 0

    def add_streamers(self, streamers):
        self.added.extend(getattr(s, "username", s) for s in streamers)

    def remove_streamers(self, usernames):
        self.removed.extend(usernames)

    def refresh_categories(self, config):
        self.refreshed += 1


def test_the_base_watcher_picks_up_changes_made_by_the_settings_editor(egg):
    module = runner._load_config(egg.config)
    miner = FakeMiner()
    thread = threading.Thread(
        target=runner._watch_config, args=(egg.config, miner, module, 0.05), daemon=True
    )
    thread.start()
    time.sleep(0.2)
    settings_model.update(
        egg.config, {"action": "add", "kind": "streamers", "value": "livestreamer"}
    )
    settings_model.update(
        egg.config, {"action": "remove", "kind": "streamers", "value": "Halbsteiv"}
    )
    deadline = time.time() + 5
    while time.time() < deadline and not (miner.added and miner.removed):
        time.sleep(0.05)
    miner.running = False
    assert "livestreamer" in miner.added
    assert any(name.lower() == "halbsteiv" for name in miner.removed)


class Stdin:
    def __init__(self, lines):
        self.lines = list(lines)
        self.closed = False

    def readline(self):
        return self.lines.pop(0) if self.lines else ""


def fake_accept(monkeypatch, valid=True, user="someone"):
    from TwitchChannelPointsMiner.classes.TwitchLogin import TwitchLogin

    def accept(self, token):
        if not valid or token != TOKEN:
            return False
        self.set_token(token)
        self.user_id = "1"
        self.login_check_result = True
        return True

    monkeypatch.setattr(TwitchLogin, "_TwitchLogin__accept_android_token", accept)


def test_android_paste_stores_the_cookie_and_never_logs_the_token(
    tmp_path, monkeypatch, caplog
):
    fake_accept(monkeypatch)
    android.configure("someone", False, cookies_dir=str(tmp_path / "cookies"))
    with caplog.at_level(logging.DEBUG):
        ok, message = android.submit(URL)
    assert ok is True and "Neustart" in message
    stored = (tmp_path / "cookies" / "someone-android.pkl").read_text(encoding="utf-8")
    assert TOKEN in stored
    assert TOKEN not in caplog.text and TOKEN not in message
    assert android.status()["stored"] is True


def test_android_invalid_token_is_rejected(tmp_path, monkeypatch, caplog):
    fake_accept(monkeypatch, valid=False)
    android.configure("someone", False, cookies_dir=str(tmp_path / "cookies"))
    with caplog.at_level(logging.DEBUG):
        assert android.submit(URL)[0] is False
        assert android.submit("kein token hier")[0] is False
    assert not (tmp_path / "cookies" / "someone-android.pkl").exists()
    assert TOKEN not in caplog.text


def test_android_active_message_when_already_in_use(tmp_path, monkeypatch):
    fake_accept(monkeypatch)
    android.configure("someone", True, cookies_dir=str(tmp_path / "cookies"))
    assert "bereits aktiv" in android.submit(TOKEN)[1]


def test_android_page_endpoint(tmp_path, monkeypatch, egg):
    fake_accept(monkeypatch)
    android.configure("someone", False, cookies_dir=str(tmp_path / "cookies"))
    server = make_server(tmp_path, monkeypatch)
    client = server.app.test_client()
    assert (
        client.post(
            "/settings/api/android", json={"value": URL}, headers=HEADERS
        ).status_code
        == 401
    )
    login(client)
    ok = client.post("/settings/api/android", json={"value": URL}, headers=HEADERS)
    assert ok.status_code == 200 and TOKEN not in ok.get_data(as_text=True)
    bad = client.post(
        "/settings/api/android", json={"value": "nichts"}, headers=HEADERS
    )
    assert bad.status_code == 400


def test_android_console_thread_reads_a_pasted_line(tmp_path, monkeypatch):
    fake_accept(monkeypatch)
    android.configure("someone", False, cookies_dir=str(tmp_path / "cookies"))
    thread = android.start_console_reader(Stdin(["hallo\n", URL + "\n"]))
    thread.join(5)
    assert (tmp_path / "cookies" / "someone-android.pkl").is_file()


def test_android_console_thread_survives_closed_or_missing_input(tmp_path):
    android.configure("someone", False, cookies_dir=str(tmp_path / "cookies"))
    closed = Stdin([])
    closed.closed = True
    assert android.start_console_reader(closed) is None
    empty = android.start_console_reader(Stdin([]))
    empty.join(5)
    assert not empty.is_alive()

    class Broken:
        closed = False

        def readline(self):
            raise OSError("kein Eingang")

    broken = android.start_console_reader(Broken())
    broken.join(5)
    assert not broken.is_alive()


def test_android_offer_logs_the_instruction_once_and_never_blocks(
    tmp_path, monkeypatch, caplog
):
    android.configure("someone", False, cookies_dir=str(tmp_path / "cookies"))
    monkeypatch.delenv(android.ANDROID_LOGIN_ENV_VAR, raising=False)
    with caplog.at_level(logging.INFO):
        assert android.offer(Stdin([])) is True
        assert android.offer(Stdin([])) is False
    text = caplog.text
    assert text.count(android.ANDROID_LOGIN_URL) == 1
    assert "Optional" in text


def test_android_offer_stays_quiet_when_a_login_is_stored(tmp_path, caplog):
    android.configure("someone", False, cookies_dir=str(tmp_path / "cookies"))
    (tmp_path / "cookies").mkdir()
    (tmp_path / "cookies" / "someone-android.pkl").write_text("[]", encoding="utf-8")
    with caplog.at_level(logging.INFO):
        assert android.offer(Stdin([])) is False
    assert android.ANDROID_LOGIN_URL not in caplog.text


def test_android_environment_variable_is_accepted(tmp_path, monkeypatch):
    fake_accept(monkeypatch)
    android.configure("someone", False, cookies_dir=str(tmp_path / "cookies"))
    monkeypatch.setenv(android.ANDROID_LOGIN_ENV_VAR, URL)
    android.read_environment().join(5)
    assert (tmp_path / "cookies" / "someone-android.pkl").is_file()


def test_new_texts_name_no_base_project():
    root = Path(package.__file__).resolve().parents[1]
    files = [
        root / "assets" / "eranio" / "settings.html",
        root / "assets" / "eranio" / "settings.js",
        root / "assets" / "eranio" / "settings.css",
    ]
    for path in files:
        text = path.read_text(encoding="utf-8").lower()
        for word in ("zarmstrong", "upstream", "v3"):
            assert word not in text, (path.name, word)
        assert "—" not in text and "–" not in text
