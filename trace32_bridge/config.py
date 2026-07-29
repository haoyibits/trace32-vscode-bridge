from __future__ import annotations

import os
import platform
import re
import shlex
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .errors import BridgeError


TOOLKIT_DIR = Path(__file__).resolve().parent.parent


def _table(document: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = document.get(name, {})
    if not isinstance(value, dict):
        raise BridgeError(f"[{name}] in trace32.toml must be a table")
    return value


def _text(table: Mapping[str, Any], key: str, default: str = "") -> str:
    value = table.get(key, default)
    if not isinstance(value, str):
        raise BridgeError(f"{key} must be a string")
    return value


def _integer(table: Mapping[str, Any], key: str, default: int) -> int:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise BridgeError(f"{key} must be an integer")
    return value


def _number(table: Mapping[str, Any], key: str, default: float) -> float:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BridgeError(f"{key} must be a number")
    return float(value)


def _boolean(table: Mapping[str, Any], key: str, default: bool) -> bool:
    value = table.get(key, default)
    if not isinstance(value, bool):
        raise BridgeError(f"{key} must be a boolean")
    return value


def _string_list(table: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = table.get(key, [])
    if isinstance(value, str):
        return tuple(shlex.split(value))
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise BridgeError(f"{key} must be an array of strings")
    return tuple(value)


def _expand_path(value: str) -> str:
    return os.path.expandvars(os.path.expanduser(value))


def _resolve(value: str, base: Path) -> Path:
    path = Path(_expand_path(value))
    return path if path.is_absolute() else base / path


def _host_default() -> str:
    system = platform.system()
    if system == "Darwin":
        return "macosx64"
    if system == "Linux":
        return "linux64"
    raise BridgeError(
        f"cannot auto-detect the TRACE32 host directory on {system}; "
        "set trace32.host"
    )


def _env_text(env: Mapping[str, str], name: str, fallback: str) -> str:
    value = env.get(name)
    return value if value not in (None, "") else fallback


def _env_override(env: Mapping[str, str], name: str, fallback: str) -> str:
    return env[name] if name in env else fallback


def _env_integer(
    env: Mapping[str, str], name: str, fallback: int, description: str
) -> int:
    value = env.get(name)
    if value in (None, ""):
        return fallback
    try:
        return int(value)
    except ValueError as error:
        raise BridgeError(
            f"{description} environment override must be an integer"
        ) from error


def _env_arguments(
    env: Mapping[str, str], name: str, fallback: tuple[str, ...]
) -> tuple[str, ...]:
    if name not in env:
        return fallback
    try:
        return tuple(shlex.split(env[name]))
    except ValueError as error:
        raise BridgeError(f"cannot parse {name}: {error}") from error


@dataclass(frozen=True)
class Config:
    toolkit_dir: Path
    config_file: Path
    run_dir: Path
    project_dir: Path
    program: str
    elf: Path
    cpu: str
    cores: str
    mem_access: str
    jtag_clock: str
    dual_port: str
    rtos_config: str
    rtos_menu: str
    rtos_show_tasks: bool
    flash_script: str
    flash_args: tuple[str, ...]
    t32_sys: Path
    t32_host: str
    t32_binary: Path
    t32_config: Path
    debug_adapter: Path
    rcl_port: int
    dap_port: int
    dap_backend_port: int
    dap_backend_timeout: int
    operation_timeout: int
    rtt_symbol: str
    rtt_control_block_address: int | None
    rtt_poll_interval: float

    @property
    def toolbar_script(self) -> Path:
        return Path(__file__).resolve().parent / "cmm" / "toolbar.cmm"

    @property
    def resolved_flash_script(self) -> str:
        if not self.flash_script or self.flash_script.startswith("~~"):
            return self.flash_script
        return str(_resolve(self.flash_script, self.toolkit_dir).resolve())

    def validate_common(self) -> None:
        if not self.program:
            raise BridgeError("project.program is empty in trace32.toml")
        for name, port in (
            ("trace32.rcl_port", self.rcl_port),
            ("trace32.dap_port", self.dap_port),
            ("trace32.dap_backend_port", self.dap_backend_port),
        ):
            if not 1 <= port <= 65535:
                raise BridgeError(f"{name} must be between 1 and 65535")
        if self.dap_port == self.dap_backend_port:
            raise BridgeError(
                "trace32.dap_port and trace32.dap_backend_port must be different"
            )
        if self.dap_backend_timeout <= 0:
            raise BridgeError("trace32.dap_backend_timeout must be positive")
        if self.operation_timeout <= 0:
            raise BridgeError("trace32.operation_timeout must be positive")
        if self.rtt_poll_interval <= 0:
            raise BridgeError("rtt.poll_interval must be positive")
        command_values = {
            "toolkit path": str(self.toolkit_dir),
            "project.program": self.program,
            "project.elf": str(self.elf),
            "target.cpu": self.cpu,
            "target.cores": self.cores,
            "target.mem_access": self.mem_access,
            "target.jtag_clock": self.jtag_clock,
            "target.dual_port": self.dual_port,
            "rtos.config": self.rtos_config,
            "rtos.menu": self.rtos_menu,
            "flash.script": self.resolved_flash_script,
            "flash.args": " ".join(self.flash_args),
        }
        for name, value in command_values.items():
            if '"' in value or "\n" in value or "\r" in value:
                raise BridgeError(
                    f"{name} contains characters unsafe for TRACE32 commands"
                )


def load_config(
    path: str | os.PathLike[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    toolkit_dir: Path | None = None,
) -> Config:
    environment = os.environ if env is None else env
    root = TOOLKIT_DIR if toolkit_dir is None else toolkit_dir.resolve()
    config_file = (
        Path(path).expanduser().resolve()
        if path is not None
        else (root / "trace32.toml").resolve()
    )
    try:
        with config_file.open("rb") as handle:
            document = tomllib.load(handle)
    except FileNotFoundError as error:
        raise BridgeError(f"config not found: {config_file}") from error
    except tomllib.TOMLDecodeError as error:
        raise BridgeError(f"cannot parse {config_file}: {error}") from error

    project = _table(document, "project")
    target = _table(document, "target")
    flash = _table(document, "flash")
    rtos = _table(document, "rtos")
    trace32 = _table(document, "trace32")
    rtt = _table(document, "rtt")

    project_root = _resolve(
        _env_text(environment, "PROJECT_ROOT", _text(project, "root", "..")),
        root,
    ).resolve()
    if not project_root.is_dir():
        raise BridgeError(
            f"project.root does not resolve to a directory: {project_root}"
        )
    elf = _resolve(
        _env_text(environment, "ELF", _text(project, "elf")), project_root
    ).resolve()

    sys_value = _env_text(
        environment,
        "T32_SYS",
        _env_text(
            environment,
            "T32SYS",
            _text(trace32, "sys") or str(Path.home() / "t32"),
        ),
    )
    t32_sys = Path(_expand_path(sys_value)).resolve()
    t32_host = _env_text(environment, "T32_HOST", _text(trace32, "host"))
    if not t32_host:
        t32_host = _host_default()

    executable = _env_text(
        environment, "T32_EXE", _text(trace32, "executable", "t32marm-qt")
    )
    binary_value = _env_text(environment, "T32_BIN", _text(trace32, "binary"))
    config_value = _env_text(environment, "T32_CONFIG", _text(trace32, "config"))
    adapter_value = _env_text(
        environment, "T32_DEBUG_ADAPTER", _text(trace32, "debug_adapter")
    )

    binary = (
        Path(_expand_path(binary_value)).resolve()
        if binary_value
        else t32_sys / "bin" / t32_host / executable
    )
    t32_config = (
        Path(_expand_path(config_value)).resolve()
        if config_value
        else t32_sys / "config.t32"
    )
    adapter = (
        Path(_expand_path(adapter_value)).resolve()
        if adapter_value
        else t32_sys
        / "demo"
        / "env"
        / "vscode"
        / "bin"
        / t32_host
        / "t32debugadapter"
    )

    address_text = _text(rtt, "control_block_address")
    try:
        control_block_address = int(address_text, 0) if address_text else None
    except ValueError as error:
        raise BridgeError(
            "rtt.control_block_address must be empty or an integer such as 0x20000000"
        ) from error

    config = Config(
        toolkit_dir=root,
        config_file=config_file,
        run_dir=root / ".run",
        project_dir=project_root,
        program=_env_override(
            environment, "PROGRAM_NAME", _text(project, "program")
        ),
        elf=elf,
        cpu=_env_override(environment, "T32_CPU", _text(target, "cpu")),
        cores=_env_override(
            environment, "T32_CORES", _text(target, "cores", "1.")
        ),
        mem_access=_env_override(
            environment, "T32_MEMACCESS", _text(target, "mem_access")
        ),
        jtag_clock=_env_override(
            environment, "T32_JTAG_CLOCK", _text(target, "jtag_clock")
        ),
        dual_port=_env_override(
            environment, "T32_DUALPORT", _text(target, "dual_port")
        ),
        rtos_config=_text(rtos, "config"),
        rtos_menu=_text(rtos, "menu"),
        rtos_show_tasks=_boolean(rtos, "show_tasks", False),
        flash_script=_env_override(
            environment, "T32_FLASH_SCRIPT", _text(flash, "script")
        ),
        flash_args=_env_arguments(
            environment, "T32_FLASH_ARGS", _string_list(flash, "args")
        ),
        t32_sys=t32_sys,
        t32_host=t32_host,
        t32_binary=binary,
        t32_config=t32_config,
        debug_adapter=adapter,
        rcl_port=_env_integer(
            environment,
            "T32_RCL_PORT",
            _integer(trace32, "rcl_port", 20000),
            "T32_RCL_PORT",
        ),
        dap_port=_env_integer(
            environment,
            "T32_DAP_PORT",
            _integer(trace32, "dap_port", 58870),
            "T32_DAP_PORT",
        ),
        dap_backend_port=_env_integer(
            environment,
            "T32_DAP_BACKEND_PORT",
            _integer(trace32, "dap_backend_port", 58871),
            "T32_DAP_BACKEND_PORT",
        ),
        dap_backend_timeout=_env_integer(
            environment,
            "T32_DAP_BACKEND_TIMEOUT",
            _integer(trace32, "dap_backend_timeout", 30),
            "T32_DAP_BACKEND_TIMEOUT",
        ),
        operation_timeout=_env_integer(
            environment,
            "T32_TIMEOUT",
            _integer(trace32, "operation_timeout", 600),
            "T32_TIMEOUT",
        ),
        rtt_symbol=_env_text(
            environment, "RTT_SYMBOL", _text(rtt, "symbol", "_SEGGER_RTT")
        ),
        rtt_control_block_address=control_block_address,
        rtt_poll_interval=_number(rtt, "poll_interval", 0.02),
    )
    config.validate_common()
    return config


_PRACTICE_PREFIX = re.compile(r"^~~(?:/|$)")


def flash_script_exists(config: Config) -> bool:
    path = config.resolved_flash_script
    return bool(path) and (
        bool(_PRACTICE_PREFIX.match(path)) or Path(path).is_file()
    )
