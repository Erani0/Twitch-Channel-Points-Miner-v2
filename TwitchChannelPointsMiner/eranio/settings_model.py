import ast
import stat
from pathlib import Path

from TwitchChannelPointsMiner.classes.Chat import ChatPresence
from TwitchChannelPointsMiner.classes.entities.Bet import DelayMode, Strategy
from TwitchChannelPointsMiner.classes.Settings import Priority
from TwitchChannelPointsMiner.config_editor import (
    CONFIG_FILE_MUTEX,
    ConfigEditError,
    _assignment,
    _call_keyword,
    _dict_item,
    _insert_item_bytes,
    _node_span,
    _replace_config_bytes,
    _require_parses,
    _set_dict_items,
    _simple_value,
    _streamer_key,
    _with_config_import,
    migrate_web_config,
    read_managed_web_config,
    update_managed_web_config,
)

ENUMS = {
    "Priority": (
        Priority,
        "from TwitchChannelPointsMiner.classes.Settings import Priority",
    ),
    "Strategy": (
        Strategy,
        "from TwitchChannelPointsMiner.classes.entities.Bet import Strategy",
    ),
    "DelayMode": (
        DelayMode,
        "from TwitchChannelPointsMiner.classes.entities.Bet import DelayMode",
    ),
    "ChatPresence": (
        ChatPresence,
        "from TwitchChannelPointsMiner.classes.Chat import ChatPresence",
    ),
}
CLASS_IMPORTS = {
    "StreamerSettings": "from TwitchChannelPointsMiner.classes.entities.Streamer import StreamerSettings",
    "BetSettings": "from TwitchChannelPointsMiner.classes.entities.Bet import BetSettings",
}

MINER_SPEC = {
    "claim_drops_startup": ("bool", False),
    "disable_at_in_nickname": ("bool", False),
    "streams_watched": ("choice", (1, 2, 3), 2),
}
ERANIO_SPEC = {
    "watch_only_drops": ("bool", False),
    "stop_watch_when_drops_completed": ("bool", False),
    "auto_discover_drops": ("bool", False),
    "watch_streak_max_parallel": ("int", 1, 20, None),
    "watch_streak_min_offline_seconds": ("int", 0, 604800, 1800),
    "priority": ("enumlist", "Priority", ["ORDER"]),
}
ERANIO_BLOCK = "ERANIO_CONFIG"
BACKUP_SUFFIX = ".eranio.bak"
LOGGER_SPEC = {
    "save": ("bool", True),
    "less": ("bool", False),
    "console_username": ("bool", False),
    "emoji": ("bool", True),
    "colored": ("bool", False),
    "auto_clear": ("bool", True),
    "time_zone": ("text", None),
    "log_retention_days": ("int", 1, 365, 7),
}
DEFAULTS_SPEC = {
    "make_predictions": ("bool", True),
    "follow_raid": ("bool", True),
    "claim_drops": ("bool", True),
    "claim_moments": ("bool", True),
    "watch_streak": ("bool", True),
    "community_goals": ("bool", False),
    "chat": ("enum", "ChatPresence", "ONLINE"),
}
BET_SPEC = {
    "strategy": ("enum", "Strategy", "SMART"),
    "percentage": ("int", 1, 100, 5),
    "percentage_gap": ("int", 1, 100, 20),
    "max_points": ("int", 1, 100000000, 50000),
    "minimum_points": ("int", 0, 100000000, 0),
    "stealth_mode": ("bool", False),
    "delay_mode": ("enum", "DelayMode", "FROM_START"),
    "delay": ("float", 0, 3600, 6),
}
MINE_SPEC = {
    "drop_pick_stickiness_minutes": ("float", 0, 1440, 15),
    "drop_progress_stall_minutes": ("float", 1, 1440, 10),
    "watch_status_interval_minutes": ("float", 1, 1440, 15),
    "drop_badge_catalog": ("bool", True),
    "badge_drop_streamer_limit": ("int", 1, 50, 1),
    "wildcard_category_limit": ("int", 1, 100, 10),
    "wildcard_category_streamer_limit": ("int", 1, 50, 1),
    "wildcard_category_pin_active": ("bool", True),
}
STREAMER_EXTRA_SPEC = {"watch_streak": ("bool", True)}

SPECS = {
    "update_miner": MINER_SPEC,
    "update_eranio": ERANIO_SPEC,
    "update_logger": LOGGER_SPEC,
    "update_defaults": DEFAULTS_SPEC,
    "update_bet": BET_SPEC,
    "update_mine": MINE_SPEC,
}
EXTRA_ACTIONS = set(SPECS) | {"update_streamer_extra"}

LIVE_AREAS = (
    "Streamer hinzufügen oder entfernen",
    "Kategorien und Wildcard-Einstellungen",
)


def enum_choices(name):
    return [member.name for member in ENUMS[name][0]]


def spec_for_ui():
    ui = {}
    for key, spec in {**SPECS, "update_streamer_extra": STREAMER_EXTRA_SPEC}.items():
        fields = {}
        for name, definition in spec.items():
            entry = {"type": definition[0]}
            kind = definition[0]
            if kind in ("int", "float"):
                entry.update(
                    min=definition[1], max=definition[2], default=definition[3]
                )
            elif kind == "choice":
                entry.update(choices=list(definition[1]), default=definition[2])
            elif kind in ("enum", "enumlist"):
                entry.update(choices=enum_choices(definition[1]), default=definition[2])
            else:
                entry.update(default=definition[1])
            fields[name] = entry
        ui[key] = fields
    return ui


def render_value(name, definition, value):
    kind = definition[0]
    if kind == "bool":
        if not isinstance(value, bool):
            raise ConfigEditError(f"{name} muss an oder aus sein.")
        return repr(value), None
    if kind in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigEditError(f"{name} muss eine Zahl sein.")
        if kind == "int" and (isinstance(value, float) and not value.is_integer()):
            raise ConfigEditError(f"{name} muss eine ganze Zahl sein.")
        if not definition[1] <= value <= definition[2]:
            raise ConfigEditError(
                f"{name} muss zwischen {definition[1]} und {definition[2]} liegen."
            )
        return repr(int(value) if kind == "int" else value), None
    if kind == "choice":
        if value not in definition[1] or isinstance(value, bool):
            raise ConfigEditError(f"{name} hat einen ungültigen Wert.")
        return repr(value), None
    if kind == "text":
        if value in (None, ""):
            return "None", None
        if not isinstance(value, str) or len(value) > 100 or "\n" in value:
            raise ConfigEditError(f"{name} ist ungültig.")
        return repr(value), None
    if kind == "enum":
        _, statement = ENUMS[definition[1]]
        if value not in enum_choices(definition[1]):
            raise ConfigEditError(f"{name} hat einen ungültigen Wert.")
        return f"{definition[1]}.{value}", statement
    if kind == "enumlist":
        _, statement = ENUMS[definition[1]]
        if (
            not isinstance(value, list)
            or not value
            or any(item not in enum_choices(definition[1]) for item in value)
            or len(set(value)) != len(value)
        ):
            raise ConfigEditError(f"{name} hat einen ungültigen Wert.")
        return (
            "[" + ", ".join(f"{definition[1]}.{item}" for item in value) + "]",
            statement,
        )
    raise ConfigEditError(f"{name} wird nicht unterstützt.")


def validate_values(spec, values):
    if not isinstance(values, dict) or not values:
        raise ConfigEditError("Keine Werte übergeben.")
    unknown = set(values) - set(spec)
    if unknown:
        raise ConfigEditError(
            "Nicht unterstützte Einstellung: " + ", ".join(sorted(unknown))
        )
    rendered = {}
    imports = []
    for name, value in values.items():
        text, statement = render_value(name, spec[name], value)
        rendered[name] = text
        if statement:
            imports.append(statement)
    return rendered, imports


def imported_names(tree):
    names = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(
                alias.asname or alias.name.split(".")[0] for alias in node.names
            )
    return names


def ensure_imports(config_path, statements):
    path = Path(config_path)
    for statement in dict.fromkeys(statements):
        name = statement.rsplit(" import ", 1)[1].strip()
        source = path.read_text(encoding="utf-8")
        if name in imported_names(ast.parse(source)):
            continue
        encoded = source.encode("utf-8")
        updated = _with_config_import(encoded, statement)
        _require_parses(updated)
        _replace_config_bytes(path, updated, stat.S_IMODE(path.stat().st_mode))


def write_keywords(config_path, locate, values):
    path = Path(config_path)
    for name, rendered in values.items():
        encoded = path.read_text(encoding="utf-8").encode("utf-8")
        call = locate(ast.parse(encoded.decode("utf-8")))
        if not isinstance(call, ast.Call):
            raise ConfigEditError(
                "Diese Einstellungsgruppe hat in der Datei nicht die erwartete Form."
            )
        keyword = _call_keyword(call, name)
        if keyword is not None:
            lines = encoded.splitlines(keepends=True)
            start, end = _node_span(lines, keyword.value)
            updated = encoded[:start] + rendered.encode("utf-8") + encoded[end:]
        else:
            updated = _insert_item_bytes(
                encoded, call, f"{name}={rendered}", inline=True
            )
        _require_parses(updated)
        _replace_config_bytes(path, updated, stat.S_IMODE(path.stat().st_mode))


def miner_item(tree, key):
    return _dict_item(_assignment(tree, "MINER_CONFIG"), key)


def locate_logger(tree):
    return miner_item(tree, "logger_settings")


def locate_defaults(tree):
    return miner_item(tree, "streamer_settings")


def locate_bet(tree):
    settings = locate_defaults(tree)
    keyword = _call_keyword(settings, "bet") if isinstance(settings, ast.Call) else None
    return keyword.value if keyword is not None else None


def ensure_call(config_path, parent_locate, key, class_name, in_dict):
    path = Path(config_path)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    if isinstance(parent_locate(tree), ast.Call):
        return
    ensure_imports(config_path, [CLASS_IMPORTS[class_name]])
    if in_dict:
        _set_dict_items(config_path, "MINER_CONFIG", {key: f"{class_name}()"})
    else:
        write_keywords(
            config_path,
            locate_defaults,
            {key: f"{class_name}()"},
        )


def locate_streamer_settings(username):
    wanted = username.strip().lower()

    def locate(tree):
        listing = _assignment(tree, "STREAMERS")
        for node in getattr(listing, "elts", []):
            if _streamer_key(node) == wanted and isinstance(node, ast.Call):
                keyword = _call_keyword(node, "settings")
                if keyword is not None:
                    return keyword.value
                if len(node.args) > 1:
                    return node.args[1]
        return None

    return locate


def locate_streamer(username):
    wanted = username.strip().lower()

    def locate(tree):
        listing = _assignment(tree, "STREAMERS")
        for node in getattr(listing, "elts", []):
            if _streamer_key(node) == wanted and isinstance(node, ast.Call):
                return node
        return None

    return locate


def backup_before_write(config_path):
    path = Path(config_path)
    target = path.with_name(path.name + BACKUP_SUFFIX)
    target.write_bytes(path.read_bytes())


def write_eranio_block(config_path, rendered):
    path = Path(config_path)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    if not isinstance(_assignment(tree, ERANIO_BLOCK), ast.Dict):
        text = path.read_text(encoding="utf-8")
        newline = chr(10)
        updated = (
            text.rstrip(newline) + newline + newline + ERANIO_BLOCK + " = {}" + newline
        ).encode("utf-8")
        _require_parses(updated)
        _replace_config_bytes(path, updated, stat.S_IMODE(path.stat().st_mode))
    _set_dict_items(config_path, ERANIO_BLOCK, rendered)
    _require_parses(path.read_bytes())


def apply_extra(config_path, payload):
    action = payload.get("action")
    values = payload.get("values")
    if action == "update_miner":
        rendered, imports = validate_values(MINER_SPEC, values)
        ensure_imports(config_path, imports)
        _set_dict_items(config_path, "MINER_CONFIG", rendered)
    elif action == "update_eranio":
        rendered, imports = validate_values(ERANIO_SPEC, values)
        ensure_imports(config_path, imports)
        write_eranio_block(config_path, rendered)
    elif action == "update_logger":
        rendered, imports = validate_values(LOGGER_SPEC, values)
        write_keywords(config_path, locate_logger, rendered)
    elif action == "update_defaults":
        rendered, imports = validate_values(DEFAULTS_SPEC, values)
        ensure_call(
            config_path, locate_defaults, "streamer_settings", "StreamerSettings", True
        )
        ensure_imports(config_path, imports)
        write_keywords(config_path, locate_defaults, rendered)
    elif action == "update_bet":
        rendered, imports = validate_values(BET_SPEC, values)
        ensure_call(
            config_path, locate_defaults, "streamer_settings", "StreamerSettings", True
        )
        ensure_call(config_path, locate_bet, "bet", "BetSettings", False)
        ensure_imports(config_path, imports)
        write_keywords(config_path, locate_bet, rendered)
    elif action == "update_mine":
        rendered, imports = validate_values(MINE_SPEC, values)
        _set_dict_items(config_path, "MINE_CONFIG", rendered)
    elif action == "update_streamer_extra":
        username = str(payload.get("username", "")).strip()
        rendered, imports = validate_values(STREAMER_EXTRA_SPEC, values)
        tree = ast.parse(Path(config_path).read_text(encoding="utf-8"))
        if not isinstance(locate_streamer(username)(tree), ast.Call):
            raise ConfigEditError(
                "Dieser Streamer ist nicht in der Liste oder nicht änderbar."
            )
        if not isinstance(locate_streamer_settings(username)(tree), ast.Call):
            ensure_imports(config_path, [CLASS_IMPORTS["StreamerSettings"]])
            write_keywords(
                config_path,
                locate_streamer(username),
                {"settings": "StreamerSettings()"},
            )
        write_keywords(config_path, locate_streamer_settings(username), rendered)
    else:
        raise ConfigEditError("Nicht unterstützte Aktion.")


def update(config_path, payload):
    if not isinstance(payload, dict):
        raise ConfigEditError("Die Änderung muss ein JSON-Objekt sein.")
    backup_before_write(config_path)
    if payload.get("action") in EXTRA_ACTIONS:
        with CONFIG_FILE_MUTEX:
            migrate_web_config(config_path)
            apply_extra(config_path, payload)
        return read_state(config_path)
    update_managed_web_config(config_path, payload)
    return read_state(config_path)


def with_defaults(spec, found):
    result = {}
    for name, definition in spec.items():
        value = found.get(name) if isinstance(found, dict) else None
        if value is None:
            value = definition[-1]
        result[name] = value
    return result


def read_extras(config_path):
    tree = ast.parse(Path(config_path).read_text(encoding="utf-8"))
    miner = _simple_value(_assignment(tree, "MINER_CONFIG")) or {}
    mine = _simple_value(_assignment(tree, "MINE_CONFIG")) or {}
    logger_settings = miner.get("logger_settings")
    defaults = miner.get("streamer_settings")
    bet = defaults.get("bet") if isinstance(defaults, dict) else None
    watch_streak = {}
    listing = _assignment(tree, "STREAMERS")
    for node in getattr(listing, "elts", []):
        name = _streamer_key(node)
        if name is None:
            continue
        settings = None
        if isinstance(node, ast.Call):
            keyword = _call_keyword(node, "settings")
            settings = (
                keyword.value
                if keyword is not None
                else (node.args[1] if len(node.args) > 1 else None)
            )
        parsed = _simple_value(settings) if settings is not None else None
        value = parsed.get("watch_streak") if isinstance(parsed, dict) else None
        watch_streak[name] = value
    eranio = _simple_value(_assignment(tree, ERANIO_BLOCK)) or {}
    return {
        "miner": with_defaults(MINER_SPEC, miner),
        "eranio": with_defaults(ERANIO_SPEC, eranio),
        "logger": with_defaults(LOGGER_SPEC, logger_settings),
        "defaults": with_defaults(DEFAULTS_SPEC, defaults),
        "bet": with_defaults(BET_SPEC, bet),
        "mine": with_defaults(MINE_SPEC, mine),
        "streamer_watch_streak": watch_streak,
        "has_bet": isinstance(bet, dict),
    }


def read_state(config_path):
    state = read_managed_web_config(config_path)
    state["extras"] = read_extras(config_path)
    return state
