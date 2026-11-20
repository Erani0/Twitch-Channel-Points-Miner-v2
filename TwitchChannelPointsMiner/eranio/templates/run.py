# -*- coding: utf-8 -*-
import os
import sys
import subprocess

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# --- AUTO-UPDATER & AUTO-INSTALLER VOR DEM EIGENTLICHEN START ---


def _read_version(text):
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip("'\"")
    return None


def _local_version():
    try:
        with open(
            os.path.join("TwitchChannelPointsMiner", "__init__.py"),
            "r",
            encoding="utf-8",
        ) as f:
            return _read_version(f.read())
    except Exception:
        return None


def _remote_version():
    try:
        import urllib.request

        url = "https://raw.githubusercontent.com/Erani0/Twitch-Channel-Points-Miner-v2/refs/heads/master/TwitchChannelPointsMiner/__init__.py"
        with urllib.request.urlopen(url, timeout=15) as resp:
            return _read_version(resp.read().decode("utf-8"))
    except Exception:
        return None


if os.path.exists(".git"):
    print("Suche nach Updates auf GitHub...")
    try:
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", "/home/container"],
            stderr=subprocess.DEVNULL,
        )
        local_hash = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()

        fetch = subprocess.run(
            ["git", "fetch", "--all"], capture_output=True, text=True
        )
        if fetch.returncode != 0:
            print(f"Warnung: 'git fetch' fehlgeschlagen: {fetch.stderr.strip()}")
        remote_hash = subprocess.check_output(
            ["git", "rev-parse", "origin/master"], text=True
        ).strip()

        local_ver = _local_version()
        remote_ver = _remote_version()
        if (
            local_ver is not None
            and remote_ver is not None
            and local_ver != remote_ver
            and local_hash == remote_hash
        ):
            print(
                f"Hinweis: Versionsangabe weicht ab (lokal {local_ver}, GitHub-Metadaten "
                f"{remote_ver}), aber Git meldet denselben Commit-Stand - vermutlich nur "
                "eine kurzzeitig veraltete CDN-Antwort, kein Handlungsbedarf."
            )

        if local_hash != remote_hash:
            print(
                f"Updates gefunden! Aktualisiere von {local_hash[:7]} auf {remote_hash[:7]}..."
            )
            subprocess.run(["git", "reset", "--hard", "origin/master"], check=True)
            if os.path.exists(".setup_done"):
                os.remove(".setup_done")
        else:
            print("Bereits auf dem neuesten Stand.")
    except Exception as e:
        print(f"Hinweis: Update-Pruefung fehlgeschlagen: {e}")

for item in [
    ".agent",
    ".ai",
    ".claude",
    ".github",
    ".vscode",
    ".superpowers",
    "tests",
    ".ai-agent-checkpoints",
    "setup.py",
    "pyproject.toml",
    "uv.lock",
    "egg-twitch-channel-points-miner",
    "Dockerfile",
    "CLAUDE.md",
    "CLONE.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "DELETE_PYCACHE.bat",
    "FAQ.md",
    "FEEDBACK_AUDIT.md",
    "FORK_FEATURES.md",
    "LICENSE",
    "README.md",
    "TRAFFIC.md",
    "example.py",
    "pickle_view.py",
    ".pre-commit-config.yaml",
    ".gitattributes",
]:
    if os.path.exists(item):
        try:
            if os.path.isdir(item):
                import shutil

                shutil.rmtree(item, ignore_errors=True)
            else:
                os.remove(item)
        except Exception:
            pass

MARKER_FILE = ".setup_done"
if not os.path.exists(MARKER_FILE):
    print("=========================================================================")
    print("Installiere/Aktualisiere benoetigte Python-Module...")
    print("HINWEIS: Das kann einige Minuten dauern (pandas, etc.).")
    print("Bitte schliesse diese Konsole nicht und warte ab!")
    print("=========================================================================")
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--user",
                "--no-cache-dir",
                "--upgrade",
                "pip",
            ]
        )

        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--user",
                "--no-cache-dir",
                "-r",
                "requirements.txt",
            ]
        )

        with open(MARKER_FILE, "w") as f:
            f.write("done")

        print("=== Installation erfolgreich! Miner wird nun gestartet... ===")

        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        print(f"Fehler bei der Installation der Abhaengigkeiten: {e}")
        sys.exit(1)


# --- HIER STARTET DER EIGENTLICHE MINER CODE ---
SERVER_PORT = int(os.environ.get("SERVER_PORT", 5000))
for i, arg in enumerate(sys.argv):
    if arg == "--port" and i + 1 < len(sys.argv):
        SERVER_PORT = int(sys.argv[i + 1])
    elif arg.startswith("--port="):
        SERVER_PORT = int(arg.split("=")[1])

CONFIG_PASSWORD = os.environ.get("CONFIG_PASSWORD", "")

from TwitchChannelPointsMiner.eranio.launcher import run

try:
    sys.exit(
        run(port=SERVER_PORT, config_password=CONFIG_PASSWORD, host="0.0.0.0") or 0
    )
except KeyboardInterrupt:
    print("Miner durch Benutzer gestoppt (KeyboardInterrupt). Beende...")
    sys.exit(0)
except Exception as e:
    print("=========================================================================")
    print(f"KRITISCHER FEHLER aufgetreten: {e}")
    print("Miner wird in 15 Sekunden komplett neu gestartet...")
    print("=========================================================================")
    import time

    time.sleep(15)
    os.execv(sys.executable, [sys.executable] + sys.argv)
