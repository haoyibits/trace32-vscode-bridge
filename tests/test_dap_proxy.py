from __future__ import annotations

import asyncio
import json
import unittest
from unittest import mock

from trace32_bridge.dap.protocol import encode_message
from trace32_bridge.dap.proxy import DapProxy, DapSession


async def stream_pair():
    accepted = asyncio.get_running_loop().create_future()

    async def accept(reader, writer):
        accepted.set_result((reader, writer))

    server = await asyncio.start_server(accept, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    remote_reader, remote_writer = await asyncio.open_connection(
        "127.0.0.1", port
    )
    local_reader, local_writer = await accepted
    server.close()
    return local_reader, local_writer, remote_reader, remote_writer


async def read_message(reader: asyncio.StreamReader):
    header = await reader.readuntil(b"\r\n\r\n")
    length = None
    for line in header.decode("ascii").split("\r\n"):
        name, separator, value = line.partition(":")
        if separator and name.lower() == "content-length":
            length = int(value.strip())
    if length is None:
        raise AssertionError("missing Content-Length")
    return json.loads((await reader.readexactly(length)).decode("utf-8"))


class DapProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_locals_reference_is_intercepted(self) -> None:
        (
            proxy_client_reader,
            proxy_client_writer,
            test_client_reader,
            test_client_writer,
        ) = await stream_pair()
        (
            proxy_backend_reader,
            proxy_backend_writer,
            test_backend_reader,
            test_backend_writer,
        ) = await stream_pair()

        request = {
            "seq": 1,
            "type": "request",
            "command": "scopes",
            "arguments": {"frameId": 1},
        }
        proxy = DapProxy(mock.Mock())
        task = asyncio.create_task(
            proxy.proxy_session(
                proxy_client_reader,
                proxy_client_writer,
                proxy_backend_reader,
                proxy_backend_writer,
                encode_message(request),
            )
        )

        self.assertEqual((await read_message(test_backend_reader))["command"], "scopes")
        test_backend_writer.write(
            encode_message(
                {
                    "seq": 2,
                    "type": "response",
                    "request_seq": 1,
                    "success": True,
                    "command": "scopes",
                    "body": {
                        "scopes": [
                            {
                                "name": "Locals",
                                "presentationHint": "locals",
                                "variablesReference": 42,
                            }
                        ]
                    },
                }
            )
        )
        await test_backend_writer.drain()
        await read_message(test_client_reader)

        test_client_writer.write(
            encode_message(
                {
                    "seq": 3,
                    "type": "request",
                    "command": "variables",
                    "arguments": {"variablesReference": 42},
                }
            )
        )
        await test_client_writer.drain()
        response = await read_message(test_client_reader)
        self.assertTrue(response["success"])
        self.assertEqual(response["body"], {"variables": []})
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(test_backend_reader.read(1), timeout=0.02)

        test_client_writer.close()
        await test_client_writer.wait_closed()
        await asyncio.wait_for(task, timeout=1)
        proxy_client_writer.close()
        await proxy_client_writer.wait_closed()
        test_backend_writer.close()
        await test_backend_writer.wait_closed()

    async def test_closing_session_cancels_pending_restart(self) -> None:
        (
            proxy_client_reader,
            proxy_client_writer,
            _,
            test_client_writer,
        ) = await stream_pair()
        (
            proxy_backend_reader,
            proxy_backend_writer,
            _,
            test_backend_writer,
        ) = await stream_pair()
        restart = {
            "seq": 1,
            "type": "request",
            "command": "restart",
            "arguments": {},
        }
        started = asyncio.Event()
        cancelled = asyncio.Event()
        never = asyncio.Event()

        async def blocked_reset() -> None:
            started.set()
            try:
                await never.wait()
            finally:
                cancelled.set()

        proxy = DapProxy(mock.Mock())
        proxy.reset_target = blocked_reset
        session = DapSession(
            proxy,
            proxy_client_reader,
            proxy_client_writer,
            proxy_backend_reader,
            proxy_backend_writer,
            encode_message(restart),
        )
        task = asyncio.create_task(session.run())
        await asyncio.wait_for(started.wait(), timeout=1)

        test_client_writer.close()
        await test_client_writer.wait_closed()
        await asyncio.wait_for(task, timeout=1)

        self.assertTrue(cancelled.is_set())
        self.assertFalse(session.background_tasks)
        proxy_client_writer.close()
        await proxy_client_writer.wait_closed()
        test_backend_writer.close()
        await test_backend_writer.wait_closed()


if __name__ == "__main__":
    unittest.main()
