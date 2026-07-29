from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from trace32_bridge.errors import BridgeError
from trace32_bridge.powerview import (
    install_toolbar,
    start_powerview,
    wait_for_powerview,
)


class PowerViewTests(unittest.TestCase):
    def test_toolbar_is_installed_through_rcl(self) -> None:
        config = mock.Mock()
        config.toolbar_script = "/toolkit/scripts/cmm/toolbar.cmm"
        config.toolkit_dir = "/toolkit"
        debugger = mock.MagicMock()

        with mock.patch(
            "trace32_bridge.powerview.connect_debugger",
            return_value=debugger,
        ):
            install_toolbar(config)

        debugger.cmm.assert_called_once_with(
            f'"/toolkit/scripts/cmm/toolbar.cmm" "/toolkit" "{sys.executable}"',
            timeout=10,
        )

    def test_existing_port_must_answer_as_rcl(self) -> None:
        config = mock.Mock(rcl_port=20000)
        with (
            mock.patch("trace32_bridge.powerview.port_open", return_value=True),
            mock.patch(
                "trace32_bridge.powerview.verify_rcl",
                side_effect=BridgeError("not RCL"),
            ),
        ):
            with self.assertRaisesRegex(BridgeError, "not a usable TRACE32"):
                start_powerview(config)

    def test_process_exit_is_reported_without_waiting_for_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "powerview"
            binary.write_text("", encoding="utf-8")
            binary.chmod(0o700)
            t32_config = root / "config.t32"
            t32_config.write_text("", encoding="utf-8")
            run_dir = root / ".run"
            config = mock.Mock(
                rcl_port=20000,
                t32_binary=binary,
                t32_config=t32_config,
                run_dir=run_dir,
                project_dir=root,
            )
            process = mock.Mock()
            process.poll.return_value = 7

            with (
                mock.patch(
                    "trace32_bridge.powerview.port_open", return_value=False
                ),
                mock.patch(
                    "trace32_bridge.powerview.subprocess.Popen",
                    return_value=process,
                ),
            ):
                with self.assertRaisesRegex(BridgeError, "exited with code 7"):
                    start_powerview(config)

    def test_successful_launcher_exit_waits_for_detached_application(self) -> None:
        config = mock.Mock(rcl_port=20000)
        process = mock.Mock()
        process.poll.return_value = 0

        with (
            mock.patch(
                "trace32_bridge.powerview.port_open",
                side_effect=[False, True],
            ),
            mock.patch("trace32_bridge.powerview.verify_rcl") as verify_rcl,
            mock.patch("trace32_bridge.powerview.time.sleep"),
        ):
            wait_for_powerview(
                config,
                process,
                Path("/tmp/powerview.log"),
                timeout=1,
            )

        verify_rcl.assert_called_once_with(config)


if __name__ == "__main__":
    unittest.main()
