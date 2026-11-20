import ast
import inspect
from pathlib import Path

import pytest

import TwitchChannelPointsMiner as package
from TwitchChannelPointsMiner import config_editor, config_migration, constants, runner
from TwitchChannelPointsMiner.classes import AnalyticsServer as server_module
from TwitchChannelPointsMiner.classes import Settings as settings_module
from TwitchChannelPointsMiner.classes import Twitch as twitch_module
from TwitchChannelPointsMiner.classes.entities.Streamer import Streamer
from TwitchChannelPointsMiner.eranio import config_file, launcher, upgrade

ROOT = Path(__file__).resolve().parents[1]


def parameters(function):
    return list(inspect.signature(function).parameters)


def source(obj):
    return inspect.getsource(obj)


@pytest.mark.parametrize(
    "module, names",
    [
        (runner, ["main", "_load_config", "run_config", "restart_process", "_run_legacy", "_create_default_config", "cli"]),
        (config_migration, ["convert_runner", "migrate_config", "_find_calls", "ConfigMigrationError", "CONFIG_VERSION"]),
        (
            config_editor,
            [
                "_byte_offset",
                "_assignment",
                "_simple_value",
                "_set_dict_items",
                "_insert_item_bytes",
                "_replace_config_bytes",
                "update_managed_web_config",
                "read_managed_web_config",
                "migrate_web_config",
                "ConfigEditError",
            ],
        ),
        (constants, ["GITHUB_REPOSITORY_URL", "GITHUB_LATEST_RELEASE_API"]),
    ],
)
def test_base_functions_the_extension_calls_exist(module, names):
    for name in names:
        assert hasattr(module, name), f"{module.__name__}.{name} fehlt"


def test_base_signatures_used_by_the_extension():
    assert parameters(runner.main) == ["argv", "on_miner_ready"]
    assert parameters(runner._load_config) == ["path"]
    assert parameters(runner.run_config) == ["config", "path", "on_miner_ready"]
    assert parameters(config_migration.convert_runner) == ["runner_path", "config_path"]
    assert parameters(config_editor._byte_offset)[:3] == ["lines", "line", "column"] or len(parameters(config_editor._byte_offset)) == 3
    for name in ("host", "port", "refresh", "days_ago", "username", "password", "log_poll_interval", "logs_file"):
        assert name in parameters(server_module.AnalyticsServer.__init__)


def test_runner_main_reads_the_documented_arguments():
    text = source(runner.main)
    for flag in ("--config-dir", "--legacy-runner", "--convert-only"):
        assert flag in text


def test_twitch_hooks_are_in_place():
    for name in ("_has_pending_watch_streak", "send_minute_watched_events", "sync_campaigns", "login", "get_drops_inventory"):
        assert hasattr(twitch_module.Twitch, name), name
    text = source(twitch_module.Twitch.send_minute_watched_events)
    for token in ("eranio_streak.apply", "eranio_drops.allows_watch", "eranio_drops.pick_key", "eranio_drops.reserve"):
        assert token in text, token
    assert "eranio_streak.is_pending" in source(twitch_module.Twitch._has_pending_watch_streak)
    assert "eranio_drops.drop_rank" in text
    sync = source(twitch_module.Twitch.sync_campaigns)
    assert "eranio_drops.remember" in sync and "eranio_drops.publish" in sync


def test_dashboard_hook_and_view_functions():
    assert "dashboard.install" in source(server_module.AnalyticsServer.__init__)
    assert hasattr(Streamer, "persistent_series") and hasattr(Streamer, "persistent_streak_days")
    assert hasattr(server_module.AnalyticsServer, "run")


def test_settings_and_enum_members():
    Priority = settings_module.Priority
    Events = settings_module.Events
    for name in ("STREAK", "DROPS", "ORDER", "STREAK_LENGTH_ASCENDING", "STREAK_LENGTH_DESCENDING"):
        assert name in Priority.__members__
    assert "SUBSCRIPTION" in Events.__members__
    assert "Settings.config_path" in source(runner.run_config)


def test_package_exports_the_compatible_class():
    from TwitchChannelPointsMiner.eranio.compat import TwitchChannelPointsMiner as compat_class

    assert package.TwitchChannelPointsMiner is compat_class
    assert package.__version__
    assert "from .eranio import TwitchChannelPointsMiner" in (ROOT / "TwitchChannelPointsMiner" / "__init__.py").read_text(encoding="utf-8")


def test_old_run_py_entry_points_keep_working():
    from TwitchChannelPointsMiner import run_config_migration

    assert parameters(run_config_migration.ensure_constructor_kwargs) == ["file_path", "class_name", "expected_kwargs"]
    assert parameters(run_config_migration.discover_new_constructor_kwargs) == ["cls"]
    for name in ("LoggerSettings", "ColorPalette"):
        assert hasattr(__import__("TwitchChannelPointsMiner.logger", fromlist=[name]), name)
    assert "upgrade.switch_if_needed" in source(run_config_migration.ensure_constructor_kwargs)


def test_launcher_and_upgrade_interfaces():
    assert parameters(launcher.run) == ["port", "config_password", "host", "config_dir", "legacy_run_py"]
    assert parameters(config_file.convert) == ["legacy_run_py", "target"]
    assert parameters(upgrade.switch_if_needed) == ["file_path", "argv"]
    assert parameters(config_file.create_default)[:3] == ["target", "username", "port"]


def test_base_template_still_produces_a_usable_default_config(tmp_path):
    target = config_file.create_default(tmp_path / "config" / "config.py", "konto", 4321)
    module = runner._load_config(target)
    assert module.MINER_CONFIG["username"] == "konto"
    assert module.ANALYTICS_CONFIG["port"] == 4321
    assert module.MINER_CONFIG["enable_analytics"] is True
    assert module.ERANIO_CONFIG


def test_thin_start_file_keeps_the_updater_behaviour():
    text = upgrade.TEMPLATE.read_text(encoding="utf-8")
    ast.parse(text)
    for token in (
        '"fetch", "--all"',
        '"reset", "--hard", "origin/master"',
        "refs/heads/master/TwitchChannelPointsMiner/__init__.py",
        '".setup_done"',
        '"requirements.txt"',
        "eranio.launcher import run",
        "--port",
    ):
        assert token in text, token
    assert "TwitchChannelPointsMiner(" not in text


def test_base_marker_file_has_version_and_commit():
    parts = (ROOT / "TwitchChannelPointsMiner" / "eranio" / "V3_BASE").read_text(encoding="utf-8").split()
    assert len(parts) == 2 and parts[0].count(".") == 2
