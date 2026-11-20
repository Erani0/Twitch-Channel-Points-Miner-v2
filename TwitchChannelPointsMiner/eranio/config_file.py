import ast
import logging
import os
import tempfile
from pathlib import Path

from TwitchChannelPointsMiner.config_editor import _byte_offset
from TwitchChannelPointsMiner.config_migration import (
    ConfigMigrationError,
    _find_calls,
    convert_runner,
)

logger = logging.getLogger(__name__)


class ConfigState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.config_dir = None
        self.load_error = None


STATE = ConfigState()


def config_dir():
    if STATE.config_dir is not None:
        return Path(STATE.config_dir)
    return Path(os.environ.get("TCPM_CONFIG_DIR") or Path().absolute() / "config")


def config_path():
    return config_dir() / "config.py"


def exists():
    return config_path().is_file()


def _replace_spans(encoded, edits):
    for start, end, text in sorted(edits, reverse=True):
        encoded = encoded[:start] + text.encode("utf-8") + encoded[end:]
    return encoded


def _module_assignments(tree, source):
    assigned = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id not in assigned
        ):
            assigned[node.targets[0].id] = ast.get_source_segment(source, node.value)
    return assigned


def prepared_source(source):
    tree = ast.parse(source)
    assigned = _module_assignments(tree, source)
    encoded = source.encode("utf-8")
    lines = encoded.splitlines(keepends=True)
    edits = []
    calls = []
    for name in ("TwitchChannelPointsMiner", "analytics", "mine"):
        calls.extend(_find_calls(tree, name))
    for call in calls:
        for node in ast.walk(call):
            if (
                isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and assigned.get(node.id)
            ):
                start = _byte_offset(lines, node.lineno, node.col_offset)
                end = _byte_offset(lines, node.end_lineno, node.end_col_offset)
                edits.append((start, end, f"({assigned[node.id]})"))
    for call in _find_calls(tree, "analytics"):
        for keyword in call.keywords:
            if keyword.arg == "config_password":
                start = _byte_offset(
                    lines, keyword.value.lineno, keyword.value.col_offset
                )
                start = encoded.rfind(b"config_password", 0, start)
                end = _byte_offset(
                    lines, keyword.value.end_lineno, keyword.value.end_col_offset
                )
                tail = end
                while encoded[tail : tail + 1] in (b" ", b"\t"):
                    tail += 1
                if encoded[tail : tail + 1] == b",":
                    end = tail + 1
                    while encoded[end : end + 1] in (b" ", b"\t"):
                        end += 1
                else:
                    head = start
                    while encoded[head - 1 : head] in (b" ", b"\t", b"\r", b"\n"):
                        head -= 1
                    if encoded[head - 1 : head] == b",":
                        start = head - 1
                edits.append((start, end, ""))
    return _replace_spans(encoded, edits).decode("utf-8")


def ensure_categories(text):
    tree = ast.parse(text)
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "MINE_CONFIG" for t in node.targets
            )
            and isinstance(node.value, ast.Dict)
        ):
            has = any(
                isinstance(key, ast.Constant) and key.value == "categories"
                for key in node.value.keys
            )
            if has:
                return text
            lines = text.encode("utf-8").splitlines(keepends=True)
            end = (
                _byte_offset(lines, node.value.end_lineno, node.value.end_col_offset)
                - 1
            )
            encoded = text.encode("utf-8")
            body = encoded[:end].rstrip()
            separator = b"" if body.endswith((b"{", b",")) else b","
            return (
                body + separator + b"\n    'categories': [],\n" + encoded[end:]
            ).decode("utf-8")
    return text


ERANIO_KEYS = (
    "auto_discover_drops",
    "watch_streak_max_parallel",
    "watch_streak_min_offline_seconds",
    "priority",
    "watch_only_drops",
    "stop_watch_when_drops_completed",
    "use_hermes",
)
BLOCK_NAME = "ERANIO_CONFIG"
NL = chr(10)
LF = bytes([10])


def move_to_eranio_block(text):
    tree = ast.parse(text)
    encoded = text.encode("utf-8")
    lines = encoded.splitlines(keepends=True)
    miner = None
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "MINER_CONFIG" for t in node.targets
            )
            and isinstance(node.value, ast.Dict)
        ):
            miner = node.value
    moved = []
    edits = []
    if miner is not None:
        for key, value in zip(miner.keys, miner.values):
            if not (isinstance(key, ast.Constant) and key.value in ERANIO_KEYS):
                continue
            start = _byte_offset(lines, key.lineno, 0)
            end = _byte_offset(lines, value.end_lineno, value.end_col_offset)
            while encoded[end : end + 1] in (b" ", b"\t"):
                end += 1
            if encoded[end : end + 1] == b",":
                end += 1
            while encoded[end : end + 1] in (b" ", b"\t"):
                end += 1
            if encoded[end : end + 1] == b"\r":
                end += 1
            if encoded[end : end + 1] == LF:
                end += 1
            moved.append((key.value, ast.get_source_segment(text, value)))
            edits.append((start, end, ""))
    result = _replace_spans(encoded, edits).decode("utf-8")
    if BLOCK_NAME in {
        t.id
        for node in ast.parse(result).body
        if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Name)
    }:
        return result
    if moved:
        body = "".join(f"    {name!r}: {source},{NL}" for name, source in moved)
        block = f"{BLOCK_NAME} = {{{NL}{body}}}{NL}"
    else:
        block = f"{BLOCK_NAME} = {{}}{NL}"
    return result.rstrip(NL) + NL + NL + block


def build_config_text(run_py):
    path = Path(run_py)
    if not path.is_file():
        raise ConfigMigrationError("Die Startdatei run.py wurde nicht gefunden.")
    return prepared_source(path.read_text(encoding="utf-8"))


def convert(legacy_run_py, target):
    legacy = Path(legacy_run_py)
    target = Path(target)
    staged_source = build_config_text(legacy)
    with tempfile.TemporaryDirectory() as folder:
        staged = Path(folder) / legacy.name
        staged.write_text(staged_source, encoding="utf-8")
        convert_runner(staged, target)
    try:
        text = target.read_text(encoding="utf-8")
        text = move_to_eranio_block(ensure_categories(text))
        ast.parse(text)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, target)
    except Exception:
        target.unlink(missing_ok=True)
        target.with_name(".converted-from-run-py").unlink(missing_ok=True)
        raise
    return target


ENV_PORT = "ERANIO_DASHBOARD_PORT"
ENV_HOST = "ERANIO_DASHBOARD_HOST"
ENV_PASSWORD = "ERANIO_CONFIG_PASSWORD"


def dashboard_overrides(host, port, config_password):
    host = os.environ.get(ENV_HOST) or host
    raw_port = os.environ.get(ENV_PORT)
    if raw_port:
        try:
            port = int(raw_port)
        except ValueError:
            logger.warning(
                "Der Wert von %s ist keine Zahl und wird ignoriert.", ENV_PORT
            )
    config_password = os.environ.get(ENV_PASSWORD) or config_password
    return host, port, config_password


def runtime_eranio_options():
    from TwitchChannelPointsMiner.classes.Settings import Settings

    if STATE.config_dir is None and not getattr(Settings, "config_path", None):
        return {}
    return read_eranio_block(config_path())


def read_eranio_block(path):
    from TwitchChannelPointsMiner.classes.Settings import Priority
    from TwitchChannelPointsMiner.config_editor import _assignment, _simple_value

    path = Path(path)
    if not path.is_file():
        return {}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return {}
    block = _simple_value(_assignment(tree, BLOCK_NAME))
    if not isinstance(block, dict):
        return {}
    options = {}
    for name, value in block.items():
        if name not in ERANIO_KEYS:
            logger.warning(
                "Unbekannter Wert in %s wird ignoriert: %s", BLOCK_NAME, name
            )
            continue
        if name == "priority":
            if not isinstance(value, list):
                continue
            members = [Priority[item] for item in value if item in Priority.__members__]
            if not members:
                continue
            value = members
        options[name] = value
    return options


EXAMPLE_NAME = "config.example.py"
DEFAULT_ERANIO_BLOCK = (
    "ERANIO_CONFIG = {"
    + NL
    + "    'watch_streak_max_parallel': 2,"
    + NL
    + "    'use_hermes': True,"
    + NL
    + "}"
    + NL
)
_DEFAULT_REPLACEMENTS = (
    ('"username": "your-twitch-username"', '"username": {username!r}'),
    ('"claim_drops_startup": False', '"claim_drops_startup": True'),
    ('"enable_analytics": False', '"enable_analytics": True'),
    ('"update_check": True', '"update_check": False'),
    ('time_zone=""', 'time_zone="Europe/Berlin"'),
    (
        "ANALYTICS_CONFIG = None",
        "ANALYTICS_CONFIG = {{'host': '0.0.0.0', 'port': {port}, 'refresh': 5, 'days_ago': 360}}",
    ),
    (
        "# Copy this template to config/config.py and review each setting before use.",
        "# Einstellungen des Miners. Sie lassen sich hier oder auf der Einstellungsseite ändern.",
    ),
)


def default_config_text(username, port, template=None):
    template = (
        Path(template)
        if template
        else Path(__file__).resolve().parents[2] / EXAMPLE_NAME
    )
    text = template.read_text(encoding="utf-8")
    for old, new in _DEFAULT_REPLACEMENTS:
        text = text.replace(old, new.format(username=username, port=port), 1)
    ast.parse(text)
    return text.rstrip(NL) + NL + NL + DEFAULT_ERANIO_BLOCK


def create_default(target, username, port=5000, template=None):
    target = Path(target)
    text = default_config_text(username, port, template)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, target)
    return target
