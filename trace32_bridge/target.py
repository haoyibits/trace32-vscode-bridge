from __future__ import annotations

from .config import Config, flash_script_exists
from .errors import BridgeError
from .powerview import require_file
from .remote import connect_debugger


def validate_target_action(config: Config, action: str) -> None:
    if action not in {"flash", "load"}:
        raise BridgeError(f"unknown target action: {action}")
    require_file(config.elf, "ELF")
    if action == "flash":
        if not config.flash_script:
            raise BridgeError(
                "flash.script is empty in trace32.toml; use load for RAM images"
            )
        if not flash_script_exists(config):
            raise BridgeError(f"flash script not found: {config.resolved_flash_script}")


def run_target(config: Config, action: str) -> None:
    validate_target_action(config, action)
    try:
        with connect_debugger(config) as debugger:
            if action == "flash":
                program(config, debugger)
            setup_debug(config, debugger)
    except BridgeError:
        raise
    except TimeoutError as error:
        raise BridgeError(
            f"TRACE32 operation exceeded {config.operation_timeout}s"
        ) from error
    except Exception as error:
        raise BridgeError(f"TRACE32 {action} failed: {error}") from error


def program(config: Config, debugger) -> None:
    arguments = " ".join(config.flash_args)
    command = f'"{config.resolved_flash_script}" PREPAREONLY'
    if arguments:
        command += f" {arguments}"
    debugger.cmm(command, timeout=config.operation_timeout)

    if config.jtag_clock:
        debugger.cmd(f"SYStem.JtagClock {config.jtag_clock}")
    debugger.cmd("FLASH.ReProgram ALL /Erase")
    primary_error: BaseException | None = None
    try:
        debugger.cmd(f'Data.LOAD.Elf "{config.elf}"')
    except BaseException as error:
        primary_error = error
        raise
    finally:
        try:
            debugger.cmd("FLASH.ReProgram OFF")
        except Exception as cleanup_error:
            if primary_error is None:
                raise
            primary_error.add_note(
                f"also failed to leave FLASH.ReProgram mode: {cleanup_error}"
            )

    debugger.cmd("SYStem.Down")
    debugger.cmd("SYStem.Up")
    if config.jtag_clock:
        debugger.cmd(f"SYStem.JtagClock {config.jtag_clock}")
    debugger.cmd("SYStem.Option.IMASKASM ON")
    debugger.cmd("SYStem.Option.IMASKHLL ON")
    debugger.print(f"trace32-vscode-bridge: flashed {config.elf}")


def setup_debug(config: Config, debugger) -> None:
    if not debugger.fnc.system_up():
        debugger.cmd("SYStem.Mode Down")
        if config.cpu:
            debugger.cmd(f"SYStem.CPU {config.cpu}")
        if config.mem_access:
            debugger.cmd(f"SYStem.MemAccess {config.mem_access}")
        if config.cores:
            debugger.cmd(f"CORE.ASSIGN {config.cores}")
        debugger.cmd("SYStem.Mode Attach")

    debugger.cmd(f'Data.LOAD.Elf "{config.elf}" /NoCODE')
    if config.dual_port:
        debugger.cmd(f"SYStem.Option.DUALPORT {config.dual_port}")
    debugger.cmd("List.auto")

    rtos_enabled = bool(config.rtos_config or config.rtos_menu)
    if config.rtos_config:
        debugger.cmd(f'TASK.CONFIG "{config.rtos_config}"')
    if config.rtos_menu:
        debugger.cmd(f'MENU.ReProgram "{config.rtos_menu}"')
    if rtos_enabled and config.rtos_show_tasks:
        debugger.cmd("TASK.List")

    if not debugger.fnc.state_run():
        debugger.cmd("Go")
    debugger.print(
        f"trace32-vscode-bridge: symbols loaded for {config.program}"
    )
