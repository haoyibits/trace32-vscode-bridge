from __future__ import annotations

import json
from typing import Any


MAX_HEADER_BYTES = 16 * 1024
MAX_MESSAGE_BYTES = 16 * 1024 * 1024


class DapProtocolError(ValueError):
    pass


def encode_message(message: dict[str, Any]) -> bytes:
    body = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    if len(body) > MAX_MESSAGE_BYTES:
        raise DapProtocolError(f"DAP message exceeds {MAX_MESSAGE_BYTES} bytes")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


class DapDecoder:
    def __init__(
        self,
        *,
        max_header_bytes: int = MAX_HEADER_BYTES,
        max_message_bytes: int = MAX_MESSAGE_BYTES,
    ) -> None:
        self._buffer = bytearray()
        self.max_header_bytes = max_header_bytes
        self.max_message_bytes = max_message_bytes

    def feed(self, chunk: bytes) -> list[dict[str, Any]]:
        self._buffer.extend(chunk)
        messages: list[dict[str, Any]] = []

        while True:
            separator = self._buffer.find(b"\r\n\r\n")
            if separator < 0:
                if len(self._buffer) > self.max_header_bytes:
                    raise DapProtocolError("DAP header is too large")
                return messages
            if separator > self.max_header_bytes:
                raise DapProtocolError("DAP header is too large")

            header = bytes(self._buffer[:separator]).decode("ascii", errors="strict")
            length: int | None = None
            for line in header.split("\r\n"):
                name, delimiter, value = line.partition(":")
                if delimiter and name.strip().lower() == "content-length":
                    try:
                        length = int(value.strip())
                    except ValueError as error:
                        raise DapProtocolError(
                            f"invalid DAP Content-Length: {value.strip()}"
                        ) from error
                    break
            if length is None:
                raise DapProtocolError("DAP message has no Content-Length")
            if length < 0 or length > self.max_message_bytes:
                raise DapProtocolError(f"invalid DAP message length: {length}")

            message_end = separator + 4 + length
            if len(self._buffer) < message_end:
                return messages

            payload = bytes(self._buffer[separator + 4 : message_end])
            del self._buffer[:message_end]
            try:
                decoded = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise DapProtocolError(f"invalid DAP JSON: {error}") from error
            if not isinstance(decoded, dict):
                raise DapProtocolError("DAP payload must be a JSON object")
            messages.append(decoded)

