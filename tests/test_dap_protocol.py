from __future__ import annotations

import unittest

from trace32_bridge.dap.protocol import (
    DapDecoder,
    DapProtocolError,
    encode_message,
)


class DapProtocolTests(unittest.TestCase):
    def test_decodes_split_message(self) -> None:
        message = {"seq": 1, "type": "request", "command": "initialize"}
        encoded = encode_message(message)
        decoder = DapDecoder()
        midpoint = len(encoded) // 2
        self.assertEqual(decoder.feed(encoded[:midpoint]), [])
        self.assertEqual(decoder.feed(encoded[midpoint:]), [message])

    def test_decodes_multiple_messages(self) -> None:
        first = {"seq": 1}
        second = {"seq": 2}
        decoder = DapDecoder()
        self.assertEqual(
            decoder.feed(encode_message(first) + encode_message(second)),
            [first, second],
        )

    def test_rejects_missing_content_length(self) -> None:
        decoder = DapDecoder()
        with self.assertRaisesRegex(DapProtocolError, "no Content-Length"):
            decoder.feed(b"Other: value\r\n\r\n{}")

    def test_rejects_oversized_message(self) -> None:
        decoder = DapDecoder(max_message_bytes=4)
        with self.assertRaisesRegex(DapProtocolError, "invalid DAP message length"):
            decoder.feed(b"Content-Length: 5\r\n\r\n12345")


if __name__ == "__main__":
    unittest.main()

