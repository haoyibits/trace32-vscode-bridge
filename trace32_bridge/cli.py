from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import Config, load_config
from .errors import BridgeError
from .powerview import port_open, start_powerview
from .target import run_target


def info(message: str) -> None:
    print(f"\033[1;36m[t32]\033[0m {message}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="t32", description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        help="configuration file (default: trace32.toml in the toolkit root)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("flash", help="flash, load symbols and run")
    subparsers.add_parser("load", help="load symbols without programming")
    subparsers.add_parser("open", help="start or reuse PowerView")
    subparsers.add_parser("adapter", help="run the DAP compatibility proxy")
    subparsers.add_parser("config", help="print resolved configuration")
    subparsers.add_parser("install-vscode", help="merge the VS Code templates")
    subparsers.add_parser("rtt", help="run the interactive RTT terminal")
    return parser


def _print_config(config: Config) -> None:
    entries = {
        "project": config.project_dir,
        "ELF": config.elf,
        "T32_BIN": config.t32_binary,
        "T32_CONFIG": config.t32_config,
        "T32_DEBUG_ADAPTER": config.debug_adapter,
    }
    info(f"configuration: {config.config_file}")
    for name, path in entries.items():
        state = "ok     " if path.exists() else "MISSING"
        print(f"  {state} {name}={path}")


def _run(args: argparse.Namespace, config: Config) -> None:
    command = args.command
    if command in {"flash", "load", "open"}:
        started = start_powerview(config)
        info("PowerView ready" if started else f"reusing PowerView on RCL port {config.rcl_port}")
        if command != "open":
            verb = "flashing" if command == "flash" else "loading symbols from"
            info(f"{verb} {config.elf}")
            run_target(config, command)
            info(
                "flashed, symbols loaded, target running"
                if command == "flash"
                else "symbols loaded, target running"
            )
        return

    if command == "config":
        _print_config(config)
        return

    if command == "rtt":
        from . import rtt

        rtt_parser = argparse.ArgumentParser(prog="t32 rtt")
        rtt.add_arguments(rtt_parser, config)
        rtt_args = rtt_parser.parse_args(args.forwarded)
        if not port_open(config.rcl_port):
            raise BridgeError(
                f"no PowerView on RCL port {config.rcl_port}; "
                "run flash, load or open first"
            )
        rtt.run(config, rtt_args)
        return

    if command == "adapter":
        if port_open(config.dap_port):
            info(f"debug adapter already listening on {config.dap_port}")
            return
        from .dap.proxy import run_proxy

        info(f"starting DAP compatibility proxy on port {config.dap_port}")
        run_proxy(config)
        return

    if command == "install-vscode":
        from .vscode.installer import install

        install(config)
        return

    raise BridgeError(f"unsupported command: {command}")


def main(argv: list[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    # RTT owns the arguments after its command. Keeping them out of the root
    # parser avoids duplicating the RTT option definitions.
    forwarded: list[str] = []
    if "rtt" in arguments:
        index = arguments.index("rtt")
        forwarded = arguments[index + 1 :]
        arguments = arguments[: index + 1]

    parser = _parser()
    args = parser.parse_args(arguments)
    args.forwarded = forwarded
    try:
        config = load_config(args.config)
        _run(args, config)
    except BridgeError as error:
        print(f"trace32-vscode-bridge: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        raise SystemExit(130) from None
