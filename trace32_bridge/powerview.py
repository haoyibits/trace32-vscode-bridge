from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from .config import Config
from .errors import BridgeError
from .remote import connect_debugger


def port_open(port: int, *, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return True
    except OSError:
        return False


def require_file(path: Path, description: str, *, executable: bool = False) -> None:
    if not path.is_file():
        raise BridgeError(f"{description} not found: {path}")
    if executable and not os.access(path, os.X_OK):
        raise BridgeError(f"{description} not executable: {path}")


def verify_rcl(config: Config, *, timeout: float = 0.5) -> None:
    with connect_debugger(config, timeout=timeout):
        pass


def wait_for_powerview(
    config: Config,
    process: subprocess.Popen[bytes],
    log_path: Path,
    *,
    timeout: float = 120,
) -> None:
    deadline = time.monotonic() + timeout
    last_rcl_error: BridgeError | None = None
    launcher_exited_cleanly = False
    while time.monotonic() <= deadline:
        return_code = process.poll()
        if return_code not in (None, 0):
            raise BridgeError(
                f"PowerView exited with code {return_code} before RCL became ready; "
                f"check {log_path}"
            )
        if return_code == 0:
            # On macOS the t32*-qt launcher delegates to `open`, which exits
            # successfully while the application continues starting.
            launcher_exited_cleanly = True
        if port_open(config.rcl_port):
            try:
                verify_rcl(config)
                return
            except BridgeError as error:
                last_rcl_error = error
        time.sleep(0.2)

    detail = f": {last_rcl_error}" if last_rcl_error is not None else ""
    launcher_detail = (
        " (the launcher exited successfully, but RCL never became ready)"
        if launcher_exited_cleanly
        else ""
    )
    raise BridgeError(
        f"PowerView did not become ready on RCL port {config.rcl_port}"
        f"{launcher_detail}{detail}; "
        f"check RCL=NETTCP in {config.t32_config} and {log_path}"
    )


def start_powerview(config: Config) -> bool:
    """Start PowerView when needed. Return True when a new process was started."""
    if port_open(config.rcl_port):
        try:
            verify_rcl(config)
        except BridgeError as error:
            raise BridgeError(
                f"port {config.rcl_port} is open but is not a usable TRACE32 "
                f"RCL endpoint: {error}"
            ) from error
        return False

    require_file(config.t32_binary, "PowerView", executable=True)
    require_file(config.t32_config, "TRACE32 config")
    config.run_dir.mkdir(parents=True, exist_ok=True)

    log_path = config.run_dir / "powerview.log"
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            [
                str(config.t32_binary),
                "-c",
                str(config.t32_config),
            ],
            cwd=config.project_dir,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    wait_for_powerview(config, process, log_path)
    install_toolbar(config)
    return True


def install_toolbar(config: Config) -> None:
    deadline = time.monotonic() + 60
    last_error: Exception | None = None
    python = sys.executable
    if any(character in python for character in ('"', "\r", "\n")):
        raise BridgeError("Python executable path is unsafe for a TRACE32 command")
    command = (
        f'"{config.toolbar_script}" "{config.toolkit_dir}" "{python}"'
    )
    debugger = None
    while time.monotonic() <= deadline:
        try:
            debugger = connect_debugger(config)
            break
        except Exception as error:
            last_error = error
            time.sleep(0.2)
    if debugger is None:
        raise BridgeError(f"could not connect to install the toolbar: {last_error}")
    try:
        with debugger:
            debugger.cmm(command, timeout=10)
    except Exception as error:
        raise BridgeError(
            f"could not install the PowerView toolbar: {error}"
        ) from error
