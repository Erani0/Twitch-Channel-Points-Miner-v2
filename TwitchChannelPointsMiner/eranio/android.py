import logging
import os
import sys
import threading
from pathlib import Path

from TwitchChannelPointsMiner.classes.TwitchLogin import (
    TwitchLogin,
    parse_android_login,
)
from TwitchChannelPointsMiner.constants import (
    ANDROID_CLIENT_ID,
    ANDROID_LOGIN_ENV_VAR,
    ANDROID_LOGIN_URL,
    USER_AGENTS,
)

logger = logging.getLogger(__name__)

SUBMIT_LOCK = threading.Lock()
NEWLINE = bytes([10])


class AndroidState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.username = None
        self.active = False
        self.cookies_dir = None
        self.offered = False
        self.thread = None
        self.message = None


STATE = AndroidState()


def configure(username, active, cookies_dir=None):
    STATE.username = username
    STATE.active = bool(active)
    STATE.cookies_dir = cookies_dir


def cookie_file(username=None):
    name = username or STATE.username
    base = STATE.cookies_dir or os.path.join(Path().absolute(), "cookies")
    return os.path.join(base, f"{name}-android.pkl")


def stored():
    return bool(STATE.username) and os.path.isfile(cookie_file())


def status():
    return {
        "stored": stored(),
        "active": STATE.active,
        "link": ANDROID_LOGIN_URL,
        "env_var": ANDROID_LOGIN_ENV_VAR,
    }


def submit(text):
    if not STATE.username:
        return False, "Der Miner ist noch nicht bereit."
    token = parse_android_login(text)
    if not token:
        return False, "In der Eingabe wurde kein Zugangstoken gefunden."
    with SUBMIT_LOCK:
        login = TwitchLogin(
            ANDROID_CLIENT_ID,
            os.urandom(16).hex(),
            STATE.username,
            USER_AGENTS["Android"]["App"],
        )
        try:
            accepted = login._TwitchLogin__accept_android_token(token)
        except Exception:
            accepted = False
        if not accepted:
            return (
                False,
                "Twitch hat den Token nicht angenommen. Er muss mit dem Android-Link "
                "und dem richtigen Konto erzeugt worden sein.",
            )
        try:
            Path(cookie_file()).parent.mkdir(parents=True, exist_ok=True)
            login.save_cookies(cookie_file())
        except OSError:
            return False, "Die Anmeldung konnte nicht gespeichert werden."
    if STATE.active:
        message = "Gespeichert. Der Android-Login ist bereits aktiv."
    else:
        message = (
            "Gespeichert. Aktiv nach dem nächsten Neustart, sobald "
            '"Android-Login nutzen" eingeschaltet ist.'
        )
    STATE.message = message
    logger.info("Android-Login gespeichert. %s", message)
    return True, message


def instructions():
    return [
        "Optional: Android-Login für alle Drops anbieten.",
        f"1. Als {STATE.username} bei Twitch angemeldet diesen Link öffnen: {ANDROID_LOGIN_URL}",
        "2. Twitch zeigt eine leere Seite. Die Adresse (twitch.tv/#access_token=...) "
        "aus dem Browserverlauf kopieren.",
        "3. Die Adresse hier in der Konsole eingeben, auf der Einstellungsseite einfügen "
        f"oder in der Variable {ANDROID_LOGIN_ENV_VAR} setzen.",
        "Der Miner läuft ohne Android-Login normal weiter.",
    ]


def handle_line(line):
    text = line.strip()
    if not text or not parse_android_login(text):
        return
    try:
        ok, message = submit(text)
    except Exception:
        ok, message = False, "Der Token konnte nicht geprüft werden."
    if not ok:
        logger.warning("Android-Login: %s", message)


def read_descriptor(descriptor):
    buffer = b""
    while True:
        try:
            chunk = os.read(descriptor, 4096)
        except (OSError, ValueError):
            return
        if not chunk:
            return
        buffer += chunk
        if len(buffer) > 65536:
            buffer = b""
            continue
        while NEWLINE in buffer:
            line, buffer = buffer.split(NEWLINE, 1)
            handle_line(line.decode("utf-8", "ignore"))


def read_stream(stream):
    while True:
        try:
            line = stream.readline()
        except (OSError, ValueError):
            return
        if not line:
            return
        handle_line(line)


def start_console_reader(stream=None):
    stream = stream if stream is not None else sys.stdin
    if stream is None or getattr(stream, "closed", False):
        return None
    try:
        descriptor = stream.fileno()
    except (OSError, ValueError, AttributeError):
        descriptor = None
        if not hasattr(stream, "readline"):
            return None
    if descriptor is not None:
        target, argument = read_descriptor, descriptor
    else:
        target, argument = read_stream, stream
    thread = threading.Thread(
        target=target, args=(argument,), name="Android login input", daemon=True
    )
    thread.start()
    STATE.thread = thread
    return thread


def read_environment():
    supplied = os.environ.get(ANDROID_LOGIN_ENV_VAR)
    if not supplied or not parse_android_login(supplied):
        return None
    thread = threading.Thread(
        target=lambda: submit(supplied), name="Android login env", daemon=True
    )
    thread.start()
    return thread


def offer(stream=None):
    if STATE.offered or not STATE.username:
        return False
    STATE.offered = True
    if stored():
        return False
    for line in instructions():
        logger.info(line)
    read_environment()
    start_console_reader(stream)
    return True
