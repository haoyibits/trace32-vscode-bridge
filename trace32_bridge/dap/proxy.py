from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from typing import Any

from ..config import Config
from ..errors import BridgeError
from ..powerview import port_open, require_file
from ..remote import reset_and_stop
from .protocol import DapDecoder, DapProtocolError, encode_message


class DapSession:
    def __init__(
        self,
        proxy: DapProxy,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        backend_reader: asyncio.StreamReader,
        backend_writer: asyncio.StreamWriter,
        initial: bytes,
    ) -> None:
        self.proxy = proxy
        self.client_reader = client_reader
        self.client_writer = client_writer
        self.backend_reader = backend_reader
        self.backend_writer = backend_writer
        self.initial = initial
        self.client_decoder = DapDecoder()
        self.backend_decoder = DapDecoder()
        self.client_commands: dict[int, str] = {}
        self.internal_requests: dict[
            int, asyncio.Future[dict[str, Any]]
        ] = {}
        self.local_references: set[int] = set()
        self.client_lock = asyncio.Lock()
        self.backend_lock = asyncio.Lock()
        self.background_tasks: set[asyncio.Task[None]] = set()

    def start_background(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self.background_tasks.add(task)
        task.add_done_callback(self.background_finished)

    def background_finished(self, task: asyncio.Task[None]) -> None:
        self.background_tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            print(
                f"[t32-dap-proxy] background operation failed: {error}",
                flush=True,
            )

    async def backend_request(
        self, command: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        sequence = self.proxy.next_sequence()
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        self.internal_requests[sequence] = future
        await self.proxy.send(
            self.backend_writer,
            {
                "seq": sequence,
                "type": "request",
                "command": command,
                "arguments": arguments,
            },
            self.backend_lock,
        )
        try:
            return await asyncio.wait_for(future, timeout=5)
        finally:
            self.internal_requests.pop(sequence, None)

    async def restart(self, request: dict[str, Any]) -> None:
        print("[t32-dap-proxy] Restart -> reset, then DAP continue", flush=True)
        try:
            await self.proxy.reset_target()
            self.local_references.clear()
            await self.backend_request("continue", {"threadId": 0})
            await self.proxy.send(
                self.client_writer,
                self.proxy.response(request, True),
                self.client_lock,
            )
            await self.proxy.send(
                self.client_writer,
                {
                    "seq": self.proxy.next_sequence(),
                    "type": "event",
                    "event": "continued",
                    "body": {
                        "threadId": 0,
                        "allThreadsContinued": True,
                    },
                },
                self.client_lock,
            )
        except Exception as error:
            await self.proxy.send(
                self.client_writer,
                self.proxy.response(request, False, message=str(error)),
                self.client_lock,
            )

    async def handle_client_message(self, message: dict[str, Any]) -> None:
        if message.get("type") == "request":
            sequence = message.get("seq")
            command = message.get("command")
            if isinstance(sequence, int) and isinstance(command, str):
                self.client_commands[sequence] = command
            if command == "restart":
                self.start_background(self.restart(message))
                return
            arguments = message.get("arguments") or {}
            reference = arguments.get("variablesReference")
            if command == "variables" and reference in self.local_references:
                await self.proxy.send(
                    self.client_writer,
                    self.proxy.response(
                        message, True, body={"variables": []}
                    ),
                    self.client_lock,
                )
                return
        await self.proxy.send(
            self.backend_writer, message, self.backend_lock
        )

    async def handle_backend_message(self, message: dict[str, Any]) -> None:
        if message.get("type") == "response":
            request_sequence = message.get("request_seq")
            pending = self.internal_requests.get(request_sequence)
            if pending is not None:
                if message.get("success"):
                    if not pending.done():
                        pending.set_result(message)
                elif not pending.done():
                    pending.set_exception(
                        BridgeError(
                            str(
                                message.get("message")
                                or f"{message.get('command')} failed"
                            )
                        )
                    )
                return

            command = message.get("command") or self.client_commands.get(
                request_sequence
            )
            if command == "scopes":
                body = message.get("body") or {}
                for scope in body.get("scopes", []):
                    name = str(scope.get("name", "")).lower()
                    if (
                        scope.get("presentationHint") == "locals"
                        or name == "locals"
                    ):
                        reference = scope.get("variablesReference")
                        if isinstance(reference, int):
                            self.local_references.add(reference)
        await self.proxy.send(
            self.client_writer, message, self.client_lock
        )

    async def pump_client(self) -> None:
        chunks = [self.initial]
        while chunks:
            for message in self.client_decoder.feed(chunks.pop()):
                await self.handle_client_message(message)
            chunk = await self.client_reader.read(65536)
            if not chunk:
                return
            chunks.append(chunk)

    async def pump_backend(self) -> None:
        while True:
            chunk = await self.backend_reader.read(65536)
            if not chunk:
                return
            for message in self.backend_decoder.feed(chunk):
                await self.handle_backend_message(message)

    async def run(self) -> None:
        pump_tasks = {
            asyncio.create_task(self.pump_client()),
            asyncio.create_task(self.pump_backend()),
        }
        try:
            done, _ = await asyncio.wait(
                pump_tasks, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                task.result()
        finally:
            tasks = pump_tasks | self.background_tasks
            for task in tasks:
                if not task.done():
                    task.cancel()
            for future in self.internal_requests.values():
                if not future.done():
                    future.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.background_tasks.clear()
            self.backend_writer.close()
            with contextlib.suppress(Exception):
                await self.backend_writer.wait_closed()


class DapProxy:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.sequence = 1_000_000
        self.adapter: asyncio.subprocess.Process | None = None
        self.server: asyncio.Server | None = None
        self.session_active = False
        self.session_finished = asyncio.Event()
        self.shutdown_requested = asyncio.Event()
        self.exit_code = 0

    def next_sequence(self) -> int:
        value = self.sequence
        self.sequence += 1
        return value

    @staticmethod
    async def send(
        writer: asyncio.StreamWriter,
        message: dict[str, Any],
        lock: asyncio.Lock,
    ) -> None:
        async with lock:
            writer.write(encode_message(message))
            await writer.drain()

    def response(
        self,
        request: dict[str, Any],
        success: bool,
        *,
        message: str | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "seq": self.next_sequence(),
            "type": "response",
            "request_seq": request["seq"],
            "success": success,
            "command": request["command"],
            "message": message,
            "body": body,
        }

    async def start_adapter(self) -> None:
        require_file(self.config.debug_adapter, "t32debugadapter", executable=True)
        if port_open(self.config.dap_backend_port):
            raise BridgeError(
                f"internal DAP port {self.config.dap_backend_port} is already in use"
            )
        arguments = [
            str(self.config.debug_adapter),
            "--port",
            str(self.config.dap_backend_port),
            "--log_to",
            "stdout",
        ]
        if os.environ.get("T32_DAP_DEBUG") == "1":
            arguments.extend(["--log_level", "debug"])
        self.adapter = await asyncio.create_subprocess_exec(*arguments)

    async def connect_backend(
        self,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.config.dap_backend_timeout
        while True:
            try:
                return await asyncio.open_connection(
                    "127.0.0.1", self.config.dap_backend_port
                )
            except ConnectionRefusedError:
                if loop.time() >= deadline:
                    raise BridgeError(
                        "cannot connect to t32debugadapter on "
                        f"{self.config.dap_backend_port}"
                    ) from None
                await asyncio.sleep(0.1)

    async def reset_target(self) -> None:
        await asyncio.to_thread(reset_and_stop, self.config)

    async def handle_client(
        self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ) -> None:
        peer = client_writer.get_extra_info("peername")
        claimed = False
        try:
            initial = await client_reader.read(65536)
            if not initial:
                return
            if self.session_active:
                return
            self.session_active = True
            claimed = True

            backend_reader, backend_writer = await self.connect_backend()
            print(f"[t32-dap-proxy] VS Code connected ({peer})", flush=True)
            await self.proxy_session(
                client_reader,
                client_writer,
                backend_reader,
                backend_writer,
                initial,
            )
        except (BridgeError, DapProtocolError, OSError, asyncio.TimeoutError) as error:
            print(f"[t32-dap-proxy] session error: {error}", flush=True)
            self.exit_code = 1
        finally:
            client_writer.close()
            with contextlib.suppress(Exception):
                await client_writer.wait_closed()
            if claimed:
                self.session_finished.set()

    async def proxy_session(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        backend_reader: asyncio.StreamReader,
        backend_writer: asyncio.StreamWriter,
        initial: bytes,
    ) -> None:
        session = DapSession(
            self,
            client_reader,
            client_writer,
            backend_reader,
            backend_writer,
            initial,
        )
        await session.run()

    async def shutdown(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
        if self.adapter is not None and self.adapter.returncode is None:
            self.adapter.terminate()
            try:
                await asyncio.wait_for(self.adapter.wait(), timeout=2)
            except asyncio.TimeoutError:
                self.adapter.kill()
                await self.adapter.wait()

    async def run(self) -> int:
        await self.start_adapter()
        self.server = await asyncio.start_server(
            self.handle_client, "127.0.0.1", self.config.dap_port
        )
        print(
            f"[t32-dap-proxy] Listening on 127.0.0.1:{self.config.dap_port} "
            f"(adapter {self.config.dap_backend_port})",
            flush=True,
        )

        adapter_wait = asyncio.create_task(self.adapter.wait())
        session_wait = asyncio.create_task(self.session_finished.wait())
        shutdown_wait = asyncio.create_task(self.shutdown_requested.wait())
        done, pending = await asyncio.wait(
            {adapter_wait, session_wait, shutdown_wait},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if adapter_wait in done and not self.session_finished.is_set():
            code = adapter_wait.result()
            print(f"[t32-dap-proxy] adapter exited ({code})", flush=True)
            self.exit_code = code or 1
        for task in pending:
            task.cancel()
        await self.shutdown()
        return self.exit_code


async def _async_main(config: Config) -> int:
    proxy = DapProxy(config)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, proxy.shutdown_requested.set)
    return await proxy.run()


def run_proxy(config: Config) -> None:
    try:
        exit_code = asyncio.run(_async_main(config))
    except OSError as error:
        raise BridgeError(f"cannot start DAP proxy: {error}") from error
    if exit_code:
        raise BridgeError(f"DAP proxy exited with code {exit_code}")
