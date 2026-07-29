from __future__ import annotations

from .config import Config
from .errors import BridgeError


def connect_debugger(config: Config, *, timeout: float = 5.0):
    try:
        import lauterbach.trace32.rcl as rcl
    except ImportError as error:
        raise BridgeError(
            "lauterbach-trace32-rcl is not installed for this Python; "
            "install the project in a virtual environment with "
            "'python -m pip install .'"
        ) from error
    try:
        return rcl.connect(
            node="localhost",
            port=str(config.rcl_port),
            protocol="TCP",
            packlen=1024,
            timeout=timeout,
        )
    except Exception as error:
        raise BridgeError(
            f"cannot connect to TRACE32 on RCL port {config.rcl_port}: {error}"
        ) from error


def reset_and_stop(config: Config) -> None:
    try:
        with connect_debugger(config) as debugger:
            debugger.cmd("Break")
            debugger.cmd("SYStem.Mode Up")
    except BridgeError:
        raise
    except Exception as error:
        raise BridgeError(f"TRACE32 reset failed: {error}") from error
