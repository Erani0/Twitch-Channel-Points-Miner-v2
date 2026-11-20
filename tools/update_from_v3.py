import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_FILE = ROOT / "TwitchChannelPointsMiner" / "eranio" / "V3_BASE"
INIT_FILE = "TwitchChannelPointsMiner/__init__.py"
VERSION_PATTERN = re.compile(r'^__version__\s*=\s*"[^"]*".*$', re.M)
CONFLICT_PATTERN = re.compile(
    r"<<<<<<< [^\n]*\n(?P<ours>.*?)=======\n(?P<theirs>.*?)>>>>>>> [^\n]*\n", re.S
)


def git(*args, check=True):
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8"
    )
    if check and result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} fehlgeschlagen: {result.stderr.strip()}")
    return result


def version_of(ref):
    text = git("show", f"{ref}:{INIT_FILE}").stdout
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
    if not match:
        raise SystemExit("Die Versionsnummer der Basis konnte nicht gelesen werden.")
    return match.group(1)


def read_base():
    parts = BASE_FILE.read_text(encoding="utf-8").split()
    return parts[0], parts[1]


def resolve_version_conflict(path):
    text = path.read_text(encoding="utf-8")

    def merge_sides(match):
        ours, theirs = match.group("ours"), match.group("theirs")
        if "__version__" not in ours + theirs:
            raise ValueError("Konflikt außerhalb der Versionszeile")
        own_line = VERSION_PATTERN.search(ours)
        merged = VERSION_PATTERN.sub(lambda found: own_line.group(0) if own_line else found.group(0), theirs)
        theirs_lines = set(theirs.splitlines())
        extra = [
            line
            for line in ours.splitlines()
            if line not in theirs_lines and "__version__" not in line
        ]
        return merged + "".join(line + chr(10) for line in extra)

    resolved = CONFLICT_PATTERN.sub(merge_sides, text)
    path.write_text(resolved, encoding="utf-8")


def restore_own_version(own_line):
    path = ROOT / INIT_FILE
    text = path.read_text(encoding="utf-8")
    path.write_text(VERSION_PATTERN.sub(lambda match: own_line, text, count=1), encoding="utf-8")


def run_tests():
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q", "--ignore=tests/test_windows_launcher.py"],
        cwd=ROOT,
    ).returncode


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", default=os.environ.get("V3_REMOTE", "v3"))
    parser.add_argument("--branch", default=os.environ.get("V3_BRANCH", "master"))
    parser.add_argument("--no-tests", action="store_true")
    parser.add_argument("--notes-out")
    args = parser.parse_args(argv)

    if git("status", "--porcelain").stdout.strip():
        print("Es gibt nicht gespeicherte Änderungen. Bitte zuerst speichern oder verwerfen.")
        return 2
    if git("remote", "get-url", args.remote, check=False).returncode != 0:
        print(f"Die Gegenstelle '{args.remote}' ist nicht eingerichtet (git remote add {args.remote} <Adresse>).")
        return 2
    git("fetch", args.remote, "--tags")
    target = f"{args.remote}/{args.branch}"
    target_sha = git("rev-parse", "--short=7", target).stdout.strip()
    base_version, base_sha = read_base()
    if git("merge-base", "--is-ancestor", target, "HEAD", check=False).returncode == 0:
        print(f"Die Basis ist bereits aktuell (Stand {base_version}, {base_sha}).")
        return 3
    new_version = version_of(target)
    original = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    branch = f"update/v3-{new_version}"
    if git("rev-parse", "--verify", branch, check=False).returncode == 0:
        print(f"Der Zweig {branch} gibt es schon.")
        return 2
    own_line = VERSION_PATTERN.search((ROOT / INIT_FILE).read_text(encoding="utf-8")).group(0)
    git("switch", "-c", branch)
    merge = git("merge", "--no-ff", "--no-commit", target, check=False)
    conflicts = [
        name
        for name in git("diff", "--name-only", "--diff-filter=U").stdout.split("\n")
        if name
    ]
    unresolved = []
    for name in conflicts:
        if name == INIT_FILE:
            try:
                resolve_version_conflict(ROOT / name)
                git("add", name)
                continue
            except ValueError:
                pass
        unresolved.append(name)
    if unresolved:
        git("merge", "--abort", check=False)
        git("switch", original)
        git("branch", "-D", branch)
        print("Die Zusammenführung hat Konflikte, die von Hand gelöst werden müssen:")
        for name in unresolved:
            print(f"  {name}")
        return 1
    restore_own_version(own_line)
    git("add", INIT_FILE)
    BASE_FILE.write_text(f"{new_version} {target_sha}\n", encoding="utf-8")
    git("add", str(BASE_FILE.relative_to(ROOT)))
    log = git("log", "--oneline", f"{base_sha}..{target}", check=False).stdout.strip()
    notes = f"Neue Basis {new_version} ({target_sha}), bisher {base_version} ({base_sha}).\n\nÄnderungen:\n{log}\n"
    if args.notes_out:
        Path(args.notes_out).write_text(notes, encoding="utf-8")
    result = 0 if args.no_tests else run_tests()
    git("commit", "-m", f"Merge base update {new_version} into {branch}")
    print(f"Zweig {branch} angelegt (nichts wurde hochgeladen).")
    print(f"Basis: {base_version} -> {new_version}")
    if args.no_tests:
        print("Tests: nicht ausgeführt")
    else:
        print("Tests: bestanden" if result == 0 else "Tests: FEHLGESCHLAGEN, bitte prüfen")
    print("Übernahme nach master nur nach Prüfung und Freigabe.")
    return 0 if result == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
