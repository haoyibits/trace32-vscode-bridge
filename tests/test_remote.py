from __future__ import annotations

import unittest
from contextlib import nullcontext
from unittest import mock

from trace32_bridge.remote import reset_and_stop


class RemoteTests(unittest.TestCase):
    def test_reset_breaks_then_resets_to_up(self) -> None:
        config = mock.Mock()
        debugger = mock.Mock()
        with mock.patch(
            "trace32_bridge.remote.connect_debugger",
            return_value=nullcontext(debugger),
        ):
            reset_and_stop(config)

        self.assertEqual(
            [call.args[0] for call in debugger.cmd.call_args_list],
            ["Break", "SYStem.Mode Up"],
        )


if __name__ == "__main__":
    unittest.main()
