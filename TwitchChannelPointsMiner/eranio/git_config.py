import os


def dedupe_git_safe_directories(path=None):
    path = path or os.path.join(os.path.expanduser("~"), ".gitconfig")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return False
    seen = set()
    section = None
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped.lower()
        if section == "[safe]" and stripped.replace(" ", "").startswith("directory="):
            key = stripped.replace(" ", "")
            if key in seen:
                continue
            seen.add(key)
        result.append(line)
    if len(result) == len(lines):
        return False
    temporary = f"{path}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.writelines(result)
        os.replace(temporary, path)
    except OSError:
        return False
    return True
