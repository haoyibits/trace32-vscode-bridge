"""Interactive SEGGER RTT terminal through a running TRACE32 PowerView session.

TRACE32 owns the debug probe. This process connects to TRACE32's Remote API
(RCL), drains RTT up-channel 0 to stdout, and forwards stdin to down-channel 0,
so it carries both printf output and an interactive CLI.

All defaults come from trace32.toml. Command-line options only override them
for a one-off run.
"""

import argparse
import contextlib
import os
import select
import struct
import sys
import termios
import time

import lauterbach.trace32.rcl as rcl

from .config import Config
from .errors import BridgeError

ID_STRING = b"SEGGER RTT"

# 32-bit SEGGER RTT control-block offsets.
UP_DESCRIPTOR = 0x18
DOWN_DESCRIPTOR = 0x30  # UP_DESCRIPTOR + one 24-byte up descriptor
DESC_BUFFER = 0x04
DESC_SIZE = 0x08
DESC_WR_OFF = 0x0C
DESC_RD_OFF = 0x10


class RttChannel:
    """Bidirectional RTT channel 0 accessed through TRACE32 run-time memory."""

    def __init__(self, debugger, control_block):
        self.dbg = debugger
        self.cb = control_block
        self.initialized = False

    def address(self, value):
        return self.dbg.address.from_string(f"E:0x{value:X}")

    def cb_address(self, offset):
        return self.address(self.cb + offset)

    def refresh_state(self):
        identifier = self.dbg.memory.read(self.cb_address(0), length=16)
        self.initialized = identifier[: len(ID_STRING)] == ID_STRING
        return self.initialized

    def read_up(self):
        """Drain currently available target-to-host bytes."""
        if not self.initialized and not self.refresh_state():
            return b""

        pbuf, size, write_offset, read_offset = struct.unpack(
            "<4I",
            self.dbg.memory.read(
                self.cb_address(UP_DESCRIPTOR + DESC_BUFFER),
                length=16,
            ),
        )

        if pbuf == 0 or size < 2 or write_offset >= size or read_offset >= size:
            self.initialized = False
            return b""
        if write_offset == read_offset:
            return b""

        data = b""
        if write_offset < read_offset:
            data += self.dbg.memory.read(
                self.address(pbuf + read_offset),
                length=size - read_offset,
            )
            read_offset = 0
        if write_offset > read_offset:
            data += self.dbg.memory.read(
                self.address(pbuf + read_offset),
                length=write_offset - read_offset,
            )

        # The host is the sole writer of the up-channel read offset.
        self.dbg.memory.write_uint32(
            self.cb_address(UP_DESCRIPTOR + DESC_RD_OFF),
            write_offset,
        )
        return data

    def write_down(self, data):
        """Write as much as possible to host-to-target channel 0."""
        if not data:
            return 0
        if not self.initialized and not self.refresh_state():
            return 0

        pbuf, size, write_offset, read_offset = struct.unpack(
            "<4I",
            self.dbg.memory.read(
                self.cb_address(DOWN_DESCRIPTOR + DESC_BUFFER),
                length=16,
            ),
        )

        if pbuf == 0 or size < 2 or write_offset >= size or read_offset >= size:
            self.initialized = False
            return 0

        free = (read_offset - write_offset - 1) % size
        count = min(len(data), free)
        if count == 0:
            return 0

        first = min(count, size - write_offset)
        self.dbg.memory.write(self.address(pbuf + write_offset), bytes(data[:first]))
        if count > first:
            self.dbg.memory.write(self.address(pbuf), bytes(data[first:count]))

        # Publish WrOff last so the target never sees incomplete input.
        self.dbg.memory.write_uint32(
            self.cb_address(DOWN_DESCRIPTOR + DESC_WR_OFF),
            (write_offset + count) % size,
        )
        return count


def resolve_control_block(debugger, program, symbol):
    """Resolve the RTT control block from the symbols loaded by target.py."""
    name = f"\\\\{program}\\Global\\{symbol}"
    return debugger.symbol.query_by_name(name=name).address.value


@contextlib.contextmanager
def terminal_input(enabled):
    """Use a no-echo, character-at-a-time terminal while preserving Ctrl-C."""
    if not enabled or not sys.stdin.isatty():
        yield
        return

    fd = sys.stdin.fileno()
    original = termios.tcgetattr(fd)
    modified = termios.tcgetattr(fd)
    modified[3] &= ~(termios.ICANON | termios.ECHO)
    modified[6][termios.VMIN] = 1
    modified[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSADRAIN, modified)
    try:
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original)


def read_terminal_input():
    if not select.select([sys.stdin], [], [], 0)[0]:
        return b""
    data = os.read(sys.stdin.fileno(), 256)
    # Embedded consoles usually treat BS as erase; most terminals send DEL.
    return data.replace(b"\x7f", b"\x08")


def add_arguments(parser: argparse.ArgumentParser, config: Config) -> None:
    parser.add_argument(
        "--program",
        default=config.program,
        help="TRACE32 symbol program name (default: project.program)",
    )
    parser.add_argument(
        "--symbol",
        default=config.rtt_symbol,
        help="RTT control-block symbol (default: _SEGGER_RTT)",
    )
    parser.add_argument(
        "--cb",
        type=lambda value: int(value, 0),
        default=config.rtt_control_block_address,
        help="control-block address; bypasses symbol lookup, e.g. 0x20000000",
    )
    parser.add_argument("--node", default="localhost")
    parser.add_argument("--port", default=config.rcl_port, type=int)
    parser.add_argument(
        "--protocol",
        default="TCP",
        choices=["UDP", "TCP"],
        help="must match the TRACE32 RCL configuration (default: TCP/NETTCP)",
    )
    parser.add_argument(
        "--poll",
        default=config.rtt_poll_interval,
        type=float,
        help="poll period in seconds (default: 0.02)",
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        help="set up-channel RdOff to zero before polling",
    )
    parser.add_argument(
        "--output-only",
        action="store_true",
        help="do not forward terminal input to the RTT down-channel",
    )


def run(config: Config, args: argparse.Namespace) -> None:
    try:
        debugger = rcl.connect(
            node=args.node,
            port=str(args.port),
            protocol=args.protocol,
            packlen=1024,
            timeout=5.0,
        )
        debugger.print(f"RTT terminal connected (pid {os.getpid()})")
    except Exception as error:
        raise BridgeError(
            f"cannot connect to TRACE32 at {args.node}:{args.port} ({error})\n"
            "Check the RCL=NETTCP / PORT= section of your config.t32."
        ) from error

    if args.cb is not None:
        control_block = args.cb
    elif not args.program:
        raise BridgeError("project.program is empty and no --cb was given")
    else:
        try:
            control_block = resolve_control_block(debugger, args.program, args.symbol)
        except Exception as error:
            raise BridgeError(
                f"cannot resolve {args.symbol} in '{args.program}' ({error})\n"
                "Run the 'T32: Load ELF' task first, or pass --cb 0x<address>."
            ) from error

    channel = RttChannel(debugger, control_block)
    print(
        f"TRACE32 RTT: {args.symbol} @ 0x{control_block:08X}; Ctrl-C to stop",
        file=sys.stderr,
    )

    try:
        initialized = channel.refresh_state()
    except Exception:
        initialized = False
    if not initialized:
        print(
            "[rtt] waiting for the target to initialize SEGGER RTT; "
            "if debugging is paused before RTT initialization, press Continue",
            file=sys.stderr,
        )

    if args.replay:
        debugger.memory.write_uint32(
            channel.cb_address(UP_DESCRIPTOR + DESC_RD_OFF),
            0,
        )

    pending_input = bytearray()
    consecutive_errors = 0

    with terminal_input(not args.output_only):
        while True:
            try:
                output = channel.read_up()
                if output:
                    # Passed through byte for byte: whatever escape sequences
                    # the target emits are the target's business.
                    sys.stdout.buffer.write(output)
                    sys.stdout.flush()

                if not args.output_only:
                    pending_input.extend(read_terminal_input())
                    if pending_input:
                        sent = channel.write_down(pending_input)
                        del pending_input[:sent]

                consecutive_errors = 0
                time.sleep(args.poll)
            except KeyboardInterrupt:
                break
            except Exception as error:
                consecutive_errors += 1
                channel.initialized = False
                if consecutive_errors in (5, 50) or consecutive_errors % 300 == 0:
                    print(
                        f"\n[rtt] run-time memory access failed "
                        f"x{consecutive_errors}: {error}",
                        file=sys.stderr,
                    )
                time.sleep(0.2)

    print("\nTRACE32 RTT terminal stopped", file=sys.stderr)
