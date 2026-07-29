from __future__ import annotations

import unittest

from trace32_bridge.errors import BridgeError
from trace32_bridge.vscode import jsonc


class JsoncTests(unittest.TestCase):
    def test_comments_and_trailing_commas(self) -> None:
        document = jsonc.loads(
            """
            {
                // line comment
                "url": "https://example.com/a//b",
                "items": [1, 2,],
                /* block comment */
            }
            """
        )
        self.assertEqual(document["url"], "https://example.com/a//b")
        self.assertEqual(document["items"], [1, 2])

    def test_unterminated_block_comment_is_rejected(self) -> None:
        with self.assertRaisesRegex(BridgeError, "unterminated"):
            jsonc.loads('{"value": 1 /*')

    def test_comma_at_end_of_file_is_not_silently_removed(self) -> None:
        with self.assertRaises(BridgeError):
            jsonc.loads('{"value": 1},')


if __name__ == "__main__":
    unittest.main()
