from __future__ import annotations

import unittest
import tempfile
import sys
from pathlib import Path
from types import SimpleNamespace

from trace32_bridge.vscode import jsonc
from trace32_bridge.vscode.installer import (
    install,
    merge_document,
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
            (toolkit / "vscode").mkdir(parents=True)
            (project / ".vscode").mkdir(parents=True)
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

            install(config)

            installed = jsonc.load(target)
            self.assertEqual(
                [task["label"] for task in installed["tasks"]],
                ["build", "T32: Flash"],
            )
            self.assertEqual(installed["tasks"][1]["command"], sys.executable)
            self.assertTrue(list((project / ".vscode").glob("tasks.json.bak.*")))


if __name__ == "__main__":
    unittest.main()
