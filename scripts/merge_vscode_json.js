#!/usr/bin/env node

"use strict";

const fs = require("fs");

function fail(message) {
    console.error(`[trace32-install] ${message}`);
    process.exit(1);
}

function stripJsonComments(text) {
    let result = "";
    let inString = false;
    let escaped = false;
    let lineComment = false;
    let blockComment = false;

    for (let index = 0; index < text.length; index += 1) {
        const character = text[index];
        const next = text[index + 1];

        if (lineComment) {
            if (character === "\n") {
                lineComment = false;
                result += character;
            }
            continue;
        }
        if (blockComment) {
            if (character === "*" && next === "/") {
                blockComment = false;
                index += 1;
            } else if (character === "\n") {
                result += character;
            }
            continue;
        }
        if (inString) {
            result += character;
            if (escaped) {
                escaped = false;
            } else if (character === "\\") {
                escaped = true;
            } else if (character === "\"") {
                inString = false;
            }
            continue;
        }
        if (character === "\"") {
            inString = true;
            result += character;
        } else if (character === "/" && next === "/") {
            lineComment = true;
            index += 1;
        } else if (character === "/" && next === "*") {
            blockComment = true;
            index += 1;
        } else {
            result += character;
        }
    }
    return result;
}

function stripTrailingCommas(text) {
    let result = "";
    let inString = false;
    let escaped = false;

    for (let index = 0; index < text.length; index += 1) {
        const character = text[index];
        if (inString) {
            result += character;
            if (escaped) {
                escaped = false;
            } else if (character === "\\") {
                escaped = true;
            } else if (character === "\"") {
                inString = false;
            }
            continue;
        }
        if (character === "\"") {
            inString = true;
            result += character;
            continue;
        }
        if (character === ",") {
            let lookahead = index + 1;
            while (/\s/.test(text[lookahead] || "")) {
                lookahead += 1;
            }
            if (text[lookahead] === "}" || text[lookahead] === "]") {
                continue;
            }
        }
        result += character;
    }
    return result;
}

function readJsonc(filename) {
    try {
        const source = fs.readFileSync(filename, "utf8").replace(/^\uFEFF/, "");
        return JSON.parse(stripTrailingCommas(stripJsonComments(source)));
    } catch (error) {
        fail(`cannot parse ${filename}: ${error.message}`);
    }
}

function mergeTasks(existing, template) {
    if (!Array.isArray(existing.tasks) || !Array.isArray(template.tasks)) {
        fail("tasks.json must contain a tasks array");
    }

    const aliases = new Map([
        ["T32: Flash + Debug", "T32: Flash"],
        ["T32: Load + Debug", "T32: Load ELF"]
    ]);
    const templates = new Map(
        template.tasks.map((task) => [task.label, task])
    );
    const installed = new Set();
    const tasks = [];

    for (const task of existing.tasks) {
        const label = aliases.get(task.label) || task.label;
        const replacement = templates.get(label);
        if (!replacement) {
            tasks.push(task);
        } else if (!installed.has(label)) {
            tasks.push({ ...task, ...replacement });
            installed.add(label);
        }
    }

    for (const task of template.tasks) {
        if (!installed.has(task.label)) {
            tasks.push(task);
        }
    }

    return { ...existing, version: template.version, tasks };
}

function mergeLaunch(existing, template) {
    if (
        !Array.isArray(existing.configurations) ||
        !Array.isArray(template.configurations)
    ) {
        fail("launch.json must contain a configurations array");
    }

    const legacyNames = new Set(["1. Flash + Debug", "2. Load + Debug"]);
    const templates = new Map(
        template.configurations.map((configuration) => [
            configuration.name,
            configuration
        ])
    );
    const installed = new Set();
    const configurations = [];

    for (const configuration of existing.configurations) {
        if (legacyNames.has(configuration.name)) {
            continue;
        }
        const replacement = templates.get(configuration.name);
        if (!replacement) {
            configurations.push(configuration);
        } else if (!installed.has(configuration.name)) {
            configurations.push({ ...configuration, ...replacement });
            installed.add(configuration.name);
        }
    }

    for (const configuration of template.configurations) {
        if (!installed.has(configuration.name)) {
            configurations.push(configuration);
        }
    }

    return {
        ...existing,
        version: template.version,
        configurations
    };
}

const [kind, templatePath, targetPath] = process.argv.slice(2);
if (!["tasks", "launch"].includes(kind) || !templatePath || !targetPath) {
    fail("usage: merge_vscode_json.js tasks|launch TEMPLATE TARGET");
}

const existing = readJsonc(targetPath);
const template = readJsonc(templatePath);
const merged =
    kind === "tasks"
        ? mergeTasks(existing, template)
        : mergeLaunch(existing, template);
const temporaryPath = `${targetPath}.tmp.${process.pid}`;

try {
    fs.writeFileSync(temporaryPath, `${JSON.stringify(merged, null, 4)}\n`);
    fs.renameSync(temporaryPath, targetPath);
} catch (error) {
    try {
        fs.unlinkSync(temporaryPath);
    } catch {
        // Nothing to clean up.
    }
    fail(`cannot update ${targetPath}: ${error.message}`);
}
