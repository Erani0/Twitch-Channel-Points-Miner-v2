import logging
import os
import sys
from pathlib import Path

from TwitchChannelPointsMiner import runner
from TwitchChannelPointsMiner.eranio import config_file

logger = logging.getLogger(__name__)

LEGACY_ENV = "ERANIO_LEGACY_RUN"


def default_base_directory():
    main = sys.modules.get("__main__")
    found = getattr(main, "__file__", None)
    return Path(found).resolve().parent if found else Path.cwd()


def run_legacy(legacy_run_py, reason):
    legacy = Path(legacy_run_py)
    print(
        f"Hinweis: {reason} Die bisherige Startdatei {legacy.name} läuft unverändert weiter.",
        file=sys.stderr,
        flush=True,
    )
    if not legacy.is_file():
        raise RuntimeError(f"Startdatei nicht gefunden: {legacy}")
    environment = os.environ.copy()
    environment[LEGACY_ENV] = "1"
    os.execve(sys.executable, [sys.executable, "-u", str(legacy)], environment)


def prepare(config_dir, legacy_run_py):
    config_dir = Path(config_dir)
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "config.py"
    if path.is_file() or legacy_run_py is None or not Path(legacy_run_py).is_file():
        return None
    try:
        config_file.convert(legacy_run_py, path)
    except Exception as error:
        return f"Die Einstellungen konnten nicht übernommen werden ({error})."
    return None


def create_first_config(config_dir, port):
    username = os.environ.get("TWITCH_USER", "").strip()
    if not username:
        return "FEHLER: Es ist kein Twitch-Benutzername gesetzt (Variable TWITCH_USER)."
    try:
        config_file.create_default(
            Path(config_dir) / "config.py", username, port or 5000
        )
    except Exception as error:
        return f"FEHLER: Die Datei config.py konnte nicht angelegt werden ({error})."
    return None


def run(
    port=None, config_password=None, host=None, config_dir=None, legacy_run_py=None
):
    base = default_base_directory()
    try:
        from TwitchChannelPointsMiner.eranio import upgrade

        if upgrade.refresh_thin(base / "run.py"):
            print(
                "Die Startdatei run.py wurde auf den aktuellen Stand gebracht.",
                flush=True,
            )
    except Exception as error:
        logger.debug("run.py refresh failed: %s", error)
    config_dir = Path(config_dir) if config_dir else base / "config"
    if legacy_run_py is None:
        for name in ("run.py.v2-sicherung", "run.py.old"):
            if (base / name).is_file():
                legacy_run_py = base / name
                break
    if port is not None:
        os.environ[config_file.ENV_PORT] = str(int(port))
    if host:
        os.environ[config_file.ENV_HOST] = str(host)
    if isinstance(config_password, str) and config_password:
        os.environ[config_file.ENV_PASSWORD] = config_password
    failure = prepare(config_dir, legacy_run_py)
    if failure is not None:
        return run_legacy(legacy_run_py, failure)
    if not (config_dir / "config.py").is_file() and legacy_run_py is None:
        failure = create_first_config(config_dir, port)
        if failure is not None:
            print(failure, file=sys.stderr, flush=True)
            return 1
        print(
            "Die Datei config/config.py wurde mit Standardwerten angelegt. Der Miner startet jetzt.",
            flush=True,
        )
    if not (config_dir / "config.py").is_file():
        print(
            "FEHLER: Es gibt weder eine Datei config.py noch eine alte Startdatei zum Übernehmen.",
            file=sys.stderr,
            flush=True,
        )
        return 1
    arguments = ["--config-dir", str(config_dir)]
    if legacy_run_py is not None:
        arguments += ["--legacy-runner", str(legacy_run_py)]
    try:
        return runner.main(arguments)
    except RuntimeError as error:
        print(f"FEHLER: {error}", file=sys.stderr, flush=True)
        return 1
