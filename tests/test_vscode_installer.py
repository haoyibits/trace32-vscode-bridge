from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from trace32_bridge.errors import BridgeError
from trace32_bridge.vscode import jsonc
from trace32_bridge.vscode.installer import (
    clean_toolkit,
    install,
    merge_document,
    require_runtime_python,
    replace_tokens,
)


class InstallerTests(unittest.TestCase):
    def test_merge_tasks_preserves_unrelated_and_updates_trace32(self) -> None:
        existing = {
            "version": "2.0.0",
            "tasks": [
                {"label": "build", "command": "make"},
                {"label": "T32: Flash + Debug", "command": "old"},
            ],
        }
        template = {
            "version": "2.0.0",
            "tasks": [
                {"label": "T32: Flash", "command": "python3"},
                {"label": "T32: Load ELF", "command": "python3"},
            ],
        }
        merged = merge_document("tasks", existing, template)
        self.assertEqual(
            [task["label"] for task in merged["tasks"]],
            ["build", "T32: Flash", "T32: Load ELF"],
        )
        self.assertEqual(merged["tasks"][1]["command"], "python3")

    def test_replace_tokens_preserves_number_type(self) -> None:
        result = replace_tokens(
            {"debugServer": "__PORT__", "text": "port=__PORT__"},
            {"__PORT__": 58870},
        )
        self.assertEqual(result["debugServer"], 58870)
        self.assertEqual(result["text"], "port=58870")

    def test_install_creates_backup_and_merges_templates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            toolkit = root / "toolkit"
            project = root / "project"
            (toolkit / "trace32_bridge").mkdir(parents=True)
            (toolkit / "vscode").mkdir(parents=True)
            (project / ".vscode").mkdir(parents=True)
            (toolkit / "t32.py").write_text("", encoding="utf-8")
            (toolkit / "trace32.toml").write_text("", encoding="utf-8")
            (toolkit / "vscode" / "tasks.json").write_text(
                '{"version":"2.0.0","tasks":['
                '{"label":"T32: Flash","command":"__PYTHON_EXECUTABLE__",'
                '"args":["__TRACE32_TOOLKIT_REL__"]}]}',
                encoding="utf-8",
            )
            (toolkit / "vscode" / "launch.json").write_text(
                '{"version":"0.2.0","configurations":['
                '{"name":"TRACE32: Attach","debugServer":"__T32_DAP_PORT__"}]}',
                encoding="utf-8",
            )
            target = project / ".vscode" / "tasks.json"
            target.write_text(
                '{"version":"2.0.0","tasks":[{"label":"build"}]}',
                encoding="utf-8",
            )
            config = SimpleNamespace(
                project_dir=project,
                toolkit_dir=toolkit,
                dap_port=58870,
                rcl_port=20000,
            )

            runtime_python = Path("/usr/local/bin/python3")
            with mock.patch(
                "trace32_bridge.vscode.installer.require_runtime_python",
                return_value=runtime_python,
            ):
                install(config)

            installed = jsonc.load(target)
            self.assertEqual(
                [task["label"] for task in installed["tasks"]],
                ["build", "T32: Flash"],
            )
            self.assertEqual(
                installed["tasks"][1]["command"], str(runtime_python)
            )
            self.assertTrue(list((project / ".vscode").glob("tasks.json.bak.*")))

    def test_runtime_python_requires_preinstalled_rcl_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            toolkit = Path(directory) / "toolkit"
            config = SimpleNamespace(toolkit_dir=toolkit)

            with (
                mock.patch(
                    "trace32_bridge.vscode.installer._can_import_rcl",
                    return_value=False,
                ),
                mock.patch(
                    "trace32_bridge.vscode.installer.sys.executable",
                    "/usr/local/bin/python3",
                ),
            ):
                with self.assertRaisesRegex(
                    BridgeError, "Lauterbach RCL is not installed"
                ):
                    require_runtime_python(config)

    def test_runtime_python_rejects_legacy_toolkit_venv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            toolkit = Path(directory) / "toolkit"
            python = toolkit / ".venv" / "bin" / "python"
            config = SimpleNamespace(toolkit_dir=toolkit)

            with mock.patch(
                "trace32_bridge.vscode.installer.sys.executable", str(python)
            ):
                with self.assertRaisesRegex(
                    BridgeError, "legacy toolkit .venv"
                ):
                    require_runtime_python(config)

    def test_clean_toolkit_removes_only_development_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            toolkit = Path(directory) / "toolkit"
            (toolkit / "trace32_bridge" / "__pycache__").mkdir(parents=True)
            (toolkit / "tests").mkdir()
            (toolkit / ".git").mkdir()
            (toolkit / "build").mkdir()
            (toolkit / "bridge.egg-info").mkdir()
            (toolkit / ".venv").mkdir()
            (toolkit / ".run").mkdir()
            (toolkit / "t32.py").write_text("", encoding="utf-8")
            (toolkit / "trace32.toml").write_text("", encoding="utf-8")
            (toolkit / "README.md").write_text("", encoding="utf-8")
            (toolkit / "tests" / "test_bridge.py").write_text(
                "", encoding="utf-8"
            )
            (toolkit / "trace32_bridge" / "__pycache__" / "cli.pyc").write_bytes(
                b"cache"
            )
            (toolkit / ".venv" / "keep.pyc").write_bytes(b"venv")
            (toolkit / ".run" / "powerview.log").write_text(
                "", encoding="utf-8"
            )
            config = SimpleNamespace(toolkit_dir=toolkit)

            clean_toolkit(config)

            self.assertFalse((toolkit / "tests").exists())
            self.assertFalse((toolkit / ".git").exists())
            self.assertFalse((toolkit / "build").exists())
            self.assertFalse((toolkit / "bridge.egg-info").exists())
            self.assertFalse(
                (toolkit / "trace32_bridge" / "__pycache__").exists()
            )
            self.assertFalse((toolkit / ".venv").exists())
            self.assertTrue((toolkit / ".run" / "powerview.log").exists())
            self.assertTrue((toolkit / "README.md").exists())


if __name__ == "__main__":
    unittest.main()
