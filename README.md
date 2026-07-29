# trace32-vscode-bridge

A reusable TRACE32 PowerView integration for VS Code. All host-side code is
Python; target-specific flash CMM scripts belong to the consuming project.

*中文：[README.zh-CN.md](README.zh-CN.md)*

It installs three visible tasks and one debug configuration:

| VS Code item | Action |
|---|---|
| `T32: Flash` | Program an existing ELF, load symbols, and run |
| `T32: Load ELF` | Load symbols without programming and run |
| `T32: RTT Viewer` | Bidirectional SEGGER RTT terminal |
| `TRACE32: Attach` | Start the DAP compatibility proxy and attach |

## Requirements

- Python 3.11 or newer
- TRACE32 PowerView and `t32debugadapter`
- Remote API enabled in the PowerView configuration:

  ```text
  RCL=NETTCP
  PORT=20000
  ```

Install the Python dependency:

```bash
python3 -m pip install -e ./trace32-vscode-bridge
```

Bash and Node.js are no longer required.

## Layout

```text
trace32-vscode-bridge/
├── pyproject.toml
├── trace32.toml
├── t32.py
├── trace32_bridge/
│   ├── cmm/
│   │   └── toolbar.cmm
│   ├── cli.py
│   ├── config.py
│   ├── powerview.py
│   ├── remote.py
│   ├── target.py
│   ├── rtt.py
│   ├── dap/
│   │   ├── protocol.py
│   │   └── proxy.py
│   └── vscode/
│       ├── installer.py
│       └── jsonc.py
├── vscode/
│   ├── tasks.json
│   └── launch.json
└── tests/
```

`.run/` is generated and contains the PowerView log.

## Add it to a project

1. Place this directory inside the target project.

2. Edit `trace32.toml`:

   ```toml
   [project]
   root = ".."
   program = "my_app"
   elf = "build/my_app.elf"

   [target]
   cpu = "STM32F407ZG"
   cores = "1."
   mem_access = "AXI"
   jtag_clock = "10MHz"
   dual_port = "ON"

   [rtos]
   config = "~~/demo/arm/kernel/freertos/freertos.t32"
   menu = "~~/demo/arm/kernel/freertos/freertos.men"
   show_tasks = true

   [flash]
   script = "~~/demo/arm/flash/stm32f4xx.cmm"
   args = ["CPU=STM32F407ZG", "DUALPORT=1"]
   ```

   `project.elf` is relative to `project.root`. Normal flash paths are relative
   to the toolkit; paths beginning with `~~` are resolved by TRACE32.

3. Install or update the VS Code configuration:

   ```bash
   python3 trace32-vscode-bridge/t32.py install-vscode
   ```

   Existing task and launch files are backed up and merged. Unrelated entries
   are preserved. The generated tasks record the exact Python interpreter used
   for installation, so VS Code and the PowerView toolbar use the environment
   where the bridge dependency was installed.

4. Run `T32: Flash` or `T32: Load ELF`, then select `TRACE32: Attach` and press
   F5.

## Configuration

`trace32.toml` contains:

- `[project]`: project root, program name, and ELF
- `[target]`: CPU, cores, memory access, JTAG clock, and dual-port access
- `[rtos]`: optional RTOS-awareness configuration, menu, and task window
- `[flash]`: the consuming project's flash CMM and its arguments
- `[trace32]`: installation paths, ports, and timeouts
- `[rtt]`: RTT symbol, address override, and polling period

The TRACE32 installation defaults to `~/t32`. Standard executable and
configuration paths are derived automatically. Override an installation for
one invocation with:

```bash
T32SYS=/opt/t32 python3 trace32-vscode-bridge/t32.py load
```

The precedence is environment, TOML, then platform defaults.

## Commands

```bash
python3 t32.py flash
python3 t32.py load
python3 t32.py open
python3 t32.py rtt
python3 t32.py adapter
python3 t32.py config
python3 t32.py install-vscode
```

RTT can bypass symbol resolution:

```bash
python3 t32.py rtt --cb 0x20000000
```

## Flash extension contract

This repository does not own a target-specific flash CMM. The configured
script must support Lauterbach's `PREPAREONLY` convention: connect and
configure the target, declare its flash, and return without programming.

Python then performs the common sequence through RCL:

```text
FLASH.ReProgram ALL /Erase
Data.LOAD.Elf <ELF>
FLASH.ReProgram OFF
SYStem.Down
SYStem.Up
```

## Architecture

```text
VS Code/CLI
    └─ Python CLI
       ├─ flash/load ──> Python RCL ──> project flash.cmm PREPAREONLY
       ├─ open ────────> PowerView + Python-installed toolbar
       ├─ rtt ─────────> Python RCL
       ├─ adapter ─────> Python DAP proxy ──> t32debugadapter
       └─ install ─────> Python VS Code installer

PowerView toolbar ──> toolbar.cmm ──> asynchronous Python CLI ──> RCL
```

Python owns configuration, paths, processes, networking, DAP, target setup,
flash/load sequencing, reset, error handling, and installation. The only
tool-owned CMM file defines the PowerView toolbar, whose block-based GUI DSL
has no useful Python representation. Python installs it after the RCL port is
ready; all operations return directly through the Python Remote API.

## Building

The bridge consumes an existing ELF and does not build the project. To build
before flashing, add this to the installed `T32: Flash` task:

```jsonc
"dependsOn": ["your build task"],
"dependsOrder": "sequence"
```

## Tests

Host-side tests do not need hardware:

```bash
python3 -m unittest discover -v
```

They cover TOML configuration, path handling, flash cleanup, PowerView startup,
JSONC merging, DAP framing, and DAP session cleanup. Hardware acceptance should
still cover Flash, Load, RTT, Pause, Restart, and breakpoints.

## Troubleshooting

- If PowerView does not open the RCL port, check `RCL=NETTCP`, the configured
  port, and `.run/powerview.log`.
- If an operation times out, inspect the PowerView AREA window and adjust
  `trace32.operation_timeout` if appropriate.
- RTT requires an attached target and working run-time memory access, normally
  enabled with `target.dual_port = "ON"`.
- The proxy suppresses a known-bad Locals request on affected adapter versions.
  Watch expressions, registers, stacks, breakpoints, and stepping are still
  forwarded normally.
