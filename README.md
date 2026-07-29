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
- A macOS or Linux host
- VS Code
- TRACE32 PowerView and `t32debugadapter`
- Remote API enabled in the PowerView configuration:

  ```text
  RCL=NETTCP
  PORT=20000
  ```

Install Lauterbach RCL into the Python that will run the tool:

```bash
python3.13 -m pip install 'lauterbach-trace32-rcl>=1.1,<2'
```

If Homebrew Python reports `externally-managed-environment`, use a user-level
installation:

```bash
python3.13 -m pip install --user --break-system-packages \
  'lauterbach-trace32-rcl>=1.1,<2'
```

`--user` keeps the package in the current user's directory rather than writing
into Homebrew's Python installation.

`install-vscode` checks RCL in the current Python and pins every TRACE32 task
to that interpreter. It does not create a `.venv` or modify the Python
environment automatically.

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

`.run/` is generated and contains only the PowerView log. It can be deleted at
any time and is recreated on the next launch. The `tests/` directory shown
above exists only in the source repository and is removed during deployment.

## Usage guide

Run the following commands from the consuming project's root. Do not run
`install-vscode` in this tool's source repository: it is intended for a
deployed copy and removes that copy's `.git/` and `tests/` after installation.

### 1. Prepare TRACE32

Install PowerView and `t32debugadapter`, then enable the Remote API in
TRACE32's `config.t32`:

```text
RCL=NETTCP
PORT=20000
```

When using a different port, set the same value in
`trace32.rcl_port` in `trace32.toml`.

### 2. Add the tool and Flash script

Copy this directory into the consuming project and place that project's SR6P6
Flash script beside `toolbar.cmm`:

```text
actual-project/
├── .vscode/                              # created or merged by install-vscode
├── trace32-vscode-bridge/
│   ├── t32.py
│   ├── trace32.toml
│   └── trace32_bridge/
│       └── cmm/
│           ├── toolbar.cmm
│           └── flash.cmm                 # supplied by the consuming project
├── src/
└── build/
```

This tool does not ship a chip-specific `flash.cmm`, because Flash layout and
algorithms belong to the consuming project.

### 3. Configure the consuming project

Edit `trace32-vscode-bridge/trace32.toml`:

```toml
[project]
root = ".."
program = "my_app"
elf = "build/my_app.elf"

[target]
cpu = "SR6P6"
cores = "1."
mem_access = "AXI"
jtag_clock = "10MHz"
dual_port = "ON"

[rtos]
config = "~~/demo/arm/kernel/freertos/freertos.t32"
menu = "~~/demo/arm/kernel/freertos/freertos.men"
show_tasks = true

[flash]
script = "trace32_bridge/cmm/flash.cmm"
args = ["DUALPORT=1", "JTAG_CLOCK=10MHz"]
```

Path rules:

- `project.root` is relative to the toolkit; use `..` when the toolkit is
  directly inside the project
- `project.elf` is relative to `project.root`
- a normal `flash.script` path is relative to the toolkit
- paths beginning with `~~` are resolved by TRACE32
- leave `[rtos]` `config` and `menu` empty to disable RTOS awareness

### 4. Install RCL and the VS Code configuration

Use Python 3.11 or newer. The following example uses Python 3.13:

```bash
python3.13 -m pip install 'lauterbach-trace32-rcl>=1.1,<2'
python3.13 -c "import lauterbach.trace32.rcl; print('RCL OK')"
python3.13 trace32-vscode-bridge/t32.py install-vscode
```

If Homebrew Python rejects the first command, use the
`--user --break-system-packages` form from Requirements.

The final command:

1. Verifies that the current Python can import `lauterbach.trace32.rcl`
2. Backs up and merges `.vscode/tasks.json` and `.vscode/launch.json`
3. Makes every TRACE32 task use the current Python
4. Removes development files and generated artifacts from the deployed copy

Existing non-TRACE32 tasks and launch configurations are preserved. Backups
are stored in the consuming project's `.vscode/` directory with names such as
`tasks.json.bak.<timestamp>`.

Cleanup is confined to `trace32-vscode-bridge/`: it removes `test/`, `tests/`,
the deployed copy's own `.git/` and `.github/`, `build/`, `dist/`,
`*.egg-info`, Python caches, and a legacy tool-local `.venv/`. It preserves the
consuming project's `.git/` and the toolkit's `.run/`, configuration,
documentation, and runtime source.

Installing RCL requires access to a Python package index. On another computer,
install RCL into that computer's Python before running `install-vscode`.

### 5. Verify the installation

This command does not connect to hardware. It reports the resolved project,
ELF, and TRACE32 paths:

```bash
python3.13 trace32-vscode-bridge/t32.py config
```

Resolve every `MISSING` entry before using Flash or Load.

### 6. Daily workflow

1. Build the ELF selected by `project.elf` with the consuming project's build
   system.
2. In VS Code, run **Tasks: Run Task → T32: Flash**. It starts or reuses
   PowerView, invokes the project's `flash.cmm`, programs the ELF, loads
   symbols, and runs the target.
3. Open **Run and Debug**, select `TRACE32: Attach`, and press F5. Its hidden
   `T32: Start Debug Adapter` task starts automatically.
4. When the code is already programmed and only symbols need refreshing, use
   `T32: Load ELF`; it does not modify Flash.
5. After the firmware initializes SEGGER RTT, run `T32: RTT Viewer`. Press
   `Ctrl-C` in its terminal to exit.

Use the `open` CLI command to start PowerView without loading or programming.
When this tool launches a new PowerView process, it also installs `Flash` and
`Load ELF` toolbar buttons.

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
T32SYS=/opt/t32 python3.13 trace32-vscode-bridge/t32.py load
```

The precedence is environment, TOML, then platform defaults.

## Commands

The following command form still assumes the consuming project's root as the
working directory:

```bash
python3.13 trace32-vscode-bridge/t32.py <command>
```

| Command | Action |
|---|---|
| `flash` | Program the ELF, load symbols, and run |
| `load` | Load symbols and run without modifying Flash |
| `open` | Start or reuse PowerView |
| `rtt` | Start the bidirectional RTT terminal |
| `config` | Report resolved paths without connecting to hardware |
| `install-vscode` | Check RCL and install or update VS Code files |
| `adapter` | Start the DAP proxy; normally invoked by `TRACE32: Attach` |

RTT can bypass symbol resolution:

```bash
python3.13 trace32-vscode-bridge/t32.py rtt --cb 0x20000000
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
       └─ install-vscode ──> Python VS Code installer

PowerView toolbar ──> toolbar.cmm ──> asynchronous Python CLI ──> RCL
```

Python owns configuration, paths, processes, networking, DAP, target setup,
flash/load sequencing, reset, error handling, and installation. The only
tool-owned CMM file defines the PowerView toolbar, whose block-based GUI DSL
has no useful Python representation. When the tool launches a new PowerView
process, it installs the toolbar after the RCL port is ready. All operations
return directly through the Python Remote API.

## Building

The bridge consumes an existing ELF and does not build the project. To build
before flashing, add this to the installed `T32: Flash` task:

```jsonc
"dependsOn": ["your build task"],
"dependsOrder": "sequence"
```

## Source development tests

This section applies only to the source repository; tests are removed from a
deployed copy. Do not run `install-vscode` to prepare development tests.
Create a separate development environment instead:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -v
```

They cover TOML configuration, path handling, flash cleanup, PowerView startup,
JSONC merging, DAP framing, and DAP session cleanup. Hardware acceptance should
still cover Flash, Load, RTT, Pause, Restart, and breakpoints.

## Troubleshooting

- If PowerView does not open the RCL port, check `RCL=NETTCP`, the configured
  port, and `.run/powerview.log`.
- If the ELF or a TRACE32 path is reported as `MISSING`, build the ELF first.
  When TRACE32 is not installed under `~/t32`, configure its paths or the
  corresponding environment variables, then rerun `t32.py config`.
- If `flash.cmm` is missing, remember that normal paths are relative to
  `trace32-vscode-bridge/`; the default is
  `trace32_bridge/cmm/flash.cmm`.
- If VS Code reports a missing RCL package, install RCL into the same Python
  used for `install-vscode`, then rerun the installer:

  ```bash
  python3.13 -m pip install 'lauterbach-trace32-rcl>=1.1,<2'
  python3.13 trace32-vscode-bridge/t32.py install-vscode
  ```
- If an operation times out, inspect the PowerView AREA window and adjust
  `trace32.operation_timeout` if appropriate.
- RTT requires an attached target and working run-time memory access, normally
  enabled with `target.dual_port = "ON"`.
- The proxy suppresses a known-bad Locals request on affected adapter versions.
  Watch expressions, registers, stacks, breakpoints, and stepping are still
  forwarded normally.
