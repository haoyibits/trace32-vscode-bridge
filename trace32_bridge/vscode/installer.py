from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import Config
from ..errors import BridgeError
from . import jsonc


TASK_ALIASES = {
    "T32: Flash + Debug": "T32: Flash",
    "T32: Load + Debug": "T32: Load ELF",
}
LEGACY_LAUNCH_NAMES = {"1. Flash + Debug", "2. Load + Debug"}
DEVELOPMENT_PATHS = (
    "test",
    "tests",
    ".git",
    ".github",
    "build",
    "dist",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".venv",
    "htmlcov",
    ".coverage",
)
PRESERVED_GENERATED_DIRS = {".run"}
RCL_IMPORT = "import lauterbach.trace32.rcl"


def replace_tokens(value: Any, replacements: dict[str, Any]) -> Any:
    if isinstance(value, list):
        return [replace_tokens(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            key: replace_tokens(item, replacements)
            for key, item in value.items()
        }
    if not isinstance(value, str):
        return value
    if value in replacements:
        return replacements[value]
    result = value
    for token, replacement in replacements.items():
        result = result.replace(token, str(replacement))
    return result


def merge_named_items(
    existing: list[dict[str, Any]],
    template: list[dict[str, Any]],
    *,
    key: str,
    aliases: dict[str, str] | None = None,
    ignored: set[str] | None = None,
) -> list[dict[str, Any]]:
    aliases = aliases or {}
    ignored = ignored or set()
    templates = {item[key]: item for item in template}
    installed: set[str] = set()
    merged: list[dict[str, Any]] = []

    for item in existing:
        raw_name = item.get(key)
        if raw_name in ignored:
            continue
        name = aliases.get(raw_name, raw_name)
        replacement = templates.get(name)
        if replacement is None:
            merged.append(item)
        elif name not in installed:
            merged.append({**item, **replacement})
            installed.add(name)

    for item in template:
        if item[key] not in installed:
            merged.append(item)
    return merged


def merge_document(kind: str, existing: Any, template: Any) -> dict[str, Any]:
    if not isinstance(existing, dict) or not isinstance(template, dict):
        raise BridgeError(f"{kind}.json must contain a JSON object")
    if kind == "tasks":
        if not isinstance(existing.get("tasks"), list) or not isinstance(
            template.get("tasks"), list
        ):
            raise BridgeError("tasks.json must contain a tasks array")
        return {
            **existing,
            "version": template.get("version", "2.0.0"),
            "tasks": merge_named_items(
                existing["tasks"],
                template["tasks"],
                key="label",
                aliases=TASK_ALIASES,
            ),
        }
    if kind == "launch":
        if not isinstance(existing.get("configurations"), list) or not isinstance(
            template.get("configurations"), list
        ):
            raise BridgeError(
                "launch.json must contain a configurations array"
            )
        return {
            **existing,
            "version": template.get("version", "0.2.0"),
            "configurations": merge_named_items(
                existing["configurations"],
                template["configurations"],
                key="name",
                ignored=LEGACY_LAUNCH_NAMES,
            ),
        }
    raise BridgeError(f"unknown VS Code document kind: {kind}")


def backup(path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    candidate = path.with_name(f"{path.name}.bak.{timestamp}")
    suffix = 0
    while candidate.exists():
        suffix += 1
        candidate = path.with_name(f"{path.name}.bak.{timestamp}.{suffix}")
    shutil.copy2(path, candidate)
    return candidate


def atomic_write_json(path: Path, document: dict[str, Any]) -> None:
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(document, indent=4, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise BridgeError(f"cannot update {path}: {error}") from error


def _can_import_rcl(python: Path) -> bool:
    result = subprocess.run(
        [str(python), "-c", RCL_IMPORT],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def require_runtime_python(config: Config) -> Path:
    root = config.toolkit_dir.resolve()
    python = Path(sys.executable)
    legacy_venv = (root / ".venv").resolve()
    resolved_python = python.resolve()
    if resolved_python == legacy_venv or legacy_venv in resolved_python.parents:
        raise BridgeError(
            "install-vscode is running from the legacy toolkit .venv; "
            "run it with the Python where Lauterbach RCL is installed"
        )
    if not _can_import_rcl(python):
        raise BridgeError(
            f"Lauterbach RCL is not installed for {python}; install "
            "'lauterbach-trace32-rcl>=1.1,<2' with this Python and retry "
            "(see README)"
        )
    return python


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        return
    print(f"removed {path}")


def clean_toolkit(config: Config) -> None:
    root = config.toolkit_dir.resolve()
    required = (root / "t32.py", root / "trace32.toml", root / "trace32_bridge")
    if (
        root == Path(root.anchor)
        or root == Path.home()
        or not required[0].is_file()
        or not required[1].is_file()
        or not required[2].is_dir()
    ):
        raise BridgeError(f"refusing to clean unexpected toolkit directory: {root}")

    for name in DEVELOPMENT_PATHS:
        _remove_path(root / name)
    for path in root.glob("*.egg-info"):
        _remove_path(path)

    for directory, names, files in os.walk(root, topdown=True):
        names[:] = [
            name
            for name in names
            if name not in PRESERVED_GENERATED_DIRS
        ]
        current = Path(directory)
        if "__pycache__" in names:
            _remove_path(current / "__pycache__")
            names.remove("__pycache__")
        for filename in files:
            if filename == ".DS_Store" or filename.endswith((".pyc", ".pyo")):
                _remove_path(current / filename)


def install(config: Config) -> None:
    runtime_python = require_runtime_python(config)
    target_dir = config.project_dir / ".vscode"
    target_dir.mkdir(parents=True, exist_ok=True)
    toolkit_relative = os.path.relpath(
        config.toolkit_dir, config.project_dir
    ).replace(os.sep, "/")
    replacements: dict[str, Any] = {
        "__TRACE32_TOOLKIT_REL__": toolkit_relative,
        "__PYTHON_EXECUTABLE__": str(runtime_python),
        "__T32_DAP_PORT__": config.dap_port,
        "__T32_RCL_PORT__": config.rcl_port,
    }

    for kind, filename, empty in (
        ("tasks", "tasks.json", {"version": "2.0.0", "tasks": []}),
        (
            "launch",
            "launch.json",
            {"version": "0.2.0", "configurations": []},
        ),
    ):
        template_path = config.toolkit_dir / "vscode" / filename
        target_path = target_dir / filename
        existing = jsonc.load(target_path) if target_path.exists() else empty
        template = replace_tokens(jsonc.load(template_path), replacements)
        merged = merge_document(kind, existing, template)
        if target_path.exists():
            backup_path = backup(target_path)
            print(f"backed up {target_path} -> {backup_path}")
        atomic_write_json(target_path, merged)
        print(f"installed/merged {target_path}")

    clean_toolkit(config)
    print(
        f"\nDone. VS Code uses {runtime_python}. Development files removed; "
        "Flash/Load/RTT are visible tasks; 'TRACE32: Attach' starts the "
        "hidden adapter."
    )
