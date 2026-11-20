import ast
import inspect
import os
import time

_PREFIX = "run_config_migration:"

def discover_new_constructor_kwargs(cls) -> dict[str, str]:
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
    if not expected_kwargs:
        return False

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            original_source = f.read()
    except OSError as exc:
        print(f"{_PREFIX} could not read {file_path}: {exc}")
        return False

    try:
        tree = ast.parse(original_source)
    except SyntaxError as exc:
        print(
            f"{_PREFIX} {file_path} is not valid Python, leaving it untouched: {exc}"
        )
        return False

    call_node = _find_call(tree, class_name)
    if call_node is None:
        return False

    if call_node.end_lineno is None or call_node.end_lineno == call_node.lineno:
        pending = ", ".join(f"{name}={default}" for name, default in expected_kwargs.items())
        print(
            f"{_PREFIX} {class_name}(...) call in {file_path} is on a single line, "
            f"please add the following manually: {pending}"
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
        print(f"{_PREFIX} patch would break {file_path}, leaving it untouched: {exc}")
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
        print(f"{_PREFIX} failed to write {file_path}: {exc}")
        return False

    added = ", ".join(missing.keys())
    print(f"{_PREFIX} added new setting(s) {added} to {file_path} (backup: {backup_path})")
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
    for kw in call_node.keywords:
        if kw.value is not None:
            line = lines[kw.value.lineno - 1]
            stripped = line.lstrip(" ")
            return line[: len(line) - len(stripped)]
    call_line = lines[call_node.lineno - 1]
    stripped = call_line.lstrip(" ")
    base_indent = call_line[: len(call_line) - len(stripped)]
    return base_indent + "    "
