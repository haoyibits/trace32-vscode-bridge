#!/usr/bin/env node

"use strict";

const net = require("net");
const { spawn } = require("child_process");

const host = "127.0.0.1";

function requiredEnv(name) {
    const value = process.env[name];
    if (!value) {
        console.error(`[t32-dap-proxy] missing environment variable ${name}`);
        process.exit(2);
    }
    return value;
}

const frontendPort = Number(process.env.T32_DAP_PORT || "58870");
const backendPort = Number(process.env.T32_DAP_BACKEND_PORT || "58871");
const backendTimeoutMs =
    Number(process.env.T32_DAP_BACKEND_TIMEOUT || "30") * 1000;
const rclPort = Number(process.env.T32_RCL_PORT || "20000");
const adapter = requiredEnv("T32_DEBUG_ADAPTER");
const t32rem = requiredEnv("T32_REM");
// Required rather than derived from __dirname: the CMM scripts live in
// scripts/cmm/ and this proxy in scripts/host/, so a relative guess from here
// would fail silently at Reset time instead of at startup. t32.sh always sets it.
const resetScript = requiredEnv("T32_RESET_SCRIPT");

let proxySequence = 1000000;
let activeClient = null;
let activeBackend = null;
let shuttingDown = false;
let dapSessionStarted = false;
const localVariableReferences = new Set();

function encode(message) {
    const body = Buffer.from(JSON.stringify(message), "utf8");
    return Buffer.concat([
        Buffer.from(`Content-Length: ${body.length}\r\n\r\n`, "ascii"),
        body
    ]);
}

class DapDecoder {
    constructor(onMessage) {
        this.buffer = Buffer.alloc(0);
        this.onMessage = onMessage;
    }

    push(chunk) {
        this.buffer = Buffer.concat([this.buffer, chunk]);

        while (true) {
            const separator = this.buffer.indexOf("\r\n\r\n");
            if (separator < 0) {
                return;
            }

            const header = this.buffer.subarray(0, separator).toString("ascii");
            const match = /(?:^|\r\n)Content-Length:\s*(\d+)/i.exec(header);
            if (!match) {
                throw new Error(`DAP message has no Content-Length: ${header}`);
            }

            const length = Number(match[1]);
            const messageEnd = separator + 4 + length;
            if (this.buffer.length < messageEnd) {
                return;
            }

            const payload = this.buffer
                .subarray(separator + 4, messageEnd)
                .toString("utf8");
            this.buffer = this.buffer.subarray(messageEnd);
            this.onMessage(JSON.parse(payload));
        }
    }
}

function sendClient(message) {
    if (activeClient && !activeClient.destroyed) {
        activeClient.write(encode(message));
    }
}

function responseFor(request, success, message = null, body = null) {
    return {
        seq: proxySequence++,
        type: "response",
        request_seq: request.seq,
        success,
        command: request.command,
        message,
        body
    };
}

function handleRestart(request, continueTarget) {
    console.log("[t32-dap-proxy] Restart -> reset, then DAP continue");

    const reset = spawn(
        t32rem,
        [
            "localhost",
            "protocol=NETTCP",
            `port=${rclPort}`,
            "wait=5000",
            "DO",
            resetScript
        ],
        { stdio: ["ignore", "pipe", "pipe"] }
    );

    let output = "";
    let finished = false;

    reset.stdout.on("data", (chunk) => {
        output += chunk.toString();
    });
    reset.stderr.on("data", (chunk) => {
        output += chunk.toString();
    });

    reset.on("error", (error) => {
        finished = true;
        sendClient(responseFor(request, false, error.message));
    });

    reset.on("close", async (code) => {
        if (finished) {
            return;
        }
        if (code !== 0) {
            const detail = output.trim() || `t32rem exited with code ${code}`;
            sendClient(responseFor(request, false, detail));
            return;
        }

        localVariableReferences.clear();
        try {
            await continueTarget();
            sendClient(responseFor(request, true));
            sendClient({
                seq: proxySequence++,
                type: "event",
                event: "continued",
                body: {
                    threadId: 0,
                    allThreadsContinued: true
                }
            });
        } catch (error) {
            sendClient(responseFor(request, false, error.message));
        }
    });
}

function connectBackend(
    client,
    initialChunk,
    deadline = Date.now() + backendTimeoutMs
) {
    if (client.destroyed) {
        if (activeClient === client) {
            activeClient = null;
        }
        return;
    }

    const backend = net.connect(backendPort, host);

    backend.once("connect", () => {
        if (client.destroyed) {
            backend.destroy();
            if (activeClient === client) {
                activeClient = null;
            }
            return;
        }

        activeBackend = backend;
        console.log("[t32-dap-proxy] VS Code connected");

        const clientRequests = new Map();
        const internalRequests = new Map();

        function sendBackendRequest(command, args) {
            return new Promise((resolve, reject) => {
                const seq = proxySequence++;
                const timeout = setTimeout(() => {
                    internalRequests.delete(seq);
                    reject(new Error(`DAP ${command} timed out`));
                }, 5000);

                internalRequests.set(seq, {
                    resolve: (message) => {
                        clearTimeout(timeout);
                        resolve(message);
                    },
                    reject: (error) => {
                        clearTimeout(timeout);
                        reject(error);
                    }
                });

                backend.write(
                    encode({
                        seq,
                        type: "request",
                        command,
                        arguments: args
                    })
                );
            });
        }

        const clientDecoder = new DapDecoder((message) => {
            dapSessionStarted = true;

            if (message.type === "request") {
                clientRequests.set(message.seq, message.command);

                if (message.command === "restart") {
                    handleRestart(
                        message,
                        () => sendBackendRequest("continue", { threadId: 0 })
                    );
                    return;
                }

                if (
                    message.command === "variables" &&
                    localVariableReferences.has(
                        message.arguments?.variablesReference
                    )
                ) {
                    sendClient(
                        responseFor(message, true, null, { variables: [] })
                    );
                    return;
                }
            }

            backend.write(encode(message));
        });

        const backendDecoder = new DapDecoder((message) => {
            if (
                message.type === "response" &&
                internalRequests.has(message.request_seq)
            ) {
                const pending = internalRequests.get(message.request_seq);
                internalRequests.delete(message.request_seq);
                if (message.success) {
                    pending.resolve(message);
                } else {
                    pending.reject(
                        new Error(message.message || `${message.command} failed`)
                    );
                }
                return;
            }

            if (
                message.type === "response" &&
                (message.command === "scopes" ||
                    clientRequests.get(message.request_seq) === "scopes")
            ) {
                for (const scope of message.body?.scopes || []) {
                    if (
                        scope.presentationHint === "locals" ||
                        scope.name?.toLowerCase() === "locals"
                    ) {
                        localVariableReferences.add(
                            scope.variablesReference
                        );
                    }
                }
            }

            sendClient(message);
        });

        client.on("data", (chunk) => {
            try {
                clientDecoder.push(chunk);
            } catch (error) {
                console.error(`[t32-dap-proxy] client DAP error: ${error}`);
                shutdown(1);
            }
        });
        backend.on("data", (chunk) => {
            try {
                backendDecoder.push(chunk);
            } catch (error) {
                console.error(`[t32-dap-proxy] backend DAP error: ${error}`);
                shutdown(1);
            }
        });

        clientDecoder.push(initialChunk);
        client.resume();
    });

    backend.once("error", (error) => {
        backend.destroy();
        if (Date.now() < deadline && error.code === "ECONNREFUSED") {
            if (client.destroyed) {
                if (activeClient === client) {
                    activeClient = null;
                }
                return;
            }
            setTimeout(
                () => connectBackend(client, initialChunk, deadline),
                100
            );
            return;
        }

        console.error(
            `[t32-dap-proxy] cannot connect to adapter on ${backendPort}: ${error.message}`
        );
        client.destroy();
        shutdown(1);
    });

    backend.once("close", () => {
        if (activeBackend === backend && activeClient) {
            activeClient.end();
        }
    });
}

let adapterProcess;
let server;

function shutdown(exitCode = 0) {
    if (shuttingDown) {
        return;
    }
    shuttingDown = true;

    activeClient?.destroy();
    activeBackend?.destroy();
    server?.close();

    if (adapterProcess && !adapterProcess.killed) {
        adapterProcess.kill("SIGTERM");
    }

    setTimeout(() => process.exit(exitCode), 100);
}

const adapterArgs = [
    "--port",
    String(backendPort),
    "--log_to",
    "stdout"
];
if (process.env.T32_DAP_DEBUG === "1") {
    adapterArgs.push("--log_level", "debug");
}

adapterProcess = spawn(adapter, adapterArgs, {
    stdio: ["ignore", "inherit", "inherit"]
});

adapterProcess.on("error", (error) => {
    console.error(`[t32-dap-proxy] cannot start adapter: ${error.message}`);
    shutdown(1);
});
adapterProcess.on("exit", (code, signal) => {
    if (!shuttingDown) {
        console.error(
            `[t32-dap-proxy] adapter exited (${signal || code})`
        );
        shutdown(code || 1);
    }
});

server = net.createServer((client) => {
    let claimed = false;
    client.setNoDelay(true);
    client.once("data", (chunk) => {
        if (activeClient) {
            client.destroy();
            return;
        }
        activeClient = client;
        claimed = true;
        dapSessionStarted = true;
        client.pause();
        connectBackend(client, chunk);
    });
    client.on("close", () => {
        if (!claimed) {
            return;
        }
        if (dapSessionStarted) {
            shutdown(0);
            return;
        }

        if (activeClient === client) {
            activeClient = null;
        }
        activeBackend?.destroy();
        activeBackend = null;
    });
    client.on("error", (error) => {
        console.error(`[t32-dap-proxy] VS Code socket error: ${error.message}`);
    });
});

server.on("error", (error) => {
    console.error(`[t32-dap-proxy] listen error: ${error.message}`);
    shutdown(1);
});

server.listen(frontendPort, host, () => {
    console.log(
        `[t32-dap-proxy] Listening on ${host}:${frontendPort} (adapter ${backendPort})`
    );
});

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));
