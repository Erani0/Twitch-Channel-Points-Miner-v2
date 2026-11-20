import ast
import logging
import os
import shutil
import sys
import time
from pathlib import Path

from TwitchChannelPointsMiner.eranio import config_file

logger = logging.getLogger(__name__)

BACKUP_NAME = "run.py.v2-sicherung"
TEMPLATE = Path(__file__).resolve().parent / "templates" / "run.py"
PASSWORD_LINE = 'CONFIG_PASSWORD = os.environ.get("CONFIG_PASSWORD", "")'
THIN_MARKER = "eranio.launcher import run"
SKIP_ENV = "ERANIO_LEGACY_RUN"


def thin_source(config_password=""):
    text = TEMPLATE.read_text(encoding="utf-8")
    if config_password:
        replacement = (
            f'CONFIG_PASSWORD = os.environ.get("CONFIG_PASSWORD", {config_password!r})'
        )
        if PASSWORD_LINE not in text:
            raise RuntimeError(
                "Die Vorlage der Startdatei enthält die Passwortzeile nicht."
            )
        text = text.replace(PASSWORD_LINE, replacement)
    return text


def is_thin(source):
    return THIN_MARKER in source


def is_old_run_py(source):
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return not is_thin(source) and bool(
        config_file._find_calls(tree, "TwitchChannelPointsMiner")
    )


def _literal_string(node, assigned):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in assigned:
        return _literal_string(assigned[node.id], {})
    return ""


def old_config_password(source):
    tree = ast.parse(source)
    assigned = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            assigned.setdefault(node.targets[0].id, node.value)
    for call in config_file._find_calls(tree, "analytics"):
        for keyword in call.keywords:
            if keyword.arg == "config_password":
                return _literal_string(keyword.value, assigned)
    return ""


def _backup_target(run_py):
    target = run_py.with_name(BACKUP_NAME)
    if target.exists():
        target = run_py.with_name(f"{BACKUP_NAME}.{time.strftime('%Y%m%d-%H%M%S')}")
    return target


def _verify_config(config_path):
    from TwitchChannelPointsMiner import runner

    module = runner._load_config(config_path)
    if not isinstance(module.STREAMERS, list) or "username" not in module.MINER_CONFIG:
        raise RuntimeError("Die übernommene Konfiguration ist unvollständig.")
    return module


def _remove_config(config_dir):
    for name in ("config.py", ".converted-from-run-py", "config.py.migrating"):
        try:
            (config_dir / name).unlink(missing_ok=True)
        except OSError:
            pass


def convert_installation(run_py):
    run_py = Path(run_py).resolve()
    source = run_py.read_text(encoding="utf-8")
    if not is_old_run_py(source):
        return None
    config_dir = run_py.parent / "config"
    config_path = config_dir / "config.py"
    password = old_config_password(source)
    thin = thin_source(password)
    ast.parse(thin)
    created = False
    try:
        if config_path.exists():
            _verify_config(config_path)
        else:
            config_dir.mkdir(parents=True, exist_ok=True)
            created = True
            config_file.convert(run_py, config_path)
            _verify_config(config_path)
        backup = _backup_target(run_py)
        shutil.copy2(run_py, backup)
        temporary = run_py.with_name(run_py.name + ".neu")
        temporary.write_text(thin, encoding="utf-8", newline="\n")
        os.replace(temporary, run_py)
    except BaseException:
        if created:
            _remove_config(config_dir)
        run_py.with_name(run_py.name + ".neu").unlink(missing_ok=True)
        raise
    return backup


def switch_if_needed(file_path, argv=None):
    if os.environ.get(SKIP_ENV) == "1":
        return False
    run_py = Path(file_path)
    argv = sys.argv if argv is None else argv
    try:
        if run_py.name != "run.py" or not argv:
            return False
        if os.path.abspath(argv[0]) != os.path.abspath(run_py):
            return False
        backup = convert_installation(run_py)
    except Exception as error:
        print(
            f"Hinweis: Die Einstellungen konnten nicht in die neue Form übernommen werden ({error}). "
            "Die bisherige Startdatei läuft unverändert weiter.",
            file=sys.stderr,
            flush=True,
        )
        return False
    if backup is None:
        return False
    print(
        f"Die Einstellungen wurden in config/config.py übernommen. Die bisherige Startdatei liegt als {backup.name} bereit.",
        flush=True,
    )
    os.execv(
        sys.executable,
        [sys.executable, "-u", os.path.abspath(run_py), *argv[1:]],
    )
    return True
