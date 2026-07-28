# trace32-vscode-bridge

A reusable TRACE32 PowerView + VS Code debug harness. Moving it to a new
project means editing **one file**: `config.env`.

*中文版：[README.zh-CN.md](README.zh-CN.md)*

Three visible tasks and one launch configuration:

| VS Code | What it does |
|---|---|
| Task `T32: Flash` | flash the existing ELF → load symbols → run; no build |
| Task `T32: Load ELF` | no build and no flash: load symbols from the existing ELF, then run |
| Task `T32: RTT Viewer` | bidirectional SEGGER RTT terminal (printf output plus CLI input) |
| Launch config `TRACE32: Attach` | start the hidden DAP adapter task automatically, then attach |

Run Flash or Load ELF when needed, then press F5 and select `TRACE32: Attach`.
The adapter starts automatically; set breakpoints and single-step in VS Code
as usual.

**Building is out of scope.** The toolkit does not know or care whether the
project is Rust, C or anything else — it consumes a finished ELF. See
[Chaining your build](#chaining-your-build).

---

## Layout

```text
trace32-vscode-bridge/
├── config.env                 ← the only file you edit per project
├── install.sh                 ← copies vscode/ templates into the project's .vscode/
├── install/
│   └── merge_vscode_json.js   ← install-time only; not used while debugging
├── vscode/
│   ├── tasks.json
│   └── launch.json
└── scripts/
    ├── t32.sh                 ← single entry point, called by the VS Code tasks
    ├── cmm/                   ← runs inside PowerView (PRACTICE)
    │   ├── startup.cmm        ← PowerView startup script
    │   ├── load_config.cmm    ← loads the generated .run/config.cmm
    │   ├── target.cmm         ← the flash and load actions
    │   ├── toolbar.cmm        ← two PowerView toolbar buttons
    │   └── reset_stop.cmm     ← reset-and-stop helper; DAP then continues
    └── host/                  ← host processes, talking to PowerView over a socket
        ├── rtt_viewer.py      ← RTT terminal (RCL)
        └── dap_proxy.js       ← DAP compatibility proxy (Pause / Reset fixes)
```

The split is by **where the code executes**, not by language: everything under
`cmm/` runs inside PowerView's PRACTICE interpreter and cannot be run or tested
from the host, while `host/` holds ordinary local processes that reach PowerView
through a socket. `t32.sh` is the only entry point and stays at the top. A
patched vendor flash script, on the rare occasion you need one, goes into
`cmm/` alongside the rest.

`.run/` is generated (PowerView log, handshake stamps, and the `config.cmm`
translated from `config.env`) and is git-ignored.

### Paths

Nothing here is tied to one machine except the TRACE32 installation, which by
definition lives outside the project:

| What | How it is resolved |
|---|---|
| The scripts themselves | from `${BASH_SOURCE[0]}` / TRACE32's `~~~~` prefix — the toolkit finds itself wherever you drop it |
| `PROJECT_ROOT`, `ELF` | relative to `trace32-vscode-bridge/` and to `PROJECT_ROOT` |
| Stock flash scripts | `~~/demo/...`, where `~~` is TRACE32's own installation prefix |
| VS Code tasks | `${workspaceFolder}/trace32-vscode-bridge/scripts/t32.sh` |
| **TRACE32 tools** | **`T32_SYS`, absolute** — defaults to `$HOME/t32` |

`T32_BIN`, `T32_REM`, `T32_CONFIG` and `T32_DEBUG_ADAPTER` are all derived from
`T32_SYS` plus the auto-detected host directory, so a standard installation
needs no absolute path at all. Set any of them explicitly only if your layout
differs. To point at another installation without editing the file:

```bash
T32SYS=/opt/t32 ./trace32-vscode-bridge/scripts/t32.sh load
```

`./trace32-vscode-bridge/scripts/t32.sh config` prints every resolved path and flags the
ones that do not exist.

---

## Adding it to a project

1. Copy the whole `trace32-vscode-bridge/` directory into the project root:

   ```bash
   cp -r /path/to/trace32-vscode-bridge <your-project>/
   ```

2. Edit `<your-project>/trace32-vscode-bridge/config.env`. In practice only these
   four keys change between projects:

   ```sh
   PROGRAM_NAME="my_app"                        # must equal the ELF basename
   ELF="build/.../my_app.elf"                   # relative to PROJECT_ROOT
   T32_CPU="STM32F407ZG"
   T32_FLASH_SCRIPT="~~/demo/arm/flash/stm32f4xx.cmm"   # empty = never flash
   ```

3. Install the VS Code files:

   ```bash
   ./trace32-vscode-bridge/install.sh
   ```

   If `.vscode/tasks.json` or `.vscode/launch.json` already exists, the
   installer backs it up and merges it. Existing tasks and launch
   configurations are retained, matching TRACE32 entries are updated, and
   repeated installs do not create duplicates.

4. Make sure `~/t32/config.t32` enables the Remote API:

   ```text
   RCL=NETTCP
   PORT=20000
   ```

5. Install the Python dependency once (needed for RTT):

   ```bash
   python3 -m pip install lauterbach-trace32-rcl
   ```

6. Make sure Node.js is installed (the DAP compatibility proxy uses it):

   ```bash
   node --version
   ```

### Chaining your build

The toolkit never builds anything. To rebuild before flashing, point the flash
task at whatever build task the project already has, in `.vscode/tasks.json`:

```jsonc
{
    "label": "T32: Flash",
    "command": "${workspaceFolder}/trace32-vscode-bridge/scripts/t32.sh",
    "args": ["flash"],
    "dependsOn": ["cargo build"],     // or "make", "CMake: build", ...
    "dependsOrder": "sequence"
}
```

The template has no build dependency by default; add `dependsOn` yourself when
needed. The referenced task can be defined in the same file or provided by an extension
(rust-analyzer, CMake Tools, …). `"dependsOrder": "sequence"` is what makes VS
Code wait for the build to finish instead of running both at once.

If the build produces the ELF somewhere new, that is a one-line `ELF=` change in
`config.env` — nothing else in the toolkit cares.

### Switching to a different device

`T32_FLASH_SCRIPT` can point straight at a stock Lauterbach flash script, so a
device change is normally one line:

```sh
T32_FLASH_SCRIPT="~~/demo/arm/flash/stm32f4xx.cmm"
T32_FLASH_ARGS="CPU=STM32F407ZG DUALPORT=1"
T32_CPU="STM32F407ZG"
```

`~~` is TRACE32's installation directory. `target.cmm` invokes the script with
Lauterbach's `PREPAREONLY` convention — "connect, set up the target, declare
the flash, program nothing" — and then runs the programming sequence itself,
which is identical for every device:

```text
FLASH.ReProgram ALL /Erase
Data.LOAD.Elf <ELF>
FLASH.ReProgram OFF
SYStem.Down / SYStem.Up
```

`PREPAREONLY` is close to universal in the shipped scripts (about 770 of the
839 under `~~/demo/arm/flash`, and similar ratios for PowerPC, TriCore and
RISC-V), so most devices need no new script at all. Check the header comment of
the one you pick for the arguments it accepts, and put them in
`T32_FLASH_ARGS`.

### A different architecture

Still `config.env` only, but more than one line, because `T32_EXE` selects the
PowerView executable. Infineon AURIX for example:

```sh
T32_EXE="t32mtc-qt"
T32_CPU="TC387QP"
T32_MEMACCESS=""                                      # TriCore has no such command
T32_FLASH_SCRIPT="~~/demo/tricore/flash/tc38x.cmm"
T32_FLASH_ARGS="CPU=TC387QP DUALPORT=1"
```

`T32_CPU`, `T32_CORES`, `T32_MEMACCESS` and `T32_DUALPORT` are each skipped when
left empty, precisely so architectures that lack the corresponding command
still work. `SYStem.Option.DUALPORT` and `CORE.ASSIGN` do exist on TriCore, so
RTT and core selection carry over; `SYStem.MemAccess` does not, hence the empty
value above.

### Things `config.env` cannot fix

- A device whose shipped script has **no `PREPAREONLY`**, or which needs a
  local patch — a missing watchdog-disable that lets the chip reset itself
  mid-erase, a different RAM window for the flash algorithm, an erratum
  workaround. Copy the vendor script into `scripts/cmm/` and patch it there,
  then point `T32_FLASH_SCRIPT` at your copy — paths that do not start with
  `~~` are resolved relative to the toolkit directory, so
  `T32_FLASH_SCRIPT="scripts/cmm/stm32f4xx.cmm"`. The copy has to keep the
  contract `target.cmm` relies on: accept a `PREPAREONLY` argument, end with
  `IF &param_prepareonly / ENDDO PREPAREDONE` after the flash declaration, and
  leave the reset alone — `target.cmm` owns the `SYStem.Down` / `SYStem.Up`.
- **RTT** needs a SEGGER RTT implementation compiled into the firmware and an
  architecture that supports run-time memory access. Without both, use the
  flash and load flows and skip the RTT task.

---

## Command line

`scripts/t32.sh` is usable directly:

```bash
./trace32-vscode-bridge/scripts/t32.sh flash     # flash + symbols + run
./trace32-vscode-bridge/scripts/t32.sh load      # symbols + run
./trace32-vscode-bridge/scripts/t32.sh rtt       # RTT terminal
./trace32-vscode-bridge/scripts/t32.sh open      # start PowerView only
./trace32-vscode-bridge/scripts/t32.sh adapter   # foreground DAP proxy (normally started by F5)
./trace32-vscode-bridge/scripts/t32.sh config    # print the resolved configuration
```

PowerView is **started once**. Every later invocation detects the open RCL port
and drives the running instance instead of opening another window.

---

## How it works

```text
VS Code ──dependsOn──> your build task            (cargo / make / cmake / ...)
        └───task─────> t32.sh ──┬─> PowerView  -s startup.cmm         (first run only)
                                └─> t32rem ──RCL 20000──> target.cmm  (flash / symbols)

VS Code F5 ──> hidden adapter task ──> t32.sh adapter
VS Code ──DAP 58870──> compatibility proxy ──DAP 58871──> t32debugadapter
                                                        └─RCL 20000──> PowerView
rtt_viewer.py ─────────────────────────RCL 20000──> PowerView
```

Design notes:

- **One source of configuration.** `t32.sh` reads `config.env` and translates it
  into the `&CFG_*` globals in `.run/config.cmm`. The CMM side never parses
  strings: PRACTICE macro expansion is textual, so a quoted value would break
  the surrounding expression outright.
- **`t32rem` is asynchronous** — it returns as soon as a command is queued, not
  when it completes. So `target.cmm` writes `.run/done` (`OK` or `FAIL: ...`)
  when it finishes and `t32.sh` blocks on that file. That is what makes
  "attach only after flashing completed" reliable. `startup.cmm` writes
  `.run/ready` the same way. `target.cmm` also installs an `ON ERROR` handler
  so a TRACE32 failure reports back instead of stalling until the timeout.
- **Symbols are loaded, never written.** `Data.LOAD.Elf /NoCODE` leaves the
  running target's memory alone.
- **`SYStem.Option.DUALPORT ON`** is what RTT depends on: the viewer reads and
  writes the ring buffers through run-time AXI access without halting the core.
- **Pause/Locals workaround.** The proxy suppresses only the Locals request
  that can terminate adapter v0.0.27. Breakpoints, pause, stepping, call stack,
  registers, and explicit Watch expressions still use normal DAP requests.
- **Reset workaround.** RCL resets the target and leaves it stopped; the DAP
  adapter then issues Continue itself, so post-reset VS Code breakpoint hits
  are reported correctly.

---

## RTT

This PowerView build has no native `TERM.METHOD RTT`, so `rtt_viewer.py`
implements the standard RTT host protocol itself:

1. Resolve `_SEGGER_RTT` from the ELF symbols (`PROGRAM_NAME` selects the
   symbol table).
2. Read channel 0's `WrOff`/`RdOff` through `E:` run-time memory access.
3. Update `RdOff` after draining the up ring buffer.
4. Write keyboard input into the down ring buffer, publishing `WrOff` last.

An RTT channel must have exactly one host-side consumer, so do not run two
viewers at once.

Bytes are passed through verbatim — the viewer does no colouring or rewriting.
Whatever escape sequences the target emits are the target's business.

If symbols are not loaded yet, skip the lookup and give the address directly:

```bash
./trace32-vscode-bridge/scripts/t32.sh rtt --cb 0x20000000
```

---

## Troubleshooting

**"PowerView did not open RCL port 20000"**
`config.t32` is missing `RCL=NETTCP` / `PORT=20000`, or another process holds
the port.

**"TRACE32 script did not finish within 600s"**
`t32rem` delivered the command but `target.cmm` never wrote its completion
stamp — usually flashing stopped on an error. Open the PowerView AREA window
for the real message. `T32_TIMEOUT` is configurable in `config.env`.

**"path must not contain spaces"**
TRACE32 splits CMM arguments on whitespace, so the project and ELF paths cannot
contain spaces.

**RTT reports "run-time memory access failed"**
Check that the target is attached and `SYStem.Option.DUALPORT ON` took effect;
the `load` action sets it automatically.

**Variables pane reports `Invalid letter code`**
The compatibility proxy suppresses this known-bad Locals request, so Locals is
temporarily empty instead of terminating the debug session. Add ordinary
globals to Watch; inspect complex structures and RTOS objects in PowerView.

**Reset runs forever and does not report a breakpoint**
Make sure the adapter was started through `t32.sh`, not by launching the raw
adapter manually, and inspect the VS Code `T32: Start Debug Adapter` task
terminal. Reset must pass through the proxy to perform the coordinated RCL
Reset plus DAP Continue.
