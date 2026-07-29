from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..errors import BridgeError


def strip_comments(source: str) -> str:
    result: list[str] = []
    index = 0
    in_string = False
    escaped = False
    line_comment = False
    block_comment = False

    while index < len(source):
        character = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if line_comment:
            if character == "\n":
                line_comment = False
                result.append(character)
        elif block_comment:
            if character == "*" and following == "/":
                block_comment = False
                index += 1
            elif character == "\n":
                result.append(character)
        elif in_string:
            result.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
            result.append(character)
        elif character == "/" and following == "/":
            line_comment = True
            index += 1
        elif character == "/" and following == "*":
            block_comment = True
            index += 1
        else:
            result.append(character)
        index += 1
    if block_comment:
        raise BridgeError("unterminated block comment in JSONC")
    return "".join(result)


def strip_trailing_commas(source: str) -> str:
    result: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(source):
        character = source[index]
        if in_string:
            result.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
            result.append(character)
        elif character == ",":
            lookahead = index + 1
            while lookahead < len(source) and source[lookahead].isspace():
                lookahead += 1
            if lookahead >= len(source) or source[lookahead] not in "}]":
                result.append(character)
        else:
            result.append(character)
        index += 1
    return "".join(result)


def loads(source: str, *, source_name: str = "<string>") -> Any:
    try:
        return json.loads(strip_trailing_commas(strip_comments(source)))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise BridgeError(f"cannot parse {source_name}: {error}") from error


def load(path: Path) -> Any:
    try:
        source = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise BridgeError(f"cannot read {path}: {error}") from error
    return loads(source, source_name=str(path))
