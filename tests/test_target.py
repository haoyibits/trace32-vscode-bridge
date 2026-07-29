from __future__ import annotations

import tempfile
import unittest
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from unittest import mock

from trace32_bridge.config import Config
from trace32_bridge.errors import BridgeError
from trace32_bridge.target import program, run_target, validate_target_action


def make_config(root: Path) -> Config:
    run_dir = root / ".run"
    run_dir.mkdir()
    elf = root / "demo.elf"
    elf.write_bytes(b"\x7fELF")
    flash = root / "flash.cmm"
    flash.write_text("", encoding="utf-8")
    return Config(
        toolkit_dir=root,
        config_file=root / "trace32.toml",
        run_dir=run_dir,
        project_dir=root,
        program="demo",
        elf=elf,
        cpu="CPU",
        cores="1.",
        mem_access="",
        jtag_clock="",
        dual_port="",
        rtos_config="",
        rtos_menu="",
        rtos_show_tasks=False,
        flash_script=str(flash),
        flash_args=(),
        t32_sys=root,
        t32_host="test",
        t32_binary=root / "powerview",
        t32_config=root / "config.t32",
        debug_adapter=root / "adapter",
        rcl_port=20000,
        dap_port=58870,
        dap_backend_port=58871,
        dap_backend_timeout=1,
        operation_timeout=1,
        rtt_symbol="_SEGGER_RTT",
        rtt_control_block_address=None,
        rtt_poll_interval=0.02,
    )


class TargetTests(unittest.TestCase):
    def test_flash_requires_configured_script(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = make_config(Path(directory))
            config = replace(config, flash_script="")
            with self.assertRaisesRegex(BridgeError, "flash.script is empty"):
                validate_target_action(config, "flash")

    def test_load_is_driven_directly_through_rcl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = make_config(Path(directory))
            debugger = mock.Mock()
            debugger.fnc.system_up.return_value = False
            debugger.fnc.state_run.return_value = False

            with mock.patch(
                "trace32_bridge.target.connect_debugger",
                return_value=nullcontext(debugger),
            ):
                run_target(config, "load")

            commands = [call.args[0] for call in debugger.cmd.call_args_list]
            self.assertIn("SYStem.Mode Attach", commands)
            self.assertIn(f'Data.LOAD.Elf "{config.elf}" /NoCODE', commands)
            self.assertEqual(commands[-1], "Go")

    def test_flash_waits_for_project_cmm_then_programs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = make_config(Path(directory))
            debugger = mock.Mock()
            debugger.fnc.system_up.return_value = True
            debugger.fnc.state_run.return_value = True

            with mock.patch(
                "trace32_bridge.target.connect_debugger",
                return_value=nullcontext(debugger),
            ):
                run_target(config, "flash")

            debugger.cmm.assert_called_once_with(
                f'"{config.resolved_flash_script}" PREPAREONLY',
                timeout=config.operation_timeout,
            )
            commands = [call.args[0] for call in debugger.cmd.call_args_list]
            self.assertIn("FLASH.ReProgram ALL /Erase", commands)
            self.assertIn("FLASH.ReProgram OFF", commands)

    def test_flash_leaves_reprogram_mode_when_loading_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = make_config(Path(directory))
            debugger = mock.Mock()

            def command(text: str) -> None:
                if text.startswith("Data.LOAD.Elf"):
                    raise RuntimeError("programming failed")

            debugger.cmd.side_effect = command
            with self.assertRaisesRegex(RuntimeError, "programming failed"):
                program(config, debugger)

            commands = [call.args[0] for call in debugger.cmd.call_args_list]
            load_index = next(
                index
                for index, text in enumerate(commands)
                if text.startswith("Data.LOAD.Elf")
            )
            self.assertEqual(commands[load_index + 1], "FLASH.ReProgram OFF")


if __name__ == "__main__":
    unittest.main()
