import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from TwitchChannelPointsMiner import runner
from TwitchChannelPointsMiner.eranio import config_file, launcher, upgrade

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "eranio_egg_run.py"
EXCLUDED = ("tests/", "docs/", ".github/")
MARKER = "ANMELDEPHASE ERREICHT"
USER = "probe_konto"

HOOK = textwrap.dedent(
    """
    import importlib.abc
    import importlib.util
    import os
    import sys
    import urllib.request

    def _offline(*args, **kwargs):
        raise OSError("offline")

    urllib.request.urlopen = _offline
    TARGET = "TwitchChannelPointsMiner.classes.Twitch"

    class Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path, target=None):
            if name != TARGET:
                return None
            sys.meta_path.remove(self)
            spec = importlib.util.find_spec(name)
            original = spec.loader.exec_module

            def exec_module(module):
                original(module)

                def login(self_, *args, **kwargs):
                    print("%s", flush=True)
                    os._exit(0)

                module.Twitch.login = login

            spec.loader.exec_module = exec_module
            return spec

    sys.meta_path.insert(0, Finder())
    """
    % MARKER
)


def git(*args, cwd, check=True):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_CONFIG_GLOBAL": str(Path(cwd).parent / "gitconfig")},
    )


def old_egg_run_py():
    source = subprocess.check_output(
        [
            "git",
            "show",
            "v2-final-2.6.4:egg-twitch-channel-points-miner/egg-twitch-channel-points-miner-python-auto--install.yaml",
        ],
        cwd=ROOT,
    ).decode("utf-8")
    body = re.search(r"cat << 'EOF' > /mnt/server/run.py\n(.*?)\n      EOF\n", source, re.S).group(1)
    text = "\n".join(line[6:] if line.startswith("      ") else line for line in body.split("\n"))
    return text.replace("claim_drops_startup=True,", "claim_drops_startup=True,\n        auto_discover_drops=True,", 1)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(folder):
    return {
        str(path.relative_to(folder)): sha(path)
        for path in sorted(Path(folder).rglob("*"))
        if path.is_file()
    }


@pytest.fixture(scope="module")
def rehearsal(tmp_path_factory):
    if shutil.which("git") is None:
        pytest.skip("git fehlt")
    top = tmp_path_factory.mktemp("umstieg")
    origin = top / "origin"
    origin.mkdir()
    git("init", "-b", "master", cwd=origin)
    tracked = subprocess.check_output(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT
    ).decode("utf-8").split("\0")
    for name in tracked:
        source = ROOT / name
        if not name or name.startswith(EXCLUDED) or not source.is_file():
            continue
        target = origin / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    git("add", "-A", "-f", cwd=origin)
    git("-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-q", "-m", "neuer master", cwd=origin)

    install = top / "install"
    clone = subprocess.run(
        ["git", "clone", "-q", "--depth", "1", "--no-single-branch", "--branch", "v2-final-2.6.4", (ROOT).as_uri(), str(install)],
        capture_output=True,
        text=True,
    )
    if clone.returncode != 0:
        pytest.skip(f"alter Stand nicht verfügbar: {clone.stderr}")
    git("remote", "set-url", "origin", str(origin), cwd=install)
    assert '__version__ = "2.6' in (install / "TwitchChannelPointsMiner" / "__init__.py").read_text(encoding="utf-8")

    (install / "run.py").write_text(old_egg_run_py(), encoding="utf-8", newline="\n")
    (install / ".setup_done").write_text("done")
    (install / "cookies").mkdir(exist_ok=True)
    (install / "cookies" / f"{USER}.pkl").write_bytes(b"\x80\x04]\x94.")
    (install / "logs").mkdir(exist_ok=True)
    (install / "logs" / f"watch_streak_cache.{USER}.json").write_text(
        '{"version": 4, "streamers": {}}', encoding="utf-8"
    )
    (install / "analytics" / USER).mkdir(parents=True, exist_ok=True)
    (install / "analytics" / USER / "zicke8.json").write_text('{"series": []}', encoding="utf-8")
    (install / "drop_campaigns.json").write_text('{"kampagnen": []}', encoding="utf-8")
    hooks = top / "hooks"
    hooks.mkdir()
    (hooks / "sitecustomize.py").write_text(HOOK, encoding="utf-8")
    return type("Rehearsal", (), {"top": top, "install": install, "origin": origin, "hooks": hooks})


def start(rehearsal, directory=None):
    environment = {
        **os.environ,
        "PYTHONPATH": str(rehearsal.hooks),
        "TWITCH_USER": USER,
        "GIT_CONFIG_GLOBAL": str(rehearsal.top / "gitconfig"),
        "PYTHONIOENCODING": "utf-8",
    }
    environment.pop("ERANIO_LEGACY_RUN", None)
    return subprocess.run(
        [sys.executable, "-u", "run.py", "--port", "5999"],
        cwd=directory or rehearsal.install,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=240,
    )


USER_FILES = (
    f"cookies/{USER}.pkl",
    f"logs/watch_streak_cache.{USER}.json",
    f"analytics/{USER}/zicke8.json",
    "drop_campaigns.json",
)


def test_old_installation_switches_to_the_thin_start_file(rehearsal):
    install = rehearsal.install
    original = (install / "run.py").read_bytes()
    before = {name: sha(install / name) for name in USER_FILES}

    result = start(rehearsal)
    output = result.stdout + result.stderr

    assert "Updates gefunden" in output
    assert MARKER in output, output
    backup = install / "run.py.v2-sicherung"
    assert backup.read_bytes() == original
    assert (install / "run.py").read_text(encoding="utf-8") == upgrade.thin_source()
    unchanged = [name for name in USER_FILES if not name.startswith("analytics/")]
    assert {name: sha(install / name) for name in unchanged} == {name: before[name] for name in unchanged}
    analytics = install / "analytics" / USER
    assert sha(analytics / "zicke8.json.v0.bak") == before[f"analytics/{USER}/zicke8.json"]
    assert json.loads((analytics / "zicke8.json").read_text(encoding="utf-8"))["series"] == []

    config = install / "config" / "config.py"
    module = runner._load_config(config)
    assert len(module.STREAMERS) == 14
    assert "TWITCH_USER" in config.read_text(encoding="utf-8")
    assert module.MINER_CONFIG["claim_drops_startup"] is True
    assert module.ANALYTICS_CONFIG["port"] == 5999 or module.ANALYTICS_CONFIG["host"] == "0.0.0.0"
    assert module.ERANIO_CONFIG["auto_discover_drops"] is True
    assert module.ERANIO_CONFIG["watch_streak_max_parallel"] == 2
    assert "password" not in module.MINER_CONFIG


def test_second_start_changes_nothing(rehearsal):
    install = rehearsal.install
    names = ("run.py", "run.py.v2-sicherung", "config/config.py", *USER_FILES)
    before = {name: sha(install / name) for name in names}
    files_before = sorted(path.name for path in install.glob("run.py*"))

    result = start(rehearsal)

    assert MARKER in result.stdout + result.stderr
    assert {name: sha(install / name) for name in names} == before
    assert sorted(path.name for path in install.glob("run.py*")) == files_before



EGG = "egg-twitch-channel-points-miner/egg-twitch-channel-points-miner-python-auto--install.yaml"


def bash():
    for candidate in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
        shutil.which("bash"),
    ):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip("bash fehlt")


def egg_yaml(new):
    import yaml

    if new:
        return yaml.safe_load((ROOT / EGG).read_text(encoding="utf-8"))
    return yaml.safe_load(subprocess.check_output(["git", "show", f"v2-final-2.6.4:{EGG}"], cwd=ROOT).decode("utf-8"))


def run_install_script(rehearsal, new, directory):
    script = egg_yaml(new)["scripts"]["installation"]["script"]
    lines = [line for line in script.split("\n") if not line.strip().startswith("apt-get")]
    script = "\n".join(lines).replace("/mnt/server", Path(directory).as_posix())
    script = script.replace("https://github.com/Erani0/Twitch-Channel-Points-Miner-v2.git", rehearsal.origin.as_posix())
    result = subprocess.run(
        [bash(), "-s"],
        input=script,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env={**os.environ, "GIT_CONFIG_GLOBAL": str(rehearsal.top / "gitconfig")},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    (Path(directory) / ".setup_done").write_text("done")


def test_egg_update_keeps_startup_command_variables_and_identity():
    old, new = egg_yaml(False), egg_yaml(True)
    assert new["startup_commands"] == old["startup_commands"]
    assert new["startup_commands"]["Default"] == "python -u /home/container/run.py --port {{SERVER_PORT}}"
    for key in ("uuid", "docker_images", "meta", "config"):
        assert new[key] == old[key]
    old_vars = {v["env_variable"]: v for v in old["variables"]}
    new_vars = {v["env_variable"]: v for v in new["variables"]}
    assert set(old_vars) <= set(new_vars)
    for name in set(new_vars) - set(old_vars):
        assert new_vars[name]["default_value"] == ""
        assert "required" not in new_vars[name]["rules"]
    assert "required" not in new_vars["TWITCH_PASS"]["rules"]


def test_fresh_install_with_the_new_egg_reaches_the_login_stage(rehearsal):
    target = rehearsal.top / "frisch"
    target.mkdir()
    run_install_script(rehearsal, True, target)
    assert (target / "run.py").read_text(encoding="utf-8") == upgrade.thin_source()
    assert not (target / "config" / "config.py").exists()
    result = start(rehearsal, target)
    assert MARKER in result.stdout + result.stderr
    module = runner._load_config(target / "config" / "config.py")
    assert module.MINER_CONFIG["username"] == USER
    assert module.ANALYTICS_CONFIG["host"] == "0.0.0.0"


def user_data(target):
    (target / "cookies").mkdir(exist_ok=True)
    (target / "cookies" / f"{USER}.pkl").write_bytes(b"cookie")
    (target / "logs").mkdir(exist_ok=True)
    (target / "logs" / "miner.log").write_text("log", encoding="utf-8")
    (target / "analytics").mkdir(exist_ok=True)
    (target / "analytics" / "a.json").write_text("{}", encoding="utf-8")
    (target / "drop_campaigns.json").write_text("{}", encoding="utf-8")
    return [f"cookies/{USER}.pkl", "logs/miner.log", "analytics/a.json", "drop_campaigns.json", "config/config.py"]


def test_reinstall_with_the_new_egg_keeps_all_user_data(rehearsal):
    target = rehearsal.top / "neu_neu"
    target.mkdir()
    run_install_script(rehearsal, True, target)
    config_file.create_default(target / "config" / "config.py", "eigener_name", 5000)
    names = user_data(target)
    before = {name: sha(target / name) for name in names}
    run_install_script(rehearsal, True, target)
    assert {name: sha(target / name) for name in names} == before
    assert (target / "run.py").read_text(encoding="utf-8") == upgrade.thin_source()
    assert not list(target.glob("run.py.neu"))


def test_reinstall_with_the_old_egg_does_not_convert_again(rehearsal):
    target = rehearsal.top / "neu_alt"
    target.mkdir()
    run_install_script(rehearsal, True, target)
    config_file.create_default(target / "config" / "config.py", "eigener_name", 5000)
    names = user_data(target)
    before = {name: sha(target / name) for name in names}
    run_install_script(rehearsal, False, target)
    big = (target / "run.py").read_bytes()
    assert b"twitch_miner.mine(" in big
    result = start(rehearsal, target)
    assert MARKER in result.stdout + result.stderr
    after = {name: sha(target / name) for name in names if not name.startswith("analytics/")}
    assert after == {name: before[name] for name in after}
    assert (target / "run.py.v2-sicherung").read_bytes() == big
    assert (target / "run.py").read_text(encoding="utf-8") == upgrade.thin_source()
    assert not (target / "config" / ".converted-from-run-py").exists()


def test_old_password_is_carried_into_the_thin_start_file():
    source = 'TwitchChannelPointsMiner(username="x")\nPW = "geheim"\nm.analytics(host="0.0.0.0", port=1, config_password=PW)\n'
    assert upgrade.old_config_password(source) == "geheim"
    thin = upgrade.thin_source("geheim")
    assert "geheim" in thin and upgrade.is_thin(thin)
    assert upgrade.old_config_password("TwitchChannelPointsMiner()\nm.mine([])\n") == ""
