from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from trace32_bridge.config import load_config
from trace32_bridge.errors import BridgeError


CONFIG = """
[project]
root = "project"
program = "demo"
elf = "build/demo.elf"

[target]
cpu = "CORTEXM4"
cores = "1."
mem_access = "AXI"
jtag_clock = "10MHz"
dual_port = "ON"

[flash]
script = "project/flash.cmm"
args = ["CPU=DEMO", "DUALPORT=1"]

[trace32]
sys = "fake-t32"
rcl_port = 20000
dap_port = 58870
dap_backend_port = 58871

[rtt]
symbol = "_SEGGER_RTT"
control_block_address = "0x20001000"
poll_interval = 0.05
"""


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "project" / "build").mkdir(parents=True)
        (self.root / "project" / "flash.cmm").write_text("", encoding="utf-8")
        (self.root / "trace32.toml").write_text(CONFIG, encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_loads_typed_configuration_and_resolves_paths(self) -> None:
        config = load_config(toolkit_dir=self.root, env={})
        self.assertEqual(config.project_dir, (self.root / "project").resolve())
        self.assertEqual(
            config.elf, (self.root / "project" / "build" / "demo.elf").resolve()
        )
        self.assertEqual(config.rtt_control_block_address, 0x20001000)
        self.assertEqual(config.flash_args, ("CPU=DEMO", "DUALPORT=1"))
        self.assertEqual(
            config.resolved_flash_script,
            str((self.root / "project" / "flash.cmm").resolve()),
        )

    def test_environment_overrides_trace32_installation(self) -> None:
        config = load_config(
            toolkit_dir=self.root,
            env={
                "T32SYS": str(self.root / "override"),
                "T32_RCL_PORT": "21000",
                "PROGRAM_NAME": "override-program",
            },
        )
        self.assertEqual(config.t32_sys, (self.root / "override").resolve())
        self.assertEqual(config.rcl_port, 21000)
        self.assertEqual(config.program, "override-program")

    def test_paths_with_spaces_are_supported(self) -> None:
        toolkit = self.root / "tool kit"
        (toolkit / "project" / "build").mkdir(parents=True)
        (toolkit / "project" / "flash.cmm").write_text("", encoding="utf-8")
        (toolkit / "trace32.toml").write_text(CONFIG, encoding="utf-8")

        config = load_config(toolkit_dir=toolkit, env={})

        self.assertEqual(config.toolkit_dir, toolkit.resolve())
        self.assertIn("tool kit", str(config.elf))

    def test_loads_optional_rtos_configuration(self) -> None:
        source = CONFIG + """
[rtos]
config = "~~/demo/freertos.t32"
menu = "~~/demo/freertos.men"
show_tasks = true
"""
        (self.root / "trace32.toml").write_text(source, encoding="utf-8")
        config = load_config(toolkit_dir=self.root, env={})
        self.assertEqual(config.rtos_config, "~~/demo/freertos.t32")
        self.assertTrue(config.rtos_show_tasks)

    def test_rejects_unsafe_trace32_value(self) -> None:
        source = CONFIG.replace('program = "demo"', "program = 'bad\"name'")
        (self.root / "trace32.toml").write_text(source, encoding="utf-8")
        with self.assertRaisesRegex(BridgeError, "unsafe for TRACE32"):
            load_config(toolkit_dir=self.root, env={})


if __name__ == "__main__":
    unittest.main()
