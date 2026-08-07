"""Safely add new, missing keyword arguments to a constructor call (e.g. in a
user's own run.py) without touching anything else in the file.

run.py is per-user and untracked by git (see .gitignore), so a new parameter on
TwitchChannelPointsMiner's constructor never reaches an existing installation on
its own. This module lets run.py's own auto-updater patch itself with any new,
missing settings (using their safe defaults) whenever the core package updates,
without disturbing the user's own customizations (streamer list, existing
values, comments, formatting).

Only ever ADDS missing keyword arguments. Never changes or removes anything
that's already there, and never writes a file that doesn't parse as valid
Python afterwards - any failure leaves the original file untouched.
"""

import ast
import inspect
import logging
import os
import time

logger = logging.getLogger(__name__)


def discover_new_constructor_kwargs(cls) -> dict[str, str]:
    """Read cls.__init__'s own signature and return every optional parameter
    that has a plain literal default (bool/int/float/str/None) as a
    name -> Python source expression mapping, suitable for ensure_constructor_kwargs.

    This is the single source of truth: whoever adds a new optional setting to
    the constructor (e.g. `auto_discover_drops: bool = False`) doesn't need to
    register it anywhere else - it shows up here automatically. Required
    parameters (no default, e.g. username/password) and parameters whose
    default isn't a simple literal (e.g. `logger_settings=LoggerSettings()`)
    are skipped, since those aren't "new toggle" style settings and can't be
    safely reproduced as source text without knowing the caller's imports.
    """
    discovered: dict[str, str] = {}
    try:
        signature = inspect.signature(cls.__init__)
    except (TypeError, ValueError):
        return discovered

    for name, param in signature.parameters.items():
        if name == "self" or param.default is inspect.Parameter.empty:
            continue
        literal = _safe_literal_repr(param.default)
        if literal is not None:
            discovered[name] = literal
    return discovered


def _safe_literal_repr(value) -> str | None:
    if value is None or isinstance(value, (bool, int, float, str)):
        return repr(value)
    return None


def ensure_constructor_kwargs(
    file_path: str, class_name: str, expected_kwargs: dict[str, str]
) -> bool:
    """Ensure the `class_name(...)` call in file_path includes each keyword in
    expected_kwargs (name -> Python source expression to use as its default,
    e.g. {"auto_discover_drops": "False"}).

    Returns True if the file was modified, False otherwise (nothing to add, the
    call couldn't be found/patched safely, or an error occurred - in all of
    these cases the file is left exactly as it was).
    """
    if not expected_kwargs:
        return False

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            original_source = f.read()
    except OSError as exc:
        logger.warning("run_config_migration: could not read %s: %s", file_path, exc)
        return False

    try:
        tree = ast.parse(original_source)
    except SyntaxError as exc:
        logger.warning(
            "run_config_migration: %s is not valid Python, leaving it untouched: %s",
            file_path,
            exc,
        )
        return False

    call_node = _find_call(tree, class_name)
    if call_node is None:
        logger.debug(
            "run_config_migration: no %s(...) call found in %s, nothing to migrate",
            class_name,
            file_path,
        )
        return False

    if call_node.end_lineno is None or call_node.end_lineno == call_node.lineno:
        # Single-line call - inserting a new line here would land outside the
        # parentheses. Too risky to patch automatically; ask the user instead.
        logger.warning(
            "run_config_migration: %s(...) call in %s is on a single line, "
            "please add the following manually: %s",
            class_name,
            file_path,
            ", ".join(f"{name}={default}" for name, default in expected_kwargs.items()),
        )
        return False

    existing_kwarg_names = {kw.arg for kw in call_node.keywords if kw.arg is not None}
    missing = {
        name: default
        for name, default in expected_kwargs.items()
        if name not in existing_kwarg_names
    }
    if not missing:
        return False

    lines = original_source.splitlines(keepends=True)
    indent = _detect_arg_indent(lines, call_node)
    new_lines = "".join(f"{indent}{name}={default},\n" for name, default in missing.items())

    patched_lines = list(lines)
    patched_lines.insert(call_node.lineno, new_lines)
    patched_source = "".join(patched_lines)

    try:
        ast.parse(patched_source)
    except SyntaxError as exc:
        logger.warning(
            "run_config_migration: patch would break %s, leaving it untouched: %s",
            file_path,
            exc,
        )
        return False

    timestamp = int(time.time())
    backup_path = f"{file_path}.bak-{timestamp}"
    tmp_path = f"{file_path}.tmp-{timestamp}"
    try:
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(original_source)
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(patched_source)
        os.replace(tmp_path, file_path)
    except OSError as exc:
        logger.warning("run_config_migration: failed to write %s: %s", file_path, exc)
        return False

    logger.info(
        "run_config_migration: added new setting(s) %s to %s (backup: %s)",
        ", ".join(missing.keys()),
        file_path,
        backup_path,
    )
    return True


def _find_call(tree: ast.AST, class_name: str):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else (
                func.attr if isinstance(func, ast.Attribute) else None
            )
            if name == class_name:
                return node
    return None


def _detect_arg_indent(lines: list[str], call_node: ast.Call) -> str:
    # Match the indentation of an existing keyword argument's line so the
    # inserted line fits the user's own formatting.
    for kw in call_node.keywords:
        if kw.value is not None:
            line = lines[kw.value.lineno - 1]
            stripped = line.lstrip(" ")
            return line[: len(line) - len(stripped)]
    # No existing keyword args to copy from - indent one level past the call itself.
    call_line = lines[call_node.lineno - 1]
    stripped = call_line.lstrip(" ")
    base_indent = call_line[: len(call_line) - len(stripped)]
    return base_indent + "    "
