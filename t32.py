#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


if sys.version_info < (3, 11):
    raise SystemExit(
        "trace32-vscode-bridge requires Python 3.11 or newer; "
        f"this interpreter is {sys.version.split()[0]}"
    )

TOOLKIT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLKIT_DIR))

from trace32_bridge.cli import main  # noqa: E402


if __name__ == "__main__":
    main()
