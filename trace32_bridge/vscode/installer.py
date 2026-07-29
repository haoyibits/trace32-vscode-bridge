from __future__ import annotations

import json
import os
import shutil
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


def install(config: Config) -> None:
    target_dir = config.project_dir / ".vscode"
    target_dir.mkdir(parents=True, exist_ok=True)
    toolkit_relative = os.path.relpath(
        config.toolkit_dir, config.project_dir
    ).replace(os.sep, "/")
    replacements: dict[str, Any] = {
        "__TRACE32_TOOLKIT_REL__": toolkit_relative,
        "__PYTHON_EXECUTABLE__": sys.executable,
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

    print(
        "\nDone. Flash/Load/RTT are visible tasks; "
        "'TRACE32: Attach' starts the hidden adapter."
    )
